from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleTransition, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import (
    ActionDelayEmissionIR,
    ActionDefinitionIR,
    BreakStatusEmissionIR,
    CombatantProfileIR,
    RuleEntity,
    StatusDamageEmissionIR,
    ToughnessEmissionIR,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.dynamic_values import find_status_detail
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _avatar_for_action, _scenario_dict
from .validate_v0_231 import _profile_for_element, _state_with_dynamic_binding


VALIDATION_VERSION = "v0_234"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    case = _select_status_tick_case(ir, rules)
    break_case = _execute_break_setup(rules, case)
    tick_case = _execute_tick_case(rules, break_case["after_state"], case)
    delay_case = _execute_delay_case(rules, break_case["after_state"], case)
    negative_cases = _negative_cases(rules, break_case["after_state"], case)
    static_result = run_static_checks(package_root)
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "selection": _selection_checks(case),
        "break_setup": break_case["checks"],
        "tick_transition": tick_case["checks"],
        "delay_blocked": delay_case["checks"],
        "negative_cases": negative_cases["checks"],
        "show_stance_guard": _show_stance_guard(ir),
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_status_damage_emission": case["status_damage_emission"].to_json(),
            "selected_break_status_emission": case["break_status_emission"].to_json(),
            "selected_toughness_emission": case["toughness_emission"].to_json(),
            "selected_profile": case["profile"].to_json(),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "tick_source_audit": tick_case["source_audit"],
        "trust_summary": _trust_summary(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_234.json", result)
    write_json(output_dir / "sample_break_setup_transition_v0_234.json", break_case["transition"])
    write_json(output_dir / "sample_status_tick_transition_v0_234.json", tick_case["transition"])
    write_json(output_dir / "sample_status_callback_negative_cases_v0_234.json", negative_cases)
    write_json(output_dir / "sample_action_delay_blocked_v0_234.json", delay_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_234 break status callback tick.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_status_tick_case(ir, rules: RuleBook) -> dict[str, Any]:
    for status_damage in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if status_damage.coverage_status != "executable":
            continue
        if status_damage.source.source_path != "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json":
            continue
        if status_damage.attack_type != "DOT" or status_damage.event != "OnPhase1":
            continue
        break_status = _break_status_for_modifier(rules, status_damage.modifier_name)
        if break_status is None:
            continue
        template = rules.break_template(break_status.template_id)
        if template is None or template.coverage_status != "executable":
            continue
        state_case = _base_state_case(ir, rules)
        if state_case is None:
            continue
        return {
            "status_damage_emission": status_damage,
            "break_status_emission": break_status,
            "break_template": template,
            "toughness_emission": state_case["toughness_emission"],
            "action": state_case["action"],
            "profile": state_case["profile"],
            "avatar": state_case["avatar"],
        }
    raise RuntimeError("no structured mainline break DOT status callback case found")


def _break_status_for_modifier(rules: RuleBook, modifier_name: str) -> BreakStatusEmissionIR | None:
    for emission in rules.break_status_emissions():
        if emission.coverage_status == "executable" and emission.modifier_name == modifier_name:
            return emission
    return None


def _toughness_case_for_element(ir, rules: RuleBook, element_type: str | None) -> ToughnessEmissionIR | None:
    if not element_type:
        return None
    for emission in sorted(ir.toughness_emissions, key=lambda item: item.toughness_emission_id):
        if emission.coverage_status != "executable" or emission.element_type != element_type:
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
        return emission
    return None


def _base_state_case(ir, rules: RuleBook) -> dict[str, Any] | None:
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
        return {
            "toughness_emission": emission,
            "action": action,
            "profile": profile,
            "avatar": _avatar_for_action(ir, action),
        }
    return None


def _execute_break_setup(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    action: ActionDefinitionIR = case["action"]
    profile: CombatantProfileIR = case["profile"]
    avatar: RuleEntity = case["avatar"]
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(
            profile,
            action,
            avatar,
            enemy_panel={"max_hp": 100000.0, "hp": 100000.0},
        )
    )
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = build_result.state
    effect = rules.effect(case["break_status_emission"].effect_id)
    if effect is None:
        raise RuntimeError("selected break status effect is missing")
    effect_result = EffectRegistry(StatusSystem(rules)).execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id="ally:actor",
            source_id=case["break_status_emission"].break_status_emission_id,
            owner_id="enemy:profile_target",
            param_entity_id="enemy:profile_target",
            current_action_target_id="enemy:profile_target",
        ),
    )
    after_state = MutationReducer().apply_all(state, effect_result.mutations)
    transition = _callback_transition(
        before_state=state,
        after_state=after_state,
        records=effect_result.records,
        mutations=effect_result.mutations,
        events=effect_result.events,
        actor_id="ally:actor",
        target_id="enemy:profile_target",
        metadata={
            "event": "StanceBreakAddModifierSetup",
            "modifier_name": case["break_status_emission"].modifier_name,
            "break_status_emission_id": case["break_status_emission"].break_status_emission_id,
        },
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    expected_modifier = str(case.get("expected_modifier_name") or case["status_damage_emission"].modifier_name)
    checks = {
        "identity_ok": identity_result.ok,
        "source_audit": source_audit.ok,
        "status_created": find_status_detail(after_state, "enemy:profile_target", modifier_name=expected_modifier) is not None,
        "setup_uses_break_status_effect": case["break_status_emission"].effect_id == effect.effect_id,
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "initial_state": state,
        "after_state": after_state,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _execute_tick_case(rules: RuleBook, state, case: dict[str, Any]) -> dict[str, Any]:
    modifier_name = case["status_damage_emission"].modifier_name
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:profile_target",
        modifier_name=modifier_name,
        event="OnPhase1",
    )
    transition = _callback_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        actor_id="ally:actor",
        target_id="enemy:profile_target",
        metadata={"event": "OnPhase1", "modifier_name": modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(state.snapshot())
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    mutations = transition.transaction.mutations
    checks = {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
        "break_dot_tick_record": any(record.get("record_type") == "break_dot_tick" for record in records),
        "hp_mutation_present": any(mutation.source == "damage_system" and mutation.path[-1] == "hp" for mutation in mutations),
        "hp_reduced": result.after_state.units["enemy:profile_target"].hp < state.units["enemy:profile_target"].hp,
        "no_direct_multiplier_ledger": all(
            mutation.metadata.get("normal_multiplier_terms") == []
            for mutation in mutations
            if mutation.source == "damage_system"
        ),
        "status_damage_source_metadata": all(
            bool(mutation.metadata.get("status_damage_emission_id"))
            and bool(mutation.metadata.get("status_callback_id"))
            and bool(mutation.metadata.get("numeric_evaluation"))
            for mutation in mutations
            if mutation.source == "damage_system"
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _execute_delay_case(rules: RuleBook, state, case: dict[str, Any]) -> dict[str, Any]:
    delay = _mainline_break_delay(rules)
    if delay is None:
        return {"checks": {"ok": False, "mainline_action_delay_lowered": False}, "records": []}
    delay_break_case = _case_for_break_modifier(rules, case, delay.modifier_name)
    if delay_break_case is None:
        return {"checks": {"ok": False, "mainline_action_delay_lowered": True, "delay_break_case_found": False}, "selected_delay": delay.to_json(), "records": []}
    setup = _execute_break_setup(rules, delay_break_case)
    state = setup["after_state"]
    before = state.snapshot().to_json()
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:profile_target",
        modifier_name=delay.modifier_name,
        event=delay.event,
    )
    after = result.after_state.snapshot().to_json()
    checks = {
        "mainline_action_delay_lowered": True,
        "delay_break_case_found": True,
        "delay_status_created": find_status_detail(state, "enemy:profile_target", modifier_name=delay.modifier_name) is not None,
        "action_delay_blocked_record": any(
            record.get("record_type") == "action_delay_blocked"
            and record.get("payload", {}).get("action_delay_emission_id") == delay.action_delay_emission_id
            for record in result.records
        ),
        "no_mutation": not result.mutations,
        "snapshot_unchanged": before == after,
        "blocked_reason_specific": bool(delay.blocked_reason),
    }
    checks["ok"] = all(checks.values())
    return {"checks": checks, "selected_delay": delay.to_json(), "setup_transition": setup["transition"], "records": list(result.records)}


def _mainline_break_delay(rules: RuleBook) -> ActionDelayEmissionIR | None:
    for emission in rules.ir.action_delay_emissions:
        if emission.source.source_path != "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json":
            continue
        if emission.event != "OnStack":
            continue
        if emission.opcode not in {"ModifyActionDelay", "SetActionDelay"}:
            continue
        if _break_status_for_modifier(rules, emission.modifier_name) is None:
            continue
        return emission
    for emission in rules.ir.action_delay_emissions:
        if emission.source.source_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json" and emission.event == "OnStack":
            return emission
    return None


def _case_for_break_modifier(rules: RuleBook, reference_case: dict[str, Any], modifier_name: str) -> dict[str, Any] | None:
    break_status = _break_status_for_modifier(rules, modifier_name)
    if break_status is None:
        return None
    template = rules.break_template(break_status.template_id)
    if template is None or template.coverage_status != "executable":
        return None
    return {
        "break_status_emission": break_status,
        "break_template": template,
        "toughness_emission": reference_case["toughness_emission"],
        "action": reference_case["action"],
        "profile": reference_case["profile"],
        "avatar": reference_case["avatar"],
        "expected_modifier_name": modifier_name,
        "status_damage_emission": reference_case["status_damage_emission"],
    }


def _negative_cases(rules: RuleBook, state, case: dict[str, Any]) -> dict[str, Any]:
    modifier_name = case["status_damage_emission"].modifier_name
    target = state.units["enemy:profile_target"]
    details = [
        {
            **detail,
            "dynamic_values": {},
        }
        for detail in target.flags.get("status_details", ())
        if isinstance(detail, dict)
    ]
    state_without_dynamic = replace(
        state,
        units={
            **state.units,
            "enemy:profile_target": replace(target, flags={**target.flags, "status_details": details}),
        },
    )
    before = state_without_dynamic.snapshot().to_json()
    result = StatusCallbackSystem(rules).execute(
        state_without_dynamic,
        unit_id="enemy:profile_target",
        modifier_name=modifier_name,
        event="OnPhase1",
    )
    after = result.after_state.snapshot().to_json()
    unsupported_callback = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:profile_target",
        modifier_name=modifier_name,
        event="OnListenTurnEnd",
    )
    checks = {
        "unbound_dynamic_no_mutation": not result.mutations,
        "unbound_dynamic_snapshot_unchanged": before == after,
        "unbound_dynamic_blocked_reason": any(
            "dynamic_hash_unbound" in str(record.get("payload", {}).get("reason"))
            or "status_damage_binding_source_not_admitted" in str(record.get("payload", {}).get("reason"))
            for record in result.records
        ),
        "unsupported_callback_no_mutation": not unsupported_callback.mutations,
        "unsupported_callback_snapshot_unchanged": unsupported_callback.after_state.snapshot().to_json() == state.snapshot().to_json(),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "unbound_dynamic_records": list(result.records),
        "unsupported_callback_records": list(unsupported_callback.records),
    }


def _callback_transition(
    *,
    before_state,
    after_state,
    records,
    mutations,
    events,
    actor_id: str,
    target_id: str,
    metadata: dict[str, Any],
) -> BattleTransition:
    command = ActionCommand(
        actor_id=actor_id,
        action_id="status_tick:ModifierPhase1End",
        action_level=0,
        target_ids=(target_id,),
        source="manual",
        metadata=metadata,
    )
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=actor_id,
        target_ids=(target_id,),
        records=tuple(records),
    )
    transaction = ActionTransaction(
        command=command,
        before=before_state.snapshot(),
        events=tuple(events),
        mutations=tuple(mutations),
        trigger_windows=(
            {
                "window": "ModifierPhase1End",
                "event": metadata.get("event"),
                "modifier_name": metadata.get("modifier_name"),
                "source": "status_callback_system",
            },
        ),
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=(target_id,),
            legal=(target_id,),
            selected=(target_id,),
            reason="status_tick_target",
            source="status_callback_system",
        ),
        coverage={
            "status_callback_tick_mutation_count": len(mutations),
            "status_callback_tick_record_count": len(records),
        },
    )


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    callbacks = status.get("status_callbacks", {})
    damage = status.get("status_damage_emissions", {})
    delay = status.get("action_delay_emissions", {})
    checks = {
        "status_callbacks_lowered": callbacks.get("lowered", 0) > 0,
        "status_damage_emissions_executable": damage.get("executable", 0) >= 1,
        "action_delay_emissions_lowered": delay.get("lowered", 0) > 0,
        "action_delay_executable_zero": delay.get("executable", 0) == 0,
        "canonical_ir_has_status_callback": len(ir.status_callbacks) > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "action_execution_status": status}


def _selection_checks(case: dict[str, Any]) -> dict[str, object]:
    damage: StatusDamageEmissionIR = case["status_damage_emission"]
    status: BreakStatusEmissionIR = case["break_status_emission"]
    checks = {
        "structured_selection": True,
        "mainline_global_modifier_source": damage.source.source_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json",
        "on_phase1_dot": damage.event == "OnPhase1" and damage.attack_type == "DOT",
        "break_status_matches_modifier": status.modifier_name == damage.modifier_name,
        "state_case_has_executable_action": case["action"].coverage_status == "executable",
        "state_profile_has_weakness": bool(case["profile"].weaknesses),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _show_stance_guard(ir) -> dict[str, object]:
    show_stance_profiles = [
        profile
        for profile in ir.hit_profiles
        if isinstance(profile.stance_source, dict) and profile.stance_source.get("show_stance_audit_only") is True
    ]
    show_stance_toughness_sources = [
        emission
        for emission in ir.toughness_emissions
        if "ShowStance" in str(emission.toughness_amount_expr.get("raw_path", ""))
        or "show_stance" in str(emission.toughness_amount_expr.get("source_kind", ""))
    ]
    checks = {
        "show_stance_evidence_present": bool(show_stance_profiles),
        "show_stance_not_toughness_source": not show_stance_toughness_sources,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "show_stance_profile_count": len(show_stance_profiles),
        "show_stance_toughness_sources": [item.to_json() for item in show_stance_toughness_sources[:5]],
    }


def _trust_summary(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "break_status_creation": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "break AddModifier status creation from executable BreakStatusEmissionIR",
        },
        "break_dot_tick": {
            "semantic_status": "trusted_for_current_scope" if checks["tick_transition"]["ok"] else "blocked",
            "scope": "OnPhase1 ByBreakDamage DOT with break base damage and status dynamic value binding",
        },
        "break_delay": {
            "semantic_status": "blocked",
            "blocking_dependency": "ModifyActionDelay AddNormalizedValue to final AV scale is not admitted",
        },
        "unsupported_callbacks": {
            "semantic_status": "blocked",
            "blocking_dependency": "OnListen/global/being-hit callbacks are not admitted in v0_234",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
