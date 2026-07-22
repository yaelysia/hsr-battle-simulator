from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..resource_event_contract import (
    RESOURCE_EVENT_CONTRACTS,
    RETIRED_RESOURCE_EVENT_TYPES,
    TEAM_SKILL_POINT_EVENT_CONTRACT,
    UNIT_ENERGY_EVENT_CONTRACT,
    resource_callback_runtime_sources,
    resource_production_event_types,
)
from ..rules.ir import StatusEventFamilyIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.mutation_events import before_toughness_event, events_for_mutation
from ..systems.resource import ResourceSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import STATUS_EVENT_RUNTIME_SOURCES, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p7_s0_kernel_trust_baseline import (
    _minimal_rulebook,
    _source,
)


VALIDATION_VERSION = "v0_286"

MUTATION_BACKED_EVENTS = (
    "OnHPChange",
    "OnListenHPChange",
    "OnAfterBeingHeal",
    "OnAfterDealHeal",
    "OnHPOverflow",
    "OnShieldChange",
    "OnListenShieldChange",
    "OnListenInitShield",
    "OnBeforeBeingStanceDamage",
    "OnBeingStanceDamage",
    "OnListenBreak",
    "OnAddModifierSuc",
    "OnListenModifierAdd",
    "OnListenModifierRemove",
    "OnModifierOnStack",
    "OnListenModifierOnStack",
    "OnModifierDotAdd",
    "OnActionDelayEffect",
    "OnActionDelayEffectAll",
    "OnListenGlobalActionDelayChanged",
    *tuple(resource_callback_runtime_sources()),
)

