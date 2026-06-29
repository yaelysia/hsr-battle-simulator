from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, GameEvent, JSONValue, Mutation, UnitState
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.mutation_events import before_toughness_event, events_for_mutation
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


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
    "OnSPChange",
    "OnBeforeEnergyPointChange",
    "OnEnergyPointChange",
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
)

STILL_BLOCKED_EVENTS = (
    "OnDispel",
    "OnListenModifierDispel",
    "OnResistModifier",
    "OnListenModifierResist",
    "OnLockHPThresholdReached",
    "OnCustomEvent",
    "OnWaveMonster",
    "OnVersusBarFever",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    family_case = _family_case(rules)
    mutation_event_case = _mutation_event_case(rules)
    before_case = _before_event_safety_case(rules)
    boundary_case = _boundary_case(rules)
    checks = {
        "family": family_case["checks"],
        "mutation_events": mutation_event_case["checks"],
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
                "runtime_sources": [
                    "hp.change",
                    "heal.after",
                    "shield.change",
                    "sp.change",
                    "energy.before_change",
                    "energy.change",
                    "toughness.before_hit",
                    "toughness.hit",
                    "status.lifecycle",
                    "action_delay.changed",
                ],
            },
        },
        "checks": checks,
        "family_case": family_case,
        "mutation_event_case": mutation_event_case,
        "before_event_safety_case": before_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_286.json", result)
    write_json(output_dir / "mutation_backed_event_families_v0_286.json", family_case)
    write_json(output_dir / "mutation_backed_event_payloads_v0_286.json", mutation_event_case)
    write_json(output_dir / "before_event_safety_v0_286.json", before_case)
    write_json(output_dir / "mutation_backed_event_boundaries_v0_286.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_286 mutation-backed status event sources.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
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
    mutations = _probe_mutations()
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
        "sp_event_engine_convention": _case_source_kind(cases, "skill_points") == "engine_convention",
        "energy_event_engine_convention": _case_source_kind(cases, "energy_kill") == "engine_convention",
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
        "wave_event_still_blocked": blocked_statuses.get("OnWaveMonster") == "blocked",
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


def _probe_mutations() -> dict[str, Mutation]:
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
        "skill_points": Mutation(
            op="set",
            path=("skill_points",),
            before=3,
            after=4,
            reason="apply action skill point delta",
            source="combat_executor.resources",
            metadata={"resource_operation": "action_skill_point_delta", "source_trace": {"validation": VALIDATION_VERSION}},
        ),
        "energy_kill": Mutation(
            op="set",
            path=("units", "ally:a", "energy"),
            before=40.0,
            after=50.0,
            reason="gain kill energy",
            source="resource_system",
            metadata={
                "resource_operation": "kill_energy_gain",
                "resource_rule_source_kind": "engine_convention",
                "resource_rule_source": {"source_path": "CanonicalIR/resource_rules", "raw_type": "KillEnergy"},
            },
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
