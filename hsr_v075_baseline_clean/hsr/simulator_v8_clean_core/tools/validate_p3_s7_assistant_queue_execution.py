from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue
from ..rules.ir import AssistantAbilityResolutionIR, QueueIntentIR, QueueResolutionIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.queue import QueueEntry, QueueSystem
from ..tbgd.lowering import (
    TBGDLowering,
    _lower_assistant_ability_resolutions,
    _queue_intent_admission,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p3_s0_summon_source_inventory import (
    _assistant_source_matrix,
    _raw_ability_source_matrix,
    _sample_item,
    _source_trace_sample,
)
from .validate_v0_287 import _counter_top


VALIDATION_VERSION = "p3_s7_assistant_queue_execution"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    raw_sources = _raw_ability_source_matrix(tbgd_root)
    source_matrix = _assistant_source_matrix(raw_sources, ir, rules)
    groups = {
        "assistant_source_layers": _assistant_source_layers_case(raw_sources, source_matrix, rules),
        "assistant_queue_window_consistency": _assistant_queue_window_consistency_case(rules),
        "assistant_scope_negative_cases": _assistant_scope_negative_cases(rules),
        "assistant_queue_drain_boundary": _assistant_queue_drain_boundary_case(rules),
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
                "mode": "structured_assistant_raw_ir_rulebook_queue_boundary_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "validation_only_negative_variants": True,
            },
        },
        "summary": {
            "assistant_raw_count": source_matrix["raw_count"],
            "assistant_queue_intent_ir_count": source_matrix["queue_intent_ir_count"],
            "assistant_resolution_ir_count": source_matrix["assistant_resolution_ir_count"],
            "assistant_queue_window_ir_count": source_matrix["assistant_queue_window_ir_count"],
            "assistant_executable_resolution_count": source_matrix["resolution_coverage_status_counts"].get("executable", 0),
            "assistant_executable_window_count": source_matrix["queue_window_coverage_status_counts"].get("executable", 0),
            "classification": groups["assistant_source_layers"]["classification"],
            "negative_case_count": groups["assistant_scope_negative_cases"]["negative_case_count"],
            "queue_drain_classification": groups["assistant_queue_drain_boundary"]["classification"],
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s7_assistant_queue_execution.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S7 assistant queue/window and execution boundaries.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _assistant_source_layers_case(
    raw_sources: dict[str, Any],
    source_matrix: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    intents = _assistant_intents(rules)
    resolutions = rules.assistant_ability_resolutions()
    raw_count = int(raw_sources["summary"]["opcode_counts"].get("TurnInsertAssistantAbility", 0) or 0)
    reason_counts = Counter(token for resolution in resolutions for token in _reason_tokens(resolution.blocked_reason))
    attribution_blocked = [
        resolution
        for resolution in resolutions
        if resolution.attribution_policy.get("kind") == "blocked"
        and _source_blocked(resolution.attribution_policy.get("actor_source"), "assistant_actor_source_not_admitted")
        and _source_blocked(resolution.attribution_policy.get("stat_source"), "assistant_stats_source_not_admitted")
        and _source_blocked(resolution.attribution_policy.get("action_graph_source"), "assistant_action_graph_source_not_admitted")
    ]
    source_present = raw_count > 0
    checks = {
        "raw_to_ir_projection_present_or_absent_consistent": (
            source_present
            and bool(intents)
            and len(resolutions) == len(intents)
            and source_matrix["rulebook_visible_count"] == len(resolutions)
        )
        or (not source_present and not intents and not resolutions),
        "all_assistant_intents_blocked": not any(intent.coverage_status == "executable" for intent in intents),
        "all_assistant_resolutions_blocked": not any(
            resolution.coverage_status == "executable" for resolution in resolutions
        ),
        "assistant_actor_source_gap_explicit": not resolutions
        or all("assistant_actor_source_not_admitted" in _reason_tokens(item.blocked_reason) for item in resolutions),
        "assistant_stats_source_gap_explicit": not resolutions
        or all("assistant_stats_source_not_admitted" in _reason_tokens(item.blocked_reason) for item in resolutions),
        "assistant_action_graph_gap_explicit": not resolutions
        or all("assistant_action_graph_source_not_admitted" in _reason_tokens(item.blocked_reason) for item in resolutions),
        "no_assistant_graph_resolved_without_source": not any(item.resolved_graph_id for item in resolutions),
        "attribution_policy_process_blocked": len(attribution_blocked) == len(resolutions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    first_resolution = resolutions[0] if resolutions else None
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "out_of_scope" if source_present else "source_absent_not_required",
        "raw_count": raw_count,
        "queue_intent_count": len(intents),
        "assistant_resolution_count": len(resolutions),
        "scope_exclusion_reason": (
            "TurnInsertAssistantAbility targets the AssistantAvatar / avatar assistant ability system, "
            "which is no longer part of P3 summon monster or servant acceptance."
        )
        if source_present
        else "",
        "coverage_status_counts": {
            "intent": dict(sorted(Counter(intent.coverage_status for intent in intents).items())),
            "resolution": dict(sorted(Counter(item.coverage_status for item in resolutions).items())),
        },
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "sample_source_trace": _source_trace_sample(first_resolution.source if first_resolution is not None else None),
        "sample_resolution": _sample_item(first_resolution),
    }


def _assistant_queue_window_consistency_case(rules: RuleBook) -> dict[str, Any]:
    intents = _assistant_intents(rules)
    rows = []
    blocked_intent_executable_windows = []
    executable_windows = []
    executable_resolutions = []
    missing_resolution = []
    missing_window = []
    wrong_family = []
    for intent in intents:
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        window = rules.queue_window_for_intent(intent.queue_intent_id)
        if resolution is None:
            missing_resolution.append(intent.queue_intent_id)
        elif resolution.coverage_status == "executable":
            executable_resolutions.append(resolution.queue_resolution_id)
        if window is None:
            missing_window.append(intent.queue_intent_id)
        else:
            if window.window_family != "assistant":
                wrong_family.append(window.queue_window_id)
            if window.coverage_status == "executable":
                executable_windows.append(window.queue_window_id)
            if intent.coverage_status != "executable" and window.coverage_status == "executable":
                blocked_intent_executable_windows.append(window.queue_window_id)
        rows.append(
            {
                "queue_intent_id": intent.queue_intent_id,
                "intent_status": intent.coverage_status,
                "intent_blocked_reason": intent.blocked_reason,
                "queue_resolution_id": resolution.queue_resolution_id if resolution is not None else "",
                "resolution_status": resolution.coverage_status if resolution is not None else "missing",
                "resolution_kind": resolution.resolved_kind if resolution is not None else "",
                "resolution_blocked_reason": resolution.blocked_reason if resolution is not None else "",
                "queue_window_id": window.queue_window_id if window is not None else "",
                "window_family": window.window_family if window is not None else "",
                "window_status": window.coverage_status if window is not None else "missing",
                "window_blocked_reason": window.blocked_reason if window is not None else "",
            }
        )
    checks = {
        "assistant_intents_have_resolution": not missing_resolution,
        "assistant_intents_have_window": not missing_window,
        "assistant_windows_are_assistant_family": not wrong_family,
        "blocked_intent_has_no_executable_window": not blocked_intent_executable_windows,
        "assistant_windows_not_executable": not executable_windows,
        "assistant_queue_resolutions_not_executable": not executable_resolutions,
        "blocked_assistant_intent_does_not_generate_downstream_executable_ir": not blocked_intent_executable_windows
        and not executable_windows
        and not executable_resolutions,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only" if intents else "source_absent_not_required",
        "assistant_intent_count": len(intents),
        "rows": rows[:12],
        "missing_resolution": missing_resolution[:20],
        "missing_window": missing_window[:20],
        "executable_resolution_ids": executable_resolutions[:20],
        "executable_window_ids": executable_windows[:20],
    }


def _assistant_scope_negative_cases(rules: RuleBook) -> dict[str, Any]:
    first = _first_assistant_intent(rules)
    if first is None:
        return {
            "checks": {"ok": True, "checks": {"assistant_sources_absent": True}},
            "classification": "source_absent_not_required",
            "negative_case_count": 0,
            "cases": {},
        }
    cases = {
        "missing_owner_alias": _admission_result_case(
            first,
            actor_target_alias=None,
            ability_target_alias="AbilityTargetEntity",
            priority_source=_admitted_priority_source(first),
            expected_reason="queue_actor_target_alias_not_admitted:missing",
        ),
        "target_alias_unsupported": _admission_result_case(
            first,
            actor_target_alias="Caster",
            ability_target_alias="UnsupportedAssistantTarget",
            priority_source=_admitted_priority_source(first),
            expected_reason="queue_ability_target_alias_not_admitted:UnsupportedAssistantTarget",
        ),
        "priority_missing": _admission_result_case(
            first,
            actor_target_alias="Caster",
            ability_target_alias="AbilityTargetEntity",
            priority_source={},
            expected_reason="queue_priority_not_admitted",
        ),
        "dynamic_ability_id": _dynamic_assistant_ability_case(first),
        "missing_actor_source": _real_resolution_reason_case(
            rules,
            expected_reason="assistant_actor_source_not_admitted",
        ),
        "missing_stats_source": _real_resolution_reason_case(
            rules,
            expected_reason="assistant_stats_source_not_admitted",
        ),
        "missing_action_graph_source": _real_resolution_reason_case(
            rules,
            expected_reason="assistant_action_graph_source_not_admitted",
        ),
    }
    checks = {f"{name}_blocked": case["ok"] for name, case in cases.items()}
    checks["all_negative_cases_blocked"] = all(case["ok"] for case in cases.values())
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "negative_case_count": len(cases),
        "cases": cases,
    }


def _assistant_queue_drain_boundary_case(rules: RuleBook) -> dict[str, Any]:
    bundle = _first_assistant_bundle(rules)
    if bundle is None:
        return {
            "checks": {"ok": True, "checks": {"assistant_sources_absent": True}},
            "classification": "source_absent_not_required",
            "drain_plan": {},
            "availability": {},
        }
    intent, resolution, window = bundle
    state = _state_with_assistant_queue_entry(intent, window)
    before = state.snapshot().to_json()
    plan = QueueSystem().plan_next_drain(state, intent.queue_kind, {intent.queue_intent_id: resolution})
    availability = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    checks = {
        "queue_entry_present": bool(state.queues.get(intent.queue_kind)),
        "queue_drain_blocked": not plan.ok,
        "queue_drain_reason_from_assistant_source_gate": _assistant_queue_gate_reason(plan.blocked_reason),
        "availability_blocked": availability.mode == "blocked",
        "availability_has_no_choices": not availability.choices,
        "availability_has_no_selectable_window": not availability.selectable_windows,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "queue_intent_id": intent.queue_intent_id,
        "queue_resolution_id": resolution.queue_resolution_id,
        "queue_window_id": window.queue_window_id,
        "drain_plan": plan.to_json(),
        "availability": {
            "mode": availability.mode,
            "ordinary_input_blocked_reason": availability.ordinary_input_blocked_reason,
            "queue": availability.queue.to_json(),
            "blocked_reasons": [item.reason for item in availability.blocked],
            "choice_count": len(availability.choices),
            "selectable_window_count": len(availability.selectable_windows),
        },
    }


def _admission_result_case(
    intent: QueueIntentIR,
    *,
    actor_target_alias: str | None,
    ability_target_alias: str | None,
    priority_source: dict[str, JSONValue],
    expected_reason: str,
) -> dict[str, Any]:
    status, reason = _queue_intent_admission(
        task={},
        opcode="TurnInsertAssistantAbility",
        source=intent.source,
        actor_target_alias=actor_target_alias,
        ability_target_alias=ability_target_alias,
        ability_name="",
        skill_index_expr={"kind": "fixed", "value": 1, "source_field": "ValidationFixedAssistantAbility"},
        priority_source=priority_source,
        abort_policy={},
    )
    return {
        "ok": status == "blocked" and reason == expected_reason,
        "coverage_status": status,
        "blocked_reason": reason,
        "expected_reason": expected_reason,
    }


def _dynamic_assistant_ability_case(intent: QueueIntentIR) -> dict[str, Any]:
    variant = replace(
        intent,
        skill_index_expr={
            "kind": "dynamic",
            "source_field": "ValidationDynamicAssistantAbility",
            "validation_only": True,
        },
    )
    resolutions = _lower_assistant_ability_resolutions([variant], [])
    resolution = resolutions[0] if resolutions else None
    reason = resolution.blocked_reason if resolution is not None else "assistant_resolution_missing"
    return {
        "ok": resolution is not None
        and resolution.coverage_status == "blocked"
        and "assistant_ability_id_missing_or_dynamic" in _reason_tokens(reason),
        "coverage_status": resolution.coverage_status if resolution is not None else "missing",
        "blocked_reason": reason,
        "assistant_ability_id": resolution.assistant_ability_id if resolution is not None else "",
        "validation_only": True,
    }


def _real_resolution_reason_case(rules: RuleBook, *, expected_reason: str) -> dict[str, Any]:
    resolutions = rules.assistant_ability_resolutions()
    matches = [
        resolution.assistant_resolution_id
        for resolution in resolutions
        if expected_reason in _reason_tokens(resolution.blocked_reason)
    ]
    return {
        "ok": bool(resolutions) and len(matches) == len(resolutions),
        "coverage_status": "blocked" if matches else "missing",
        "blocked_reason": expected_reason,
        "matched_count": len(matches),
        "resolution_count": len(resolutions),
        "sample_resolution_id": matches[0] if matches else "",
    }


def _state_with_assistant_queue_entry(intent: QueueIntentIR, window: QueueWindowIR) -> BattleState:
    entry = QueueEntry(
        entry_id=f"validation_assistant_queue_entry:{intent.queue_intent_id}",
        queue_name=intent.queue_kind,
        queue_kind=intent.queue_kind,
        queue_intent_id=intent.queue_intent_id,
        actor_id="assistant:validation_missing_actor",
        action_or_ability_ref=intent.action_ref_or_ability_name,
        target_ids=("enemy:validation_target",),
        priority_source=intent.priority_source,
        source_trace={
            "queue_intent_source": intent.source.to_json(),
            "queue_window_source": window.source.to_json(),
            "validation_only": True,
        },
        priority_key=str(intent.priority_source.get("priority_key") or ""),
        priority_value=_json_float(intent.priority_source.get("priority_value")),
        queue_priority_id=str(intent.priority_source.get("queue_priority_id") or ""),
        priority_source_trace=_json_dict(intent.priority_source.get("source_trace")),
        queue_window_id=window.queue_window_id,
        window_family=window.window_family,
        window_policy=window.window_policy,
        target_resolution={
            "ok": False,
            "actor_id": "assistant:validation_missing_actor",
            "target_ids": ["enemy:validation_target"],
            "actor_alias": intent.actor_target_alias or "",
            "target_alias": intent.ability_target_alias or "",
            "blocked_reason": "assistant_target_resolution_not_admitted_current_scope",
            "validation_only": True,
        },
        owner_id="assistant:validation_owner",
        source_id=intent.callback_id,
        expiration_policy={},
        cancel_policy={},
        status="pending",
        drain_status="not_admitted",
    )
    return BattleState(
        global_flags={"phase": "combat", "current_window": "queue"},
        queues={intent.queue_kind: (entry.to_json(),)},
    )


def _assistant_intents(rules: RuleBook) -> tuple[QueueIntentIR, ...]:
    return tuple(
        sorted(
            (intent for intent in rules.ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility"),
            key=lambda item: item.queue_intent_id,
        )
    )


def _first_assistant_intent(rules: RuleBook) -> QueueIntentIR | None:
    intents = _assistant_intents(rules)
    return intents[0] if intents else None


def _first_assistant_bundle(rules: RuleBook) -> tuple[QueueIntentIR, QueueResolutionIR, QueueWindowIR] | None:
    for intent in _assistant_intents(rules):
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        window = rules.queue_window_for_intent(intent.queue_intent_id)
        if resolution is not None and window is not None:
            return intent, resolution, window
    return None


def _admitted_priority_source(intent: QueueIntentIR) -> dict[str, JSONValue]:
    source = dict(intent.priority_source)
    if source.get("priority_ordering_admitted") is True:
        return source
    return {
        "queue_priority_id": "validation_assistant_priority",
        "priority_key": "validation_assistant_priority",
        "priority_value": 0.0,
        "priority_ordering_admitted": True,
        "source_trace": {"validation_only": True},
    }


def _reason_tokens(reason: str) -> tuple[str, ...]:
    return tuple(item for item in (part.strip() for part in str(reason or "").split(";")) if item)


def _assistant_queue_gate_reason(reason: str) -> bool:
    text = str(reason or "")
    return bool(text) and any(
        token in text
        for token in (
            "queue_actor_target_alias_not_admitted",
            "queue_ability_target_alias_not_admitted",
            "queue_priority_not_admitted",
            "queue_insert_assistant_ability_not_admitted",
            "assistant_actor_source_not_admitted",
            "assistant_stats_source_not_admitted",
            "assistant_action_graph_source_not_admitted",
        )
    )


def _source_blocked(value: Any, expected_reason: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("coverage_status") == "blocked"
        and value.get("blocked_reason") == expected_reason
    )


def _json_dict(value: Any) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


def _json_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
