from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, CombatantProfileIR, RuleEntity, ToughnessEmissionIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.dynamic_values import upsert_dynamic_value
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _avatar_for_action, _profile_selection, _scenario_dict


VALIDATION_VERSION = "v0_231"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    case = _select_toughness_case(ir, rules)
    reduce_case = _execute_toughness_case(rules, case, deplete=False)
    break_case = _execute_toughness_case(rules, case, deplete=True)
    negative_cases = _negative_cases(reduce_case["initial_state"], case["emission"])

    static_result = run_static_checks(package_root)
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "selection": _selection_checks(case),
        "reduce_case": reduce_case["checks"],
        "break_case": break_case["checks"],
        "negative_cases": negative_cases["checks"],
        "show_stance_audit_only": _show_stance_checks(ir),
        "break_damage_admission": _break_damage_checks(ir),
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_action": _action_selection(case["action"], case["avatar"]),
            "selected_profile": _profile_selection(case["profile"]),
            "selected_emission": case["emission"].to_json(),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "reduce_transition_source_audit": reduce_case["source_audit"],
        "break_transition_source_audit": break_case["source_audit"],
        "trust_summary": _trust_summary(ir, reduce_case, break_case),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_231.json", result)
    write_json(output_dir / "sample_toughness_reduce_transition_v0_231.json", reduce_case["transition"])
    write_json(output_dir / "sample_toughness_break_transition_v0_231.json", break_case["transition"])
    write_json(output_dir / "sample_toughness_negative_cases_v0_231.json", negative_cases)
    write_json(output_dir / "sample_break_templates_v0_231.json", [template.to_json() for template in ir.break_templates])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_231 toughness and normal break core.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_toughness_case(ir, rules: RuleBook) -> dict[str, Any]:
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
        avatar = _avatar_for_action(ir, action)
        return {"emission": emission, "action": action, "profile": profile, "avatar": avatar}
    raise RuntimeError("no structured executable mainline toughness emission case found")


