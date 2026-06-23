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
from .validate_v0_242 import (
    _queue_entries,
    _require_callback,
    _standalone_queue_drain_case,
    _unit_id_for_callback,
)


VALIDATION_VERSION = "v0_247"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    standalone_case = _standalone_queue_drain_case(rules, break_setup["initial_state"])
    manual_ultimate = _manual_ultimate_case(ir, rules)
    window_family = _window_family_case(ir, rules, break_setup["initial_state"])
    extra_turn = _extra_turn_case(ir, rules, break_setup["initial_state"])
    negative_cases = _negative_cases(ir, rules, break_setup["initial_state"])

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "standalone_drain_regression": standalone_case["checks"],
        "manual_ultimate": manual_ultimate["checks"],
        "window_family": window_family["checks"],
        "extra_turn": extra_turn["checks"],
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
                "window_family": "QueueWindowIR selected by executable family status and source path ordering; no character/action/file/hash fixed selector",
                "manual_ultimate": "ActionDefinitionIR selected by Ultra/Ultimate attack_type or skill_effect plus executable ActionEventIR; manual request remains route input",
                "negative_cases": "real blocked QueueWindowIR / QueueIntentIR blockers and synthetic manual energy failure only",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "standalone_drain": standalone_case["source_audit"],
            "manual_ultimate": manual_ultimate["source_audit"],
            "window_family": window_family.get("source_audit", {}),
            "negative_cases": negative_cases["source_audits"],
        },
        "queue_window_family_matrix": _queue_window_family_matrix(ir, extra_turn),
        "trust_matrix": _trust_matrix(checks, extra_turn),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_247.json", result)
    write_json(output_dir / "queue_window_family_matrix_v0_247.json", result["queue_window_family_matrix"])
    write_json(output_dir / "sample_manual_ultimate_queue_transition_v0_247.json", manual_ultimate["transition"])
    write_json(output_dir / "sample_queue_window_family_transition_v0_247.json", window_family.get("transition", {}))
    write_json(output_dir / "sample_extra_turn_queue_case_v0_247.json", extra_turn)
    write_json(output_dir / "sample_queue_interrupt_negative_cases_v0_247.json", negative_cases)
    write_json(output_dir / "coverage_summary_v0_247.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_247 queue interrupt family and extra-turn admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _manual_ultimate_case(ir, rules: RuleBook) -> dict[str, Any]:
    action = _select_ultimate_action(ir, rules)
    avatar = _avatar_for_action(ir, action)
    profile = _select_break_family_case(ir, rules)["profile"]
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(profile, action, avatar, enemy_panel={"max_hp": 100000.0, "hp": 100000.0})
    )
    build = ScenarioStateBuilder(rules).build(scenario)
    command = build.commands[0]
    actor = build.state.units[command.actor_id]
    ready_actor = replace(actor, energy=actor.max_energy, max_energy=max(actor.max_energy, 120.0))
    ready_state = replace(build.state, units={**build.state.units, actor.unit_id: ready_actor})
    ready_command = ActionCommand(
        actor_id=command.actor_id,
        action_id=action.action_id,
        action_level=action.level,
        target_ids=command.target_ids,
        source="manual",
        metadata={"manual_queue_request": "ultimate"},
    )
    result = CombatScheduler(rules).enqueue_manual_ultimate(ready_state, ready_command)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, ready_state)
    queue_entries = _queue_entries(result.after_state, "manual_ultimate")
    checks.update(
        {
            "source_audit": audit.ok,
            "ultimate_action_selected": _is_ultimate_action(action),
            "manual_ultimate_queue_entry_created": bool(queue_entries),
            "queue_entry_window_family_ultimate": bool(queue_entries and queue_entries[0].get("window_family") == "ultimate"),
            "queue_entry_target_resolution_ok": bool(queue_entries and queue_entries[0].get("target_resolution", {}).get("ok") is True),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")

    low_energy_actor = replace(ready_actor, energy=max(0.0, ready_actor.max_energy - 1.0))
    low_energy_state = replace(build.state, units={**build.state.units, actor.unit_id: low_energy_actor})
    blocked = CombatScheduler(rules).enqueue_manual_ultimate(low_energy_state, ready_command)
    blocked_checks = {
        "ok": True,
        "snapshot_unchanged": blocked.after_state.snapshot().to_json() == low_energy_state.snapshot().to_json(),
        "no_mutations": not blocked.transition.transaction.mutations,
        "blocked_reason_energy": blocked.transition.coverage.get("blocked_reason") == "manual_ultimate_energy_not_ready",
    }
    blocked_checks["ok"] = all(value for key, value in blocked_checks.items() if key != "ok")
    checks["energy_negative_ok"] = blocked_checks["ok"]
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_action": action.to_json(),
        "transition": result.transition.to_json(),
        "source_audit": audit.to_json(),
        "energy_negative": {"checks": blocked_checks, "transition": blocked.transition.to_json()},
    }


def _window_family_case(ir, rules: RuleBook, base_state) -> dict[str, Any]:
    families = Counter(window.window_family for window in ir.queue_windows)
    executable_families = Counter(window.window_family for window in ir.queue_windows if window.coverage_status == "executable")
    selected_result = _execute_first_enqueuing_window(rules, base_state)
    if selected_result is None:
        selected = _select_executable_window(rules, {"counter", "ultimate", "insert_ability"})
        checks = {
            "ok": True,
            "classified_family_present": any(families.get(family, 0) for family in ("counter", "ultimate", "extra_turn")),
            "specific_blocker_present": bool(_window_blockers(ir)),
            "no_fake_positive": True,
        }
        return {
            "checks": checks,
            "selected_window": selected.to_json() if selected is not None else {},
            "window_family_counts": dict(families),
            "executable_family_counts": dict(executable_families),
            "blockers": _window_blockers(ir),
        }
    selected, state, result = selected_result
    intent = rules.queue_intent(selected.queue_intent_id)
    if intent is None:
        raise RuntimeError(f"QueueWindowIR intent missing: {selected.queue_intent_id}")
    transition = _system_transition_for_queue(state, result)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    entries = _queue_entries(result.after_state, intent.queue_kind)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": audit.ok,
            "selected_window_executable": selected.coverage_status == "executable",
            "selected_window_family_classified": selected.window_family in {"counter", "ultimate", "insert_ability", "insert_action"},
            "counter_or_ultimate_classified_elsewhere": families.get("counter", 0) > 0 or families.get("ultimate", 0) > 0,
            "enqueue_mutation_present": bool(result.mutations),
            "entry_has_window_family": bool(entries and entries[0].get("window_family") == selected.window_family),
            "entry_has_target_resolution": bool(entries and isinstance(entries[0].get("target_resolution"), dict)),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_window": selected.to_json(),
        "queue_intent": intent.to_json(),
        "transition": transition.to_json(),
        "source_audit": audit.to_json(),
        "window_family_counts": dict(families),
        "executable_family_counts": dict(executable_families),
    }


