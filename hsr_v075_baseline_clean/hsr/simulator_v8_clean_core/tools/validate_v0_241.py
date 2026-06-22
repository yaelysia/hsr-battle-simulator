from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import QueueIntentIR, QueueResolutionIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.queue import QueueDrainPlan, QueueSystem
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _system_transition, _transition_checks
from .validate_v0_237 import _event_for_callback, _records, _records_of_type, _state_with_callback_status
from .validate_v0_240 import _select_blocked_queue_intent, _select_executable_queue_intent


VALIDATION_VERSION = "v0_241"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    executable_intent = _select_executable_queue_intent(rules)
    enqueue_case = _queue_enqueue_state_case(rules, break_setup["initial_state"], executable_intent)
    drain_case = _queue_drain_gate_case(rules, enqueue_case["after_state"], executable_intent)
    blocked_resolution_case = _blocked_resolution_case(rules, _select_blocked_queue_intent(rules))

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "enqueue_regression": enqueue_case["checks"],
        "drain_gate": drain_case["checks"],
        "blocked_resolution": blocked_resolution_case["checks"],
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
            "selected_queue_resolution": drain_case["queue_resolution"],
            "selected_blocked_queue_resolution": blocked_resolution_case["queue_resolution"],
            "selection_policy": {
                "enqueue": "same structural executable QueueIntentIR predicate as v0_240",
                "drain": "QueueEntry resolved only through RuleBook.queue_resolution_for_intent; no AbilityName string mapping",
                "blocked": "coverage_status!=executable queue intent with retained QueueResolutionIR blocked reason",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "enqueue": enqueue_case["source_audit"],
            "drain_gate": drain_case["source_audit"],
            "blocked_resolution": blocked_resolution_case["source_audit"],
        },
        "trust_matrix": _trust_matrix(checks, drain_case),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_241.json", result)
    write_json(output_dir / "sample_queue_enqueue_transition_v0_241.json", enqueue_case["transition"])
    write_json(output_dir / "sample_queue_drain_gate_transition_v0_241.json", drain_case["transition"])
    write_json(output_dir / "sample_blocked_queue_resolution_transition_v0_241.json", blocked_resolution_case["transition"])
    write_json(output_dir / "coverage_summary_v0_241.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_241 queue resolution and drain admission gate.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _queue_enqueue_state_case(rules: RuleBook, base_state: BattleState, intent: QueueIntentIR) -> dict[str, Any]:
    callback = _require_callback(rules, intent)
    state = _state_with_callback_status(base_state, callback)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
        state,
        event=_event_for_callback(callback),
    )
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="event_dispatch:queue_intent_v0_241",
        metadata={"event": callback.event, "queue_intent_id": intent.queue_intent_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    queue_entries = _queue_entries(result.after_state, intent.queue_kind)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "queue_entry_created": len(queue_entries) == 1,
            "queue_entry_has_intent_id": bool(queue_entries) and queue_entries[0].get("queue_intent_id") == intent.queue_intent_id,
            "queue_entry_pending": bool(queue_entries) and queue_entries[0].get("status") == "pending",
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "after_state": result.after_state,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _queue_drain_gate_case(rules: RuleBook, state: BattleState, intent: QueueIntentIR) -> dict[str, Any]:
    queue = QueueSystem()
    resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
    plan = queue.plan_drain(state, intent.queue_kind, resolution)
    if plan.ok:
        mutation = queue.drain_admitted(
            state,
            plan,
            source="queue_system",
            metadata={"queue_operation": "dequeue"},
        )
        after_state = MutationReducer().apply_all(state, (mutation,))
        records = (
            SettlementRecord(
                record_type="queue_dequeue",
                source="queue_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={"drain_plan": plan.to_json()},
                trace=plan.source_trace or {},
            ).to_json(),
        )
        mutations = (mutation,)
    else:
        after_state = state
        records = (
            SettlementRecord(
                record_type="queue_drain_blocked",
                source="queue_system",
                process_only=True,
                payload={"drain_plan": plan.to_json(), "blocking_dependency": plan.blocked_reason},
                trace=plan.source_trace or {},
            ).to_json(),
        )
        mutations = ()
    transition = _system_transition(
        before_state=state,
        after_state=after_state,
        records=records,
        mutations=mutations,
        events=(),
        action_id="queue:drain_gate",
        metadata={"queue_intent_id": intent.queue_intent_id, "queue_resolution_id": plan.queue_resolution_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    queue_entries_after = _queue_entries(after_state, intent.queue_kind)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "resolution_exists": resolution is not None,
            "plan_status_known": plan.status in {"blocked", "drain_candidate"},
            "blocked_has_reason": plan.ok or bool(plan.blocked_reason),
            "blocked_snapshot_unchanged": plan.ok or after_state.snapshot().to_json() == state.snapshot().to_json(),
            "blocked_queue_preserved": plan.ok or queue_entries_after == _queue_entries(state, intent.queue_kind),
            "dequeue_has_resolution_metadata": (not plan.ok)
            or all("queue_resolution_id" in mutation.metadata for mutation in mutations),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "queue_resolution": resolution.to_json() if resolution else {},
        "drain_plan": plan.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _blocked_resolution_case(rules: RuleBook, intent: QueueIntentIR) -> dict[str, Any]:
    resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
    plan = QueueDrainPlan(
        ok=False,
        status="blocked",
        queue_name=intent.queue_kind,
        queue_entry={},
        queue_intent_id=intent.queue_intent_id,
        queue_resolution_id=resolution.queue_resolution_id if resolution else "",
        blocked_reason=(resolution.blocked_reason if resolution else "queue_resolution_missing"),
        source_trace={"queue_resolution_source": resolution.source.to_json()} if resolution else {},
    )
    state = BattleState()
    transition = _system_transition(
        before_state=state,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="queue_resolution_blocked",
                source="queue_system",
                process_only=True,
                payload={"drain_plan": plan.to_json(), "queue_intent_id": intent.queue_intent_id},
                trace=plan.source_trace or {},
            ).to_json(),
        ),
        mutations=(),
        events=(),
        action_id="queue:blocked_resolution",
        metadata={"queue_intent_id": intent.queue_intent_id, "queue_resolution_id": plan.queue_resolution_id},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "resolution_exists": resolution is not None,
            "resolution_blocked": resolution is not None and resolution.coverage_status != "executable",
            "blocked_reason_present": bool(plan.blocked_reason),
            "no_mutations": not transition.transaction.mutations,
            "snapshot_unchanged": transition.after.to_json() == state.snapshot().to_json(),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "queue_resolution": resolution.to_json() if resolution else {},
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, Any]:
    status = coverage_json.get("action_execution_status", {})
    intents = status.get("queue_intents", {})
    resolutions = status.get("queue_resolutions", {})
    checks = {
        "canonical_ir_has_queue_resolutions": len(ir.queue_resolutions) == len(ir.queue_intents) and len(ir.queue_resolutions) > 0,
        "coverage_reports_queue_resolutions": isinstance(resolutions, dict) and resolutions.get("lowered", 0) > 0,
        "blocked_resolution_present": resolutions.get("blocked", 0) >= 1,
        "queue_intent_regression": intents.get("executable", 0) >= 1 and intents.get("blocked", 0) >= 1,
        "resolved_kind_counts_present": bool(resolutions.get("resolved_kind_counts", {})),
    }
    return {"ok": all(checks.values()), "checks": checks, "queue_intents": intents, "queue_resolutions": resolutions}


def _trust_matrix(checks: dict[str, Any], drain_case: dict[str, Any]) -> dict[str, Any]:
    drain_plan = drain_case.get("drain_plan", {})
    drain_trusted = checks["drain_gate"]["ok"] and bool(drain_plan.get("ok"))
    return {
        "queue_enqueue": {
            "semantic_status": "trusted_for_current_scope" if checks["enqueue_regression"]["ok"] else "needs_fix",
            "scope": "v0_240 admitted QueueIntentIR still enqueues pending QueueEntry with source audit",
        },
        "queue_resolution": {
            "semantic_status": "trusted_for_current_scope" if checks["coverage"]["ok"] and checks["drain_gate"]["ok"] else "needs_fix",
            "scope": "QueueEntry action_or_ability_ref is resolved only through QueueResolutionIR; unresolved ability graph remains blocked",
        },
        "queue_drain": {
            "semantic_status": "trusted_for_current_scope" if drain_trusted else "blocked",
            "blocking_dependency": "" if drain_trusted else str(drain_plan.get("blocked_reason") or "no admitted queue drain candidate"),
        },
        "full_inserted_action_execution": {
            "semantic_status": "blocked",
            "blocking_dependency": "requires admitted queue drain plus inserted ActionCommand or standalone ability runner semantics",
        },
    }


def _queue_entries(state: BattleState, queue_name: str) -> tuple[dict[str, Any], ...]:
    return tuple(entry for entry in state.queues.get(queue_name, ()) if isinstance(entry, dict))


def _require_callback(rules: RuleBook, intent: QueueIntentIR) -> StatusCallbackIR:
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError(f"QueueIntentIR callback missing: {intent.callback_id}")
    return callback


if __name__ == "__main__":
    raise SystemExit(main())
