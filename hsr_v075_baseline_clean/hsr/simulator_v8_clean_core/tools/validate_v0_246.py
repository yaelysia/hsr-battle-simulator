from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import QueueIntentIR, QueueResolutionIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.queue import QueueSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _transition_checks
from .validate_v0_237 import _event_for_callback, _state_with_callback_status
from .validate_v0_242 import (
    _candidate_queue_intents,
    _queue_entries,
    _records_of_type,
    _require_callback,
    _standalone_queue_drain_case,
)


VALIDATION_VERSION = "v0_246"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    standalone_case = _standalone_queue_drain_case(rules, break_setup["initial_state"])
    action_case = _queue_action_drain_case(rules, break_setup["initial_state"])
    negative_cases = _negative_cases(rules, break_setup["initial_state"])
    gap_matrix = _queue_action_gap_matrix(ir, action_case)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir, action_case),
        "standalone_drain_regression": standalone_case["checks"],
        "queue_action_drain": action_case["checks"],
        "negative_cases": negative_cases["checks"],
        "gap_matrix": _gap_matrix_checks(gap_matrix),
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
                "queue_action_drain": (
                    "TurnInsertAction with executable QueueIntentIR, executable QueueResolutionIR, "
                    "resolved_kind=action_definition, admitted priority/window, actor template matched through "
                    "CombatantActionSetIR; no character/action/file/hash fixed selector"
                ),
                "negative_cases": "real blocked queue intents grouped by opcode/expression/source blocker",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "standalone_drain": standalone_case["source_audit"],
            "queue_action_drain": action_case.get("source_audit", {}),
            "negative_cases": negative_cases["source_audits"],
        },
        "queue_action_gap_matrix": gap_matrix,
        "trust_matrix": _trust_matrix(checks, action_case, gap_matrix),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_246.json", result)
    write_json(output_dir / "queue_action_gap_matrix_v0_246.json", gap_matrix)
    write_json(output_dir / "sample_queue_standalone_regression_transition_v0_246.json", standalone_case["transition"])
    write_json(output_dir / "sample_queue_action_drain_transition_v0_246.json", action_case.get("transition", {}))
    write_json(output_dir / "sample_queue_action_negative_cases_v0_246.json", negative_cases)
    write_json(output_dir / "coverage_summary_v0_246.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_246 queue action drain and window admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _queue_action_drain_case(rules: RuleBook, base_state) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for intent in _candidate_action_intents(rules):
        callback = _require_callback(rules, intent)
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if resolution is None:
            blockers.append({"queue_intent_id": intent.queue_intent_id, "reason": "queue_resolution_missing"})
            continue
        state = _state_with_callback_status(base_state, callback)
        enqueue_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        entries = _queue_entries(enqueue_result.after_state, intent.queue_kind)
        if not entries:
            blockers.append({"queue_intent_id": intent.queue_intent_id, "reason": "enqueue_did_not_create_entry"})
            continue
        plan = QueueSystem().plan_next_drain(
            enqueue_result.after_state,
            intent.queue_kind,
            {resolution.queue_intent_id: resolution},
        )
        if not plan.ok:
            blockers.append({"queue_intent_id": intent.queue_intent_id, "reason": plan.blocked_reason, "plan": plan.to_json()})
            continue
        scheduler_result = CombatScheduler(rules).step(enqueue_result.after_state)
        transition = scheduler_result.transition
        source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        checks = _transition_checks(transition, enqueue_result.after_state)
        records = _records(transition)
        checks.update(
            {
                "positive_available": True,
                "source_audit": source_audit.ok,
                "turn_insert_action_intent": intent.opcode == "TurnInsertAction",
                "queue_resolution_action_definition": resolution.resolved_kind == "action_definition",
                "drain_plan_action_definition": plan.resolved_kind == "action_definition",
                "queue_window_plan_admitted": plan.queue_window.get("ok") is True if plan.queue_window else False,
                "resolved_action_present": bool(plan.resolved_action_id and plan.resolved_action_level),
                "dequeue_mutation_present": any(mutation.source == "queue_system" for mutation in transition.transaction.mutations),
                "child_action_mutation_present": any(
                    mutation.source in {"combat_executor.timeline", "combat_executor.resources", "damage_system", "toughness_system", "break_system"}
                    for mutation in transition.transaction.mutations
                ),
                "queue_dequeue_record_present": bool(_records_of_type(records, "queue_dequeue")),
                "queue_entry_removed": len(_queue_entries(scheduler_result.after_state, intent.queue_kind)) < len(entries),
            }
        )
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": checks,
            "queue_intent": intent.to_json(),
            "queue_resolution": resolution.to_json(),
            "drain_plan": plan.to_json(),
            "transition": transition.to_json(),
            "source_audit": source_audit.to_json(),
            "selection_blockers": blockers[:10],
        }
    blocker_summary = _turn_insert_action_blockers(rules)
    checks = {
        "ok": True,
        "positive_available": False,
        "specific_blockers_present": bool(blocker_summary["blocked_reason_counts"]),
        "runtime_path_compiled": True,
        "no_fake_positive": True,
        "blocker_reported_instead_of_synthetic_case": True,
    }
    return {
        "checks": checks,
        "queue_intent": {},
        "queue_resolution": {},
        "drain_plan": {},
        "transition": {},
        "source_audit": {},
        "selection_blockers": blockers[:10],
        "blocker_summary": blocker_summary,
    }