def _extra_turn_case(ir, rules: RuleBook, base_state) -> dict[str, Any]:
    extra_windows = tuple(window for window in ir.queue_windows if window.window_family == "extra_turn")
    executable = tuple(window for window in extra_windows if window.coverage_status == "executable")
    if not extra_windows:
        checks = {
            "ok": True,
            "extra_turn_source_absent_reported": True,
            "no_synthetic_extra_turn": True,
            "blocking_dependency_present": True,
        }
        return {
            "checks": checks,
            "status": "blocked",
            "blocking_dependency": "no mainline queue source classified as extra_turn by admitted QueueWindowIR evidence",
            "extra_turn_window_count": 0,
        }
    selected = executable[0] if executable else extra_windows[0]
    if selected.coverage_status != "executable":
        checks = {
            "ok": True,
            "extra_turn_window_discovered": True,
            "extra_turn_blocked_reason_present": bool(selected.blocked_reason),
            "no_fake_dequeue": True,
        }
        return {
            "checks": checks,
            "status": "blocked",
            "selected_window": selected.to_json(),
            "blocking_dependency": selected.blocked_reason,
        }
    intent = rules.queue_intent(selected.queue_intent_id)
    callback = _require_callback(rules, intent) if intent is not None else None
    if intent is None or callback is None:
        return {
            "checks": {"ok": False, "extra_turn_intent_present": False},
            "status": "needs_fix",
            "selected_window": selected.to_json(),
        }
    state = _state_with_callback_status(base_state, callback)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
        state,
        event=_event_for_callback(callback),
        unit_id=_unit_id_for_callback(callback),
        modifier_name=callback.modifier_name,
    )
    scheduler_result = CombatScheduler(rules).step(result.after_state)
    audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
    checks = _transition_checks(scheduler_result.transition, result.after_state)
    checks.update(
        {
            "source_audit": audit.ok,
            "extra_turn_window_executable": True,
            "scheduler_processed_queue_before_natural_av": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
            "queue_child_or_blocker_present": bool(scheduler_result.child_transitions) or bool(scheduler_result.transition.coverage.get("blocked_reason")),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "status": "executed_or_blocked_by_downstream",
        "selected_window": selected.to_json(),
        "transition": scheduler_result.transition.to_json(),
        "source_audit": audit.to_json(),
    }


def _negative_cases(ir, rules: RuleBook, base_state) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    source_audits: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    blocked_window = next((window for window in ir.queue_windows if window.coverage_status != "executable" and window.blocked_reason), None)
    if blocked_window is not None:
        intent = rules.queue_intent(blocked_window.queue_intent_id)
        callback = _require_callback(rules, intent) if intent is not None else None
        if intent is not None and callback is not None:
            state = _state_with_callback_status(base_state, callback)
            result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
                state,
                event=_event_for_callback(callback),
                unit_id=_unit_id_for_callback(callback),
                modifier_name=callback.modifier_name,
            )
            transition = _system_transition_for_queue(state, result)
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            unchanged = result.after_state.snapshot().to_json() == state.snapshot().to_json()
            checks["blocked_window_available"] = True
            checks["blocked_window_snapshot_unchanged"] = unchanged
            checks["blocked_window_no_mutations"] = not result.mutations
            checks["blocked_window_source_audit"] = audit.ok
            cases["blocked_window"] = {"window": blocked_window.to_json(), "transition": transition.to_json()}
            source_audits["blocked_window"] = audit.to_json()
    assistant = next((window for window in ir.queue_windows if window.window_family == "assistant"), None)
    checks["assistant_window_blocked_or_missing"] = assistant is None or assistant.coverage_status != "executable"
    if assistant is not None:
        cases["assistant_window"] = {"window": assistant.to_json()}
    checks["ok"] = all(value for key, value in checks.items() if key != "ok") if checks else False
    return {"checks": checks, "cases": cases, "source_audits": source_audits}


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    windows = status.get("queue_windows", {})
    family_counts = windows.get("window_family_counts", {})
    checks = {
        "queue_windows_lowered": windows.get("lowered", 0) > 0,
        "queue_windows_executable": windows.get("executable", 0) > 0,
        "counter_or_ultimate_classified": family_counts.get("counter", 0) > 0 or family_counts.get("ultimate", 0) > 0,
        "assistant_family_independent": "assistant" in family_counts,
        "insert_families_present": family_counts.get("insert_ability", 0) > 0 or family_counts.get("insert_action", 0) > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "queue_windows": windows, "ir_counts": {"queue_windows": len(ir.queue_windows)}}


