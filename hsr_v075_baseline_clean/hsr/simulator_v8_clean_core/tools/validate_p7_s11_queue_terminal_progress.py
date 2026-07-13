from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, Mutation
from ..core.compact_state import CompactStateQuery
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.ir import QueueIntentIR, QueuePriorityIR, QueueResolutionIR, QueueWindowIR
from ..rules.rulebook import RuleBook
from ..systems.ability import AbilityTaskExecutionResult
from ..systems.queue import QUEUE_DRAIN_STEP_BUDGET, QueueEntry, QueueSystem
from ..systems.scheduler import CombatScheduler, select_next_queue_drain_plan
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s11_queue_terminal_progress"
MATRIX_SCHEMA_VERSION = "p7_s11_queue_terminal_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    rules = _queue_rulebook()
    invalid_actor = _invalid_head_then_valid_case(rules)
    invalid_target = _single_terminal_case(rules, "invalid_target")
    source_status = _single_terminal_case(rules, "source_status_missing")
    expired_window = _single_terminal_case(rules, "window_expired")
    sourced_policies = _sourced_wait_and_retarget_case(rules)
    child_failure = _child_failure_case(rules)
    standalone_child_failure = _standalone_child_failure_case(rules)
    phase_admission = _phase_admission_case(rules)
    audit_equivalence = _queue_audit_equivalence_case(rules)
    static_boundary = _static_boundary(package_root)
    rows = (
        invalid_actor,
        invalid_target,
        source_status,
        expired_window,
        sourced_policies,
        child_failure,
        standalone_child_failure,
        phase_admission,
        audit_equivalence,
        static_boundary,
    )
    checks = {
        "invalid_head_removed_then_valid_entry_executes": invalid_actor["ok"],
        "invalid_target_cancelled": invalid_target["ok"],
        "missing_source_status_cancelled": source_status["ok"],
        "expired_window_cancelled": expired_window["ok"],
        "wait_and_retarget_require_typed_admission": sourced_policies["ok"],
        "child_diagnostic_has_no_partial_mutation_and_entry_removed": child_failure["ok"],
        "standalone_ability_partial_has_no_published_mutation": standalone_child_failure["ok"],
        "queue_resolution_obeys_phase_machine": phase_admission["ok"],
        "queue_policy_audit_trim_preserves_behavior": audit_equivalence["ok"],
        "one_entry_per_scheduler_step_budget": static_boundary["ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "row_count": len(rows),
        "resource_budget": {
            "tbgd_read_count": 0,
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
        },
        "deferred": {
            "new_queue_families": "source_gap_blocked",
            "queue_rng_retarget": "P7-S16 or source-specific later stage",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s11_queue_terminal_progress.json", summary)
    write_json(
        output_dir / "p7_s11_queue_terminal_matrix.json",
        {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "rows": [
                {"row_id": row["row_id"], "classification": row["classification"], "ok": row["ok"]}
                for row in rows
            ],
        },
    )
    write_json(
        output_dir / "p7_s11_queue_terminal_evidence.json",
        {
            "invalid_actor_then_valid": invalid_actor,
            "invalid_target": invalid_target,
            "source_status_missing": source_status,
            "window_expired": expired_window,
            "sourced_wait_and_retarget": sourced_policies,
            "child_failure": child_failure,
            "standalone_child_failure": standalone_child_failure,
            "phase_admission": phase_admission,
            "queue_audit_equivalence": audit_equivalence,
            "static_boundary": static_boundary,
        },
    )
    return summary


def _invalid_head_then_valid_case(rules: RuleBook) -> dict[str, Any]:
    invalid = _entry("invalid_actor", actor_id="unit:missing")
    valid = _entry("valid_after_invalid")
    initial = _state_with_entries(invalid, valid)
    scheduler = CombatScheduler(rules)
    first = scheduler.step(initial)
    second = scheduler.step(first.after_state)
    first_evidence = _transition_evidence(rules, initial, first)
    second_evidence = _transition_evidence(rules, first.after_state, second)
    remaining_after_first = first.after_state.queues.get("interrupt_queue", ())
    remaining_after_second = second.after_state.queues.get("interrupt_queue", ())
    ok = (
        first.transition.transaction.command.action_id == "queue:cancelled"
        and first.transition.coverage.get("queue_terminal_plan", {}).get("blocked_reason") == "queue_action_actor_missing"
        and len(remaining_after_first) == 1
        and remaining_after_first[0].get("entry_id") == "entry:valid_after_invalid"
        and second.transition.transaction.command.action_id == "queue:drain_admitted"
        and len(remaining_after_second) == 0
        and first_evidence["ok"]
        and second_evidence["ok"]
        and second.transition.coverage.get("queue_progress", {}).get("terminal_disposition") == "completed"
    )
    return {
        "row_id": "invalid_actor_head_removed_then_valid_entry_executes",
        "classification": "executable",
        "ok": ok,
        "first": first_evidence,
        "second": second_evidence,
        "remaining_entry_ids_after_first": [item.get("entry_id") for item in remaining_after_first],
        "remaining_count_after_second": len(remaining_after_second),
    }


def _single_terminal_case(rules: RuleBook, case: str) -> dict[str, Any]:
    entry = _entry(case)
    state = _state_with_entries(entry)
    if case == "invalid_target":
        entry = _entry(case, target_ids=("unit:missing",))
        state = _state_with_entries(entry)
        expected_reason = "queue_action_target_lifecycle_blocked:unit_missing:unit:missing"
    elif case == "source_status_missing":
        entry = _entry(
            case,
            cancel_policy={
                "requires_source_status_active": True,
                "source_status_instance_id": "status:missing",
                "source_status_owner_id": "ally:actor",
                "source_status_policy_source": _source_json(rules),
            },
            source_id="status:missing",
            owner_id="ally:actor",
        )
        state = _state_with_entries(entry)
        expected_reason = "queue_source_status_inactive"
    elif case == "window_expired":
        entry = _entry(
            case,
            expiration_policy={"expires_at_event_index": -1, "source_trace": _source_json(rules)},
        )
        state = _state_with_entries(entry)
        expected_reason = "queue_window_expired:event_index"
    else:
        raise AssertionError(case)
    result = CombatScheduler(rules).step(state)
    evidence = _transition_evidence(rules, state, result)
    plan = result.transition.coverage.get("queue_terminal_plan", {})
    ok = (
        result.transition.transaction.command.action_id == "queue:cancelled"
        and plan.get("blocked_reason") == expected_reason
        and plan.get("disposition") == "cancelled"
        and plan.get("monotonic_progress") is True
        and len(result.after_state.queues.get("interrupt_queue", ())) == 0
        and evidence["ok"]
    )
    return {
        "row_id": case,
        "classification": "executable_terminal",
        "ok": ok,
        "expected_reason": expected_reason,
        "terminal_plan": plan,
        "transition": evidence,
    }


def _sourced_wait_and_retarget_case(rules: RuleBook) -> dict[str, Any]:
    source = _source_json(rules)
    wait_entry = _entry(
        "wait_for_window",
        target_ids=("unit:missing",),
        cancel_policy={
            "wait_policy_admitted": True,
            "wait_for_windows": ["turn_active"],
            "wait_policy_source": source,
        },
    )
    wait_state = _state_with_entries(wait_entry)
    wait_result = CombatScheduler(rules).step(wait_state)
    wait_evidence = _transition_evidence(rules, wait_state, wait_result)
    waiting_entry = wait_result.after_state.queues["interrupt_queue"][0]
    waiting_plan = select_next_queue_drain_plan(rules, QueueSystem(), wait_result.after_state)
    active_window_state = replace(
        wait_result.after_state,
        global_flags={**wait_result.after_state.global_flags, "current_window": "turn_active"},
    )
    cancel_after_window = CombatScheduler(rules).step(active_window_state)

    retarget_entry = _entry(
        "retarget",
        target_ids=("unit:missing",),
        cancel_policy={
            "retarget_policy_admitted": True,
            "retarget_target_ids": ["enemy:target"],
            "retarget_policy_source": source,
        },
    )
    retarget_state = _state_with_entries(retarget_entry)
    retarget_result = CombatScheduler(rules).step(retarget_state)
    retarget_evidence = _transition_evidence(rules, retarget_state, retarget_result)
    retargeted_entry = retarget_result.after_state.queues["interrupt_queue"][0]
    completed = CombatScheduler(rules).step(retarget_result.after_state)
    completed_evidence = _transition_evidence(rules, retarget_result.after_state, completed)

    trimmed_audit = _entry(
        "trimmed_audit_retarget",
        target_ids=("unit:missing",),
        cancel_policy={
            "retarget_policy_admitted": True,
            "retarget_target_ids": ["enemy:target"],
        },
    )
    trimmed_audit_state = _state_with_entries(trimmed_audit)
    trimmed_audit_result = CombatScheduler(rules).step(trimmed_audit_state)
    unadmitted = _entry(
        "unadmitted_retarget",
        target_ids=("unit:missing",),
        cancel_policy={"retarget_target_ids": ["enemy:target"]},
    )
    unadmitted_state = _state_with_entries(unadmitted)
    unadmitted_result = CombatScheduler(rules).step(unadmitted_state)
    ok = (
        wait_result.transition.transaction.command.action_id == "queue:waiting_window"
        and waiting_entry.get("status") == "waiting_window"
        and waiting_plan is not None
        and waiting_plan.status == "waiting_window"
        and cancel_after_window.transition.transaction.command.action_id == "queue:cancelled"
        and wait_evidence["ok"]
        and retarget_result.transition.transaction.command.action_id == "queue:retargeted"
        and retargeted_entry.get("target_ids") == ["enemy:target"]
        and retargeted_entry.get("drain_status") == "retargeted"
        and completed.transition.transaction.command.action_id == "queue:drain_admitted"
        and len(completed.after_state.queues.get("interrupt_queue", ())) == 0
        and retarget_evidence["ok"]
        and completed_evidence["ok"]
        and trimmed_audit_result.transition.transaction.command.action_id == "queue:retargeted"
        and trimmed_audit_result.after_state.queues["interrupt_queue"][0].get("target_ids") == ["enemy:target"]
        and unadmitted_result.transition.transaction.command.action_id == "queue:cancelled"
        and len(unadmitted_result.after_state.queues.get("interrupt_queue", ())) == 0
    )
    return {
        "row_id": "typed_admission_wait_retarget_and_audit_trim_equivalence",
        "classification": "executable_and_negative",
        "ok": ok,
        "wait_terminal_plan": wait_result.transition.coverage.get("queue_terminal_plan", {}),
        "waiting_plan": waiting_plan.to_json() if waiting_plan is not None else {},
        "retarget_terminal_plan": retarget_result.transition.coverage.get("queue_terminal_plan", {}),
        "trimmed_audit_terminal_plan": trimmed_audit_result.transition.coverage.get("queue_terminal_plan", {}),
        "unadmitted_terminal_plan": unadmitted_result.transition.coverage.get("queue_terminal_plan", {}),
        "wait_transition": wait_evidence,
        "retarget_transition": retarget_evidence,
        "completed_transition": completed_evidence,
    }


def _child_failure_case(rules: RuleBook) -> dict[str, Any]:
    entry = _entry("child_partial", intent_kind="partial")
    state = _state_with_entries(entry)
    result = CombatScheduler(rules).step(state)
    evidence = _transition_evidence(rules, state, result)
    child = result.transition.coverage.get("child_transition", {})
    terminal = result.transition.coverage.get("queue_terminal_plan", {})
    non_queue_paths = [
        list(mutation.path)
        for mutation in result.transition.transaction.mutations
        if mutation.path != ("queues", "interrupt_queue")
    ]
    ok = (
        result.transition.transaction.command.action_id == "queue:blocked_removed"
        and terminal.get("disposition") == "blocked_removed"
        and str(terminal.get("blocked_reason") or "").startswith("queue_child_transition_not_successor:")
        and child.get("published") is False
        and child.get("outcome", {}).get("successor_eligible") is False
        and child.get("mutation_count") == 0
        and not non_queue_paths
        and len(result.after_state.queues.get("interrupt_queue", ())) == 0
        and evidence["ok"]
    )
    return {
        "row_id": "diagnostic_child_not_published_entry_blocked_removed",
        "classification": "executable_terminal",
        "ok": ok,
        "terminal_plan": terminal,
        "child_transition": child,
        "published_non_queue_mutation_paths": non_queue_paths,
        "transition": evidence,
    }


def _standalone_child_failure_case(rules: RuleBook) -> dict[str, Any]:
    state = _state_with_entries(_entry("standalone_partial", intent_kind="standalone"))
    target = state.units["enemy:target"]
    planned = Mutation(
        op="set",
        path=("units", "enemy:target", "hp"),
        before=target.hp,
        after=target.hp - 10.0,
        reason="planned standalone ability mutation before later node failure",
        source="validation_standalone_ability",
        metadata={"negative_fixture": True, "source_trace": _source_json(rules)},
    )
    candidate = MutationReducer().apply(state, planned)

    class _PartialStandaloneAbility:
        def execute_standalone(self, *_args, **_kwargs):
            return AbilityTaskExecutionResult(
                after_state=candidate,
                mutations=(planned,),
                node_results=(
                    ExecutionNodeResult("ability_task", "validation:first", "complete"),
                    ExecutionNodeResult("ability_task", "validation:later", "blocked", "validation_late_failure"),
                ),
            )

    scheduler = CombatScheduler(rules)
    scheduler.ability_tasks = _PartialStandaloneAbility()
    result = scheduler.step(state)
    terminal = result.transition.coverage.get("queue_terminal_plan", {})
    child = result.transition.coverage.get("child_transition", {})
    non_queue_paths = [
        list(mutation.path)
        for mutation in result.transition.transaction.mutations
        if mutation.path != ("queues", "interrupt_queue")
    ]
    ok = (
        result.transition.transaction.command.action_id == "queue:blocked_removed"
        and str(terminal.get("blocked_reason") or "").startswith("queue_standalone_ability_not_successor:")
        and child.get("published") is False
        and child.get("planned_mutation_count") == 1
        and child.get("outcome", {}).get("successor_eligible") is False
        and not non_queue_paths
        and result.after_state.units["enemy:target"].hp == target.hp
        and len(result.after_state.queues.get("interrupt_queue", ())) == 0
    )
    return {
        "row_id": "standalone_ability_late_failure_discards_earlier_mutations",
        "classification": "negative_atomicity",
        "ok": ok,
        "terminal_plan": terminal,
        "child_evidence": child,
        "published_non_queue_mutation_paths": non_queue_paths,
        "target_hp_before": target.hp,
        "target_hp_after": result.after_state.units["enemy:target"].hp,
    }


def _phase_admission_case(rules: RuleBook) -> dict[str, Any]:
    state = _state_with_entries(_entry("phase_blocked"))
    state = replace(
        state,
        global_flags={**state.global_flags, "combat_phase": "action_execution"},
    )
    result = CombatScheduler(rules).step(state)
    reason = str(result.transition.coverage.get("blocked_reason") or "")
    ok = (
        reason == "operation_not_allowed_in_phase:resolve_queue_entry:action_execution"
        and result.after_state == state
        and not result.transition.transaction.mutations
        and not result.transition.outcome.successor_eligible
    )
    return {
        "row_id": "queue_resolution_phase_admission",
        "classification": "negative_boundary",
        "ok": ok,
        "blocked_reason": reason,
        "state_unchanged": result.after_state == state,
        "mutation_count": len(result.transition.transaction.mutations),
        "outcome": result.transition.outcome.to_json(),
    }


def _transition_evidence(rules: RuleBook, before: BattleState, result: Any) -> dict[str, Any]:
    transition = result.transition
    replay = MutationReducer().replay_snapshot(
        before,
        transition.transaction.mutations,
        transition.after.to_json(),
    )
    contract = TransitionContractValidator().validate(transition)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    return {
        "ok": replay.ok and contract.ok and audit.ok and transition.outcome.successor_eligible,
        "action_id": transition.transaction.command.action_id,
        "outcome": transition.outcome.to_json(),
        "mutation_count": len(transition.transaction.mutations),
        "replay_ok": replay.ok,
        "contract_ok": contract.ok,
        "source_audit_ok": audit.ok,
        "source_audit_violations": [item.to_json() for item in audit.violations],
        "queue_progress": transition.coverage.get("queue_progress", {}),
    }


def _state_with_entries(*entries: dict[str, JSONValue]) -> BattleState:
    base = _base_state()
    return replace(
        base,
        queues={"interrupt_queue": tuple(entries)},
        global_flags={**base.global_flags, "current_window": "idle"},
    )


def _queue_audit_equivalence_case(rules: RuleBook) -> dict[str, Any]:
    source = _source_json(rules)
    cancel_policy = {
        "requires_source_status_active": True,
        "source_status_instance_id": "status:active",
        "source_status_owner_id": "ally:actor",
        "source_status_policy_source": source,
    }
    expiration_policy = {
        "expires_at_event_index": 999,
        "source_trace": source,
    }
    full_entry = _entry(
        "queue_audit_full",
        source_id="status:active",
        cancel_policy=cancel_policy,
        expiration_policy=expiration_policy,
    )
    trimmed_entry = {
        **full_entry,
        "source_trace": {},
        "priority_source_trace": {},
        "cancel_policy": {**cancel_policy, "source_status_policy_source": {}},
        "expiration_policy": {**expiration_policy, "source_trace": {}},
    }
    full_state = _state_with_entries(full_entry)
    actor = full_state.units["ally:actor"]
    actor = replace(
        actor,
        flags={
            **actor.flags,
            "status_details": [
                {
                    "instance_id": "status:active",
                    "lifecycle_state": "active",
                    "source_trace": source,
                }
            ],
        },
    )
    full_state = replace(full_state, units={**full_state.units, actor.unit_id: actor})
    trimmed_state = replace(full_state, queues={"interrupt_queue": (trimmed_entry,)})
    full_plan = select_next_queue_drain_plan(rules, QueueSystem(), full_state)
    trimmed_plan = select_next_queue_drain_plan(rules, QueueSystem(), trimmed_state)
    full_behavior = (
        full_plan.ok,
        full_plan.status,
        full_plan.blocked_reason,
        full_plan.resolved_action_id,
        full_plan.resolved_kind,
        full_plan.queue_intent_id,
    )
    trimmed_behavior = (
        trimmed_plan.ok,
        trimmed_plan.status,
        trimmed_plan.blocked_reason,
        trimmed_plan.resolved_action_id,
        trimmed_plan.resolved_kind,
        trimmed_plan.queue_intent_id,
    )
    checks = {
        "compact_keys_equal": CompactStateQuery().project(full_state).semantic_key
        == CompactStateQuery().project(trimmed_state).semantic_key,
        "both_queue_plans_executable": full_plan.ok and trimmed_plan.ok,
        "queue_behavior_equal": full_behavior == trimmed_behavior,
        "audit_snapshots_distinct": full_state.snapshot().to_json() != trimmed_state.snapshot().to_json(),
    }
    return {
        "row_id": "queue_policy_audit_trim_behavior_equivalence",
        "classification": "kernel_invariant",
        "ok": all(checks.values()),
        "checks": checks,
        "full_plan": full_plan.to_json(),
        "trimmed_plan": trimmed_plan.to_json(),
    }


def _entry(
    suffix: str,
    *,
    actor_id: str = "ally:actor",
    target_ids: tuple[str, ...] = ("enemy:target",),
    intent_kind: str = "normal",
    cancel_policy: dict[str, JSONValue] | None = None,
    expiration_policy: dict[str, JSONValue] | None = None,
    source_id: str = "validation:queue_source",
    owner_id: str = "ally:actor",
) -> dict[str, JSONValue]:
    intent_id = f"validation:queue_intent:{intent_kind}"
    action_id = "validation:partial" if intent_kind == "partial" else "validation:normal"
    priority_id = f"validation:queue_priority:{intent_kind}"
    window_id = f"validation:queue_window:{intent_kind}"
    source = {
        "source_path": "simulator_v8_clean_core.tools.validate_p7_s11_queue_terminal_progress",
        "raw_type": "ValidationSynthetic",
        "raw_id": suffix,
        "evidence": {"validation": VALIDATION_VERSION, "negative_or_baseline_fixture": True},
    }
    return QueueEntry(
        entry_id=f"entry:{suffix}",
        queue_name="interrupt_queue",
        queue_kind="turn_insert_action",
        queue_intent_id=intent_id,
        actor_id=actor_id,
        action_or_ability_ref=action_id,
        target_ids=target_ids,
        priority_source={
            "priority_ordering_admitted": True,
            "priority_value": 10.0,
            "priority_key": "validation",
            "queue_priority_id": priority_id,
            "priority_table": "validation",
            "source_trace": source,
        },
        source_trace=source,
        action_level=1,
        resource_policy={"ignore_skill_point_delta": True},
        priority_key="validation",
        priority_value=10.0,
        queue_priority_id=priority_id,
        priority_source_trace=source,
        queue_window_id=window_id,
        window_family="insert_action",
        window_policy={"window_ordering_admitted": True, "source_basis": source},
        target_resolution={"ok": True, "target_ids": list(target_ids), "source_trace": source},
        owner_id=owner_id,
        source_id=source_id,
        expiration_policy=expiration_policy,
        cancel_policy=cancel_policy,
    ).to_json()


def _queue_rulebook() -> RuleBook:
    baseline = _trust_rulebook()
    source = baseline.ir.timeline_rules[0].source
    intents = []
    resolutions = []
    priorities = []
    windows = []
    for kind, action_id in (
        ("normal", "validation:normal"),
        ("partial", "validation:partial"),
        ("standalone", "validation:standalone_ability"),
    ):
        intent_id = f"validation:queue_intent:{kind}"
        priority_id = f"validation:queue_priority:{kind}"
        window_id = f"validation:queue_window:{kind}"
        priority_source = {
            "priority_ordering_admitted": True,
            "priority_value": 10.0,
            "priority_key": "validation",
            "queue_priority_id": priority_id,
            "priority_table": "validation",
            "source_trace": source.to_json(),
        }
        intents.append(
            QueueIntentIR(
                queue_intent_id=intent_id,
                source_task_id=f"validation:queue_task:{kind}",
                callback_id=f"validation:queue_callback:{kind}",
                phase_id="",
                opcode="TurnInsertAction",
                queue_kind="turn_insert_action",
                priority_source=priority_source,
                actor_target_alias="Owner",
                action_ref_or_ability_name=action_id,
                skill_index_expr={"kind": "fixed", "value": 1.0},
                ability_target_alias="Target",
                auto_cast=True,
                abort_policy={},
                source=source,
                coverage_status="executable",
            )
        )
        priorities.append(
            QueuePriorityIR(
                queue_priority_id=priority_id,
                priority_table="validation",
                priority_key="validation",
                priority_value=10.0,
                source=source,
                coverage_status="executable",
            )
        )
        windows.append(
            QueueWindowIR(
                queue_window_id=window_id,
                queue_intent_id=intent_id,
                queue_kind="turn_insert_action",
                window_family="insert_action",
                priority_key="validation",
                priority_value=10.0,
                window_policy={"window_ordering_admitted": True, "source_basis": source.to_json()},
                source=source,
                coverage_status="executable",
            )
        )
        resolutions.append(
            QueueResolutionIR(
                queue_resolution_id=f"validation:queue_resolution:{kind}",
                queue_intent_id=intent_id,
                action_or_ability_ref=action_id,
                resolved_kind="standalone_ability_graph" if kind == "standalone" else "action_definition",
                resolved_ids={
                    **(
                        {"standalone_ability_graph_id": "validation:standalone_graph"}
                        | {"executable_task_ids": ["validation:first", "validation:later"]}
                        if kind == "standalone"
                        else {}
                    ),
                    "action_set_candidates": [
                        {
                            "entity_ref": "validation:actor_a",
                            "action_ref": action_id,
                            "action_level": 1,
                            "combatant_action_set_id": "validation:actor_a:actions",
                        }
                    ]
                },
                source=source,
                coverage_status="executable",
            )
        )
    return RuleBook(
        replace(
            baseline.ir,
            queue_intents=tuple(intents),
            queue_resolutions=tuple(resolutions),
            queue_priorities=tuple(priorities),
            queue_windows=tuple(windows),
        )
    )


def _source_json(rules: RuleBook) -> dict[str, JSONValue]:
    return rules.ir.timeline_rules[0].source.to_json()


def _static_boundary(package_root: Path) -> dict[str, Any]:
    queue_source = (package_root / "systems" / "queue.py").read_text(encoding="utf-8")
    scheduler_source = (package_root / "systems" / "scheduler.py").read_text(encoding="utf-8")
    checks = {
        "finite_step_budget_is_one": QUEUE_DRAIN_STEP_BUDGET == 1,
        "terminal_dispositions_present": all(
            token in queue_source
            for token in ("cancelled", "blocked_removed", "waiting_window", "retargeted")
        ),
        "child_diagnostic_terminalized": "queue_child_transition_not_successor" in scheduler_source,
        "no_default_first_alive_retarget": "first_alive" not in queue_source,
    }
    return {
        "row_id": "static_queue_progress_and_no_fallback",
        "classification": "static_boundary",
        "ok": all(checks.values()),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S11 queue terminal states and monotonic progress.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['row_count']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
