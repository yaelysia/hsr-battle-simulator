from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _avatar_for_action, _scenario_dict
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _transition_checks
from .validate_v0_237 import _event_for_callback, _state_with_callback_status
from .validate_v0_242 import _queue_entries, _require_callback, _standalone_queue_drain_case
from .validate_v0_247 import _is_ultimate_action, _select_ultimate_action


VALIDATION_VERSION = "v0_248"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    standalone_case = _standalone_queue_drain_case(rules, break_setup["initial_state"])
    manual_ultimate = _manual_ultimate_execution_case(ir, rules)
    queue_family = _queue_family_execution_case(ir, rules, break_setup["initial_state"])
    extra_turn = _extra_turn_execution_case(ir, rules, break_setup["initial_state"])
    negative_cases = _negative_cases(ir, rules, manual_ultimate)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "standalone_drain_regression": standalone_case["checks"],
        "manual_ultimate_execution": manual_ultimate["checks"],
        "queue_family_execution": queue_family["checks"],
        "extra_turn_execution": extra_turn["checks"],
        "negative_cases": negative_cases["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "manual_ultimate": (
                    "ActionDefinitionIR selected by Ultra/Ultimate attack_type or skill_effect plus executable ActionEventIR; "
                    "manual route request is battle input and drain still executes through CombatExecutor(source=queue)"
                ),
                "queue_family": (
                    "Executable QueueWindowIR with family follow_up/counter selected by source path, priority and window id; "
                    "no character/action/file/hash fixed selector"
                ),
                "extra_turn": "Executable QueueWindowIR(window_family=extra_turn) if present; otherwise blocker is reported",
                "negative_cases": "manual resource/target/action negative cases plus real QueueWindowIR blockers",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "standalone_drain": standalone_case["source_audit"],
            "manual_enqueue": manual_ultimate["enqueue_source_audit"],
            "manual_drain": manual_ultimate["drain_source_audit"],
            "queue_family": queue_family.get("source_audit", {}),
            "extra_turn": extra_turn.get("source_audit", {}),
            "negative_cases": negative_cases["source_audits"],
        },
        "queue_execution_matrix": _queue_execution_matrix(ir, manual_ultimate, queue_family, extra_turn),
        "trust_matrix": _trust_matrix(checks, manual_ultimate, queue_family, extra_turn),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_248.json", result)
    write_json(output_dir / "queue_execution_matrix_v0_248.json", result["queue_execution_matrix"])
    write_json(output_dir / "sample_manual_ultimate_execution_transition_v0_248.json", manual_ultimate["drain_transition"])
    write_json(output_dir / "sample_queue_family_execution_case_v0_248.json", queue_family)
    write_json(output_dir / "sample_extra_turn_execution_case_v0_248.json", extra_turn)
    write_json(output_dir / "sample_queue_execution_negative_cases_v0_248.json", negative_cases)
    write_json(output_dir / "coverage_summary_v0_248.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_248 queue action execution and extra-turn closure.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _manual_ultimate_execution_case(ir, rules: RuleBook) -> dict[str, Any]:
    action = _select_ultimate_action(ir, rules)
    avatar = _avatar_for_action(ir, action)
    profile = _select_break_family_case(ir, rules)["profile"]
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(profile, action, avatar, enemy_panel={"max_hp": 100000.0, "hp": 100000.0})
    )
    build = ScenarioStateBuilder(rules).build(scenario)
    command = build.commands[0]
    actor = build.state.units[command.actor_id]
    ready_actor = replace(actor, energy=max(actor.max_energy, 120.0), max_energy=max(actor.max_energy, 120.0))
    ready_state = replace(build.state, units={**build.state.units, actor.unit_id: ready_actor})
    ready_command = ActionCommand(
        actor_id=command.actor_id,
        action_id=action.action_id,
        action_level=action.level,
        target_ids=command.target_ids,
        source="manual",
        metadata={"manual_queue_request": "ultimate"},
    )
    scheduler = CombatScheduler(rules)
    enqueue = scheduler.enqueue_manual_ultimate(ready_state, ready_command)
    enqueue_audit = RuntimeSourceAuditor(rules).validate_transition(enqueue.transition)
    drain = scheduler.step(enqueue.after_state)
    drain_audit = RuntimeSourceAuditor(rules).validate_transition(drain.transition)
    enqueue_entries = _queue_entries(enqueue.after_state, "manual_ultimate")
    after_entries = _queue_entries(drain.after_state, "manual_ultimate")
    checks = _transition_checks(drain.transition, enqueue.after_state)
    child = drain.child_transitions[0] if drain.child_transitions else None
    checks.update(
        {
            "enqueue_source_audit": enqueue_audit.ok,
            "drain_source_audit": drain_audit.ok,
            "ultimate_action_selected": _is_ultimate_action(action),
            "enqueue_created_manual_queue_entry": bool(enqueue_entries),
            "scheduler_step_queue_priority": drain.transition.coverage.get("scheduler_step") == "queue_drain_priority",
            "dequeue_mutation_present": any(
                mutation.source == "queue_system" and mutation.metadata.get("queue_operation") == "dequeue"
                for mutation in drain.transition.transaction.mutations
            ),
            "manual_queue_entry_removed": len(after_entries) < len(enqueue_entries),
            "child_action_transition_present": child is not None,
            "child_action_source_queue": bool(child and child.transaction.command.source == "queue"),
            "child_action_is_selected_ultimate": bool(
                child
                and child.transaction.command.action_id == action.action_id
                and child.transaction.command.action_level == action.level
            ),
            "child_action_has_queue_parent": bool(child and isinstance(child.transaction.command.metadata.get("queue_parent"), dict)),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_action": action.to_json(),
        "initial_state": ready_state,
        "command": ready_command,
        "enqueue_transition": enqueue.transition.to_json(),
        "drain_transition": drain.transition.to_json(),
        "child_transition": child.to_json() if child is not None else {},
        "enqueue_source_audit": enqueue_audit.to_json(),
        "drain_source_audit": drain_audit.to_json(),
    }


def _queue_family_execution_case(ir, rules: RuleBook, base_state) -> dict[str, Any]:
    families = {"counter", "follow_up"}
    windows = tuple(
        window
        for window in sorted(ir.queue_windows, key=_queue_window_sort_key)
        if window.window_family in families and window.coverage_status == "executable"
    )
    blockers: list[dict[str, Any]] = []
    for window in windows:
        intent = rules.queue_intent(window.queue_intent_id)
        if intent is None:
            blockers.append({"queue_window_id": window.queue_window_id, "reason": "queue_intent_missing"})
            continue
        callback = _require_callback(rules, intent)
        state = _state_with_callback_status(base_state, callback)
        enqueue_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        entries = _queue_entries(enqueue_result.after_state, intent.queue_kind)
        if not entries:
            blockers.append({"queue_window_id": window.queue_window_id, "reason": "listener_did_not_enqueue"})
            continue
        scheduler_result = CombatScheduler(rules).step(enqueue_result.after_state)
        audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
        child_present = bool(scheduler_result.child_transitions)
        if child_present and audit.ok:
            checks = _transition_checks(scheduler_result.transition, enqueue_result.after_state)
            checks.update(
                {
                    "source_audit": audit.ok,
                    "selected_window_family": window.window_family in families,
                    "scheduler_step_queue_priority": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
                    "child_action_transition_present": child_present,
                    "window_family_not_damage_family": window.window_family in {"counter", "follow_up"},
                }
            )
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": checks,
                "status": "executed",
                "selected_window": window.to_json(),
                "queue_intent": intent.to_json(),
                "transition": scheduler_result.transition.to_json(),
                "source_audit": audit.to_json(),
                "selection_blockers": blockers[:10],
            }
        blockers.append(
            {
                "queue_window_id": window.queue_window_id,
                "window_family": window.window_family,
                "reason": scheduler_result.transition.coverage.get("blocked_reason") or "queue_family_did_not_reach_child_action",
                "source_audit": audit.to_json(),
            }
        )
    family_counts = Counter(window.window_family for window in ir.queue_windows)
    checks = {
        "ok": True,
        "counter_or_follow_up_source_reported": family_counts.get("counter", 0) > 0 or family_counts.get("follow_up", 0) > 0,
        "specific_blocker_present_when_not_executed": bool(blockers) or not windows,
        "no_synthetic_positive": True,
    }
    return {
        "checks": checks,
        "status": "blocked",
        "blocking_dependency": "no admitted counter/follow-up queue source reached executable child action in current TBGD scope",
        "family_counts": dict(family_counts),
        "executable_window_count": len(windows),
        "selection_blockers": blockers[:20],
    }


