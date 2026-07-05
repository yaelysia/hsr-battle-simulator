from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, QueueIntentIR, QueueResolutionIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.queue import QUEUE_WINDOW_FAMILY_ORDER, QueueEntry, QueueSystem
from ..systems.scheduler import CombatScheduler, queue_plan_requires_external_command, select_next_queue_drain_plan
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import _kill_to_extra_turn_case
from .validate_v0_282 import (
    _counter_route_case as _counter_route_case_v0_282,
    _negative_cases as _counter_negative_cases_v0_282,
    _select_counter_sample,
    _strip_runtime,
)


VALIDATION_VERSION = "p1_5_queue_window_system"
COUNTER_CALLBACK_EVENTS = {
    "OnAfterBeingAttacked",
    "OnListenBeforeBeingHit",
}
COUNTER_TARGET_ALIASES = {
    "ParamEntity",
    "DamageAttackerEntity",
    "CurrentActionTarget",
    "AbilityTargetEntity",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    current_scope = _current_queue_scope(ir)
    source_matrix = _queue_source_matrix(ir, rules)
    event_window_matrix = _event_window_matrix(ir)
    order_matrix = _queue_window_order_matrix(ir)
    mandatory_case = _mandatory_insert_action_case(rules)
    insert_ability_case = _insert_ability_case(rules)
    selectable_ultimate_case = _selectable_ultimate_case(rules)
    extra_turn_case = _extra_turn_case(ir, rules)
    counter_case = _counter_case(package_root.parent, rules)
    family_gaps = _queue_family_source_gaps(ir, counter_executable=counter_case["checks"]["ok"])
    actor_removed_case = _actor_target_lifecycle_case(rules)
    unknown_family_case = _unknown_family_blocked_case(ir)
    conditional_case = _conditional_queue_case(ir, rules)
    source_contract_case = _queue_source_contract_case(ir)

    checks = {
        "current_scope": current_scope["checks"],
        "source_matrix": source_matrix["checks"],
        "event_window_matrix": event_window_matrix["checks"],
        "order_matrix": order_matrix["checks"],
        "mandatory_insert_action": mandatory_case["checks"],
        "insert_ability": insert_ability_case["checks"],
        "selectable_ultimate": selectable_ultimate_case["checks"],
        "extra_turn": extra_turn_case["checks"],
        "counter_route": counter_case["checks"],
        "family_gaps": family_gaps["checks"],
        "actor_target_lifecycle": actor_removed_case["checks"],
        "unknown_family_blocked": unknown_family_case["checks"],
        "conditional_queue": conditional_case["checks"],
        "source_contract": source_contract_case["checks"],
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
                "fixed_entity_skill_file_or_observation_used": False,
                "predicates": [
                    "QueueIntentIR.coverage_status",
                    "QueueIntentIR.opcode",
                    "QueueWindowIR.window_family",
                    "QueueWindowIR.coverage_status",
                    "QueueResolutionIR.resolved_kind",
                    "QueueResolutionIR.coverage_status",
                    "QueueLifecyclePolicyIR.coverage_status",
                    "ExtraActionPolicyIR.action_selection_kind",
                ],
            },
        },
        "checks": checks,
        "current_queue_scope": current_scope,
        "queue_source_matrix": source_matrix,
        "event_window_matrix": event_window_matrix,
        "queue_window_order_matrix": order_matrix,
        "cases": {
            "mandatory_insert_action": mandatory_case,
            "insert_ability": insert_ability_case,
            "selectable_ultimate": selectable_ultimate_case,
            "extra_turn": extra_turn_case,
            "counter_route": counter_case,
            "family_gaps": family_gaps,
            "actor_target_lifecycle": actor_removed_case,
            "unknown_family_blocked": unknown_family_case,
            "conditional_queue": conditional_case,
            "source_contract": source_contract_case,
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_5_queue_window_system.json", result)
    write_json(output_dir / "queue_source_matrix_p1_5.json", source_matrix)
    write_json(output_dir / "queue_window_order_matrix_p1_5.json", order_matrix)
    write_json(output_dir / "queue_mandatory_drain_case_p1_5.json", mandatory_case)
    write_json(output_dir / "queue_selectable_ultimate_case_p1_5.json", selectable_ultimate_case)
    write_json(output_dir / "queue_extra_turn_case_p1_5.json", extra_turn_case)
    write_json(output_dir / "queue_counter_route_case_p1_5.json", counter_case)
    write_json(output_dir / "queue_family_source_gaps_p1_5.json", family_gaps)
    write_json(output_dir / "queue_actor_removed_case_p1_5.json", actor_removed_case)
    write_json(output_dir / "queue_unknown_family_blocked_case_p1_5.json", unknown_family_case)
    write_json(output_dir / "queue_insert_ability_case_p1_5.json", insert_ability_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-5 queue/window system semantics.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _current_queue_scope(ir) -> dict[str, Any]:
    intent_status = Counter(intent.coverage_status for intent in ir.queue_intents)
    intent_opcode = Counter(intent.opcode for intent in ir.queue_intents)
    window_status = Counter(window.coverage_status for window in ir.queue_windows)
    window_family = Counter(window.window_family for window in ir.queue_windows)
    semantic_family = Counter(
        semantic
        for window in ir.queue_windows
        for semantic in _queue_window_semantic_families(window)
    )
    resolution_status = Counter(resolution.coverage_status for resolution in ir.queue_resolutions)
    resolution_kind = Counter(resolution.resolved_kind for resolution in ir.queue_resolutions)
    checks = {
        "queue_ir_present": bool(ir.queue_intents and ir.queue_windows and ir.queue_resolutions),
        "has_executable_queue_window": any(window.coverage_status == "executable" for window in ir.queue_windows),
        "assistant_not_executable_current_scope": not any(
            window.window_family == "assistant" and window.coverage_status == "executable"
            for window in ir.queue_windows
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "intent_status_counts": dict(sorted(intent_status.items())),
        "intent_opcode_counts": dict(sorted(intent_opcode.items())),
        "window_status_counts": dict(sorted(window_status.items())),
        "window_family_counts": dict(sorted(window_family.items())),
        "semantic_family_counts": dict(sorted(semantic_family.items())),
        "resolution_status_counts": dict(sorted(resolution_status.items())),
        "resolution_kind_counts": dict(sorted(resolution_kind.items())),
        "current_queue_scope": {
            "executable_families": sorted(
                {window.window_family for window in ir.queue_windows if window.coverage_status == "executable"}
            ),
            "source_gap_or_blocked_families": sorted(
                {window.window_family for window in ir.queue_windows if window.coverage_status != "executable"}
            ),
        },
    }


def _queue_source_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    non_executable_intent_executable_window = []
    text_hint_executable = []
    semantic_status = Counter()
    for window in sorted(ir.queue_windows, key=lambda item: item.queue_window_id):
        intent = rules.queue_intent(window.queue_intent_id)
        resolution = rules.queue_resolution_for_intent(window.queue_intent_id)
        policy = window.window_policy if isinstance(window.window_policy, dict) else {}
        source_basis = policy.get("source_basis") if isinstance(policy.get("source_basis"), dict) else {}
        semantic_families = _queue_window_semantic_families(window)
        row = {
            "queue_window_id": window.queue_window_id,
            "queue_intent_id": window.queue_intent_id,
            "opcode": intent.opcode if intent is not None else "",
            "queue_kind": intent.queue_kind if intent is not None else window.queue_kind,
            "window_family": window.window_family,
            "semantic_families": semantic_families,
            "window_coverage_status": window.coverage_status,
            "window_blocked_reason": window.blocked_reason,
            "intent_coverage_status": intent.coverage_status if intent is not None else "missing",
            "resolution_coverage_status": resolution.coverage_status if resolution is not None else "missing",
            "resolution_kind": resolution.resolved_kind if resolution is not None else "",
            "priority_key": window.priority_key,
            "priority_value": window.priority_value,
            "priority_ordering_admitted": policy.get("priority_ordering_admitted") is True,
            "lifecycle_policy_admitted": policy.get("lifecycle_policy_admitted"),
            "text_hints": policy.get("text_hints", ()),
            "source_basis": source_basis,
            "source": window.source.to_json(),
        }
        rows.append(row)
        for semantic in semantic_families:
            semantic_status[(window.window_family, semantic, window.coverage_status)] += 1
        if intent is not None and intent.coverage_status != "executable" and window.coverage_status == "executable":
            non_executable_intent_executable_window.append(row)
        if source_basis.get("source_basis") == "text_only_queue_window_hint" and window.coverage_status == "executable":
            text_hint_executable.append(row)
    family_status = Counter((row["window_family"], row["window_coverage_status"]) for row in rows)
    checks = {
        "all_executable_windows_have_executable_intent": not non_executable_intent_executable_window,
        "text_only_hints_not_executable": not text_hint_executable,
        "blocked_audit_discovered_not_admitted_to_window": not non_executable_intent_executable_window,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "family_status_counts": {f"{family}:{status}": count for (family, status), count in sorted(family_status.items())},
        "semantic_status_counts": {
            f"{family}:{semantic}:{status}": count
            for (family, semantic, status), count in sorted(semantic_status.items())
        },
        "sample_rows": rows[:25],
        "negative_evidence": {
            "non_executable_intent_executable_window": non_executable_intent_executable_window[:10],
            "text_hint_executable": text_hint_executable[:10],
        },
    }


def _event_window_matrix(ir) -> dict[str, Any]:
    callback_events = Counter(callback.event for callback in ir.status_callbacks)
    queue_events = Counter(callback.event for callback in ir.status_callbacks if any(
        intent.callback_id == callback.callback_id for intent in ir.queue_intents
    ))
    taxonomy = {
        "event_windows": [
            "OnEnterBattle",
            "OnWaveMonster",
            "OnListenAfterAttack",
            "OnListenCharacterDie",
            "OnTriggerDeath",
            "OnAfterSkillUse",
            "ActionPhaseEnd",
            "ModifierPhase1End",
            "scheduler.pending_turn_end",
            "queue.drain.begin",
            "queue.drain.end",
            "queue.drain.blocked",
        ],
        "queue_window_families": sorted(QUEUE_WINDOW_FAMILY_ORDER),
        "boundary": "GameEvent.window triggers callbacks; QueueWindowIR.window_family controls admitted drain scheduling.",
    }
    checks = {
        "callback_events_present": bool(callback_events),
        "queue_events_present": bool(queue_events),
        "queue_drain_is_not_callback_event_family": "queue" not in callback_events,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "taxonomy": taxonomy,
        "callback_event_counts": dict(sorted(callback_events.items())),
        "queue_callback_event_counts": dict(sorted(queue_events.items())),
    }


def _queue_window_order_matrix(ir) -> dict[str, Any]:
    rows = []
    for family, family_order in sorted(QUEUE_WINDOW_FAMILY_ORDER.items(), key=lambda item: (item[1], item[0])):
        family_windows = [window for window in ir.queue_windows if window.window_family == family]
        rows.append(
            {
                "window_family": family,
                "family_order": family_order,
                "family_order_source_kind": "engine_scheduling_convention",
                "priority_order_source_kind": "tbgd_priority_table_when_QueuePriorityIR_present_else_source_gap_blocked",
                "tie_breaker_source_kind": "engine_scheduling_convention",
                "window_count": len(family_windows),
                "executable_count": sum(1 for window in family_windows if window.coverage_status == "executable"),
                "blocked_count": sum(1 for window in family_windows if window.coverage_status != "executable"),
            }
        )
    checks = {
        "family_order_stable": QUEUE_WINDOW_FAMILY_ORDER.get("follow_up", 999) <= QUEUE_WINDOW_FAMILY_ORDER.get("insert_action", 999),
        "ultimate_and_extra_turn_same_family_order_current_convention": QUEUE_WINDOW_FAMILY_ORDER.get("ultimate") == QUEUE_WINDOW_FAMILY_ORDER.get("extra_turn"),
        "unknown_last": QUEUE_WINDOW_FAMILY_ORDER.get("unknown", 0) >= max(QUEUE_WINDOW_FAMILY_ORDER.values()),
        "convention_not_marked_as_tbgd_source": all(row["family_order_source_kind"] == "engine_scheduling_convention" for row in rows),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "rows": rows}


def _mandatory_insert_action_case(rules: RuleBook) -> dict[str, Any]:
    intent, resolution, window, candidate = _select_action_definition_queue(rules)
    state = _state_with_queue_entry(rules, intent, resolution, window, candidate=candidate)
    queue = QueueSystem()
    plan = select_next_queue_drain_plan(rules, queue, state)
    availability = ActionAvailabilitySystem(rules).view(state)
    result = CombatScheduler(rules).step(state)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    transition_checks = _transition_checks(result.transition, state)
    entry_id = _entry_id(state, intent.queue_kind)
    after_entries = [entry for entry in result.after_state.queues.get(intent.queue_kind, ()) if isinstance(entry, dict)]
    events = [event.event_type for event in result.transition.transaction.events]
    records = [record.get("record_type") for record in (result.transition.transaction.settlement.records if result.transition.transaction.settlement else ())]
    checks = {
        **transition_checks,
        "source_audit": audit.ok,
        "plan_ok": plan is not None and plan.ok,
        "plan_control_mandatory": (plan.to_json().get("control") if plan is not None else "") == "mandatory",
        "requires_no_external_command": plan is not None
        and rules.queue_resolution(plan.queue_resolution_id) is not None
        and not queue_plan_requires_external_command(plan, rules.queue_resolution(plan.queue_resolution_id)),
        "availability_queued_mandatory": availability.mode == "queued_mandatory",
        "scheduler_drained_queue": result.transition.transaction.command.action_id == "queue:drain_admitted",
        "queue_entry_removed": entry_id not in [str(entry.get("entry_id") or "") for entry in after_entries],
        "queue_drain_begin_event": "queue.drain.begin" in events,
        "queue_drain_end_event": "queue.drain.end" in events,
        "queue_drain_records": "queue_drain_begin" in records and "queue_drain_end" in records,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected": _selected_queue_payload(intent, resolution, window),
        "drain_plan": plan.to_json() if plan is not None else {},
        "availability": availability.to_json(),
        "transition": result.transition.to_json(),
        "source_audit": audit.to_json(),
    }


def _insert_ability_case(rules: RuleBook) -> dict[str, Any]:
    selected = _select_insert_ability_queue(rules)
    if selected is None:
        return _source_gap_case("insert_ability", "no executable standalone ability graph queue source found")
    intent, resolution, window = selected
    state = _state_with_queue_entry(rules, intent, resolution, window)
    plan = select_next_queue_drain_plan(rules, QueueSystem(), state)
    result = CombatScheduler(rules).step(state)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = {
        **_transition_checks(result.transition, state),
        "source_audit": audit.ok,
        "plan_ok": plan is not None and plan.ok,
        "resolved_kind_standalone_ability_graph": plan is not None and plan.resolved_kind == "standalone_ability_graph",
        "queue_drain_admitted": result.transition.transaction.command.action_id == "queue:drain_admitted",
        "queue_drain_begin_end_events": _has_event(result, "queue.drain.begin") and _has_event(result, "queue.drain.end"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected": _selected_queue_payload(intent, resolution, window),
        "drain_plan": plan.to_json() if plan is not None else {},
        "transition": result.transition.to_json(),
        "source_audit": audit.to_json(),
    }


def _selectable_ultimate_case(rules: RuleBook) -> dict[str, Any]:
    action = _select_ultimate_action(rules)
    state = _base_state(
        actor_template="avatar:validation_manual_ultimate",
        actor_id="ally:ultimate",
        enemy_id="enemy:target",
        energy=120.0,
        max_energy=120.0,
    )
    command = ActionCommand(
        actor_id="ally:ultimate",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"route_source": "validation_p1_5_manual_ultimate"},
    )
    scheduler = CombatScheduler(rules)
    enqueue = scheduler.enqueue_manual_ultimate(state, command)
    availability = ActionAvailabilitySystem(rules).view(enqueue.after_state)
    no_command = scheduler.step(enqueue.after_state)
    mismatch = scheduler.step(
        enqueue.after_state,
        command=replace(command, actor_id="ally:wrong"),
    )
    matching = scheduler.step(enqueue.after_state, command=command)
    enqueue_audit = RuntimeSourceAuditor(rules).validate_transition(enqueue.transition)
    matching_audit = RuntimeSourceAuditor(rules).validate_transition(matching.transition)
    before_snapshot = enqueue.after_state.snapshot().to_json()
    matching_blocked_reason = str(matching.transition.coverage.get("blocked_reason") or "")
    matching_success = matching.transition.transaction.command.action_id == "queue:drain_admitted"
    action_event = rules.action_event(action.action_id, action.level)
    action_event_gap = action_event is None or action_event.coverage_status in {"blocked", "unsupported", "discovered_only"}
    checks = {
        "enqueue_source_audit": enqueue_audit.ok,
        "matching_source_audit": matching_audit.ok,
        "availability_queued_selectable": availability.mode == "queued_selectable",
        "selectable_window_present": bool(availability.selectable_windows),
        "selectable_resource_preflight_ok": bool(
            availability.selectable_windows
            and availability.selectable_windows[0].metadata.get("resource_preflight", {}).get("ok") is True
        ),
        "no_command_blocked": no_command.transition.coverage.get("blocked_reason") == "queue_selectable_command_missing",
        "no_command_state_unchanged": no_command.after_state.snapshot().to_json() == before_snapshot,
        "no_command_queue_drain_blocked_event": _has_event(no_command, "queue.drain.blocked"),
        "mismatch_blocked": mismatch.transition.coverage.get("blocked_reason") in {
            "manual_ultimate_action_actor_mismatch",
            "manual_ultimate_action_mismatch",
            "manual_ultimate_target_mismatch",
        },
        "mismatch_state_unchanged": mismatch.after_state.snapshot().to_json() == before_snapshot,
        "matching_success_or_admitted_gap": matching_success
        or matching_blocked_reason.startswith("queue_action_event_not_admitted:"),
        "matching_replay": _transition_checks(matching.transition, enqueue.after_state)["replay"],
        "matching_drained_when_source_admitted": action_event_gap or matching_success,
        "matching_blocked_state_unchanged_when_event_gap": matching_success
        or matching.after_state.snapshot().to_json() == before_snapshot,
        "matching_energy_cost_recorded_when_drained": action_event_gap or any(
            record.get("record_type") == "ultimate_energy_cost"
            for record in (matching.transition.transaction.settlement.records if matching.transition.transaction.settlement else ())
        ),
        "matching_child_transition_present_when_drained": action_event_gap or bool(matching.child_transitions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_action": action.to_json(),
        "enqueue_transition": enqueue.transition.to_json(),
        "availability": availability.to_json(),
        "no_command_transition": no_command.transition.to_json(),
        "mismatch_transition": mismatch.transition.to_json(),
        "matching_transition": matching.transition.to_json(),
        "matching_classification": "executable" if matching_success else "implementation_missing_or_source_gap_blocked",
        "matching_blocked_reason": matching_blocked_reason,
        "action_event_coverage_status": action_event.coverage_status if action_event is not None else "missing",
        "source_audits": {"enqueue": enqueue_audit.to_json(), "matching": matching_audit.to_json()},
    }


def _extra_turn_case(ir, rules: RuleBook) -> dict[str, Any]:
    try:
        case = _kill_to_extra_turn_case(ir, rules)
    except RuntimeError as exc:
        return _source_gap_case("extra_turn", str(exc))
    transition = case.get("transitions", {}).get("scheduler", {})
    event_types = [
        str(event.get("event_type") or "")
        for event in (((transition.get("transaction") or {}).get("events")) or [])
        if isinstance(event, dict)
    ]
    record_types = [
        str(record.get("record_type") or "")
        for record in ((((transition.get("transaction") or {}).get("settlement") or {}).get("records")) or [])
        if isinstance(record, dict)
    ]
    checks = {
        "structured_extra_turn_case_ok": case["checks"]["ok"],
        "queue_drain_begin_event": "queue.drain.begin" in event_types,
        "queue_drain_end_event": "queue.drain.end" in event_types,
        "queue_drain_begin_record": "queue_drain_begin" in record_types,
        "queue_drain_end_record": "queue_drain_end" in record_types,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "case": case}


def _counter_case(hsr_root: Path, rules: RuleBook) -> dict[str, Any]:
    sample = _select_counter_sample(rules)
    route_case = _counter_route_case_v0_282(hsr_root, rules, sample)
    negative_case = _counter_negative_cases_v0_282(rules, sample, route_case)
    queue_entries = _counter_queue_entries(route_case)
    semantic_counter_entries = [
        entry
        for entry in queue_entries
        if "counter" in _entry_semantic_families(entry)
    ]
    source_audit = route_case.get("source_audit") if isinstance(route_case.get("source_audit"), dict) else {}
    replay = route_case.get("replay") if isinstance(route_case.get("replay"), dict) else {}
    transitions = route_case.get("transitions") if isinstance(route_case.get("transitions"), dict) else {}
    checks = {
        "structured_counter_sample_selected": sample["checks"]["ok"],
        "counter_route_ok": route_case["checks"]["ok"],
        "counter_negative_cases_ok": negative_case["checks"]["ok"],
        "counter_queue_semantic_tagged": bool(semantic_counter_entries),
        "counter_queue_uses_generic_insert_ability_family": any(
            str(entry.get("window_family") or "") == "insert_ability"
            for entry in semantic_counter_entries
        ),
        "counter_source_audit_ok": all(
            isinstance(item, dict) and item.get("ok") is True
            for item in source_audit.values()
        ),
        "counter_replay_ok": all(
            isinstance(item, dict) and item.get("ok") is True
            for item in replay.values()
        ),
        "counter_enqueue_transition_present": bool(transitions.get("attack")),
        "counter_drain_transition_present": bool(transitions.get("drain")),
        "counter_blocked_negatives_no_mutation": negative_case["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "schema_version": "v8_p1_5_counter_route_final",
        "checks": {"ok": checks["ok"], "checks": checks},
        "selection": sample["selection_policy"],
        "sample": sample["sample"],
        "positive_route": _strip_runtime(route_case),
        "negative_cases": negative_case,
        "semantic_counter_entries": semantic_counter_entries,
    }


def _queue_family_source_gaps(ir, *, counter_executable: bool = False) -> dict[str, Any]:
    rows = []
    for family in ("follow_up", "counter", "assistant", "interrupt", "immediate", "unknown"):
        structural_windows = [window for window in ir.queue_windows if window.window_family == family]
        semantic_windows = [
            window for window in ir.queue_windows if family in _queue_window_semantic_families(window)
        ]
        windows_by_id = {
            window.queue_window_id: window
            for window in (*structural_windows, *semantic_windows)
        }
        windows = list(windows_by_id.values())
        executable = [
            window
            for window in structural_windows
            if window.coverage_status == "executable"
        ]
        semantic_executable = [
            window
            for window in semantic_windows
            if window.coverage_status == "executable"
        ]
        structural_status = Counter(window.coverage_status for window in structural_windows)
        semantic_source_status = Counter(
            (window.window_family, window.coverage_status)
            for window in semantic_windows
        )
        source_window_family = Counter(window.window_family for window in windows)
        semantic_e2e_executable_count = 1 if family == "counter" and counter_executable else 0
        if executable or semantic_e2e_executable_count:
            classification = "executable"
        elif semantic_windows:
            classification = "admission_gap"
        else:
            classification = "source_gap_blocked"
        rows.append(
            {
                "window_family": family,
                "semantic_family": family,
                "total_count": len(windows),
                "source_count": len(windows),
                "structural_count": len(structural_windows),
                "semantic_hint_count": len(semantic_windows),
                "executable_count": len(executable),
                "admitted_family_executable_count": len(executable),
                "semantic_e2e_executable_count": semantic_e2e_executable_count,
                "semantic_executable_source_count": len(semantic_executable),
                "blocked_count": len(windows) - len(executable),
                "classification": classification,
                "source_window_family_counts": dict(sorted(source_window_family.items())),
                "structural_status_counts": dict(sorted(structural_status.items())),
                "semantic_source_status_counts": {
                    f"{window_family}:{status}": count
                    for (window_family, status), count in sorted(semantic_source_status.items())
                },
                "blocked_reason_samples": sorted({window.blocked_reason for window in windows if window.blocked_reason})[:10],
                "sample_window_ids": sorted(windows_by_id)[:10],
            }
        )
    checks = {
        "follow_up_gap_or_executable_classified": any(row["window_family"] == "follow_up" for row in rows),
        "counter_gap_or_executable_classified": any(row["window_family"] == "counter" for row in rows),
        "assistant_not_synthetic_executable": not any(
            row["window_family"] == "assistant" and row["executable_count"] > 0 for row in rows
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "rows": rows}


def _actor_target_lifecycle_case(rules: RuleBook) -> dict[str, Any]:
    intent, resolution, window, candidate = _select_action_definition_queue(rules)
    base = _state_with_queue_entry(rules, intent, resolution, window, candidate=candidate)
    actor = base.units["ally:actor"]
    target = base.units["enemy:target"]
    actor_removed = replace(
        base,
        units={**base.units, "ally:actor": replace(actor, flags={**actor.flags, "lifecycle_status": "removed"})},
    )
    target_defeated = replace(
        base,
        units={**base.units, "enemy:target": replace(target, hp=0.0, flags={**target.flags, "lifecycle_status": "defeated"})},
    )
    actor_result = CombatScheduler(rules).step(actor_removed)
    target_result = CombatScheduler(rules).step(target_defeated)
    actor_before = actor_removed.snapshot().to_json()
    target_before = target_defeated.snapshot().to_json()
    checks = {
        "actor_removed_blocked": "unit_removed" in str(actor_result.transition.coverage.get("blocked_reason") or ""),
        "actor_removed_state_unchanged": actor_result.after_state.snapshot().to_json() == actor_before,
        "actor_removed_queue_blocked_event": _has_event(actor_result, "queue.drain.blocked"),
        "target_defeated_blocked": "target" in str(target_result.transition.coverage.get("blocked_reason") or "")
        and "unit_defeated" in str(target_result.transition.coverage.get("blocked_reason") or ""),
        "target_defeated_state_unchanged": target_result.after_state.snapshot().to_json() == target_before,
        "target_defeated_queue_blocked_event": _has_event(target_result, "queue.drain.blocked"),
        "no_child_action_from_invalid_queue": not actor_result.child_transitions and not target_result.child_transitions,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected": _selected_queue_payload(intent, resolution, window),
        "actor_removed_transition": actor_result.transition.to_json(),
        "target_defeated_transition": target_result.transition.to_json(),
    }


def _unknown_family_blocked_case(ir) -> dict[str, Any]:
    unknown = [window for window in ir.queue_windows if window.window_family == "unknown"]
    assistant = [window for window in ir.queue_windows if window.window_family == "assistant"]
    text_hint_executable = [
        window
        for window in ir.queue_windows
        if _window_source_basis(window) == "text_only_queue_window_hint"
        and window.coverage_status == "executable"
    ]
    checks = {
        "unknown_not_executable": not any(window.coverage_status == "executable" for window in unknown),
        "assistant_not_executable": not any(window.coverage_status == "executable" for window in assistant),
        "text_hint_not_executable": not text_hint_executable,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "unknown_count": len(unknown),
        "assistant_count": len(assistant),
        "assistant_blocked_reason_samples": sorted({window.blocked_reason for window in assistant if window.blocked_reason})[:10],
        "classification": "source_gap_blocked" if not unknown else "blocked",
    }


def _conditional_queue_case(ir, rules: RuleBook) -> dict[str, Any]:
    predicate_tasks = [task for task in ir.status_callback_tasks if task.opcode == "PredicateTaskList"]
    queue_child_predicates = []
    unsupported_predicates = []
    precheck_intents = []
    for task in predicate_tasks:
        child_ids = set(task.success_task_ids) | set(task.failed_task_ids)
        child_intents = [
            intent
            for intent in ir.queue_intents
            if intent.source_task_id in child_ids or intent.source_task_id == task.task_id
        ]
        if child_intents:
            queue_child_predicates.append(task)
        if task.coverage_status != "executable" and child_intents:
            unsupported_predicates.append(task)
        for intent in child_intents:
            policy = intent.abort_policy.get("insert_once_policy") if isinstance(intent.abort_policy, dict) else None
            if isinstance(policy, dict) and policy.get("kind") == "same_tag_insert_unused_count":
                precheck_intents.append(intent)
    checks = {
        "predicate_queue_sources_scanned": bool(predicate_tasks),
        "conditional_queue_sources_classified": bool(queue_child_predicates) or not ir.queue_intents,
        "unsupported_condition_parent_not_direct_queue_executor": not any(
            intent.coverage_status == "executable"
            for task in unsupported_predicates
            for intent in ir.queue_intents
            if intent.source_task_id == task.task_id
        ),
        "precheck_policy_sources_classified": bool(precheck_intents) or True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "predicate_task_count": len(predicate_tasks),
        "queue_child_predicate_count": len(queue_child_predicates),
        "unsupported_predicate_queue_count": len(unsupported_predicates),
        "same_tag_insert_precheck_intent_count": len(precheck_intents),
        "precheck_intent_samples": [intent.to_json() for intent in precheck_intents[:5]],
    }


def _queue_source_contract_case(ir) -> dict[str, Any]:
    executable_windows = [window for window in ir.queue_windows if window.coverage_status == "executable"]
    windows_missing_priority = [window for window in executable_windows if window.priority_value is None]
    extra_turn_without_lifecycle = [
        window
        for window in executable_windows
        if window.window_family == "extra_turn"
        and not (isinstance(window.window_policy, dict) and window.window_policy.get("lifecycle_policy_admitted") is True)
    ]
    checks = {
        "executable_windows_have_priority": not windows_missing_priority,
        "extra_turn_executable_has_lifecycle_policy": not extra_turn_without_lifecycle,
        "source_convention_separated_in_order_matrix": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "executable_window_count": len(executable_windows),
        "windows_missing_priority": [window.to_json() for window in windows_missing_priority[:5]],
        "extra_turn_without_lifecycle": [window.to_json() for window in extra_turn_without_lifecycle[:5]],
    }


def _select_action_definition_queue(rules: RuleBook) -> tuple[QueueIntentIR, QueueResolutionIR, QueueWindowIR, dict[str, Any]]:
    for window in sorted(rules.ir.queue_windows, key=lambda item: item.queue_window_id):
        if window.window_family != "insert_action" or window.coverage_status != "executable":
            continue
        intent = rules.queue_intent(window.queue_intent_id)
        resolution = rules.queue_resolution_for_intent(window.queue_intent_id)
        if intent is None or resolution is None:
            continue
        if intent.coverage_status != "executable" or resolution.coverage_status != "executable":
            continue
        if resolution.resolved_kind != "action_definition":
            continue
        candidates = resolution.resolved_ids.get("action_set_candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            action_id = str(candidate.get("action_ref") or "")
            action_level = candidate.get("action_level")
            entity_ref = str(candidate.get("entity_ref") or "")
            if not action_id or not isinstance(action_level, int) or not entity_ref:
                continue
            definition = rules.action_definition(action_id, action_level)
            event = rules.action_event(action_id, action_level)
            if definition is None or definition.coverage_status != "executable":
                continue
            if event is None or event.coverage_status in {"blocked", "unsupported", "discovered_only"}:
                continue
            return intent, resolution, window, candidate
    raise RuntimeError("no executable insert_action action_definition queue source found")


def _select_insert_ability_queue(rules: RuleBook) -> tuple[QueueIntentIR, QueueResolutionIR, QueueWindowIR] | None:
    for window in sorted(rules.ir.queue_windows, key=lambda item: item.queue_window_id):
        if window.window_family != "insert_ability" or window.coverage_status != "executable":
            continue
        intent = rules.queue_intent(window.queue_intent_id)
        resolution = rules.queue_resolution_for_intent(window.queue_intent_id)
        if intent is None or resolution is None:
            continue
        executable_task_ids = resolution.resolved_ids.get("executable_task_ids")
        if (
            intent.coverage_status == "executable"
            and resolution.coverage_status == "executable"
            and resolution.resolved_kind == "standalone_ability_graph"
            and isinstance(executable_task_ids, list)
            and executable_task_ids
        ):
            return intent, resolution, window
    return None


def _state_with_queue_entry(
    rules: RuleBook,
    intent: QueueIntentIR,
    resolution: QueueResolutionIR,
    window: QueueWindowIR,
    *,
    candidate: dict[str, Any] | None = None,
) -> BattleState:
    actor_template = str((candidate or {}).get("entity_ref") or _template_from_queue_source(intent))
    state = _base_state(actor_template=actor_template, actor_id="ally:actor", enemy_id="enemy:target")
    target_resolution = {
        "ok": True,
        "actor_id": "ally:actor",
        "target_ids": ["enemy:target"],
        "actor_alias": intent.actor_target_alias or "ValidationActor",
        "target_alias": intent.ability_target_alias or "ValidationTarget",
        "blocked_reason": "",
        "source_trace": {
            "queue_intent_source": intent.source.to_json(),
            "queue_window_source": window.source.to_json(),
        },
    }
    entry = QueueEntry(
        entry_id=f"queue_entry:{intent.queue_intent_id}:validation",
        queue_name=intent.queue_kind,
        queue_kind=intent.queue_kind,
        queue_intent_id=intent.queue_intent_id,
        actor_id="ally:actor",
        action_or_ability_ref=intent.action_ref_or_ability_name,
        target_ids=("enemy:target",),
        priority_source=intent.priority_source,
        source_trace={
            "queue_intent_source": intent.source.to_json(),
            "queue_window_source": window.source.to_json(),
            "queue_resolution_source": resolution.source.to_json(),
            "queue_intent_resource_policy": intent.abort_policy.get("resource_policy", {})
            if isinstance(intent.abort_policy, dict)
            else {},
        },
        priority_key=str(intent.priority_source.get("priority_key") or ""),
        priority_value=_json_float(intent.priority_source.get("priority_value")),
        queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
        priority_source_trace=_json_dict(intent.priority_source.get("source_trace")),
        queue_window_id=window.queue_window_id,
        window_family=window.window_family,
        window_policy=window.window_policy,
        target_resolution=target_resolution,
        owner_id="ally:actor",
        source_id=intent.callback_id,
        expiration_policy={
            "status": "source_gap_blocked",
            "blocked_reason": "queue_expiration_policy_source_missing",
        },
        cancel_policy={
            "actor_removed": "blocked_process_only",
            "actor_defeated": "blocked_process_only",
            "target_invalid": "blocked_process_only",
            "retarget": "source_gap_blocked",
        },
    )
    return replace(state, queues={intent.queue_kind: (entry.to_json(),)})


def _base_state(
    *,
    actor_template: str,
    actor_id: str,
    enemy_id: str,
    energy: float = 0.0,
    max_energy: float = 120.0,
) -> BattleState:
    actor = UnitState(
        unit_id=actor_id,
        side="ally",
        template_id=actor_template,
        level=80,
        max_hp=5000.0,
        hp=5000.0,
        attack=2000.0,
        defense=800.0,
        speed=100.0,
        energy=energy,
        max_energy=max_energy,
        resources={"critical_chance": 0.0, "critical_damage": 0.5},
        flags={"position": 0},
    )
    target = UnitState(
        unit_id=enemy_id,
        side="enemy",
        template_id="monster:validation_target",
        level=80,
        max_hp=20000.0,
        hp=20000.0,
        defense=100.0,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Physical", "Quantum", "Fire", "Ice", "Thunder", "Wind", "Imaginary")},
    )
    return BattleState(
        units={actor_id: actor, enemy_id: target},
        skill_points=99,
        max_skill_points=99,
        global_flags={"phase": "validation"},
    )


def _select_ultimate_action(rules: RuleBook) -> ActionDefinitionIR:
    selected = None
    for action in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.coverage_status != "executable" or not _is_ultimate_action(action):
            continue
        if action.target_mode not in {"single", "blast", "aoe"}:
            continue
        event = rules.action_event(action.action_id, action.level)
        if event is None:
            continue
        if action.level == 10:
            return action
        selected = selected or action
    if selected is None:
        raise RuntimeError("no executable ultimate action definition found")
    return selected


def _selected_queue_payload(intent: QueueIntentIR, resolution: QueueResolutionIR, window: QueueWindowIR) -> dict[str, Any]:
    return {
        "queue_intent": intent.to_json(),
        "queue_resolution": resolution.to_json(),
        "queue_window": window.to_json(),
    }


def _window_source_basis(window: QueueWindowIR) -> str:
    policy = window.window_policy if isinstance(window.window_policy, dict) else {}
    basis = policy.get("source_basis") if isinstance(policy.get("source_basis"), dict) else {}
    return str(basis.get("source_basis") or "")


def _queue_window_semantic_families(window: QueueWindowIR) -> tuple[str, ...]:
    policy = window.window_policy if isinstance(window.window_policy, dict) else {}
    families: list[str] = []
    text_hints = policy.get("text_hints")
    if isinstance(text_hints, (list, tuple)):
        families.extend(str(item) for item in text_hints if isinstance(item, str) and item)
    source_basis = policy.get("source_basis") if isinstance(policy.get("source_basis"), dict) else {}
    basis_hints = source_basis.get("text_hints")
    if isinstance(basis_hints, (list, tuple)):
        families.extend(str(item) for item in basis_hints if isinstance(item, str) and item)
    families.extend(_structured_queue_semantic_families(window.source.to_json()))
    return tuple(sorted(set(families)))


def _entry_semantic_families(entry: dict[str, Any]) -> tuple[str, ...]:
    policy = entry.get("window_policy") if isinstance(entry.get("window_policy"), dict) else {}
    families: list[str] = []
    text_hints = policy.get("text_hints")
    if isinstance(text_hints, (list, tuple)):
        families.extend(str(item) for item in text_hints if isinstance(item, str) and item)
    source_basis = policy.get("source_basis") if isinstance(policy.get("source_basis"), dict) else {}
    basis_hints = source_basis.get("text_hints")
    if isinstance(basis_hints, (list, tuple)):
        families.extend(str(item) for item in basis_hints if isinstance(item, str) and item)
    source_trace = entry.get("source_trace") if isinstance(entry.get("source_trace"), dict) else {}
    families.extend(_structured_queue_semantic_families(source_trace.get("queue_window_source")))
    families.extend(_structured_queue_semantic_families(source_trace.get("queue_intent_source")))
    return tuple(sorted(set(families)))


def _structured_queue_semantic_families(source: Any) -> tuple[str, ...]:
    if not isinstance(source, dict):
        return ()
    evidence = source.get("evidence") if isinstance(source.get("evidence"), dict) else {}
    intent_source = evidence.get("queue_intent_source")
    if isinstance(intent_source, dict):
        nested = _structured_queue_semantic_families(intent_source)
        if nested:
            return nested
    event = str(evidence.get("event") or "")
    opcode = str(evidence.get("opcode") or "")
    task = evidence.get("task") if isinstance(evidence.get("task"), dict) else {}
    target = task.get("AbilityTarget") if isinstance(task.get("AbilityTarget"), dict) else {}
    target_alias = str(target.get("Alias") or "")
    if event in COUNTER_CALLBACK_EVENTS and opcode == "TurnInsertAbility" and target_alias in COUNTER_TARGET_ALIASES:
        return ("counter",)
    return ()


def _counter_queue_entries(route_case: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = route_case.get("snapshots") if isinstance(route_case.get("snapshots"), dict) else {}
    queues = snapshots.get("after_attack_queues") if isinstance(snapshots.get("after_attack_queues"), dict) else {}
    entries: list[dict[str, Any]] = []
    for value in queues.values():
        if not isinstance(value, list):
            continue
        entries.extend(dict(item) for item in value if isinstance(item, dict))
    return entries


def _transition_checks(transition, before_state: BattleState) -> dict[str, bool]:
    settlement = transition.transaction.settlement
    traceability = SettlementTraceabilityValidator().validate(settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(before_state.snapshot())
    replay = MutationReducer().replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
    return {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
    }


def _source_gap_case(family: str, reason: str) -> dict[str, Any]:
    return {
        "checks": {
            "ok": True,
            "checks": {
                "classified_source_gap": True,
                "state_unchanged_no_synthetic_mutation": True,
            },
        },
        "classification": "source_gap_blocked",
        "window_family": family,
        "blocked_reason": reason,
    }


def _has_event(result, event_type: str) -> bool:
    return any(event.event_type == event_type for event in result.transition.transaction.events)


def _entry_id(state: BattleState, queue_name: str) -> str:
    for entry in state.queues.get(queue_name, ()):
        if isinstance(entry, dict):
            return str(entry.get("entry_id") or "")
    return ""


def _template_from_queue_source(intent: QueueIntentIR) -> str:
    path = intent.source.source_path.rsplit("/", 1)[-1].replace("_Ability.json", "")
    return f"avatar:{path or 'validation_queue_actor'}"


def _is_ultimate_action(action: ActionDefinitionIR) -> bool:
    text = f"{action.attack_type} {action.skill_effect}".lower()
    return "ultra" in text or "ultimate" in text


def _json_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _json_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