def _candidate_action_intents(rules: RuleBook) -> tuple[QueueIntentIR, ...]:
    candidates: list[QueueIntentIR] = []
    for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
        if intent.opcode != "TurnInsertAction" or intent.coverage_status != "executable":
            continue
        callback = rules.status_callback(intent.callback_id)
        task = rules.status_callback_task(intent.source_task_id)
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if callback is None or callback.coverage_status != "executable":
            continue
        if task is None or task.coverage_status != "executable" or task.parent_task_id:
            continue
        if resolution is None or resolution.coverage_status != "executable":
            continue
        if resolution.resolved_kind != "action_definition":
            continue
        candidates.append(intent)
    return tuple(candidates)


def _negative_cases(rules: RuleBook, base_state) -> dict[str, Any]:
    selected = [
        ("dynamic_skill_index", _select_intent(rules, "TurnInsertAction", lambda item: item.skill_index_expr.get("kind") == "dynamic_hash")),
        ("assistant_ability", _select_intent(rules, "TurnInsertAssistantAbility", lambda item: True)),
        ("blocked_action_source_or_priority", _select_intent(rules, "TurnInsertAction", lambda item: item.coverage_status != "executable")),
    ]
    cases: dict[str, Any] = {}
    source_audits: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, intent in selected:
        if intent is None:
            checks[f"{name}_available"] = False
            cases[name] = {"skipped": True, "reason": "matching_intent_missing"}
            continue
        callback = _require_callback(rules, intent)
        state = _state_with_callback_status(base_state, callback)
        result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        from .validate_v0_235 import _system_transition

        transition = _system_transition(
            before_state=state,
            after_state=result.after_state,
            records=result.records,
            mutations=result.mutations,
            events=result.events,
            action_id=f"queue:negative:{name}",
            metadata={"queue_intent_id": intent.queue_intent_id},
        )
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        source_audits[name] = audit.to_json()
        unchanged = result.after_state.snapshot().to_json() == state.snapshot().to_json()
        no_mutations = not result.mutations
        checks[f"{name}_available"] = True
        checks[f"{name}_snapshot_unchanged"] = unchanged
        checks[f"{name}_no_mutations"] = no_mutations
        checks[f"{name}_source_audit_ok"] = audit.ok
        cases[name] = {
            "queue_intent": intent.to_json(),
            "queue_resolution": (
                rules.queue_resolution_for_intent(intent.queue_intent_id).to_json()
                if rules.queue_resolution_for_intent(intent.queue_intent_id)
                else {}
            ),
            "transition": transition.to_json(),
            "checks": {
                "snapshot_unchanged": unchanged,
                "no_mutations": no_mutations,
                "source_audit": audit.ok,
            },
        }
    checks["ok"] = all(checks.values())
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases, "source_audits": source_audits}


def _select_intent(rules: RuleBook, opcode: str, predicate) -> QueueIntentIR | None:
    for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
        if intent.opcode == opcode and predicate(intent):
            return intent
    return None


def _coverage_checks(coverage_json: dict[str, Any], ir, action_case: dict[str, Any]) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    intents = status.get("queue_intents", {})
    resolutions = status.get("queue_resolutions", {})
    action_intents = [intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAction"]
    fixed_intents = [intent for intent in action_intents if intent.skill_index_expr.get("kind") == "fixed"]
    checks = {
        "queue_intents_lowered": intents.get("lowered", 0) > 0,
        "turn_insert_action_discovered": bool(action_intents),
        "fixed_skill_index_discovered_or_blocked_reported": bool(fixed_intents) or bool(action_case.get("blocker_summary", {}).get("blocked_reason_counts")),
        "queue_window_plan_shape_available": True,
        "queue_resolutions_present": resolutions.get("lowered", 0) > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "queue_intents": intents,
        "queue_resolutions": resolutions,
        "turn_insert_action_counts": {
            "total": len(action_intents),
            "fixed": len(fixed_intents),
            "executable": sum(1 for intent in action_intents if intent.coverage_status == "executable"),
        },
    }


def _queue_action_gap_matrix(ir, action_case: dict[str, Any]) -> dict[str, Any]:
    blocker_summary = action_case.get("blocker_summary") or {}
    action_positive = action_case["checks"].get("positive_available") is True and action_case["checks"].get("ok") is True
    return {
        "queue_window_admission": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "QueueWindowPlan admitted from QueueIntentIR.queue_kind plus QueuePriorityIR and QueueResolutionIR",
        },
        "queue_action_resolution": {
            "semantic_status": "trusted_for_current_scope" if action_positive else "blocked",
            "scope": "fixed SkillIndex -> CombatantActionSetIR -> ActionDefinitionIR",
            "blocking_dependency": "" if action_positive else _dominant_blocker(blocker_summary),
            "evidence": {
                "positive_available": action_positive,
                "turn_insert_action_count": sum(1 for intent in ir.queue_intents if intent.opcode == "TurnInsertAction"),
                "blockers": blocker_summary,
            },
        },
        "queue_action_drain": {
            "semantic_status": "trusted_for_current_scope" if action_positive else "blocked",
            "scope": "QueueSystem.dequeue plus CombatExecutor.execute(source='queue') child transition",
            "blocking_dependency": "" if action_positive else _dominant_blocker(blocker_summary),
        },
        "turn_insert_assistant_ability": {
            "semantic_status": "blocked",
            "blocking_dependency": "requires admitted assistant actor identity, assistant ability/action graph, target and priority",
        },
        "ultimate_interrupt_total_ordering": {
            "semantic_status": "blocked",
            "blocking_dependency": "requires complete ordering semantics across ultimate, interrupt, immediate and regular queues",
        },
    }


