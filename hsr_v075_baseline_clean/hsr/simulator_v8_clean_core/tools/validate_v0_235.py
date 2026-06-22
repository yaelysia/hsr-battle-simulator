from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleTransition, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDelayEmissionIR, ActionDefinitionIR, CombatantProfileIR, RuleEntity, StatusDamageEmissionIR, SuperBreakEmissionIR, ToughnessEmissionIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.break_system import BreakSystem
from ..systems.dynamic_values import find_status_detail, upsert_dynamic_value
from ..systems.effect import EffectRegistry
from ..systems.status import StatusSystem
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.super_break import SuperBreakPacket, SuperBreakSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _avatar_for_action, _scenario_dict
from .validate_v0_231 import _profile_for_element
from .validate_v0_234 import _break_status_for_modifier


VALIDATION_VERSION = "v0_235"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    case = _select_break_family_case(ir, rules)
    break_case = _execute_break_setup(rules, case)
    delay_case = _execute_action_delay_case(rules, break_case["initial_state"])
    recovery_case = _execute_recovery_case(rules, break_case["after_state"], case)
    super_break_case = _execute_super_break_case(rules, break_case["after_state"])
    negative_cases = _negative_cases(rules, break_case["after_state"], case)
    static_result = run_static_checks(package_root)
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "selection": _selection_checks(case),
        "break_setup": break_case["checks"],
        "action_delay": delay_case["checks"],
        "break_recovery": recovery_case["checks"],
        "super_break": super_break_case["checks"],
        "negative_cases": negative_cases["checks"],
        "show_stance_guard": _show_stance_guard(ir),
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_toughness_emission": case["toughness_emission"].to_json(),
            "selected_status_damage_emission": case["status_damage_emission"].to_json() if case.get("status_damage_emission") else {},
            "selected_super_break_emission": case["super_break_emission"].to_json(),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "break_setup": break_case["source_audit"],
            "action_delay": delay_case["source_audit"],
            "break_recovery": recovery_case["source_audit"],
            "super_break": super_break_case["source_audit"],
        },
        "trust_summary": _trust_summary(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_235.json", result)
    write_json(output_dir / "sample_break_setup_transition_v0_235.json", break_case["transition"])
    write_json(output_dir / "sample_action_delay_transition_v0_235.json", delay_case["transition"])
    write_json(output_dir / "sample_break_recovery_transition_v0_235.json", recovery_case["transition"])
    write_json(output_dir / "sample_super_break_transition_v0_235.json", super_break_case["transition"])
    write_json(output_dir / "sample_negative_cases_v0_235.json", negative_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_235 break closure and super-break admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_break_family_case(ir, rules: RuleBook) -> dict[str, Any]:
    super_break = _select_super_break(ir)
    for toughness in sorted(ir.toughness_emissions, key=lambda item: item.toughness_emission_id):
        if toughness.coverage_status != "executable" or not toughness.element_type:
            continue
        if toughness.toughness_amount_expr.get("kind") != "dynamic_hash":
            continue
        action = rules.action_definition(toughness.action_id, toughness.level)
        if action is None or action.coverage_status != "executable":
            continue
        binding = rules.action_ability_binding(action.action_id, action.level)
        event = rules.action_event(action.action_id, action.level)
        if not (binding and binding.coverage_status == "executable" and event and not event.blocked_reason):
            continue
        if not toughness.source.source_path.startswith("Config/ConfigAbility/Avatar/"):
            continue
        template = rules.break_template_for_element(toughness.element_type)
        if template is None or template.coverage_status != "executable" or not template.element_type:
            continue
        break_statuses = [
            item
            for item in rules.break_status_emissions_for_template(template.template_id)
            if item.coverage_status == "executable" and item.modifier_name
        ]
        if not break_statuses:
            continue
        profile = _profile_for_element(ir, rules, toughness.element_type)
        if profile is None:
            continue
        avatar = _avatar_for_action(ir, action)
        break_status = break_statuses[0]
        return {
            "status_damage_emission": _status_damage_for_modifier(ir, break_status.modifier_name or ""),
            "break_status_emission": break_status,
            "break_template": template,
            "toughness_emission": toughness,
            "action": action,
            "profile": profile,
            "avatar": avatar,
            "super_break_emission": super_break,
        }
    raise RuntimeError("no structured break family case found")


def _status_damage_for_modifier(ir, modifier_name: str) -> StatusDamageEmissionIR | None:
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.coverage_status == "executable" and emission.modifier_name == modifier_name:
            return emission
    return None


def _select_super_break(ir) -> SuperBreakEmissionIR:
    for emission in sorted(ir.super_break_emissions, key=lambda item: item.super_break_emission_id):
        if emission.coverage_status == "executable" and emission.damage_formula_family == "super_break":
            return emission
    raise RuntimeError("no executable super-break emission found")


def _toughness_case_for_element(ir, rules: RuleBook, element_type: str) -> ToughnessEmissionIR | None:
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


def _execute_break_setup(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    action: ActionDefinitionIR = case["action"]
    profile: CombatantProfileIR = case["profile"]
    avatar: RuleEntity = case["avatar"]
    emission: ToughnessEmissionIR = case["toughness_emission"]
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
    enemy = build_result.state.units["enemy:profile_target"]
    state = _state_with_toughness_binding(build_result.state, emission, enemy.toughness)
    after_state, transition = CombatExecutor(rules).execute(build_result.commands[0], state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "identity_ok": identity_result.ok,
            "target_broken": bool(after_state.units["enemy:profile_target"].flags.get("broken", False)),
            "break_status_created": find_status_detail(
                after_state,
                "enemy:profile_target",
                modifier_name=case["break_status_emission"].modifier_name or "",
            )
            is not None,
            "source_audit": source_audit.ok,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "initial_state": state,
        "after_state": after_state,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _execute_action_delay_case(rules: RuleBook, base_state) -> dict[str, Any]:
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
        action_id="status_callback:SetActionDelay",
        metadata={"event": delay.event, "modifier_name": delay.modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "action_delay_mutation_present": any(mutation.source == "status_callback_system" for mutation in result.mutations),
            "action_value_changed": result.after_state.units["enemy:profile_target"].action_value
            != state.units["enemy:profile_target"].action_value,
            "selected_delay_executable": delay.coverage_status == "executable",
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_delay": delay.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _execute_recovery_case(rules: RuleBook, state, case: dict[str, Any]) -> dict[str, Any]:
    modifier_name = case["break_status_emission"].modifier_name or ""
    result = BreakSystem(rules, EffectRegistry(StatusSystem(rules))).recover_from_break_status(
        state,
        unit_id="enemy:profile_target",
        modifier_name=modifier_name,
    )
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="break:recover",
        metadata={"event": "BreakRecovery", "modifier_name": modifier_name},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    recovered = result.after_state.units["enemy:profile_target"]
    checks.update(
        {
            "source_audit": source_audit.ok,
            "recovery_mutations_present": bool(result.mutations),
            "broken_cleared": recovered.flags.get("broken") is False,
            "toughness_restored": recovered.toughness == recovered.max_toughness,
            "break_status_removed": find_status_detail(result.after_state, "enemy:profile_target", modifier_name=modifier_name) is None,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": transition.to_json(), "source_audit": source_audit.to_json()}


def _execute_super_break_case(rules: RuleBook, state) -> dict[str, Any]:
    emission = _select_super_break(rules.ir)
    before_hp = state.units["enemy:profile_target"].hp
    packet = SuperBreakPacket(
        attacker_id="ally:actor",
        target_id="enemy:profile_target",
        super_break_emission_id=emission.super_break_emission_id,
        total_stance_damage=max(1.0, state.units["enemy:profile_target"].max_toughness),
        element_type=emission.element_type,
        source_trace={
            "selection_mode": "structured_super_break_validation",
            "super_break_source": emission.source.to_json(),
        },
    )
    result = SuperBreakSystem(rules).apply_packet(state, packet)
    transition = _system_transition(
        before_state=state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        action_id="super_break:damage",
        metadata={"event": "SuperBreakDamage"},
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "super_break_mutation_present": any(
                mutation.source == "damage_system"
                and mutation.metadata.get("damage_formula_family") == "super_break"
                for mutation in result.mutations
            ),
            "hp_reduced": result.after_state.units["enemy:profile_target"].hp < before_hp,
            "no_direct_multiplier_ledger": all(
                mutation.metadata.get("normal_multiplier_terms") == []
                for mutation in result.mutations
                if mutation.source == "damage_system"
            ),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_super_break": emission.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _negative_cases(rules: RuleBook, state, case: dict[str, Any]) -> dict[str, Any]:
    delay = _select_blocked_normalized_delay(rules)
    delay_state = _state_with_delay_status(rules, state, delay) if delay is not None else state
    blocked_delay = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_status_callback(
        delay_state,
        event=_status_callback_event(delay.event if delay else "OnStack", delay.modifier_name if delay else "__missing__"),
        unit_id="enemy:profile_target",
        modifier_name=delay.modifier_name if delay else "__missing__",
    )
    super_break_missing = SuperBreakSystem(rules).apply_packet(
        replace(
            state,
            units={
                **state.units,
                "enemy:profile_target": replace(
                    state.units["enemy:profile_target"],
                    flags={**state.units["enemy:profile_target"].flags, "broken": False},
                ),
            },
        ),
        SuperBreakPacket(
            attacker_id="ally:actor",
            target_id="enemy:profile_target",
            super_break_emission_id=case["super_break_emission"].super_break_emission_id,
            total_stance_damage=None,
            source_trace={"selection_mode": "negative_missing_total_stance_damage"},
        ),
    )
    checks = {
        "blocked_delay_found": delay is not None,
        "blocked_delay_no_mutation": not blocked_delay.mutations,
        "blocked_delay_snapshot_unchanged": blocked_delay.after_state.snapshot().to_json() == delay_state.snapshot().to_json(),
        "super_break_missing_no_mutation": not super_break_missing.mutations,
        "super_break_missing_snapshot_unchanged": super_break_missing.after_state.snapshot().to_json()
        == replace(
            state,
            units={
                **state.units,
                "enemy:profile_target": replace(
                    state.units["enemy:profile_target"],
                    flags={**state.units["enemy:profile_target"].flags, "broken": False},
                ),
            },
        ).snapshot().to_json(),
        "show_stance_not_runtime_source": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "blocked_delay_records": list(blocked_delay.records),
        "super_break_missing_records": list(super_break_missing.records),
    }


def _state_with_toughness_binding(state, emission: ToughnessEmissionIR, value: float):
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


def _state_with_delay_status(rules: RuleBook, state, delay: ActionDelayEmissionIR):
    target = state.units["enemy:profile_target"]
    definition = rules.modifier_definition(delay.modifier_name)
    expr_hashes = _dynamic_hashes(delay.delay_expr)
    dynamic_values: dict[str, Any] = {"__by_hash": {}}
    if expr_hashes:
        dynamic_values["__by_hash"] = {str(expr_hashes[0]): 37.0}
    detail = {
        "instance_id": f"validation:{VALIDATION_VERSION}:delay:{delay.modifier_name}",
        "status_id": f"modifier:{delay.modifier_name}",
        "modifier_name": delay.modifier_name,
        "owner_id": "enemy:profile_target",
        "caster_id": "ally:actor",
        "source_id": delay.action_delay_emission_id,
        "dynamic_values": dynamic_values,
        "source_trace": {
            "selection_mode": "runtime_status_input_from_modifier_definition",
            "modifier_definition": definition.source.to_json() if definition else {},
            "action_delay_source": delay.source.to_json(),
        },
    }
    details = [
        item
        for item in target.flags.get("status_details", ())
        if not (isinstance(item, dict) and item.get("modifier_name") == delay.modifier_name)
    ]
    updated = replace(
        target,
        statuses=tuple(dict.fromkeys((*target.statuses, f"modifier:{delay.modifier_name}"))),
        flags={**target.flags, "status_details": [*details, detail]},
    )
    return replace(state, units={**state.units, "enemy:profile_target": updated})


def _select_executable_action_delay(rules: RuleBook) -> ActionDelayEmissionIR:
    for emission in sorted(rules.ir.action_delay_emissions, key=lambda item: item.action_delay_emission_id):
        if emission.coverage_status != "executable":
            continue
        if emission.opcode == "SetActionDelay" and emission.source.source_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json":
            return emission
    raise RuntimeError("no executable structured SetActionDelay emission found")


def _select_blocked_normalized_delay(rules: RuleBook) -> ActionDelayEmissionIR | None:
    for emission in sorted(rules.ir.action_delay_emissions, key=lambda item: item.action_delay_emission_id):
        if emission.coverage_status == "executable":
            continue
        if emission.opcode == "ModifyActionDelay" and emission.blocked_reason == "normalized_action_delay_scale_not_admitted":
            return emission
    return None


def _system_transition(
    *,
    before_state,
    after_state,
    records,
    mutations,
    action_id: str,
    metadata: dict[str, Any],
    events=(),
) -> BattleTransition:
    command = ActionCommand(
        actor_id="ally:actor",
        action_id=action_id,
        action_level=0,
        target_ids=("enemy:profile_target",),
        source="manual",
        metadata=metadata,
    )
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=command.target_ids,
        records=tuple(records),
    )
    transaction = ActionTransaction(
        command=command,
        before=before_state.snapshot(),
        events=tuple(events),
        mutations=tuple(mutations),
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=("enemy:profile_target",),
            legal=("enemy:profile_target",),
            selected=("enemy:profile_target",),
            reason=action_id,
            source="validation_system_transition",
        ),
        coverage={"validation_action": action_id, "mutation_count": len(tuple(mutations))},
    )


def _status_callback_event(event: str, modifier_name: str):
    from ..core.model import GameEvent

    return GameEvent(
        event_type=f"status.callback.{event}",
        source_id="ally:actor",
        target_id="enemy:profile_target",
        window=event,
        process_only=True,
        payload={"callback_event": event, "modifier_name": modifier_name},
    )


def _transition_checks(transition: BattleTransition, before_state) -> dict[str, bool]:
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(before_state.snapshot())
    replay = MutationReducer().replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
    return {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
    }


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    delay = status.get("action_delay_emissions", {})
    super_break = status.get("super_break_emissions", {})
    checks = {
        "action_delay_executable_present": delay.get("executable", 0) >= 1,
        "super_break_emissions_executable": super_break.get("executable", 0) >= 1,
        "canonical_ir_has_super_break": len(ir.super_break_emissions) >= 1,
    }
    return {"ok": all(checks.values()), "checks": checks, "action_execution_status": status}


def _selection_checks(case: dict[str, Any]) -> dict[str, object]:
    super_break: SuperBreakEmissionIR = case["super_break_emission"]
    checks = {
        "structured_selection": True,
        "break_status_matches_template": case["break_status_emission"].template_id == case["break_template"].template_id,
        "super_break_source_global_template": super_break.source.raw_type == "GlobalSuperBreakDamageTask",
        "super_break_formula_family": super_break.damage_formula_family == "super_break",
        "toughness_source_avatar_ability": case["toughness_emission"].source.source_path.startswith("Config/ConfigAbility/Avatar/"),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _show_stance_guard(ir) -> dict[str, object]:
    show_stance_toughness = [
        item
        for item in ir.toughness_emissions
        if item.coverage_status == "executable" and _is_show_stance_amount_source(item)
    ]
    checks = {"show_stance_not_executable_source": not show_stance_toughness}
    return {"ok": all(checks.values()), "checks": checks, "violations": [item.to_json() for item in show_stance_toughness[:5]]}


def _is_show_stance_amount_source(emission: ToughnessEmissionIR) -> bool:
    amount_source = emission.source.evidence.get("toughness_amount_source")
    if not isinstance(amount_source, dict):
        return True
    return amount_source.get("source_kind") != "ability_task_attack_property_stance_value"


def _dynamic_hashes(expr: dict[str, Any]) -> list[Any]:
    raw = expr.get("raw")
    postfix = raw.get("PostfixExpr") if isinstance(raw, dict) else None
    hashes = postfix.get("DynamicHashes") if isinstance(postfix, dict) else None
    return list(hashes) if isinstance(hashes, list) else []


def _trust_summary(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "break_delay": {
            "semantic_status": "trusted_for_current_scope" if checks["action_delay"]["ok"] else "blocked",
            "scope": "SetActionDelay with fixed or status-bound dynamic numeric value; ModifyActionDelay AddNormalizedValue remains blocked",
        },
        "break_recovery": {
            "semantic_status": "trusted_for_current_scope" if checks["break_recovery"]["ok"] else "blocked",
            "scope": "break status recovery clears broken flags, restores toughness and removes the admitted break status instance",
        },
        "super_break": {
            "semantic_status": "trusted_for_current_scope" if checks["super_break"]["ok"] else "blocked",
            "scope": "admitted global super-break template with audited break base damage and total stance damage input",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
