from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _execute_break_setup, _select_break_family_case
from .validate_v0_237 import (
    _blocked_scoped_listener_case,
    _event_for_callback,
    _multi_target_dispatch_case,
    _record_payload,
    _records,
    _records_of_type,
    _select_blocked_scoped_listener,
    _state_with_callback_status,
    _status_local_dispatch_case,
)


VALIDATION_VERSION = "v0_238"

BLOCKED_CATEGORIES = {
    "source_not_admitted",
    "scope_not_admitted",
    "condition_not_admitted",
    "target_not_admitted",
    "effect_not_admitted",
    "downstream_intent_missing",
    "event_alias_missing",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    scenario_path = package_root / "scenarios/examples/identity_smoke_v0_204.json"
    scenario = ScenarioLoader().load_path(scenario_path)
    identity = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    static_result = run_static_checks(package_root)
    break_family_case = _select_break_family_case(ir, rules)
    break_setup = _execute_break_setup(rules, break_family_case)

    status_dispatch_case = _status_local_dispatch_case(rules, break_setup["initial_state"])
    blocked_listener_case = _blocked_scoped_listener_case(rules, break_setup["initial_state"])
    multi_target_case = _multi_target_dispatch_case(rules, ir, build_result)
    order_case = _listener_order_case(rules, break_setup["initial_state"])
    unknown_alias_case = _unknown_event_alias_case(rules, break_setup["initial_state"])

    transitions = (
        status_dispatch_case["transition"],
        blocked_listener_case["transition"],
        multi_target_case["transition"],
        order_case["transition"],
        unknown_alias_case["transition"],
    )
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "listener_order": order_case["checks"],
        "event_alias": _event_alias_checks(transitions),
        "blocked_reason_category": _blocked_reason_checks(transitions),
        "listener_record_shape": _listener_record_shape_checks(transitions),
        "action_window_record_shape": _action_window_record_shape_checks(multi_target_case["transition"]),
        "status_dispatch_regression": status_dispatch_case["checks"],
        "blocked_listener_regression": blocked_listener_case["checks"],
        "multi_target_regression": multi_target_case["checks"],
        "unknown_alias": unknown_alias_case["checks"],
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((identity.ok, static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selected_order_listener": order_case["selected_callback"],
            "selected_blocked_listener": blocked_listener_case["selected_callback"],
            "selected_status_dispatch": status_dispatch_case["selected_delay"],
            "selected_multi_target_definition": multi_target_case["selected_definition"],
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "status_local_dispatch": status_dispatch_case["source_audit"],
            "blocked_scoped_listener": blocked_listener_case["source_audit"],
            "multi_target": multi_target_case["source_audit"],
            "listener_order": order_case["source_audit"],
            "unknown_alias": unknown_alias_case["source_audit"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_238.json", result)
    write_json(output_dir / "sample_status_local_dispatch_transition_v0_238.json", status_dispatch_case["transition"])
    write_json(output_dir / "sample_blocked_scoped_listener_transition_v0_238.json", blocked_listener_case["transition"])
    write_json(output_dir / "sample_multi_target_dispatch_transition_v0_238.json", multi_target_case["transition"])
    write_json(output_dir / "sample_listener_order_transition_v0_238.json", order_case["transition"])
    write_json(output_dir / "sample_unknown_event_alias_transition_v0_238.json", unknown_alias_case["transition"])
    write_json(output_dir / "coverage_summary_v0_238.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_238 event dispatch foundation closure.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _listener_order_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    callback = _select_blocked_scoped_listener(rules)
    state = _state_with_callback_status(base_state, callback)
    event = _event_for_callback(callback)
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    first = dispatcher.dispatch_event(state, event=event)
    second = dispatcher.dispatch_event(state, event=event)
    transition = _system_transition_from_dispatch(
        before_state=state,
        result=first,
        action_id="event_dispatch:listener_order",
        metadata={"event": callback.event, "modifier_name": callback.modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    first_keys = _listener_order_keys(first.records)
    second_keys = _listener_order_keys(second.records)
    checks = _transition_checks_for_case(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "listener_records_present": bool(first_keys),
            "order_keys_stable": first_keys == second_keys,
            "order_keys_non_empty": all(isinstance(key, dict) and key for key in first_keys),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_callback": callback.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
        "first_order_keys": first_keys,
        "second_order_keys": second_keys,
    }


def _unknown_event_alias_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    event = GameEvent(
        event_type="validation.unknown_runtime_event",
        source_id="ally:actor",
        target_id="enemy:profile_target",
        window="validation.unknown_runtime_event",
        process_only=True,
        payload={"source_basis": "validation_unknown_event_alias"},
    )
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    transition = _system_transition_from_dispatch(
        before_state=state,
        result=result,
        action_id="event_dispatch:unknown_alias",
        metadata={"event_type": event.event_type},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    records = _records(transition)
    listener_records = _records_of_type(records, "listener_match")
    checks = _transition_checks_for_case(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "snapshot_unchanged": transition.after.to_json() == transition.transaction.before.to_json(),
            "no_mutations": not transition.transaction.mutations,
            "event_alias_missing_recorded": any(
                _record_payload(record).get("blocked_category") == "event_alias_missing"
                for record in listener_records
            ),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _system_transition_from_dispatch(*, before_state: BattleState, result, action_id: str, metadata: dict[str, Any]):
    from .validate_v0_235 import _system_transition

    return _system_transition(
        before_state=before_state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id=action_id,
        metadata=metadata,
    )


def _transition_checks_for_case(transition, before_state: BattleState) -> dict[str, bool]:
    from .validate_v0_235 import _transition_checks

    return _transition_checks(transition, before_state)


def _listener_order_keys(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    keys: list[dict[str, Any]] = []
    for record in records:
        if record.get("record_type") != "listener_match":
            continue
        payload = _record_payload(record)
        order_key = payload.get("order_key")
        if isinstance(order_key, dict):
            keys.append(order_key)
    return keys


def _event_alias_checks(transitions: tuple[dict[str, Any], ...]) -> dict[str, object]:
    records = _all_records(transitions)
    dispatch_records = _records_of_type(records, "event_dispatch")
    listener_records = _records_of_type(records, "listener_match")
    aliases = [_alias for record in dispatch_records for _alias in _dispatch_aliases(record)]
    known_hit_aliases = [
        _record_payload(record).get("event_alias")
        for record in listener_records
        if _record_payload(record).get("event", {}).get("event_type") in {"damage.hit", "toughness.hit", "break.triggered"}
    ]
    checks = {
        "dispatch_records_present": bool(dispatch_records),
        "aliases_present": bool(aliases),
        "aliases_have_source_basis": all(isinstance(alias.get("source_basis"), str) and alias.get("source_basis") for alias in aliases),
        "aliases_have_admission_status": all(
            alias.get("admission_status") in {"executable", "blocked", "audit_only", "discovered_only"}
            for alias in aliases
        ),
        "blocked_aliases_have_dependency": all(
            isinstance(alias.get("blocked_dependency"), str) and alias.get("blocked_dependency")
            for alias in aliases
            if alias.get("admission_status") != "executable"
        ),
        "known_hit_events_have_alias": bool(known_hit_aliases)
        and all(isinstance(alias, dict) and alias.get("source_basis") for alias in known_hit_aliases),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _blocked_reason_checks(transitions: tuple[dict[str, Any], ...]) -> dict[str, object]:
    records = _records_of_type(_all_records(transitions), "listener_match")
    blocked = [
        _record_payload(record)
        for record in records
        if _record_payload(record).get("status") in {"blocked", "skipped"}
        and _record_payload(record).get("reason")
    ]
    checks = {
        "blocked_records_present": bool(blocked),
        "blocked_records_have_category": all(payload.get("blocked_category") in BLOCKED_CATEGORIES for payload in blocked),
        "no_unknown_category": all(payload.get("blocked_category") not in {"", "unknown"} for payload in blocked),
        "event_alias_category_covered": any(payload.get("blocked_category") == "event_alias_missing" for payload in blocked),
        "downstream_category_covered": any(payload.get("blocked_category") == "downstream_intent_missing" for payload in blocked),
    }
    return {"ok": all(checks.values()), "checks": checks, "blocked_count": len(blocked)}


def _listener_record_shape_checks(transitions: tuple[dict[str, Any], ...]) -> dict[str, object]:
    records = _records_of_type(_all_records(transitions), "listener_match")
    required = {
        "event",
        "listener_kind",
        "listener_id",
        "listener_source",
        "status",
        "reason",
        "blocked_category",
        "order_key",
        "event_alias",
        "metadata",
    }
    payloads = [_record_payload(record) for record in records]
    checks = {
        "listener_records_present": bool(payloads),
        "required_fields_present": all(required.issubset(payload.keys()) for payload in payloads),
        "order_key_shape_present": all(isinstance(payload.get("order_key"), dict) for payload in payloads),
        "event_alias_shape_present": all(isinstance(payload.get("event_alias"), dict) for payload in payloads),
        "status_callback_execution_record_present": any(payload.get("listener_source") == "status_callback_system" for payload in payloads),
        "global_or_per_hit_or_being_record_present": any(
            payload.get("listener_kind") in {"global_listener", "being_hit_listener", "per_hit_listener"}
            for payload in payloads
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "listener_record_count": len(payloads)}


def _action_window_record_shape_checks(transition: dict[str, Any]) -> dict[str, object]:
    records = _records_of_type(_records_from_json(transition), "listener_match")
    trigger_payloads = [
        _record_payload(record)
        for record in records
        if _record_payload(record).get("listener_kind") == "trigger"
    ]
    checks = {
        "trigger_records_present": bool(trigger_payloads),
        "trigger_records_have_unified_order_key": all(isinstance(payload.get("order_key"), dict) and payload.get("order_key") for payload in trigger_payloads),
        "trigger_records_have_unified_event_alias": all(isinstance(payload.get("event_alias"), dict) and payload.get("event_alias") for payload in trigger_payloads),
        "trigger_records_have_blocked_category": all("blocked_category" in payload for payload in trigger_payloads),
    }
    return {"ok": all(checks.values()), "checks": checks, "trigger_record_count": len(trigger_payloads)}


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    status_callbacks = status.get("status_callbacks", {})
    categories = status_callbacks.get("blocked_category_counts", {})
    checks = {
        "status_callbacks_lowered": len(ir.status_callbacks) > 0,
        "coverage_reports_listener_blocked_categories": isinstance(categories, dict) and bool(categories),
        "coverage_reports_listener_scopes": isinstance(status_callbacks.get("scope_counts"), dict) and bool(status_callbacks.get("scope_counts")),
    }
    return {"ok": all(checks.values()), "checks": checks, "status_callbacks": status_callbacks}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "event_dispatch_foundation": {
            "semantic_status": "trusted_for_current_scope"
            if all(
                checks[name]["ok"]
                for name in (
                    "listener_order",
                    "event_alias",
                    "blocked_reason_category",
                    "listener_record_shape",
                    "action_window_record_shape",
                )
            )
            else "needs_fix",
            "scope": "listener ordering, event alias admission, blocked category, and unified listener record shape",
        },
        "global_being_hit_per_hit_execution": {
            "semantic_status": "blocked",
            "blocking_dependency": "queue/follow-up/counter/AI/downstream intent systems are not admitted in v0_238",
        },
        "action_window_dispatch": {
            "semantic_status": "trusted_for_current_scope" if checks["action_window_record_shape"]["ok"] else "needs_fix",
            "scope": "action window wrapper still delegates execution to TriggerSystem but emits unified listener records",
        },
    }


def _dispatch_aliases(record: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    metadata = _record_payload(record).get("metadata")
    if not isinstance(metadata, dict):
        return ()
    aliases = metadata.get("event_aliases")
    if not isinstance(aliases, list):
        return ()
    return tuple(alias for alias in aliases if isinstance(alias, dict))


def _all_records(transitions: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for transition in transitions:
        records.extend(_records_from_json(transition))
    return tuple(records)


def _records_from_json(transition: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    settlement = transition.get("settlement")
    if not isinstance(settlement, dict):
        return ()
    records = settlement.get("records")
    if not isinstance(records, list):
        return ()
    return tuple(record for record in records if isinstance(record, dict))


if __name__ == "__main__":
    raise SystemExit(main())