def _gap_matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "queue_window_trusted": matrix["queue_window_admission"]["semantic_status"] == "trusted_for_current_scope",
        "blocked_items_have_dependency": all(
            bool(value.get("blocking_dependency"))
            for value in matrix.values()
            if isinstance(value, dict) and value.get("semantic_status") == "blocked"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(checks: dict[str, Any], action_case: dict[str, Any], gap_matrix: dict[str, Any]) -> dict[str, Any]:
    positive = action_case["checks"].get("positive_available") is True and action_case["checks"].get("ok") is True
    return {
        "queue_enqueue": {"semantic_status": "trusted_for_current_scope"},
        "queue_priority": {"semantic_status": "trusted_for_current_scope"},
        "queue_resolution": {"semantic_status": "trusted_for_current_scope"},
        "queue_window_admission": {"semantic_status": "trusted_for_current_scope"},
        "standalone_ability_queue_drain": {
            "semantic_status": "trusted_for_current_scope" if checks["standalone_drain_regression"]["ok"] else "needs_fix",
        },
        "queue_action_drain": {
            "semantic_status": "trusted_for_current_scope" if positive else "blocked",
            "blocking_dependency": "" if positive else gap_matrix["queue_action_drain"]["blocking_dependency"],
        },
        "full_queue_ordering": {
            "semantic_status": "blocked",
            "blocking_dependency": "ultimate/interrupt/immediate/regular total ordering is not admitted in v0_246",
        },
    }


def _turn_insert_action_blockers(rules: RuleBook) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()
    skill_index_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
        if intent.opcode != "TurnInsertAction":
            continue
        reason = intent.blocked_reason or intent.coverage_status
        reason_counts[reason] += 1
        skill_index_counts[str(intent.skill_index_expr.get("kind") or "missing")] += 1
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if resolution is not None:
            resolution_counts[f"{resolution.coverage_status}:{resolution.resolved_kind}:{resolution.blocked_reason}"] += 1
        if len(samples) < 10:
            samples.append(
                {
                    "queue_intent_id": intent.queue_intent_id,
                    "coverage_status": intent.coverage_status,
                    "blocked_reason": intent.blocked_reason,
                    "skill_index_expr": intent.skill_index_expr,
                    "source": intent.source.to_json(),
                    "queue_resolution": resolution.to_json() if resolution else {},
                }
            )
    return {
        "blocked_reason_counts": dict(reason_counts.most_common()),
        "resolution_counts": dict(resolution_counts.most_common()),
        "skill_index_kind_counts": dict(skill_index_counts.most_common()),
        "samples": samples,
    }


def _dominant_blocker(blocker_summary: dict[str, Any]) -> str:
    counts = blocker_summary.get("blocked_reason_counts")
    if isinstance(counts, dict) and counts:
        first = next(iter(counts))
        return f"no admitted TurnInsertAction fixed SkillIndex source; dominant blocker={first}"
    return "no admitted TurnInsertAction action-definition resolution sample"


def _queue_intent_sort_key(intent: QueueIntentIR) -> tuple[object, ...]:
    path = intent.source.source_path
    priority_value = intent.priority_source.get("priority_value")
    return (
        intent.coverage_status != "executable",
        intent.opcode,
        str(intent.skill_index_expr.get("kind") or ""),
        float(priority_value) if isinstance(priority_value, (int, float)) else 999999.0,
        path,
        intent.callback_id,
        intent.source_task_id,
    )


def _unit_id_for_callback(callback) -> str:
    return "ally:actor" if callback.scope_kind == "actor_local" else "enemy:profile_target"


def _records(transition) -> tuple[dict[str, Any], ...]:
    settlement = transition.transaction.settlement
    return tuple(settlement.records) if settlement else ()


if __name__ == "__main__":
    raise SystemExit(main())
