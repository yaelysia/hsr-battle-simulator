from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent, TargetResolution, UnitState
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_284 import (
    ATTACHED_SINGLE_ALIASES,
    _command_for_candidate,
    _scenario_state,
    _select_runtime_positive_candidate,
)


VALIDATION_VERSION = "v0_285"
POSITIVE_RUNTIME_EVENTS = (
    "damage.before_hit",
    "damage.hit",
    "turn.end",
    "queue.action.after",
    "status.lifecycle",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    coverage_case = _coverage_case(rules)
    route_case = _route_case(rules)
    lifecycle_case = _lifecycle_source_case(rules, package_root.parent)
    boundary_case = _boundary_case(rules)
    checks = {
        "coverage": coverage_case["checks"],
        "route": route_case["checks"],
        "status_lifecycle_source": lifecycle_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "status_callback_count": len(ir.status_callbacks),
            "status_event_family_count": len(ir.status_event_families),
            "selection_policy": {
                "mode": "structured_predicate",
                "fixed_character_monster_skill_or_file_used_for_selection": False,
                "positive_routes": list(POSITIVE_RUNTIME_EVENTS),
                "blocked_routes": ["custom.event", "wave.monster", "special.mode"],
            },
        },
        "checks": checks,
        "coverage_case": coverage_case,
        "route_case": route_case,
        "status_lifecycle_source_case": lifecycle_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_285.json", result)
    write_json(output_dir / "status_event_family_coverage_v0_285.json", coverage_case)
    write_json(output_dir / "status_event_family_routes_v0_285.json", route_case)
    write_json(output_dir / "status_lifecycle_event_source_v0_285.json", lifecycle_case)
    write_json(output_dir / "status_event_family_boundary_v0_285.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_285 status event family routing.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _coverage_case(rules: RuleBook) -> dict[str, Any]:
    callback_events = {callback.event for callback in rules.ir.status_callbacks}
    family_events = {family.callback_event for family in rules.ir.status_event_families}
    executable = [family for family in rules.ir.status_event_families if family.coverage_status == "executable"]
    blocked = [family for family in rules.ir.status_event_families if family.coverage_status == "blocked"]
    event_counts = {
        "total_callback_events": len(callback_events),
        "total_event_families": len(family_events),
        "executable_event_families": len(executable),
        "blocked_event_families": len(blocked),
    }
    checks = {
        "covers_all_callback_events": callback_events == family_events,
        "executable_families_have_runtime_source": all(family.runtime_event_sources for family in executable),
        "blocked_families_have_reason": all(bool(family.blocked_reason or family.blocking_dependency) for family in blocked),
        "custom_event_blocked": _family_status(rules, "OnCustomEvent") == "blocked",
        "wave_event_blocked": _family_status(rules, "OnWaveMonster") == "blocked",
        "before_hit_family_executable": _family_status(rules, "OnBeforeHit") == "executable",
        "status_lifecycle_family_executable": _family_status(rules, "OnCreate") == "executable",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "event_counts": event_counts,
        "sample_families": {
            event: _family_json(rules, event)
            for event in (
                "OnBeforeHit",
                "OnBeforeHitAll",
                "OnAfterBeingAttacked",
                "OnCreate",
                "OnDestroy",
                "OnCustomEvent",
                "OnWaveMonster",
            )
        },
    }


def _route_case(rules: RuleBook) -> dict[str, Any]:
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    state = _probe_state()
    routes: dict[str, Any] = {}
    for event_type in POSITIVE_RUNTIME_EVENTS:
        event = _probe_event(event_type)
        result = dispatcher.dispatch_event(state, event=event)
        aliases = _aliases_from_records(result.records)
        routes[event_type] = {
            "mutation_count": len(result.mutations),
            "aliases": aliases,
            "records": result.records,
        }
    checks = {
        "runtime_events_have_event_family_alias": all(
            any(alias.get("status_event_family_id") for alias in route["aliases"])
            for route in routes.values()
        ),
        "routes_are_process_only_without_matching_status": all(route["mutation_count"] == 0 for route in routes.values()),
        "before_hit_routes_before_hit_family": any(
            alias.get("callback_event") in {"OnBeforeHit", "OnBeforeHitAll"}
            for alias in routes["damage.before_hit"]["aliases"]
        ),
        "status_lifecycle_routes_lifecycle_family": any(
            alias.get("event_family") == "status_lifecycle"
            for alias in routes["status.lifecycle"]["aliases"]
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "routes": routes}


def _lifecycle_source_case(rules: RuleBook, hsr_root: Path) -> dict[str, Any]:
    candidate = _select_runtime_positive_candidate(rules, hsr_root, aliases=ATTACHED_SINGLE_ALIASES, extra_enemy=False)
    state = _scenario_state(rules, hsr_root, candidate.card, extra_enemy=False)
    command = _command_for_candidate(rules, candidate)
    target_id = command.target_ids[0] if command.target_ids else "ally:saber"
    result = StatusSystem(rules).apply_add_modifier(
        state,
        candidate.effect,
        caster_id=command.actor_id,
        source_id="validation:v0_285:status_lifecycle_source",
        owner_id=command.actor_id,
        param_entity_id=target_id,
        current_action_target_id=target_id,
        target_resolution=TargetResolution(requested=(target_id,), legal=(target_id,), selected=(target_id,)),
    )
    lifecycle_events = [event.to_json() for event in result.events if event.event_type == "status.lifecycle"]
    checks = {
        "status_application_ok": result.ok,
        "status_mutation_present": bool(result.mutations),
        "lifecycle_events_emitted": bool(lifecycle_events),
        "lifecycle_events_have_callback_event": all(bool(event["payload"].get("callback_event")) for event in lifecycle_events),
        "lifecycle_events_are_process_only": all(event["process_only"] is True for event in lifecycle_events),
        "lifecycle_events_have_mutation_ids": all(bool(event["payload"].get("mutation_ids")) for event in lifecycle_events),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "candidate": {
            "card_id": candidate.card.card_id,
            "action_id": candidate.action_id,
            "effect_id": candidate.effect.effect_id,
            "modifier_name": candidate.modifier_name,
            "target_alias": candidate.target_alias,
        },
        "events": lifecycle_events,
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "records": result.records,
    }


def _boundary_case(rules: RuleBook) -> dict[str, Any]:
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    state = _probe_state()
    custom_result = dispatcher.dispatch_event(state, event=GameEvent("custom.event", source_id="ally:a", target_id="enemy:b"))
    wave_result = dispatcher.dispatch_event(state, event=GameEvent("wave.monster", source_id="system", target_id="enemy:b"))
    missing_result = dispatcher.dispatch_event(state, event=GameEvent("special.mode", source_id="system", target_id="enemy:b"))
    custom_aliases = _aliases_from_records(custom_result.records)
    wave_aliases = _aliases_from_records(wave_result.records)
    missing_aliases = _aliases_from_records(missing_result.records)
    checks = {
        "custom_event_state_unchanged": custom_result.after_state == state and not custom_result.mutations,
        "wave_event_state_unchanged": wave_result.after_state == state and not wave_result.mutations,
        "missing_event_state_unchanged": missing_result.after_state == state and not missing_result.mutations,
        "custom_event_blocked_alias": any(alias.get("admission_status") == "blocked" for alias in custom_aliases),
        "wave_event_blocked_alias": any(alias.get("admission_status") == "blocked" for alias in wave_aliases),
        "missing_event_alias_missing": any(alias.get("blocked_dependency") == "event_alias_missing" for alias in missing_aliases),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "custom_aliases": custom_aliases,
        "wave_aliases": wave_aliases,
        "missing_aliases": missing_aliases,
        "records": {
            "custom": custom_result.records,
            "wave": wave_result.records,
            "missing": missing_result.records,
        },
    }


def _probe_state() -> BattleState:
    return BattleState(
        units={
            "ally:a": UnitState("ally:a", "ally", "avatar:probe", max_hp=1000, hp=1000, attack=100, defense=100),
            "enemy:b": UnitState("enemy:b", "enemy", "monster:probe", max_hp=1000, hp=1000, attack=100, defense=100),
        }
    )


def _probe_event(event_type: str) -> GameEvent:
    return GameEvent(
        event_type,
        source_id="ally:a",
        target_id="enemy:b",
        window=event_type,
        process_only=True,
        payload={
            "actor_id": "ally:a",
            "attacker_id": "ally:a",
            "damage_attacker_id": "ally:a",
            "primary_target_id": "enemy:b",
            "primary_action_target_id": "enemy:b",
            "current_hit_target_id": "enemy:b",
            "target_id": "enemy:b",
            "selected_target_ids": ["enemy:b"],
            "target_ids": ["enemy:b"],
            "listener_scope": "status_local" if event_type == "status.lifecycle" else "",
            "modifier_name": "probe_modifier",
            "status_instance_id": "probe_status",
        },
    )


def _aliases_from_records(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            raw_aliases = metadata.get("event_aliases")
            if isinstance(raw_aliases, list):
                aliases.extend(alias for alias in raw_aliases if isinstance(alias, dict))
            raw_alias = metadata.get("event_alias")
            if isinstance(raw_alias, dict):
                aliases.append(raw_alias)
        raw_alias = payload.get("event_alias")
        if isinstance(raw_alias, dict):
            aliases.append(raw_alias)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for alias in aliases:
        key = (
            str(alias.get("callback_event") or ""),
            str(alias.get("scope_kind") or ""),
            str(alias.get("source_basis") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alias)
    return deduped


def _family_status(rules: RuleBook, callback_event: str) -> str:
    family = rules.status_event_family(callback_event)
    return family.coverage_status if family is not None else "missing"


def _family_json(rules: RuleBook, callback_event: str) -> dict[str, Any]:
    family = rules.status_event_family(callback_event)
    return family.to_json() if family is not None else {}


if __name__ == "__main__":
    raise SystemExit(main())