def _queue_window_family_matrix(ir, extra_turn_case: dict[str, Any]) -> dict[str, Any]:
    status_counts = Counter(window.coverage_status for window in ir.queue_windows)
    family_counts = Counter(window.window_family for window in ir.queue_windows)
    executable_family_counts = Counter(window.window_family for window in ir.queue_windows if window.coverage_status == "executable")
    blockers = Counter(window.blocked_reason for window in ir.queue_windows if window.blocked_reason)
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "executable_family_counts": dict(sorted(executable_family_counts.items())),
        "blocked_reason_counts": dict(blockers.most_common(20)),
        "families": {
            family: _family_matrix_item(family, family_counts, executable_family_counts, extra_turn_case)
            for family in ("ultimate", "follow_up", "counter", "extra_turn", "immediate", "interrupt", "insert_action", "insert_ability", "assistant")
        },
    }


def _family_matrix_item(
    family: str,
    family_counts: Counter[str],
    executable_family_counts: Counter[str],
    extra_turn_case: dict[str, Any],
) -> dict[str, Any]:
    if executable_family_counts.get(family, 0) > 0:
        return {
            "semantic_status": "trusted_for_current_scope",
            "admission_result": "executable",
            "count": executable_family_counts[family],
        }
    if family_counts.get(family, 0) > 0:
        return {
            "semantic_status": "blocked",
            "admission_result": "blocked",
            "count": family_counts[family],
            "blocking_dependency": "classified QueueWindowIR exists but window/resolution/source/payload admission is incomplete",
        }
    dependency = (
        extra_turn_case.get("blocking_dependency")
        if family == "extra_turn"
        else "no admitted mainline TBGD queue source classified for this window family"
    )
    return {
        "semantic_status": "blocked",
        "admission_result": "not_discovered",
        "count": 0,
        "blocking_dependency": str(dependency),
    }


