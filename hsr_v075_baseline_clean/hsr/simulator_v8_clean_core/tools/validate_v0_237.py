from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent
from ..core.reducer import MutationReducer
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
from .validate_v0_236 import _coverage_checks as _v236_coverage_checks
from .validate_v0_236 import _records


VALIDATION_VERSION = "v0_237"


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

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "status_local_dispatch": status_dispatch_case["checks"],
        "blocked_scoped_listener": blocked_listener_case["checks"],
        "multi_target_dispatch": multi_target_case["checks"],
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((identity.ok, static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selected_status_dispatch": status_dispatch_case["selected_delay"],
            "selected_blocked_listener": blocked_listener_case["selected_callback"],
            "selected_multi_target_definition": multi_target_case["selected_definition"],
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "status_local_dispatch": status_dispatch_case["source_audit"],
            "blocked_scoped_listener": blocked_listener_case["source_audit"],
            "multi_target": multi_target_case["source_audit"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_237.json", result)
    write_json(output_dir / "sample_status_local_dispatch_transition_v0_237.json", status_dispatch_case["transition"])
    write_json(output_dir / "sample_blocked_scoped_listener_transition_v0_237.json", blocked_listener_case["transition"])
    write_json(output_dir / "sample_multi_target_dispatch_transition_v0_237.json", multi_target_case["transition"])
    write_json(output_dir / "coverage_summary_v0_237.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_237 listener scope admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _status_local_dispatch_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    delay = _select_executable_action_delay(rules)
    state = _state_with_delay_status(rules, base_state, delay)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
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
            "dispatch_event_used": _has_dispatch_record(records, "listener_dispatch"),
            "listener_match_record_present": _has_record(records, "listener_match"),
            "status_callback_mutation_present": any(mutation.source == "status_callback_system" for mutation in result.mutations),
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


def _blocked_scoped_listener_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    callback = _select_blocked_scoped_listener(rules)
    state = _state_with_callback_status(base_state, callback)
    event = _event_for_callback(callback)
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="event_dispatch:blocked_scoped_listener",
        metadata={"event": callback.event, "modifier_name": callback.modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    records = _records(transition)
    listener_records = _records_of_type(records, "listener_match")
    checks.update(
        {
            "source_audit": source_audit.ok,
            "selected_listener_has_scope": callback.scope_kind in {"global_listener", "being_hit_target_local", "per_hit_target_local"},
            "listener_structurally_matched": any(
                _record_payload(record).get("listener_id") == callback.callback_id
                for record in listener_records
            ),
            "listener_blocked": any(
                _record_payload(record).get("listener_id") == callback.callback_id
                and _record_payload(record).get("status") == "blocked"
                for record in listener_records
            ),
            "no_mutations": not result.mutations,
            "snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_callback": callback.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _multi_target_dispatch_case(rules: RuleBook, ir, build_result) -> dict[str, Any]:
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
    records = _records(transition) if transition else ()
    hit_events = [event for event in events if event.event_type in {"damage.hit", "toughness.hit"}]
    dispatch_records = [
        record
        for record in _records_of_type(records, "event_dispatch")
        if _record_payload(record).get("scope") == "per_hit_target_local"
    ]
    checks.update(
        {
            "definition_selected": definition is not None,
            "source_audit": bool(source_audit and source_audit.ok),
            "hit_events_present": bool(hit_events),
            "per_hit_context_payload_present": all(
                isinstance(event.payload.get("current_hit_target_id"), str)
                and event.payload.get("per_hit_target_context_available") is True
                for event in hit_events
            ),
            "multi_target_has_multiple_hit_targets": len(
                {
                    event.payload.get("current_hit_target_id")
                    for event in hit_events
                    if isinstance(event.payload.get("current_hit_target_id"), str)
                }
            )
            >= 2,
            "per_hit_events_dispatched": bool(dispatch_records),
            "coverage_no_longer_marks_missing_per_hit_context": transition is not None
            and transition.coverage.get("per_hit_target_context_not_implemented") is False,
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


def _select_blocked_scoped_listener(rules: RuleBook) -> StatusCallbackIR:
    preferred_scopes = ("per_hit_target_local", "being_hit_target_local", "global_listener")
    for scope in preferred_scopes:
        for callback in sorted(rules.ir.status_callbacks, key=_blocked_listener_sort_key):
            if callback.scope_kind != scope:
                continue
            if callback.coverage_status != "executable":
                return callback
    raise RuntimeError("no blocked scoped listener callback found")


def _blocked_listener_sort_key(callback: StatusCallbackIR) -> tuple[object, ...]:
    path = callback.source.source_path
    return (
        callback.source_mode != "mainline",
        path.startswith("Config/ConfigAbility/Activity/"),
        path,
        callback.event,
        callback.modifier_name,
        callback.callback_id,
    )


def _state_with_callback_status(state: BattleState, callback: StatusCallbackIR) -> BattleState:
    unit_id = _unit_for_scope(callback.scope_kind)
    unit = state.units[unit_id]
    status_id = f"modifier:{callback.modifier_name}"
    details = [
        item
        for item in unit.flags.get("status_details", ())
        if not (isinstance(item, dict) and item.get("modifier_name") == callback.modifier_name)
    ]
    details.append(
        {
            "instance_id": f"validation:{callback.callback_id}",
            "status_id": status_id,
            "modifier_name": callback.modifier_name,
            "owner_id": unit_id,
            "source_id": callback.callback_id,
            "caster_id": "ally:actor",
            "source_trace": {"status_callback": callback.source.to_json()},
            "trigger_ids_by_event": {callback.event: [callback.callback_id]},
        }
    )
    statuses = tuple(dict.fromkeys((*unit.statuses, status_id)))
    updated_unit = replace(unit, statuses=statuses, flags={**unit.flags, "status_details": tuple(details)})
    return replace(state, units={**state.units, unit_id: updated_unit})


def _event_for_callback(callback: StatusCallbackIR) -> GameEvent:
    scope = callback.scope_kind
    target_id = _unit_for_scope(scope)
    return GameEvent(
        event_type="damage.hit" if scope in {"per_hit_target_local", "being_hit_target_local"} else f"listener.{callback.event}",
        source_id="ally:actor",
        target_id=target_id,
        window=callback.event,
        process_only=True,
        payload={
            "callback_event": callback.event,
            "listener_scope": scope,
            "actor_id": "ally:actor",
            "attacker_id": "ally:actor",
            "target_id": target_id,
            "primary_action_target_id": "enemy:profile_target",
            "current_hit_target_id": target_id,
            "modifier_name": callback.modifier_name,
            "callback_id": callback.callback_id,
            "source_trace": callback.source.to_json(),
            "per_hit_target_context_available": scope in {"per_hit_target_local", "being_hit_target_local"},
        },
    )


def _unit_for_scope(scope_kind: str) -> str:
    if scope_kind == "actor_local":
        return "ally:actor"
    return "enemy:profile_target"


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    base = _v236_coverage_checks(coverage_json, ir)
    status_callbacks = base["status_callbacks"]
    scope_counts = status_callbacks.get("scope_counts", {})
    checks = {
        **base["checks"],
        "coverage_reports_callback_scopes": isinstance(scope_counts, dict) and bool(scope_counts),
        "per_hit_or_being_or_global_scope_present": any(
            int(scope_counts.get(scope, 0) or 0) > 0
            for scope in ("per_hit_target_local", "being_hit_target_local", "global_listener")
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "status_callbacks": status_callbacks}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "event_dispatch": {
            "semantic_status": "trusted_for_current_scope" if checks["status_local_dispatch"]["ok"] else "needs_fix",
            "scope": "dispatch_event is the common entry for action/status/hit listener dispatch records",
        },
        "global_being_hit_per_hit_listener": {
            "semantic_status": "blocked" if checks["blocked_scoped_listener"]["ok"] else "needs_fix",
            "blocking_dependency": "runtime only records matched blocked listeners until source/scope/condition/target/effect are all admitted",
        },
        "per_hit_event_context": {
            "semantic_status": "trusted_for_current_scope" if checks["multi_target_dispatch"]["ok"] else "needs_fix",
            "scope": "damage/toughness hit events carry current_hit_target_id and are dispatched through EventDispatchSystem",
        },
    }


def _has_dispatch_record(records: tuple[dict[str, Any], ...], listener_kind: str) -> bool:
    return any(
        record.get("record_type") == "event_dispatch"
        and _record_payload(record).get("listener_kind") == listener_kind
        for record in records
    )


def _has_record(records: tuple[dict[str, Any], ...], record_type: str) -> bool:
    return any(record.get("record_type") == record_type for record in records)


def _records_of_type(records: tuple[dict[str, Any], ...], record_type: str) -> tuple[dict[str, Any], ...]:
    return tuple(record for record in records if record.get("record_type") == record_type)


def _record_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