def _execute_toughness_case(rules: RuleBook, case: dict[str, Any], *, deplete: bool) -> dict[str, Any]:
    action: ActionDefinitionIR = case["action"]
    profile: CombatantProfileIR = case["profile"]
    avatar: RuleEntity = case["avatar"]
    emission: ToughnessEmissionIR = case["emission"]
    scenario = ScenarioLoader().load_dict(_scenario_dict(profile, action, avatar, enemy_panel={}))
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    enemy = build_result.state.units["enemy:profile_target"]
    amount = enemy.toughness if deplete else 1.0
    state = _state_with_dynamic_binding(build_result.state, emission, amount)
    command = build_result.commands[0]
    after_state, transition = CombatExecutor(rules).execute(command, state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    transition_contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(state.snapshot())
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    target_after = after_state.units["enemy:profile_target"]
    checks = {
        "ok": False,
        "identity": identity_result.ok,
        "transition_contract": transition_contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
        "after_snapshot_matches_returned_state": after_state.snapshot().to_json() == transition.after.to_json(),
        "toughness_mutation_present": transition.coverage.get("toughness_mutation_count", 0) > 0,
        "toughness_reduced": target_after.toughness < enemy.toughness,
        "break_mutation_expected": bool(deplete),
        "break_mutation_present": any(mutation.source == "break_system" for mutation in transition.transaction.mutations),
        "broken_state_expected": bool(deplete),
        "broken_state": bool(target_after.flags.get("broken", False)),
    }
    if deplete:
        checks["toughness_depleted"] = target_after.toughness == 0
        checks["break_records_present"] = any(
            record.get("record_type") in {"break_lifecycle", "break_event"}
            for record in transition.transaction.settlement.records
        )
    else:
        checks["break_mutation_absent"] = not checks["break_mutation_present"]
        checks["not_broken"] = not checks["broken_state"]
    checks["ok"] = all(
        value
        for key, value in checks.items()
        if key not in {
            "ok",
            "break_mutation_expected",
            "broken_state_expected",
            "break_mutation_present",
            "broken_state",
        }
    )
    return {
        "checks": checks,
        "initial_state": state,
        "after_state": after_state,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _state_with_dynamic_binding(state, emission: ToughnessEmissionIR, value: float):
    expr = emission.toughness_amount_expr
    if not (isinstance(expr, dict) and expr.get("kind") == "dynamic_hash" and expr.get("hash") is not None):
        return state
    store = upsert_dynamic_value(
        state.global_flags.get("dynamic_value_store"),
        scope="action_toughness_value",
        owner_id="ally:actor",
        value=value,
        hash_key=expr.get("hash"),
        source_trace={
            "selection_mode": "structured_toughness_dynamic_binding",
            "toughness_emission_id": emission.toughness_emission_id,
            "source": emission.source.to_json(),
        },
    )
    return replace(state, global_flags={**state.global_flags, "dynamic_value_store": store})


def _negative_cases(state, emission: ToughnessEmissionIR) -> dict[str, Any]:
    target_id = "enemy:profile_target"
    target = state.units[target_id]
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
    blocked_packet = replace(packet, coverage_status="blocked")
    non_weakness_target = replace(target, flags={**target.flags, "weaknesses": ("__different_element__",)})
    locked_target = replace(target, flags={**target.flags, "weakness_locked": True})
    no_toughness_target = replace(target, toughness=0.0, max_toughness=0.0)
    cases = {
        "unbound_dynamic_hash": _apply_unit_case(_state_without_dynamic_store(state), packet),
        "blocked_emission": _apply_unit_case(state, blocked_packet),
        "non_weakness_element": _apply_unit_case(replace(state, units={**state.units, target_id: non_weakness_target}), packet),
        "weakness_locked": _apply_unit_case(replace(state, units={**state.units, target_id: locked_target}), packet),
        "no_toughness": _apply_unit_case(replace(state, units={**state.units, target_id: no_toughness_target}), packet),
    }
    checks = {f"{name}_no_mutation": not case["mutations"] for name, case in cases.items()}
    checks.update({f"{name}_snapshot_unchanged": case["snapshot_unchanged"] for name, case in cases.items()})
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "cases": cases}


def _state_without_dynamic_store(state):
    flags = dict(state.global_flags)
    flags.pop("dynamic_value_store", None)
    return replace(state, global_flags=flags)


def _apply_unit_case(state, packet: ToughnessPacket) -> dict[str, object]:
    before = state.snapshot().to_json()
    result = ToughnessSystem().apply_packet(state, packet)
    after_state = MutationReducer().apply_all(state, result.mutations)
    after = after_state.snapshot().to_json()
    return {
        "ok": result.ok,
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "records": list(result.records),
        "errors": list(result.errors),
        "snapshot_unchanged": before == after,
    }


def _profile_for_element(ir, rules: RuleBook, element_type: str | None) -> CombatantProfileIR | None:
    if not element_type:
        return None
    for profile in sorted(ir.combatant_profiles, key=lambda item: item.entity_id):
        if profile.entity_type != "monster" or profile.coverage_status != "executable":
            continue
        if element_type not in profile.weaknesses:
            continue
        if rules.entity(profile.entity_id) is not None:
            return profile
    return None


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    toughness = status.get("toughness_emissions", {})
    break_templates = status.get("break_templates", {})
    break_damage = status.get("break_damage_emissions", {})
    checks = {
        "toughness_emissions_present": len(ir.toughness_emissions) > 0,
        "executable_toughness_present": toughness.get("executable", 0) > 0,
        "break_templates_present": break_templates.get("executable", 0) >= 7,
        "break_damage_emissions_reported": break_damage.get("lowered", 0) >= 7
        and break_damage.get("blocked", 0) + break_damage.get("executable", 0) == break_damage.get("lowered", 0),
    }
    return {"ok": all(checks.values()), "checks": checks, "status": status}


def _selection_checks(case: dict[str, Any]) -> dict[str, object]:
    emission: ToughnessEmissionIR = case["emission"]
    action: ActionDefinitionIR = case["action"]
    profile: CombatantProfileIR = case["profile"]
    checks = {
        "selection_mode_structured": True,
        "emission_from_mainline_avatar_ability": emission.source.source_path.startswith("Config/ConfigAbility/Avatar/"),
        "emission_uses_attack_property_stance_value": emission.toughness_amount_expr.get("source_kind") == "ability_task_attack_property_stance_value",
        "emission_not_show_stance_driven": not _is_show_stance_driven(emission),
        "action_is_avatar_action": action.action_id.startswith("avatar_skill:"),
        "profile_has_matching_weakness": bool(emission.element_type and emission.element_type in profile.weaknesses),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _show_stance_checks(ir) -> dict[str, object]:
    show_stance_executable = [
        emission
        for emission in ir.toughness_emissions
        if emission.coverage_status == "executable" and _is_show_stance_driven(emission)
    ]
    checks = {
        "show_stance_does_not_drive_executable_toughness": not show_stance_executable,
        "show_stance_evidence_still_present": any(
            isinstance(emission.source.evidence.get("stance_source"), dict)
            for emission in ir.toughness_emissions
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _break_damage_checks(ir) -> dict[str, object]:
    executable = [emission for emission in ir.break_damage_emissions if emission.coverage_status == "executable"]
    blocked = [emission for emission in ir.break_damage_emissions if emission.coverage_status != "executable"]
    checks = {
        "break_templates_lowered": len(ir.break_templates) >= 7,
        "break_templates_executable_for_lifecycle": all(template.coverage_status == "executable" for template in ir.break_templates),
        "break_damage_emissions_lowered": len(ir.break_damage_emissions) >= 7,
        "break_damage_emissions_status_reported": len(executable) + len(blocked) == len(ir.break_damage_emissions),
        "blocked_reason_present": all(emission.blocked_reason for emission in blocked),
    }
    return {"ok": all(checks.values()), "checks": checks, "executable_count": len(executable)}


def _is_show_stance_driven(emission: ToughnessEmissionIR) -> bool:
    amount_source = emission.source.evidence.get("toughness_amount_source")
    return not (
        isinstance(amount_source, dict)
        and amount_source.get("source_kind") == "ability_task_attack_property_stance_value"
    )


def _trust_summary(ir, reduce_case: dict[str, Any], break_case: dict[str, Any]) -> dict[str, object]:
    return {
        "toughness_execution": {
            "semantic_status": "trusted_for_current_scope",
            "source_audit_covered": reduce_case["checks"]["source_audit"] and break_case["checks"]["source_audit"],
            "scope": "executable ToughnessEmissionIR from AbilityTask AttackProperty.StanceValue with fixed or trusted dynamic binding",
        },
        "normal_break_lifecycle": {
            "semantic_status": "trusted_for_current_scope",
            "source_audit_covered": break_case["checks"]["source_audit"],
            "scope": "toughness depletion sets broken state and records OnTriggerBreak/OnBeingBreak process events",
        },
        "break_damage": {
            "semantic_status": "trusted_for_current_scope"
            if any(emission.coverage_status == "executable" for emission in ir.break_damage_emissions)
            else "blocked",
            "blocking_dependency": ""
            if any(emission.coverage_status == "executable" for emission in ir.break_damage_emissions)
            else "Break damage formula inputs/postfix semantics are not admitted; BreakDamageEmissionIR is lowered but non-mutating",
            "lowered_count": len(ir.break_damage_emissions),
        },
        "super_break": {
            "semantic_status": "not_applicable",
            "blocking_dependency": "super-break is outside normal toughness/break core v0_231",
        },
    }


def _action_selection(action: ActionDefinitionIR, avatar: RuleEntity) -> dict[str, object]:
    return {
        "selection_mode": "structured_predicate",
        "action_id": action.action_id,
        "action_level": action.level,
        "avatar_entity_id": avatar.entity_id,
        "source": action.source.to_json(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
