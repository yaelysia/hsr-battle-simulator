from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import BreakDamageEmissionIR, BreakStatusEmissionIR, CombatantProfileIR, ToughnessEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.break_system import BreakSystem
from ..systems.effect import EffectRegistry
from ..systems.status import StatusSystem
from ..systems.toughness import ToughnessPacket
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_231 import (
    _execute_toughness_case,
    _negative_cases,
    _profile_for_element,
    _state_with_dynamic_binding,
)
from .validate_v0_229 import _avatar_for_action


VALIDATION_VERSION = "v0_232"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    case = _select_break_case(ir, rules)
    break_case = _execute_toughness_case(rules, case, deplete=True)
    reduce_case = _execute_toughness_case(rules, case, deplete=False)
    negative_cases = _negative_cases(reduce_case["initial_state"], case["emission"])
    already_broken_case = _already_broken_negative_case(rules, break_case["after_state"], case["emission"])

    static_result = run_static_checks(package_root)
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "selection": _selection_checks(case, rules),
        "break_transition": _break_transition_checks(break_case["transition"]),
        "break_source_audit": {"ok": bool(break_case["source_audit"].get("ok")), "source_audit": break_case["source_audit"]},
        "reduce_regression": reduce_case["checks"],
        "negative_cases": negative_cases["checks"],
        "already_broken_negative": already_broken_case["checks"],
        "break_damage_admission": _break_damage_checks(case["break_damage_emissions"]),
        "break_status": _break_status_checks(case["break_status_emissions"], break_case["transition"]),
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_emission": case["emission"].to_json(),
            "selected_profile": case["profile"].to_json(),
            "selected_break_template": case["break_template"].to_json(),
            "selected_break_status_emissions": [item.to_json() for item in case["break_status_emissions"]],
            "selected_break_damage_emissions": [item.to_json() for item in case["break_damage_emissions"]],
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "break_transition_source_audit": break_case["source_audit"],
        "trust_summary": _trust_summary(case, checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_232.json", result)
    write_json(output_dir / "sample_break_transition_v0_232.json", break_case["transition"])
    write_json(output_dir / "sample_break_negative_cases_v0_232.json", {
        "toughness_negative_cases": negative_cases,
        "already_broken_case": already_broken_case,
    })
    write_json(output_dir / "sample_break_ir_v0_232.json", {
        "break_template": case["break_template"].to_json(),
        "break_status_emissions": [item.to_json() for item in case["break_status_emissions"]],
        "break_damage_emissions": [item.to_json() for item in case["break_damage_emissions"]],
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_232 normal break damage/status lifecycle.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_break_case(ir, rules: RuleBook) -> dict[str, Any]:
    for emission in sorted(ir.toughness_emissions, key=lambda item: item.toughness_emission_id):
        if emission.coverage_status != "executable":
            continue
        if emission.toughness_amount_expr.get("kind") != "dynamic_hash":
            continue
        action = rules.action_definition(emission.action_id, emission.level)
        if action is None or action.coverage_status != "executable":
            continue
        binding = rules.action_ability_binding(action.action_id, action.level)
        event = rules.action_event(action.action_id, action.level)
        if not (binding and binding.coverage_status == "executable" and event and not event.blocked_reason):
            continue
        if not emission.source.source_path.startswith("Config/ConfigAbility/Avatar/"):
            continue
        profile = _profile_for_element(ir, rules, emission.element_type)
        if profile is None:
            continue
        template = rules.break_template_for_element(emission.element_type)
        if template is None or template.coverage_status != "executable":
            continue
        status_emissions = rules.break_status_emissions_for_template(template.template_id)
        if not any(item.coverage_status == "executable" for item in status_emissions):
            continue
        if not _status_definitions_available(rules, status_emissions):
            continue
        avatar = _avatar_for_action(ir, action)
        return {
            "emission": emission,
            "action": action,
            "profile": profile,
            "avatar": avatar,
            "break_template": template,
            "break_status_emissions": status_emissions,
            "break_damage_emissions": rules.break_damage_emissions_for_template(template.template_id),
        }
    raise RuntimeError("no structured break case with executable status emission found")


def _status_definitions_available(rules: RuleBook, emissions: tuple[BreakStatusEmissionIR, ...]) -> bool:
    for emission in emissions:
        if emission.coverage_status != "executable":
            continue
        if emission.modifier_name and rules.modifier_definition(emission.modifier_name) is not None:
            return True
    return False


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    break_status = status.get("break_status_emissions", {})
    break_damage = status.get("break_damage_emissions", {})
    checks = {
        "break_status_emissions_lowered": len(ir.break_status_emissions) > 0,
        "break_status_executable_present": break_status.get("executable", 0) > 0,
        "break_damage_emissions_lowered": len(ir.break_damage_emissions) > 0,
        "break_damage_blocked_or_executable_reported": (
            break_damage.get("blocked", 0) + break_damage.get("executable", 0)
        ) == len(ir.break_damage_emissions),
    }
    return {"ok": all(checks.values()), "checks": checks, "action_execution_status": status}


def _selection_checks(case: dict[str, Any], rules: RuleBook) -> dict[str, object]:
    emission: ToughnessEmissionIR = case["emission"]
    profile: CombatantProfileIR = case["profile"]
    status_emissions: tuple[BreakStatusEmissionIR, ...] = case["break_status_emissions"]
    checks = {
        "selection_mode_structured": True,
        "toughness_from_mainline_avatar_ability": emission.source.source_path.startswith("Config/ConfigAbility/Avatar/"),
        "profile_has_matching_weakness": bool(emission.element_type and emission.element_type in profile.weaknesses),
        "break_template_executable": case["break_template"].coverage_status == "executable",
        "break_status_executable_present": any(item.coverage_status == "executable" for item in status_emissions),
        "break_status_modifier_def_present": _status_definitions_available(rules, status_emissions),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _break_transition_checks(transition: dict[str, Any]) -> dict[str, object]:
    mutations = transition.get("mutations", [])
    records = transition.get("settlement", {}).get("records", [])
    break_mutations = [item for item in mutations if item.get("source") == "break_system"]
    status_mutations = [
        item
        for item in mutations
        if item.get("source") == "status_system"
        and _break_status_emission_id_from_mutation(item)
    ]
    checks = {
        "break_lifecycle_mutation_present": bool(break_mutations),
        "break_status_mutation_present": bool(status_mutations),
        "break_event_record_present": any(record.get("record_type") == "break_event" for record in records),
        "break_status_record_present": any(record.get("record_type") == "break_status" for record in records),
        "break_damage_record_present": any(record.get("record_type") == "break_damage_blocked" for record in records),
        "target_broken_after": _target_broken_after(transition),
        "break_mutation_has_template_source": all(
            isinstance(item.get("metadata", {}).get("break_template_source"), dict)
            for item in break_mutations
        ),
        "break_status_mutation_has_emission_trace": all(
            bool(_break_status_emission_id_from_mutation(item)) for item in status_mutations
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _break_status_checks(
    emissions: tuple[BreakStatusEmissionIR, ...],
    transition: dict[str, Any],
) -> dict[str, object]:
    executable = [item for item in emissions if item.coverage_status == "executable"]
    status_mutation_emission_ids = {
        _break_status_emission_id_from_mutation(item)
        for item in transition.get("mutations", [])
        if item.get("source") == "status_system"
    }
    status_mutation_emission_ids.discard("")
    checks = {
        "executable_break_status_present": bool(executable),
        "at_least_one_executable_status_mutated": any(
            item.break_status_emission_id in status_mutation_emission_ids for item in executable
        ),
        "non_executable_status_has_reason": all(
            item.blocked_reason for item in emissions if item.coverage_status != "executable"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _break_damage_checks(emissions: tuple[BreakDamageEmissionIR, ...]) -> dict[str, object]:
    executable = [item for item in emissions if item.coverage_status == "executable"]
    blocked = [item for item in emissions if item.coverage_status != "executable"]
    concrete_reasons = [
        item.blocked_reason
        for item in blocked
        if item.blocked_reason and item.blocked_reason != "break_damage_formula_not_admitted_v0_231"
    ]
    checks = {
        "break_damage_emission_present": bool(emissions),
        "executable_or_concrete_blocked": bool(executable) or len(concrete_reasons) == len(blocked),
        "generic_v0_231_reason_removed": all(
            item.blocked_reason != "break_damage_formula_not_admitted_v0_231" for item in emissions
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "executable_count": len(executable),
        "blocked_reasons": concrete_reasons,
    }


def _already_broken_negative_case(rules: RuleBook, state, emission: ToughnessEmissionIR) -> dict[str, Any]:
    target_id = "enemy:profile_target"
    target = state.units[target_id]
    broken_target = replace(target, toughness=0.0, flags={**target.flags, "broken": True})
    broken_state = replace(state, units={**state.units, target_id: broken_target})
    before = broken_state.snapshot().to_json()
    packet = ToughnessPacket(
        attacker_id="ally:actor",
        target_id=target_id,
        toughness_emission_id=emission.toughness_emission_id,
        source_task_id=emission.source_task_id,
        hit_profile_id=emission.hit_profile_id,
        element_type=emission.element_type,
        amount=None,
        amount_expr=emission.toughness_amount_expr,
        target_group=emission.target_group,
        coverage_status="executable",
        source_trace=emission.source.to_json(),
        metadata={"primary_action_target_id": target_id},
    )
    result = BreakSystem(rules, EffectRegistry(StatusSystem(rules))).enter_break(broken_state, packet)
    after = result.after_state.snapshot().to_json()
    checks = {
        "ok": not result.mutations and before == after,
        "no_mutation": not result.mutations,
        "snapshot_unchanged": before == after,
        "skipped_record_present": any(record.get("record_type") == "break_lifecycle_skipped" for record in result.records),
    }
    return {
        "checks": checks,
        "records": list(result.records),
        "mutations": [mutation.to_json() for mutation in result.mutations],
    }


def _target_broken_after(transition: dict[str, Any]) -> bool:
    units = transition.get("after", {}).get("units", {})
    target = units.get("enemy:profile_target") if isinstance(units, dict) else None
    if not isinstance(target, dict):
        return False
    toughness_state = target.get("toughness_state")
    return isinstance(toughness_state, dict) and toughness_state.get("broken") is True


def _break_status_emission_id_from_mutation(mutation: dict[str, Any]) -> str:
    metadata = mutation.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    lifecycle = metadata.get("lifecycle_plan")
    if not isinstance(lifecycle, dict):
        return ""
    source_trace = lifecycle.get("source_trace")
    if not isinstance(source_trace, dict):
        return ""
    effect_source = source_trace.get("effect_source")
    if not isinstance(effect_source, dict):
        return ""
    evidence = effect_source.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    value = evidence.get("break_status_emission_id")
    return value if isinstance(value, str) else ""


def _trust_summary(case: dict[str, Any], checks: dict[str, Any]) -> dict[str, object]:
    break_damage = checks["break_damage_admission"]
    damage_status = "trusted_for_current_scope" if break_damage.get("executable_count", 0) else "blocked"
    return {
        "toughness_execution": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "executable toughness emission from admitted ability task stance value",
        },
        "normal_break_lifecycle": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "toughness depletion enters broken state through executable BreakTemplateIR",
        },
        "break_status": {
            "semantic_status": "trusted_for_current_scope" if checks["break_status"]["ok"] else "blocked",
            "scope": "executable break status emission runs through EffectRegistry and StatusSystem",
            "emission_count": len(case["break_status_emissions"]),
        },
        "break_damage": {
            "semantic_status": damage_status,
            "blocking_dependency": ""
            if damage_status == "trusted_for_current_scope"
            else ",".join(break_damage.get("blocked_reasons", ())),
            "emission_count": len(case["break_damage_emissions"]),
        },
        "break_dot_tick": {
            "semantic_status": "blocked",
            "blocking_dependency": "status duration/tick lifecycle and break DoT formula admission are outside v0_232",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