STILL_BLOCKED_EVENTS = (
    "OnDispel",
    "OnListenModifierDispel",
    "OnResistModifier",
    "OnListenModifierResist",
    "OnLockHPThresholdReached",
    "OnCustomEvent",
    "OnVersusBarFever",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    family_case = _family_case(rules)
    mutation_event_case = _mutation_event_case(rules)
    resource_event_case = _resource_event_case(rules)
    before_case = _before_event_safety_case(rules)
    boundary_case = _boundary_case(rules)
    checks = {
        "family": family_case["checks"],
        "mutation_events": mutation_event_case["checks"],
        "resource_events": resource_event_case["checks"],
        "before_safety": before_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "status_event_family_count": len(ir.status_event_families),
            "selection_policy": {
                "mode": "structured_event_family_and_mutation_path",
                "fixed_character_monster_skill_or_file_used_for_selection": False,
                "runtime_sources": sorted({
                    "hp.change",
                    "heal.after",
                    "shield.change",
                    "toughness.before_hit",
                    "toughness.hit",
                    "status.lifecycle",
                    "action_delay.changed",
                    *resource_production_event_types(),
                }),
            },
        },
        "checks": checks,
        "family_case": family_case,
        "mutation_event_case": mutation_event_case,
        "resource_event_case": resource_event_case,
        "before_event_safety_case": before_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_286.json", result)
    write_json(output_dir / "mutation_backed_event_families_v0_286.json", family_case)
    write_json(output_dir / "mutation_backed_event_payloads_v0_286.json", mutation_event_case)
    write_json(output_dir / "resource_event_contract_v0_286.json", resource_event_case)
    write_json(output_dir / "before_event_safety_v0_286.json", before_case)
    write_json(output_dir / "mutation_backed_event_boundaries_v0_286.json", boundary_case)
    return result


def run_resource_event_validation(
    package_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Run only the migrated resource-event slice without full TBGD lowering."""

    baseline = _minimal_rulebook()
    runtime_sources = resource_callback_runtime_sources()
    families = tuple(
        StatusEventFamilyIR(
            status_event_family_id=f"validation:v0_286:resource:{callback_event}",
            callback_event=callback_event,
            event_family="resource_mutation",
            default_scope_kind=next(
                contract.scope_kind
                for contract in RESOURCE_EVENT_CONTRACTS
                if callback_event in contract.callback_events
            ),
            runtime_event_sources=event_sources,
            source_basis="authoritative_resource_event_contract",
            source=_source(f"resource_event:{callback_event}"),
            coverage_status="executable",
            admission_status="executable",
        )
        for callback_event, event_sources in runtime_sources.items()
    )
    rules = RuleBook(replace(baseline.ir, status_event_families=families))
    resource_case = _resource_event_case(rules)
    family_rows = {
        callback_event: _family_json(rules, callback_event)
        for callback_event in runtime_sources
    }
    checks = {
        **resource_case["checks"]["checks"],
        "lowering_uses_authoritative_resource_event_contract": all(
            STATUS_EVENT_RUNTIME_SOURCES.get(callback_event) == event_sources
            for callback_event, event_sources in runtime_sources.items()
        ),
        "resource_family_scope_matches_contract": all(
            family_rows[callback_event].get("default_scope_kind")
            == next(
                contract.scope_kind
                for contract in RESOURCE_EVENT_CONTRACTS
                if callback_event in contract.callback_events
            )
            for callback_event in runtime_sources
        ),
        "static_checks": run_static_checks(package_root).ok,
    }
    checks.pop("ok", None)
    checks["ok"] = all(checks.values())
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "schema_version": "v0_286_resource_event_focused_summary_v1",
        "ok": checks["ok"],
        "checks": checks,
        "resource_event_case": resource_case,
        "resource_event_families": family_rows,
        "resource_scope": {
            "full_tbgd_lowering_executed": False,
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_286_resource_events.json", result)
    write_json(output_dir / "resource_event_contract_v0_286.json", resource_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_286 mutation-backed status event sources.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument(
        "--resource-events-only",
        action="store_true",
        help="Validate only the migrated resource-event contract without full lowering.",
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    if args.resource_events_only:
        result = run_resource_event_validation(package_root, args.output_dir)
    else:
        tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
        result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _family_case(rules: RuleBook) -> dict[str, Any]:
    expected = {event: _family_json(rules, event) for event in MUTATION_BACKED_EVENTS if rules.status_event_family(event)}
    blocked = {event: _family_json(rules, event) for event in STILL_BLOCKED_EVENTS if rules.status_event_family(event)}
    checks = {
        "expected_families_exist": len(expected) == len(MUTATION_BACKED_EVENTS),
        "expected_families_executable": all(item.get("coverage_status") == "executable" for item in expected.values()),
        "expected_families_have_runtime_source": all(bool(item.get("runtime_event_sources")) for item in expected.values()),
        "no_expected_event_source_missing": all(
            "event_source_missing" not in str(item.get("blocked_reason") or item.get("blocking_dependency") or "")
            for item in expected.values()
        ),
        "blocked_families_remain_blocked": all(item.get("coverage_status") == "blocked" for item in blocked.values()),
        "blocked_reasons_are_explicit": all(bool(item.get("blocked_reason") or item.get("blocking_dependency")) for item in blocked.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expected_families": expected,
        "still_blocked_families": blocked,
    }


def _mutation_event_case(rules: RuleBook) -> dict[str, Any]:
    state = _probe_state()
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    mutations = _probe_mutations(state)
    cases: dict[str, Any] = {}
    for name, mutation in mutations.items():
        events = events_for_mutation(
            mutation,
            actor_id="ally:a",
            source_id="ally:a",
            event_index=state.event_index,
            extra_payload={"validation_case": name},
        )
        dispatches = [dispatcher.dispatch_event(state, event=event) for event in events]
        cases[name] = {
            "mutation": mutation.to_json(),
            "events": [event.to_json() for event in events],
            "aliases": [_aliases_from_records(result.records) for result in dispatches],
            "mutation_counts": [len(result.mutations) for result in dispatches],
        }
    checks = {
        "damage_hp_event_has_payload": _case_event_has_payload(cases, "damage_hp", "hp.change"),
        "heal_event_has_overflow_alias": any(
            "OnHPOverflow" in event["payload"].get("callback_events", ())
            for event in cases["heal_overflow"]["events"]
        ),
        "shield_event_has_init_alias": any(
            "OnListenInitShield" in event["payload"].get("callback_events", ())
            for event in cases["shield_init"]["events"]
        ),
        "bp_event_engine_convention": _case_source_kind(cases, "skill_points_gain") == "engine_convention",
        "energy_event_engine_convention": _case_source_kind(cases, "energy_gain") == "engine_convention",
        "heal_event_tbgd_effect": _case_source_kind(cases, "heal_overflow") == "tbgd_effect",
        "action_delay_event_present": _case_event_has_payload(cases, "action_delay", "action_delay.changed"),
        "all_events_process_only_without_matching_status": all(
            count == 0 for case in cases.values() for count in case["mutation_counts"]
        ),
        "all_payloads_have_mutation_id_and_path": all(
            bool(event["payload"].get("mutation_id")) and bool(event["payload"].get("mutation_path"))
            for case in cases.values()
            for event in case["events"]
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _resource_event_case(rules: RuleBook) -> dict[str, Any]:
    state = _probe_state()
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    mutations = _probe_mutations(state)
    resource_cases: dict[str, Any] = {}
    cross_trigger_count = 0
    produced_event_types: set[str] = set()
    team_callbacks = set(TEAM_SKILL_POINT_EVENT_CONTRACT.callback_events)
    energy_callbacks = set(UNIT_ENERGY_EVENT_CONTRACT.callback_events)
    for case_name in (
        "skill_points_gain",
        "skill_points_spend",
        "energy_gain",
        "energy_spend",
    ):
        mutation = mutations[case_name]
        events = events_for_mutation(
            mutation,
            actor_id="ally:a",
            source_id="ally:a",
            event_index=state.event_index,
        )
        produced_event_types.update(event.event_type for event in events)
        callback_events = {
            str(callback_event)
            for event in events
            for callback_event in event.payload.get("callback_events", ())
        }
        expected_callbacks = (
            team_callbacks if case_name.startswith("skill_points") else energy_callbacks
        )
        unexpected_callbacks = (
            energy_callbacks if case_name.startswith("skill_points") else team_callbacks
        )
        cross_trigger_count += len(callback_events & unexpected_callbacks)
        resource_cases[case_name] = {
            "mutation": mutation.to_json(),
            "events": [event.to_json() for event in events],
            "callback_events": sorted(callback_events),
            "expected_callback_events": sorted(expected_callbacks),
            "unexpected_callback_events": sorted(
                callback_events & unexpected_callbacks
            ),
        }

    energy_after_event = next(
        event
        for event in events_for_mutation(
            mutations["energy_spend"],
            actor_id="ally:a",
            source_id="ally:a",
            event_index=state.event_index,
            include_before=False,
        )
        if event.event_type == UNIT_ENERGY_EVENT_CONTRACT.after_event_type
    )
    retired_event_type = next(iter(RETIRED_RESOURCE_EVENT_TYPES))
    forged_event = replace(
        energy_after_event,
        event_type=retired_event_type,
        event_id=f"{energy_after_event.event_id}:retired_resource_event",
    )
    forged = dispatcher.dispatch_event(state, event=forged_event)
    forged_callback_records = tuple(
        record
        for record in forged.records
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id")
    )
    energy_deltas = {
        case_name: next(
            (
                event["payload"].get("change_value")
                for event in resource_cases[case_name]["events"]
                if event["event_type"]
                == UNIT_ENERGY_EVENT_CONTRACT.after_event_type
            ),
            None,
        )
        for case_name in ("energy_gain", "energy_spend")
    }
    dead_production_events = sorted(
        resource_production_event_types() - produced_event_types
    )
    checks = {
        "team_skill_points_use_bp_event": all(
            [event["event_type"] for event in resource_cases[case_name]["events"]]
            == [TEAM_SKILL_POINT_EVENT_CONTRACT.after_event_type]
            and resource_cases[case_name]["callback_events"]
            == sorted(TEAM_SKILL_POINT_EVENT_CONTRACT.after_callback_events)
            for case_name in ("skill_points_gain", "skill_points_spend")
        ),
        "unit_energy_uses_energy_event": all(
            [event["event_type"] for event in resource_cases[case_name]["events"]]
            == list(UNIT_ENERGY_EVENT_CONTRACT.production_event_types)
            and resource_cases[case_name]["callback_events"]
            == sorted(UNIT_ENERGY_EVENT_CONTRACT.callback_events)
            for case_name in ("energy_gain", "energy_spend")
        ),
        "on_sp_change_receives_energy_delta": (
            energy_deltas["energy_gain"]
            == mutations["energy_gain"].after - mutations["energy_gain"].before
            and energy_deltas["energy_spend"]
            == mutations["energy_spend"].after
            - mutations["energy_spend"].before
        ),
        "resource_event_cross_trigger_count": cross_trigger_count == 0,
        "dead_production_resource_event_count": not dead_production_events,
        "retired_sp_change_blocked_unchanged": (
            bool(forged.errors)
            and not forged_callback_records
            and not forged.mutations
            and forged.after_state == state
        ),
        "contract_paths_are_distinct": len(
            {contract.state_path_pattern for contract in RESOURCE_EVENT_CONTRACTS}
        )
        == len(RESOURCE_EVENT_CONTRACTS),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "resource_event_contract_validation_v1",
        "checks": {"ok": checks["ok"], "checks": checks},
        "contracts": [
            {
                "contract_id": contract.contract_id,
                "resource_kind": contract.resource_kind,
                "state_path_pattern": list(contract.state_path_pattern),
                "production_event_types": list(contract.production_event_types),
                "callback_events": list(contract.callback_events),
                "scope_kind": contract.scope_kind,
            }
            for contract in RESOURCE_EVENT_CONTRACTS
        ],
        "cases": resource_cases,
        "resource_event_cross_trigger_count": cross_trigger_count,
        "dead_production_resource_events": dead_production_events,
        "retired_event": forged_event.to_json(),
        "retired_errors": list(forged.errors),
    }


def _before_event_safety_case(rules: RuleBook) -> dict[str, Any]:
    state = _probe_state()
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    toughness_mutation = Mutation(
        op="set",
        path=("units", "enemy:b", "toughness"),
        before=60.0,
        after=30.0,
        reason="apply toughness damage",
        source="toughness_system",
        metadata={"source_trace": {"validation": VALIDATION_VERSION}},
    )
    event = before_toughness_event(toughness_mutation, actor_id="ally:a", event_index=state.event_index)
    result = dispatcher.dispatch_event(state, event=event) if event is not None else None
    records = result.records if result is not None else ()
    checks = {
        "before_event_created": event is not None,
        "before_event_is_process_only": event is not None and event.process_only is True,
        "before_event_blocked": result is not None and "pre_mutation_listener_recompute_not_admitted" in result.errors,
        "before_event_state_unchanged": result is not None and result.after_state == state and not result.mutations,
        "before_event_has_family_alias": any(
            alias.get("callback_event") == "OnBeforeBeingStanceDamage"
            for alias in _aliases_from_records(records)
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "event": event.to_json() if event is not None else None,
        "records": list(records),
        "errors": list(result.errors) if result is not None else [],
    }


def _boundary_case(rules: RuleBook) -> dict[str, Any]:
    blocked_statuses = {
        event: _family_status(rules, event)
        for event in STILL_BLOCKED_EVENTS
        if rules.status_event_family(event)
    }
    checks = {
        "dispel_still_blocked": blocked_statuses.get("OnDispel") == "blocked",
        "resist_still_blocked": blocked_statuses.get("OnResistModifier") == "blocked",
        "lock_hp_threshold_still_blocked": blocked_statuses.get("OnLockHPThresholdReached") == "blocked",
        "custom_event_still_blocked": blocked_statuses.get("OnCustomEvent") == "blocked",
        "wave_event_source_admitted": _family_status(rules, "OnWaveMonster") != "blocked"
        and "wave.monster" in _family_json(rules, "OnWaveMonster").get("runtime_event_sources", ()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "blocked_statuses": blocked_statuses}


def _probe_state() -> BattleState:
    return BattleState(
        skill_points=3,
        max_skill_points=5,
        units={
            "ally:a": UnitState(
                "ally:a",
                "ally",
                "avatar:probe",
                max_hp=1000,
                hp=900,
                attack=100,
                defense=100,
                energy=40,
                max_energy=120,
                toughness=0,
                max_toughness=0,
            ),
            "enemy:b": UnitState(
                "enemy:b",
                "enemy",
                "monster:probe",
                max_hp=1000,
                hp=800,
                attack=100,
                defense=100,
                toughness=60,
                max_toughness=60,
            ),
        },
    )


def _probe_mutations(state: BattleState) -> dict[str, Mutation]:
    resources = ResourceSystem()
    return {
        "damage_hp": Mutation(
            op="set",
            path=("units", "enemy:b", "hp"),
            before=800.0,
            after=700.0,
            reason="apply direct damage",
            source="damage_system",
            metadata={"source_trace": {"validation": VALIDATION_VERSION}, "damage_formula_family": "direct"},
        ),
        "heal_overflow": Mutation(
            op="set",
            path=("units", "ally:a", "hp"),
            before=990.0,
            after=1000.0,
            reason="apply numeric heal effect",
            source="effect_system",
            metadata={
                "opcode": "Heal",
                "amount": 50.0,
                "effect_source": {"source_path": "CanonicalIR/effects", "raw_type": "EffectIR", "raw_id": "probe"},
            },
        ),
        "shield_init": Mutation(
            op="set",
            path=("units", "ally:a", "resources", "shield"),
            before=0.0,
            after=100.0,
            reason="apply numeric shield effect",
            source="effect_system",
            metadata={
                "opcode": "InitShield",
                "amount": 100.0,
                "effect_source": {"source_path": "CanonicalIR/effects", "raw_type": "EffectIR", "raw_id": "probe"},
            },
        ),
        "skill_points_gain": resources.set_skill_points(
            state, state.skill_points + 1, "resource_system"
        ),
        "skill_points_spend": resources.set_skill_points(
            state, state.skill_points - 1, "resource_system"
        ),
        "energy_gain": resources.change_unit_energy(
            state, "ally:a", 10.0, "resource_system"
        ),
        "energy_spend": resources.change_unit_energy(
            state, "ally:a", -10.0, "resource_system"
        ),
        "action_delay": Mutation(
            op="set",
            path=("units", "enemy:b", "action_value"),
            before=70.0,
            after=120.0,
            reason="set action value",
            source="status_callback_system",
            metadata={
                "opcode": "SetActionDelay",
                "action_delay_emission_id": "validation:action_delay",
                "source_trace": {"validation": VALIDATION_VERSION},
            },
        ),
    }


def _case_event_has_payload(cases: dict[str, Any], case_name: str, event_type: str) -> bool:
    return any(
        event["event_type"] == event_type
        and event["payload"].get("mutation_backed_event") is True
        and bool(event["payload"].get("mutation_id"))
        for event in cases[case_name]["events"]
    )


def _case_source_kind(cases: dict[str, Any], case_name: str) -> str:
    for event in cases[case_name]["events"]:
        source_kind = event["payload"].get("source_kind")
        if isinstance(source_kind, str):
            return source_kind
    return ""


def _family_json(rules: RuleBook, event: str) -> dict[str, Any]:
    family = rules.status_event_family(event)
    return family.to_json() if family is not None else {}


def _family_status(rules: RuleBook, event: str) -> str:
    family = rules.status_event_family(event)
    return family.coverage_status if family is not None else "missing"


def _aliases_from_records(records: tuple[dict[str, JSONValue], ...] | list[dict[str, JSONValue]]) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            raw_aliases = metadata.get("event_aliases")
            if isinstance(raw_aliases, list):
                aliases.extend(item for item in raw_aliases if isinstance(item, dict))
            event_alias = metadata.get("event_alias")
            if isinstance(event_alias, dict):
                aliases.append(event_alias)
    return aliases


if __name__ == "__main__":
    raise SystemExit(main())
