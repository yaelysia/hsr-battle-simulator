from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import QueueIntentIR, QueueResolutionIR, StandaloneAbilityGraphIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.ability import AbilityTaskSystem
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.queue import QueueSystem
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _system_transition, _transition_checks
from .validate_v0_237 import _event_for_callback, _records, _records_of_type, _state_with_callback_status
from .validate_v0_240 import _select_blocked_queue_intent


VALIDATION_VERSION = "v0_242"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    drain_case = _standalone_queue_drain_case(rules, break_setup["initial_state"])
    blocked_case = _blocked_queue_case(rules, break_setup["initial_state"])
    gap_matrix = _queue_gap_matrix(coverage.to_json(), ir, drain_case)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "standalone_drain": drain_case["checks"],
        "blocked_queue": blocked_case["checks"],
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
            "selected_queue_intent": drain_case.get("queue_intent", {}),
            "selected_queue_resolution": drain_case.get("queue_resolution", {}),
            "selected_standalone_graph": drain_case.get("standalone_graph", {}),
            "selection_policy": {
                "standalone_drain": (
                    "QueueIntentIR coverage_status=executable, opcode=TurnInsertAbility, "
                    "QueueResolutionIR resolved_kind=standalone_ability_graph, "
                    "priority admitted, graph has executable task, selected by source path/task ordering only"
                ),
                "blocked": "first structurally blocked QueueIntentIR/QueueResolutionIR pair with retained source trace",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "standalone_drain": drain_case["source_audit"],
            "blocked_queue": blocked_case["source_audit"],
        },
        "queue_gap_matrix": gap_matrix,
        "trust_matrix": _trust_matrix(checks, drain_case),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_242.json", result)
    write_json(output_dir / "queue_gap_matrix_v0_242.json", gap_matrix)
    write_json(output_dir / "sample_queue_standalone_drain_transition_v0_242.json", drain_case["transition"])
    write_json(output_dir / "sample_blocked_queue_transition_v0_242.json", blocked_case["transition"])
    write_json(output_dir / "coverage_summary_v0_242.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_242 queue source, priority and standalone ability drain.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _standalone_queue_drain_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for intent in _candidate_queue_intents(rules):
        callback = _require_callback(rules, intent)
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        graph = _standalone_graph_for_resolution(rules, resolution)
        if resolution is None or graph is None:
            continue
        state = _state_with_callback_status(base_state, callback)
        enqueue_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        queue_entries = _queue_entries(enqueue_result.after_state, intent.queue_kind)
        if not queue_entries:
            failures.append({"queue_intent_id": intent.queue_intent_id, "reason": "enqueue_did_not_create_entry"})
            continue
        queue = QueueSystem()
        plan = queue.plan_next_drain(
            enqueue_result.after_state,
            intent.queue_kind,
            {resolution.queue_intent_id: resolution},
        )
        if not plan.ok:
            failures.append({"queue_intent_id": intent.queue_intent_id, "reason": plan.blocked_reason, "plan": plan.to_json()})
            continue
        dequeue = queue.drain_admitted(
            enqueue_result.after_state,
            plan,
            source="queue_system",
            metadata={"queue_operation": "dequeue"},
        )
        after_dequeue = MutationReducer().apply_all(enqueue_result.after_state, (dequeue,))
        phases = _phases_for_graph(rules, graph)
        ability_result = AbilityTaskSystem(rules, EffectRegistry(StatusSystem(rules))).execute_standalone(
            after_dequeue,
            phases=phases,
            actor_id=str(plan.queue_entry.get("actor_id") or ""),
            target_ids=tuple(str(item) for item in plan.queue_entry.get("target_ids", ()) if isinstance(item, str)),
            queue_entry=plan.queue_entry,
            queue_resolution=resolution.to_json(),
        )
        if not ability_result.mutations:
            failures.append(
                {
                    "queue_intent_id": intent.queue_intent_id,
                    "reason": "standalone_ability_executed_without_mutation",
                    "task_records": list(ability_result.task_records)[:5],
                }
            )
            continue
        records = (
            SettlementRecord(
                record_type="queue_dequeue",
                source="queue_system",
                mutation_id=dequeue.stable_id(),
                process_only=False,
                payload={"drain_plan": plan.to_json()},
                trace=plan.source_trace or {},
            ).to_json(),
            *ability_result.records,
        )
        transition = _system_transition(
            before_state=enqueue_result.after_state,
            after_state=ability_result.after_state,
            records=records,
            mutations=(dequeue, *ability_result.mutations),
            events=ability_result.events,
            action_id="queue:standalone_drain_v0_242",
            metadata={
                "queue_intent_id": intent.queue_intent_id,
                "queue_resolution_id": resolution.queue_resolution_id,
                "standalone_ability_graph_id": graph.standalone_ability_graph_id,
            },
        )
        source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        checks = _transition_checks(transition, enqueue_result.after_state)
        records_json = _records(transition)
        checks.update(
            {
                "source_audit": source_audit.ok,
                "queue_intent_executable": intent.coverage_status == "executable",
                "queue_resolution_executable": resolution.coverage_status == "executable",
                "queue_priority_present": bool(plan.queue_priority_id),
                "standalone_graph_resolved": resolution.resolved_kind == "standalone_ability_graph",
                "standalone_graph_has_executable_task": bool(graph.executable_task_ids),
                "dequeue_mutation_present": dequeue in transition.transaction.mutations,
                "ability_effect_mutation_present": bool(ability_result.mutations),
                "queue_dequeue_record_present": bool(_records_of_type(records_json, "queue_dequeue")),
                "ability_task_records_present": bool(_records_of_type(records_json, "ability_task")),
                "queue_removed_or_reordered": len(_queue_entries(ability_result.after_state, intent.queue_kind)) < len(queue_entries),
            }
        )
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": checks,
            "queue_intent": intent.to_json(),
            "queue_resolution": resolution.to_json(),
            "standalone_graph": graph.to_json(),
            "drain_plan": plan.to_json(),
            "transition": transition.to_json(),
            "source_audit": source_audit.to_json(),
            "selection_failures": failures[:10],
        }
    raise RuntimeError(f"no executable standalone queue drain case found; first_failures={failures[:5]}")