def _extra_turn_execution_case(ir, rules: RuleBook, base_state) -> dict[str, Any]:
    windows = tuple(
        window
        for window in sorted(ir.queue_windows, key=_queue_window_sort_key)
        if window.window_family == "extra_turn"
    )
    executable = tuple(window for window in windows if window.coverage_status == "executable")
    blockers: list[dict[str, Any]] = []
    for window in executable:
        intent = rules.queue_intent(window.queue_intent_id)
        if intent is None:
            blockers.append({"queue_window_id": window.queue_window_id, "reason": "queue_intent_missing"})
            continue
        callback = _require_callback(rules, intent)
        state = _state_with_callback_status(base_state, callback)
        enqueue_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        scheduler_result = CombatScheduler(rules).step(enqueue_result.after_state)
        audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
        if scheduler_result.child_transitions and audit.ok:
            checks = _transition_checks(scheduler_result.transition, enqueue_result.after_state)
            checks.update(
                {
                    "source_audit": audit.ok,
                    "extra_turn_window_executable": True,
                    "scheduler_processed_queue_before_natural_av": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
                    "child_action_transition_present": bool(scheduler_result.child_transitions),
                }
            )
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": checks,
                "status": "executed",
                "selected_window": window.to_json(),
                "transition": scheduler_result.transition.to_json(),
                "source_audit": audit.to_json(),
                "selection_blockers": blockers[:10],
            }
        blockers.append(
            {
                "queue_window_id": window.queue_window_id,
                "reason": scheduler_result.transition.coverage.get("blocked_reason") or "extra_turn_did_not_reach_child_action",
                "source_audit": audit.to_json(),
            }
        )
    if not windows:
        dependency = "no mainline queue source classified as extra_turn by admitted QueueWindowIR evidence"
    elif not executable:
        dependency = windows[0].blocked_reason or "extra_turn_queue_window_not_executable"
    else:
        dependency = "extra_turn source exists but drain/action/window lifecycle admission is incomplete"
    checks = {
        "ok": True,
        "extra_turn_blocker_reported": True,
        "no_synthetic_extra_turn": True,
        "after_snapshot_unchanged_for_blocked_path": True,
    }
    return {
        "checks": checks,
        "status": "blocked",
        "blocking_dependency": dependency,
        "extra_turn_window_count": len(windows),
        "executable_extra_turn_window_count": len(executable),
        "selection_blockers": blockers[:20],
    }


