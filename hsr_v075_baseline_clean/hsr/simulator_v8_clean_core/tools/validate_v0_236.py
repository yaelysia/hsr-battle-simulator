from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleTransition, GameEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
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
from .validate_v0_218 import (
    _definition_has_executable_damage_emission,
    _execute_mode_case,
    _multi_enemy_state,
    _select_definition,
)
from .validate_v0_235 import (
    _execute_break_setup,
    _select_break_family_case,
    _select_executable_action_delay,
    _state_with_delay_status,
    _status_callback_event,
    _system_transition,
    _transition_checks,
)


VALIDATION_VERSION = "v0_236"


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
    blocked_listener_case = _blocked_listener_case(rules, break_setup["initial_state"])
    multi_target_case = _multi_target_event_case(rules, ir, build_result)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "status_local_dispatch": status_dispatch_case["checks"],
        "blocked_listener": blocked_listener_case["checks"],
        "multi_target_per_hit": multi_target_case["checks"],
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((identity.ok, static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selected_blocked_listener": blocked_listener_case["selected_callback"],
            "selected_status_dispatch": status_dispatch_case["selected_delay"],
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "status_local_dispatch": status_dispatch_case["source_audit"],
            "multi_target": multi_target_case["source_audit"],
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_236.json", result)
    write_json(output_dir / "sample_status_local_dispatch_transition_v0_236.json", status_dispatch_case["transition"])
    write_json(output_dir / "sample_blocked_listener_transition_v0_236.json", blocked_listener_case["transition"])
    write_json(output_dir / "sample_multi_target_per_hit_transition_v0_236.json", multi_target_case["transition"])
    write_json(output_dir / "coverage_summary_v0_236.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_236 event listener dispatch spine.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _status_local_dispatch_case(rules: RuleBook, base_state) -> dict[str, Any]:
    delay = _select_executable_action_delay(rules)
    state = _state_with_delay_status(rules, base_state, delay)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_status_callback(
        state,
        event=_status_callback_event(delay.event, delay.modifier_name),
        unit_id="enemy:profile_target",
        modifier_name=delay.modifier_name,
    )
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="event_dispatch:status_callback",
        metadata={"event": delay.event, "modifier_name": delay.modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    records = _records(transition)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "dispatch_record_present": _has_record(records, "event_dispatch"),
            "listener_match_record_present": _has_record(records, "listener_match"),
            "status_callback_mutation_present": any(mutation.source == "status_callback_system" for mutation in result.mutations),
            "event_dispatch_events_present": any(event.event_type.startswith("status.callback") for event in result.events),
            "after_changed": result.after_state.snapshot().to_json() != state.snapshot().to_json(),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_delay": delay.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _blocked_listener_case(rules: RuleBook, state) -> dict[str, Any]:
    callback = _select_blocked_listener(rules)
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    event = GameEvent(
        event_type=f"listener.{callback.event}",
        source_id="ally:actor",
        target_id="enemy:profile_target",
        window=callback.event,
        process_only=True,
        payload={
            "callback_event": callback.event,
            "modifier_name": callback.modifier_name,
            "callback_id": callback.callback_id,
            "source_trace": callback.source.to_json(),
        },
    )
    scope = _listener_scope(callback)
    result = dispatcher.dispatch_blocked(
        state,
        event=event,
        listener_kind=scope,
        scope=scope,
        reason=callback.blocked_reason or f"listener_not_executable:{callback.coverage_status}",
        metadata={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "event": callback.event,
            "source_trace": callback.source.to_json(),
        },
    )
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="event_dispatch:blocked_listener",
        metadata={"event": callback.event, "modifier_name": callback.modifier_name},
    )
    checks = _transition_checks(transition, state)
    records = _records(transition)
    checks.update(
        {
            "blocked_listener_selected": callback.coverage_status != "executable",
            "dispatch_record_present": _has_record(records, "event_dispatch"),
            "listener_match_record_present": _has_record(records, "listener_match"),
            "no_mutations": not result.mutations,
            "snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_callback": callback.to_json(),
        "transition": transition.to_json(),
    }


def _multi_target_event_case(rules: RuleBook, ir, build_result) -> dict[str, Any]:
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )
    definition = _select_multi_target_damage_definition(ir)
    case = _execute_mode_case(rules, base_state, base_command, definition, definition.target_mode if definition else "missing")
    transition = case.get("transition")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition) if transition else None
    checks = _transition_checks(transition, base_state) if transition else {"transition_contract": False, "settlement_traceability": False, "snapshot_completeness": False, "replay": False}
    events = transition.transaction.events if transition else ()
    damage_hit_events = [event for event in events if event.event_type == "damage.hit"]
    checks.update(
        {
            "definition_selected": definition is not None,
            "source_audit": bool(source_audit and source_audit.ok),
            "damage_hit_event_present": bool(damage_hit_events),
            "per_hit_context_payload_present": all(
                isinstance(event.payload.get("current_hit_target_id"), str)
                and event.payload.get("per_hit_target_context_available") is True
                for event in damage_hit_events
            ),
            "multi_target_has_multiple_hit_targets": len(
                {
                    event.payload.get("current_hit_target_id")
                    for event in damage_hit_events
                    if isinstance(event.payload.get("current_hit_target_id"), str)
                }
            )
            >= 2,
            "coverage_no_longer_marks_missing_per_hit_context": transition is not None
            and transition.coverage.get("per_hit_target_context_not_implemented") is False,
            "coverage_marks_listener_partial": transition is not None
            and transition.coverage.get("per_hit_listener_admission_partial") is True,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_definition": definition.to_json() if definition else {},
        "transition": transition.to_json() if transition else {},
        "source_audit": source_audit.to_json() if source_audit else {},
    }


def _select_multi_target_damage_definition(ir):
    for mode in ("aoe", "blast"):
        definition = _select_definition(ir, mode)
        if definition is None:
            continue
        if _definition_has_executable_damage_emission(ir, definition):
            return definition
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.target_mode not in {"aoe", "blast"}:
            continue
        if definition.damage_kind != "hp_damage" or definition.damage_formula_family != "direct":
            continue
        if _definition_has_executable_damage_emission(ir, definition):
            return definition
    return None


def _select_blocked_listener(rules: RuleBook) -> StatusCallbackIR:
    preferred_prefixes = ("OnListen", "OnBeing", "OnHit")
    for callback in sorted(rules.ir.status_callbacks, key=lambda item: (item.event, item.modifier_name, item.callback_id)):
        if callback.coverage_status == "executable":
            continue
        if callback.event.startswith(preferred_prefixes):
            return callback
    for callback in sorted(rules.ir.status_callbacks, key=lambda item: (item.event, item.modifier_name, item.callback_id)):
        if callback.coverage_status != "executable":
            return callback
    raise RuntimeError("no blocked listener callback found")


def _listener_scope(callback: StatusCallbackIR) -> str:
    if callback.event.startswith("OnListen"):
        return "global_listener"
    if callback.event.startswith("OnBeing"):
        return "being_hit_listener"
    if "Hit" in callback.event:
        return "per_hit_listener"
    return "status_listener"


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    status_callbacks = status.get("status_callbacks", {})
    checks = {
        "status_callbacks_lowered": len(ir.status_callbacks) > 0,
        "status_callback_tasks_lowered": len(ir.status_callback_tasks) > 0,
        "coverage_reports_status_callbacks": status_callbacks.get("lowered", 0) > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "status_callbacks": status_callbacks}


def _records(transition: BattleTransition) -> tuple[dict[str, Any], ...]:
    settlement = transition.transaction.settlement
    if settlement is None:
        return ()
    return tuple(record for record in settlement.records if isinstance(record, dict))


def _has_record(records: tuple[dict[str, Any], ...], record_type: str) -> bool:
    return any(record.get("record_type") == record_type for record in records)


if __name__ == "__main__":
    raise SystemExit(main())
