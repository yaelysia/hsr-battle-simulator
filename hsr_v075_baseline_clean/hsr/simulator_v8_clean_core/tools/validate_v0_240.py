from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import QueueIntentIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _system_transition, _transition_checks
from .validate_v0_237 import _event_for_callback, _record_payload, _records, _records_of_type, _state_with_callback_status


VALIDATION_VERSION = "v0_240"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    executable_intent = _select_executable_queue_intent(rules)
    blocked_intent = _select_blocked_queue_intent(rules)
    enqueue_case = _queue_enqueue_case(rules, break_setup["initial_state"], executable_intent)
    blocked_case = _blocked_queue_intent_case(rules, break_setup["initial_state"], blocked_intent)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "queue_enqueue": enqueue_case["checks"],
        "blocked_queue_intent": blocked_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selected_executable_queue_intent": executable_intent.to_json(),
            "selected_blocked_queue_intent": blocked_intent.to_json(),
            "selection_policy": {
                "executable": "coverage_status=executable, opcode=TurnInsertAbility, mainline admitted source, fixed ability payload",
                "blocked": "coverage_status!=executable, opcode in TurnInsertAction/TurnInsertAssistantAbility preferred, structural source trace retained",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "queue_enqueue": enqueue_case["source_audit"],
            "blocked_queue_intent": blocked_case["source_audit"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_240.json", result)
    write_json(output_dir / "sample_queue_enqueue_transition_v0_240.json", enqueue_case["transition"])
    write_json(output_dir / "sample_blocked_queue_intent_transition_v0_240.json", blocked_case["transition"])
    write_json(output_dir / "coverage_summary_v0_240.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_240 queue intent admission and enqueue core.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _queue_enqueue_case(rules: RuleBook, base_state: BattleState, intent: QueueIntentIR) -> dict[str, Any]:
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
        action_id="event_dispatch:queue_intent",
        metadata={"event": callback.event, "queue_intent_id": intent.queue_intent_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    records = _records(transition)
    queue_records = _records_of_type(records, "queue_enqueue")
    queue_mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "queue_system"]
    queue_entries = tuple(_queue_entries(result.after_state, intent.queue_kind))
    entry = queue_entries[0] if queue_entries else {}
    checks.update(
        {
            "source_audit": source_audit.ok,
            "intent_executable": intent.coverage_status == "executable",
            "callback_executable": callback.coverage_status == "executable",
            "queue_mutation_present": len(queue_mutations) == 1,
            "queue_enqueue_record_present": len(queue_records) == 1,
            "queue_entry_present": len(queue_entries) == 1,
            "queue_entry_shape": _queue_entry_shape_ok(entry),
            "queue_entry_source_trace": bool(_dict_at(entry, "source_trace").get("queue_intent_source")),
            "queue_entry_pending": entry.get("status") == "pending",
            "queue_drain_not_admitted": entry.get("drain_status") == "not_admitted",
            "mutation_metadata_has_intent": bool(queue_mutations)
            and queue_mutations[0].metadata.get("queue_intent_id") == intent.queue_intent_id,
            "settlement_links_mutation": bool(queue_records)
            and queue_records[0].get("mutation_id") == (queue_mutations[0].stable_id() if queue_mutations else ""),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_callback": callback.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _blocked_queue_intent_case(rules: RuleBook, base_state: BattleState, intent: QueueIntentIR) -> dict[str, Any]:
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
        action_id="event_dispatch:blocked_queue_intent",
        metadata={"event": callback.event, "queue_intent_id": intent.queue_intent_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    records = _records(transition)
    listener_records = _records_of_type(records, "listener_match")
    blocked_records = _records_of_type(records, "queue_intent_blocked")
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "intent_blocked": intent.coverage_status != "executable",
            "blocked_reason_present": bool(intent.blocked_reason),
            "no_mutations": not transition.transaction.mutations,
            "snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
            "blocked_record_or_listener_record": bool(blocked_records)
            or any(
                _record_payload(record).get("listener_id") == callback.callback_id
                and _record_payload(record).get("status") == "blocked"
                for record in listener_records
            ),
            "queue_absent": not result.after_state.queues.get(intent.queue_kind, ()),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_callback": callback.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _select_executable_queue_intent(rules: RuleBook) -> QueueIntentIR:
    for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
        if intent.coverage_status != "executable":
            continue
        if intent.opcode != "TurnInsertAbility":
            continue
        if not intent.action_ref_or_ability_name:
            continue
        task = rules.status_callback_task(intent.source_task_id)
        if task is None or task.coverage_status != "executable" or task.parent_task_id:
            continue
        callback = rules.status_callback(intent.callback_id)
        if callback is None or callback.coverage_status != "executable":
            continue
        return intent
    raise RuntimeError("no executable TurnInsertAbility QueueIntentIR found")


def _select_blocked_queue_intent(rules: RuleBook) -> QueueIntentIR:
    preferred = ("TurnInsertAction", "TurnInsertAssistantAbility", "TurnInsertAbility")
    for opcode in preferred:
        for intent in sorted(rules.ir.queue_intents, key=_queue_intent_sort_key):
            if intent.opcode != opcode or intent.coverage_status == "executable":
                continue
            if not intent.blocked_reason:
                continue
            if rules.status_callback(intent.callback_id) is not None:
                return intent
    raise RuntimeError("no blocked QueueIntentIR found")


def _queue_intent_sort_key(intent: QueueIntentIR) -> tuple[object, ...]:
    path = intent.source.source_path
    return (
        intent.opcode != "TurnInsertAbility",
        path.startswith("Config/ConfigAbility/Activity/"),
        path.startswith("Config/ConfigAbility/Rogue"),
        path,
        intent.callback_id,
        intent.source_task_id,
    )


def _require_callback(rules: RuleBook, intent: QueueIntentIR) -> StatusCallbackIR:
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError(f"QueueIntentIR callback missing: {intent.callback_id}")
    return callback


def _unit_id_for_callback(callback: StatusCallbackIR) -> str:
    return "ally:actor" if callback.scope_kind == "actor_local" else "enemy:profile_target"


def _queue_entries(state: BattleState, queue_name: str) -> tuple[dict[str, Any], ...]:
    entries = []
    for entry in state.queues.get(queue_name, ()):
        if isinstance(entry, dict):
            entries.append(entry)
    return tuple(entries)


def _queue_entry_shape_ok(entry: dict[str, Any]) -> bool:
    required = {
        "entry_id",
        "queue_name",
        "queue_kind",
        "actor_id",
        "action_or_ability_ref",
        "target_ids",
        "priority_source",
        "source_trace",
        "status",
        "drain_status",
    }
    return required.issubset(entry.keys()) and isinstance(entry.get("target_ids"), list)


def _dict_at(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    queue = status.get("queue_intents", {})
    checks = {
        "canonical_ir_has_queue_intents": len(ir.queue_intents) > 0,
        "coverage_reports_queue_intents": isinstance(queue, dict) and queue.get("lowered", 0) > 0,
        "executable_queue_intent_present": queue.get("executable", 0) >= 1,
        "blocked_queue_intent_present": queue.get("blocked", 0) >= 1,
        "turn_insert_ability_lowered": queue.get("opcode_counts", {}).get("TurnInsertAbility", 0) >= 1,
        "turn_insert_action_or_assistant_lowered": (
            queue.get("opcode_counts", {}).get("TurnInsertAction", 0)
            + queue.get("opcode_counts", {}).get("TurnInsertAssistantAbility", 0)
        )
        >= 1,
    }
    return {"ok": all(checks.values()), "checks": checks, "queue_intents": queue}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    enqueue_trusted = checks["queue_enqueue"]["ok"]
    return {
        "queue_intent_lowering": {
            "semantic_status": "trusted_for_current_scope" if checks["coverage"]["ok"] else "needs_fix",
            "scope": "TurnInsertAbility/TurnInsertAction/TurnInsertAssistantAbility are lowered as QueueIntentIR with admission status",
        },
        "queue_enqueue": {
            "semantic_status": "trusted_for_current_scope" if enqueue_trusted else "needs_fix",
            "scope": "executable QueueIntentIR can enqueue pending QueueEntry through EventDispatchSystem and QueueSystem",
        },
        "queue_drain": {
            "semantic_status": "blocked",
            "blocking_dependency": "requires action/ability resolution and priority ordering admission; v0_240 only records drain_candidate process metadata",
        },
        "inserted_action_execution": {
            "semantic_status": "blocked",
            "blocking_dependency": "requires queue drain, inserted action command construction, and interrupt/ultimate priority semantics",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