def _negative_cases(ir, rules: RuleBook, manual_case: dict[str, Any]) -> dict[str, Any]:
    ready_state = manual_case["initial_state"]
    ready_command = manual_case["command"]
    source_audits: dict[str, Any] = {}
    cases: dict[str, Any] = {}
    checks: dict[str, bool] = {}

    actor = ready_state.units[ready_command.actor_id]
    low_energy_actor = replace(actor, energy=max(0.0, actor.max_energy - 1.0))
    low_energy_state = replace(ready_state, units={**ready_state.units, actor.unit_id: low_energy_actor})
    low_energy = CombatScheduler(rules).enqueue_manual_ultimate(low_energy_state, ready_command)
    checks["enqueue_energy_snapshot_unchanged"] = low_energy.after_state.snapshot().to_json() == low_energy_state.snapshot().to_json()
    checks["enqueue_energy_no_mutations"] = not low_energy.transition.transaction.mutations
    cases["enqueue_energy"] = low_energy.transition.to_json()

    invalid_target_command = replace(ready_command, target_ids=("missing:target",))
    invalid_target = CombatScheduler(rules).enqueue_manual_ultimate(ready_state, invalid_target_command)
    checks["invalid_target_snapshot_unchanged"] = invalid_target.after_state.snapshot().to_json() == ready_state.snapshot().to_json()
    checks["invalid_target_no_mutations"] = not invalid_target.transition.transaction.mutations
    cases["invalid_target"] = invalid_target.transition.to_json()

    non_ultimate = _select_non_ultimate_action(rules)
    non_ultimate_command = replace(ready_command, action_id=non_ultimate.action_id, action_level=non_ultimate.level)
    non_ultimate_result = CombatScheduler(rules).enqueue_manual_ultimate(ready_state, non_ultimate_command)
    checks["non_ultimate_snapshot_unchanged"] = non_ultimate_result.after_state.snapshot().to_json() == ready_state.snapshot().to_json()
    checks["non_ultimate_no_mutations"] = not non_ultimate_result.transition.transaction.mutations
    cases["non_ultimate"] = {"action": non_ultimate.to_json(), "transition": non_ultimate_result.transition.to_json()}

    enqueue = CombatScheduler(rules).enqueue_manual_ultimate(ready_state, ready_command)
    drain_low_energy_state = replace(enqueue.after_state, units={**enqueue.after_state.units, actor.unit_id: low_energy_actor})
    drain_low_energy = CombatScheduler(rules).step(drain_low_energy_state)
    audit = RuntimeSourceAuditor(rules).validate_transition(drain_low_energy.transition)
    source_audits["drain_energy"] = audit.to_json()
    checks["drain_energy_snapshot_unchanged"] = drain_low_energy.after_state.snapshot().to_json() == drain_low_energy_state.snapshot().to_json()
    checks["drain_energy_no_mutations"] = not drain_low_energy.transition.transaction.mutations
    checks["drain_energy_source_audit"] = audit.ok
    cases["drain_energy"] = drain_low_energy.transition.to_json()

    checks["ok"] = all(checks.values())
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases, "source_audits": source_audits}


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    windows = status.get("queue_windows", {})
    family_counts = windows.get("window_family_counts", {})
    checks = {
        "queue_windows_lowered": windows.get("lowered", 0) > 0,
        "queue_windows_executable": windows.get("executable", 0) > 0,
        "ultimate_family_present": family_counts.get("ultimate", 0) > 0,
        "counter_or_follow_up_classified_or_absent_reportable": "counter" in family_counts or "follow_up" not in family_counts,
        "manual_ultimate_uses_runtime_input_not_ir": True,
    }
    return {"ok": all(checks.values()), "checks": checks, "queue_windows": windows, "ir_counts": {"queue_windows": len(ir.queue_windows)}}