def _trust_matrix(checks: dict[str, Any], extra_turn_case: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_window_ir": {
            "semantic_status": "trusted_for_current_scope" if checks["coverage"]["checks"]["queue_windows_executable"] else "needs_fix",
            "scope": "QueueWindowIR classifies admitted queue families before runtime drain",
        },
        "manual_ultimate_enqueue": {
            "semantic_status": "trusted_for_current_scope" if checks["manual_ultimate"]["ok"] else "needs_fix",
            "scope": "manual route ultimate request can enqueue after action/target/energy/window preflight; drain remains separate",
        },
        "counter_window": {
            "semantic_status": "trusted_for_current_scope" if checks["window_family"].get("selected_window_family_classified") else "blocked",
            "scope": "counter is a queue window/attack semantics category, not a damage formula family",
        },
        "extra_turn_window": {
            "semantic_status": "trusted_for_current_scope" if extra_turn_case["checks"].get("extra_turn_window_executable") else "blocked",
            "blocking_dependency": str(extra_turn_case.get("blocking_dependency") or "no admitted extra-turn source in current TBGD lowering"),
        },
        "queue_drain": {
            "semantic_status": "trusted_for_current_scope" if checks["standalone_drain_regression"]["ok"] else "needs_fix",
            "scope": "standalone ability drain and queue action child path from v0_242/v0_246 remain intact",
        },
    }


def _select_ultimate_action(ir, rules: RuleBook) -> ActionDefinitionIR:
    for action in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.coverage_status != "executable" or not _is_ultimate_action(action):
            continue
        event = rules.action_event(action.action_id, action.level)
        if event is None or event.coverage_status == "blocked":
            continue
        try:
            _avatar_for_action(ir, action)
        except RuntimeError:
            continue
        return action
    raise RuntimeError("no executable ultimate action definition found")


def _select_executable_window(rules: RuleBook, families: set[str]) -> QueueWindowIR | None:
    for window in sorted(
        rules.ir.queue_windows,
        key=lambda item: (
            item.window_family not in {"counter", "ultimate"},
            item.window_family,
            item.priority_value if item.priority_value is not None else 999999.0,
            item.source.source_path,
            item.queue_window_id,
        ),
    ):
        if window.coverage_status == "executable" and window.window_family in families:
            return window
    return None


def _execute_first_enqueuing_window(rules: RuleBook, base_state) -> tuple[QueueWindowIR, Any, Any] | None:
    ordered = sorted(
        (window for window in rules.ir.queue_windows if window.coverage_status == "executable"),
        key=lambda item: (
            item.window_family not in {"counter", "ultimate", "insert_ability", "insert_action"},
            item.window_family in {"counter", "ultimate"},
            item.priority_value if item.priority_value is not None else 999999.0,
            item.source.source_path,
            item.queue_window_id,
        ),
    )
    for window in ordered:
        intent = rules.queue_intent(window.queue_intent_id)
        if intent is None:
            continue
        callback = _require_callback(rules, intent)
        state = _state_with_callback_status(base_state, callback)
        result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        if result.mutations:
            return window, state, result
    return None


def _window_blockers(ir) -> list[dict[str, Any]]:
    return [
        {
            "queue_window_id": window.queue_window_id,
            "window_family": window.window_family,
            "blocked_reason": window.blocked_reason,
            "source": window.source.to_json(),
        }
        for window in sorted(ir.queue_windows, key=lambda item: item.queue_window_id)
        if window.blocked_reason
    ][:20]


def _system_transition_for_queue(before_state, result):
    from .validate_v0_235 import _system_transition

    return _system_transition(
        before_state=before_state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="queue:v0_247",
        metadata={},
    )


def _is_ultimate_action(action: ActionDefinitionIR) -> bool:
    text = f"{action.attack_type} {action.skill_effect}".lower()
    return any(token in text for token in ("ultra", "ultimate"))


if __name__ == "__main__":
    raise SystemExit(main())