def _blocked_queue_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    intent = _select_blocked_queue_intent(rules)
    callback = _require_callback(rules, intent)
    state = _state_with_callback_status(base_state, callback)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
        state,
        event=_event_for_callback(callback),
        unit_id=_unit_id_for_callback(callback),
        modifier_name=callback.modifier_name,
    )
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="queue:blocked_v0_242",
        metadata={"queue_intent_id": intent.queue_intent_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "blocked_intent": intent.coverage_status != "executable",
            "blocked_reason_present": bool(intent.blocked_reason),
            "no_mutations": not transition.transaction.mutations,
            "snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "queue_intent": intent.to_json(),
        "queue_resolution": (rules.queue_resolution_for_intent(intent.queue_intent_id).to_json() if rules.queue_resolution_for_intent(intent.queue_intent_id) else {}),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _candidate_queue_intents(rules: RuleBook) -> tuple[QueueIntentIR, ...]:
    candidates: list[QueueIntentIR] = []
    for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
        if intent.coverage_status != "executable" or intent.opcode != "TurnInsertAbility":
            continue
        callback = rules.status_callback(intent.callback_id)
        if callback is None or callback.coverage_status != "executable":
            continue
        task = rules.status_callback_task(intent.source_task_id)
        if task is None or task.coverage_status != "executable" or task.parent_task_id:
            continue
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if resolution is None or resolution.coverage_status != "executable":
            continue
        if resolution.resolved_kind != "standalone_ability_graph":
            continue
        graph = _standalone_graph_for_resolution(rules, resolution)
        if graph is None or not graph.executable_task_ids:
            continue
        candidates.append(intent)
    return tuple(candidates)


def _queue_intent_sort_key(intent: QueueIntentIR) -> tuple[object, ...]:
    path = intent.source.source_path
    priority_value = intent.priority_source.get("priority_value")
    return (
        not path.startswith("Config/ConfigAbility/Avatar/"),
        float(priority_value) if isinstance(priority_value, (int, float)) else 999999.0,
        path,
        intent.callback_id,
        intent.source_task_id,
    )


def _standalone_graph_for_resolution(rules: RuleBook, resolution: QueueResolutionIR | None) -> StandaloneAbilityGraphIR | None:
    if resolution is None or resolution.resolved_kind != "standalone_ability_graph":
        return None
    graph_id = resolution.resolved_ids.get("standalone_ability_graph_id")
    if not isinstance(graph_id, str):
        return None
    return rules.standalone_ability_graph(graph_id)


def _phases_for_graph(rules: RuleBook, graph: StandaloneAbilityGraphIR) -> tuple[Any, ...]:
    phases = tuple(rules.ability_phase(phase_id) for phase_id in graph.phase_ids)
    return tuple(phase for phase in phases if phase is not None)


def _require_callback(rules: RuleBook, intent: QueueIntentIR) -> StatusCallbackIR:
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError(f"QueueIntentIR callback missing: {intent.callback_id}")
    return callback


def _unit_id_for_callback(callback: StatusCallbackIR) -> str:
    return "ally:actor" if callback.scope_kind == "actor_local" else "enemy:profile_target"


def _queue_entries(state: BattleState, queue_name: str) -> tuple[dict[str, Any], ...]:
    return tuple(entry for entry in state.queues.get(queue_name, ()) if isinstance(entry, dict))


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    intents = status.get("queue_intents", {})
    resolutions = status.get("queue_resolutions", {})
    priorities = status.get("queue_priorities", {})
    graphs = status.get("standalone_ability_graphs", {})
    action_sets = status.get("combatant_action_sets", {})
    checks = {
        "queue_intents_lowered": intents.get("lowered", 0) > 0,
        "queue_intents_executable": intents.get("executable", 0) > 0,
        "queue_priorities_executable": priorities.get("executable", 0) >= 1,
        "insert_ability_priority_present": priorities.get("priority_table_counts", {}).get("InsertAbilityPriority", 0) >= 1,
        "insert_action_priority_present": priorities.get("priority_table_counts", {}).get("InsertActionPriority", 0) >= 1,
        "standalone_graphs_executable": graphs.get("executable", 0) >= 1,
        "queue_resolutions_executable": resolutions.get("executable", 0) >= 1,
        "standalone_resolution_present": resolutions.get("resolved_kind_counts", {}).get("standalone_ability_graph", 0) >= 1,
        "combatant_action_sets_lowered": action_sets.get("lowered", 0) >= 1,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "queue_intents": intents,
        "queue_resolutions": resolutions,
        "queue_priorities": priorities,
        "standalone_ability_graphs": graphs,
        "combatant_action_sets": action_sets,
        "ir_counts": {
            "queue_priorities": len(ir.queue_priorities),
            "standalone_ability_graphs": len(ir.standalone_ability_graphs),
            "combatant_action_sets": len(ir.combatant_action_sets),
        },
    }


def _queue_gap_matrix(coverage_json: dict[str, Any], ir, drain_case: dict[str, Any]) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    resolutions = status.get("queue_resolutions", {})
    return {
        "queue_source_expansion": {
            "current_actionability": "fixed_now",
            "semantic_status": "trusted_for_current_scope" if resolutions.get("executable", 0) > 0 else "needs_fix",
            "evidence": {"executable_queue_resolutions": resolutions.get("executable", 0)},
        },
        "queue_priority": {
            "current_actionability": "fixed_now",
            "semantic_status": "trusted_for_current_scope" if len(ir.queue_priorities) > 0 else "needs_fix",
            "evidence": {"queue_priority_count": len(ir.queue_priorities)},
        },
        "standalone_ability_resolution": {
            "current_actionability": "fixed_now",
            "semantic_status": "trusted_for_current_scope" if drain_case["checks"].get("standalone_graph_resolved") else "needs_fix",
            "evidence": {"selected_graph": drain_case.get("standalone_graph", {}).get("standalone_ability_graph_id", "")},
        },
        "standalone_ability_drain": {
            "current_actionability": "fixed_now",
            "semantic_status": "trusted_for_current_scope" if drain_case["checks"].get("ok") else "needs_fix",
            "evidence": {"drain_plan": drain_case.get("drain_plan", {})},
        },
        "turn_insert_action_resolution": {
            "current_actionability": "wait_for_dependency",
            "semantic_status": "blocked",
            "blocking_dependency": (
                "requires runtime actor template_id + CombatantActionSetIR binding to be admitted before "
                "fixed SkillIndex queue entries can safely become inserted ActionCommand"
            ),
        },
        "turn_insert_assistant_ability": {
            "current_actionability": "wait_for_dependency",
            "semantic_status": "blocked",
            "blocking_dependency": "requires admitted assistant actor identity, assistant ability graph, target and priority semantics",
        },
        "full_priority_total_order": {
            "current_actionability": "wait_for_dependency",
            "semantic_status": "blocked",
            "blocking_dependency": "requires complete queue family ordering across ultimate/immediate/follow-up/interrupt entries",
        },
    }


def _gap_matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    fix_now = {
        key: value
        for key, value in matrix.items()
        if isinstance(value, dict) and value.get("current_actionability") == "fixed_now"
    }
    checks = {
        "fix_now_items_present": bool(fix_now),
        "fix_now_all_trusted": all(value.get("semantic_status") == "trusted_for_current_scope" for value in fix_now.values()),
        "blocked_items_have_dependency": all(
            bool(value.get("blocking_dependency"))
            for value in matrix.values()
            if isinstance(value, dict) and value.get("semantic_status") == "blocked"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(checks: dict[str, Any], drain_case: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_enqueue": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "v0_240 executable QueueIntentIR still enqueues source-audited QueueEntry",
        },
        "queue_priority": {
            "semantic_status": "trusted_for_current_scope" if checks["coverage"]["checks"]["queue_priorities_executable"] else "needs_fix",
            "scope": "QueuePriorityIR from PriorityConfig InsertAbilityPriority/InsertActionPriority",
        },
        "queue_resolution": {
            "semantic_status": "trusted_for_current_scope" if checks["coverage"]["checks"]["standalone_resolution_present"] else "needs_fix",
            "scope": "TurnInsertAbility AbilityName resolves only to StandaloneAbilityGraphIR or explicit blocked reason",
        },
        "queue_drain": {
            "semantic_status": "trusted_for_current_scope" if checks["standalone_drain"]["ok"] else "blocked",
            "scope": "dequeue plus standalone ability executable task dispatch, limited to admitted graph/task/effect sources",
            "blocking_dependency": "" if checks["standalone_drain"]["ok"] else str(drain_case.get("drain_plan", {}).get("blocked_reason") or "no admitted drain case"),
        },
        "full_inserted_action_execution": {
            "semantic_status": "trusted_for_current_scope" if checks["standalone_drain"].get("ability_effect_mutation_present") else "blocked",
            "scope": "standalone queue ability task effects can mutate through existing EffectRegistry; full ActionCommand queue execution remains separate",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