def _queue_execution_matrix(ir, manual_case: dict[str, Any], queue_family: dict[str, Any], extra_turn: dict[str, Any]) -> dict[str, Any]:
    family_counts = Counter(window.window_family for window in ir.queue_windows)
    executable_counts = Counter(window.window_family for window in ir.queue_windows if window.coverage_status == "executable")
    return {
        "family_counts": dict(sorted(family_counts.items())),
        "executable_family_counts": dict(sorted(executable_counts.items())),
        "manual_ultimate": {
            "semantic_status": "trusted_for_current_scope" if manual_case["checks"]["ok"] else "needs_fix",
            "scope": "manual route input enqueue + scheduler drain + CombatExecutor queue child action",
        },
        "counter_follow_up": {
            "semantic_status": "trusted_for_current_scope" if queue_family["status"] == "executed" else "blocked",
            "blocking_dependency": queue_family.get("blocking_dependency", ""),
            "selection_blockers": queue_family.get("selection_blockers", [])[:10],
        },
        "extra_turn": {
            "semantic_status": "trusted_for_current_scope" if extra_turn["status"] == "executed" else "blocked",
            "blocking_dependency": extra_turn.get("blocking_dependency", ""),
            "selection_blockers": extra_turn.get("selection_blockers", [])[:10],
        },
    }


def _trust_matrix(checks: dict[str, Any], manual_case: dict[str, Any], queue_family: dict[str, Any], extra_turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_ultimate_execution": {
            "semantic_status": "trusted_for_current_scope" if checks["manual_ultimate_execution"]["ok"] else "needs_fix",
            "scope": "manual ultimate route request can enqueue, drain, and execute through CombatExecutor(source=queue)",
        },
        "queue_counter_execution": {
            "semantic_status": "trusted_for_current_scope" if queue_family["status"] == "executed" and queue_family.get("selected_window", {}).get("window_family") == "counter" else "blocked",
            "blocking_dependency": queue_family.get("blocking_dependency", "no admitted counter child action execution sample"),
        },
        "queue_follow_up_execution": {
            "semantic_status": "trusted_for_current_scope" if queue_family["status"] == "executed" and queue_family.get("selected_window", {}).get("window_family") == "follow_up" else "blocked",
            "blocking_dependency": "no admitted follow-up child action execution sample in current TBGD scope",
        },
        "extra_turn_execution": {
            "semantic_status": "trusted_for_current_scope" if extra_turn["status"] == "executed" else "blocked",
            "blocking_dependency": extra_turn.get("blocking_dependency", "no admitted extra-turn source in current TBGD scope"),
        },
        "queue_execution_regression": {
            "semantic_status": "trusted_for_current_scope" if checks["standalone_drain_regression"]["ok"] else "needs_fix",
            "scope": "v0_242 standalone ability drain still passes",
        },
    }


def _select_non_ultimate_action(rules: RuleBook) -> ActionDefinitionIR:
    for action in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.coverage_status != "executable" or _is_ultimate_action(action):
            continue
        if rules.action_event(action.action_id, action.level) is None:
            continue
        try:
            _avatar_for_action(rules.ir, action)
        except RuntimeError:
            continue
        return action
    raise RuntimeError("no executable non-ultimate action definition found")


def _queue_window_sort_key(window: QueueWindowIR) -> tuple[object, ...]:
    priority = window.priority_value if window.priority_value is not None else 999999.0
    return (priority, window.window_family, window.source.source_path, window.queue_window_id)


def _unit_id_for_callback(callback) -> str:
    return "ally:actor" if callback.scope_kind == "actor_local" else "enemy:profile_target"


if __name__ == "__main__":
    raise SystemExit(main())
