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
from .validate_v0_229 import (
    _avatar_for_action,
    _profile_selection,
    _scenario_dict,
    _select_executable_monster_profile,
)


VALIDATION_VERSION = "v0_230"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    profile = _select_executable_monster_profile(ir, rules)
    action = _select_action_with_toughness_evidence(ir, rules)
    avatar = _avatar_for_action(ir, action)
    scenario = ScenarioLoader().load_dict(_scenario_dict(profile, action, avatar, enemy_panel={}))
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = build_result.state
    command = build_result.commands[0]
    after_state, transition = CombatExecutor(rules).execute(command, state)

    static_result = run_static_checks(package_root)
    snapshot_result = SnapshotCompletenessValidator().validate(state.snapshot())
    transition_contract = TransitionContractValidator().validate(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    unit_negative = _unit_negative_checks(state, action, rules)
    executable_case = _executable_toughness_case(ir, rules, profile)

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "show_stance_blocked": _show_stance_blocked_checks(rules.toughness_emissions_for_action(action.action_id, action.level)),
        "executor_blocked_toughness": _executor_blocked_toughness_checks(state, after_state, transition),
        "unit_negative": unit_negative,
        "executable_toughness_if_present": executable_case["checks"],
        "contracts": {
            "ok": all(
                (
                    identity_result.ok,
                    snapshot_result.ok,
                    transition_contract.ok,
                    traceability.ok,
                    source_audit.ok,
                    after_state.snapshot().to_json() == transition.after.to_json(),
                )
            ),
            "checks": {
                "identity": identity_result.ok,
                "snapshot_completeness": snapshot_result.ok,
                "transition_contract": transition_contract.ok,
                "settlement_traceability": traceability.ok,
                "source_audit": source_audit.ok,
                "after_snapshot_matches_returned_state": after_state.snapshot().to_json() == transition.after.to_json(),
            },
        },
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_profile": _profile_selection(profile),
            "selected_action": _action_selection(action, avatar),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audit": source_audit.to_json(),
        "executable_toughness_case": executable_case,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_230.json", result)
    write_json(
        output_dir / "sample_toughness_emissions_v0_230.json",
        [emission.to_json() for emission in rules.toughness_emissions_for_action(action.action_id, action.level)],
    )
    write_json(output_dir / "sample_toughness_transition_v0_230.json", transition.to_json())
    write_json(output_dir / "sample_unit_negative_cases_v0_230.json", unit_negative)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_230 toughness emission admission gate.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_action_with_toughness_evidence(ir, rules: RuleBook) -> ActionDefinitionIR:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if not definition.action_id.startswith("avatar_skill:"):
            continue
        if definition.coverage_status != "executable" or definition.level < 1:
            continue
        binding = rules.action_ability_binding(definition.action_id, definition.level)
        event = rules.action_event(definition.action_id, definition.level)
        damage_emissions = rules.damage_emissions_for_action(definition.action_id, definition.level)
        toughness_emissions = rules.toughness_emissions_for_action(definition.action_id, definition.level)
        if not (binding and binding.coverage_status == "executable" and event and not event.blocked_reason):
            continue
        if not any(emission.coverage_status == "executable" for emission in damage_emissions):
            continue
        if any(_is_show_stance_blocked(emission) for emission in toughness_emissions):
            return definition
    raise RuntimeError("no mainline avatar action with blocked toughness ShowStance evidence found")


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {}).get("toughness_emissions", {})
    checks = {
        "canonical_ir_has_toughness_emissions": len(ir.toughness_emissions) > 0,
        "coverage_has_toughness_emissions": bool(status),
        "lowered_count_matches_ir": status.get("lowered") == len(ir.toughness_emissions),
        "blocked_count_present": status.get("blocked", 0) > 0,
        "show_stance_not_executable": not any(
            emission.coverage_status == "executable" and _is_show_stance_evidence(emission)
            for emission in ir.toughness_emissions
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "status": status}


def _show_stance_blocked_checks(emissions: tuple[ToughnessEmissionIR, ...]) -> dict[str, object]:
    show_stance = [emission for emission in emissions if _is_show_stance_evidence(emission)]
    checks = {
        "selected_action_has_toughness_emissions": bool(emissions),
        "show_stance_does_not_drive_executable_toughness": not any(
            emission.coverage_status == "executable" for emission in show_stance
        ),
        "executable_emissions_use_attack_property_stance_value": all(
            _uses_attack_property_stance_value(emission)
            for emission in emissions
            if emission.coverage_status == "executable"
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "emission_count": len(emissions)}


def _executor_blocked_toughness_checks(state, after_state, transition) -> dict[str, object]:
    before_toughness = {unit_id: unit.toughness for unit_id, unit in state.units.items()}
    after_toughness = {unit_id: unit.toughness for unit_id, unit in after_state.units.items()}
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    checks = {
        "transition_has_toughness_emission_record": any(record.get("record_type") == "toughness_emissions" for record in records),
        "transition_has_blocked_toughness_record": any(record.get("record_type") == "toughness_emission_blocked" for record in records),
        "no_toughness_mutation": not any(mutation.source == "toughness_system" for mutation in transition.transaction.mutations),
        "toughness_values_unchanged": before_toughness == after_toughness,
        "coverage_reports_zero_toughness_mutations": transition.coverage.get("toughness_mutation_count") == 0,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _unit_negative_checks(state, action: ActionDefinitionIR, rules: RuleBook) -> dict[str, object]:
    target_id = next(unit_id for unit_id, unit in state.units.items() if unit.side == "enemy")
    target = state.units[target_id]
    element = str(action.element_type or "Physical")
    packet = _unit_packet(target_id=target_id, element_type=element, amount=10.0)
    blocked_packet = replace(packet, coverage_status="blocked")
    no_weakness_packet = replace(packet, element_type="__not_a_weakness__")
    locked_state = replace(
        state,
        units={
            **state.units,
            target_id: replace(target, flags={**target.flags, "weakness_locked": True, "weaknesses": (element,)}),
        },
    )
    no_toughness_state = replace(
        state,
        units={**state.units, target_id: replace(target, toughness=0.0, max_toughness=0.0)},
    )
    cases = {
        "blocked_emission": _apply_unit_case(state, blocked_packet),
        "non_weakness_element": _apply_unit_case(state, no_weakness_packet),
        "weakness_locked": _apply_unit_case(locked_state, packet),
        "no_toughness": _apply_unit_case(no_toughness_state, packet),
    }
    checks = {
        f"{name}_no_mutation": not case["mutations"]
        for name, case in cases.items()
    }
    checks.update({
        f"{name}_snapshot_unchanged": case["snapshot_unchanged"]
        for name, case in cases.items()
    })
    return {
        "ok": all(checks.values()),
        "selection_mode": "unit_contract_negative",
        "checks": checks,
        "cases": cases,
        "note": "These are unit-level negative guards; they do not count as trusted TBGD executable toughness coverage.",
        "rules_toughness_emission_count": len(rules.ir.toughness_emissions),
    }


def _executable_toughness_case(ir, rules: RuleBook, profile: CombatantProfileIR) -> dict[str, object]:
    executable = [emission for emission in ir.toughness_emissions if emission.coverage_status == "executable"]
    if not executable:
        return {
            "status": "not_applicable",
            "checks": {
                "ok": True,
                "no_executable_toughness_emission_admitted": True,
            },
            "reason": "No admitted executable ToughnessEmissionIR exists; v0_230 validates blocked admission instead of fake mutation.",
        }
    emission = executable[0]
    action = rules.require_action_definition(emission.action_id, emission.level)
    compatible_profile = _profile_for_element(ir, rules, emission.element_type) or profile
    avatar = _avatar_for_action(ir, action)
    scenario = ScenarioLoader().load_dict(_scenario_dict(compatible_profile, action, avatar, enemy_panel={}))
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = _state_with_toughness_dynamic_binding(build_result.state, emission)
    command = build_result.commands[0]
    after_state, transition = CombatExecutor(rules).execute(command, state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay_ok = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json()).ok
    checks = {
        "ok": bool(transition.coverage.get("toughness_mutation_count")) and source_audit.ok and replay_ok,
        "toughness_mutation_present": bool(transition.coverage.get("toughness_mutation_count")),
        "source_audit": source_audit.ok,
        "replay": replay_ok,
        "after_snapshot_matches_returned_state": after_state.snapshot().to_json() == transition.after.to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"status": "executed", "checks": checks, "emission": emission.to_json()}


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


def _state_with_toughness_dynamic_binding(state, emission: ToughnessEmissionIR):
    expr = emission.toughness_amount_expr
    if not (isinstance(expr, dict) and expr.get("kind") == "dynamic_hash" and expr.get("hash") is not None):
        return state
    store = upsert_dynamic_value(
        state.global_flags.get("dynamic_value_store"),
        scope="action_toughness_value",
        owner_id="ally:actor",
        value=30.0,
        hash_key=expr.get("hash"),
        source_trace={
            "selection_mode": "structured_toughness_dynamic_binding",
            "toughness_emission_id": emission.toughness_emission_id,
            "source": emission.source.to_json(),
        },
    )
    return replace(state, global_flags={**state.global_flags, "dynamic_value_store": store})


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


def _unit_packet(*, target_id: str, element_type: str, amount: float) -> ToughnessPacket:
    return ToughnessPacket(
        attacker_id="unit_contract_negative",
        target_id=target_id,
        toughness_emission_id="unit_contract_negative",
        source_task_id="unit_contract_negative",
        hit_profile_id="unit_contract_negative",
        element_type=element_type,
        amount=amount,
        target_group="selected",
        coverage_status="executable",
        source_trace={"selection_mode": "unit_contract_negative"},
        metadata={"selection_mode": "unit_contract_negative"},
    )


def _is_show_stance_blocked(emission: ToughnessEmissionIR) -> bool:
    return _is_show_stance_evidence(emission) and emission.coverage_status != "executable"


def _is_show_stance_evidence(emission: ToughnessEmissionIR) -> bool:
    evidence = emission.source.evidence
    amount_source = evidence.get("toughness_amount_source")
    if isinstance(amount_source, dict) and amount_source.get("source_kind") == "ability_task_attack_property_stance_value":
        return False
    stance_source = evidence.get("stance_source")
    return isinstance(stance_source, dict) and stance_source.get("show_stance_audit_only") is True


def _uses_attack_property_stance_value(emission: ToughnessEmissionIR) -> bool:
    evidence = emission.source.evidence
    amount_source = evidence.get("toughness_amount_source")
    return isinstance(amount_source, dict) and amount_source.get("source_kind") == "ability_task_attack_property_stance_value"


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
