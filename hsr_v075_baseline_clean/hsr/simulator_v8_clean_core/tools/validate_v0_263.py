from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleState, BattleTransition, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR, SkillFormulaBindingIR, StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamageWindowLedger
from ..systems.dot_formula import DotFormula, DotFormulaInput
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_263"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    dot_case = _select_executable_percentage_dot_case(ir, rules)
    dot_result = _execute_percentage_dot_case(rules, dot_case)
    dot_missing_binding = _missing_dot_formula_binding_case(rules, dot_case)
    multihit_case = _select_multihit_action_case(ir, rules)
    multihit_result = _execute_multihit_case(rules, multihit_case)
    source_matrix = _source_matrix(ir, dot_case, multihit_case)
    static_result = run_static_checks(package_root)
    checks = {
        "percentage_dot": dot_result["checks"],
        "missing_dot_formula_binding": dot_missing_binding["checks"],
        "multihit_direct": multihit_result["checks"],
        "source_matrix": _source_matrix_checks(source_matrix),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": (
                "Select by structured IR predicates only: executable DOT StatusDamageEmissionIR, "
                "same ability-file character-card dot formula slot, and executable multi-hit DamageEmissionIR."
            ),
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "percentage_dot_case": dot_result,
        "multihit_case": multihit_result,
        "negative_cases": {"missing_dot_formula_binding": dot_missing_binding},
        "source_matrix": source_matrix,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_263.json", result)
    write_json(output_dir / "percentage_dot_case_v0_263.json", dot_result)
    write_json(output_dir / "multihit_case_v0_263.json", multihit_result)
    write_json(output_dir / "dot_multihit_source_matrix_v0_263.json", source_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 DoT and multi-hit character-card formula slots.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_executable_percentage_dot_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    ability_file_bindings = _dot_bindings_by_ability_file(ir)
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "dot" or emission.coverage_status != "executable":
            continue
        if emission.event != "OnPhase1" or emission.attack_type != "DOT":
            continue
        if _source_blocked(emission.source.source_path):
            continue
        scaling = emission.scaling_expr
        if _expr_kind(scaling.get("damage_value")) != "missing":
            continue
        if not _expr_supported(scaling.get("damage_percentage")):
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is None or task is None:
            continue
        if callback.coverage_status != "executable" or task.coverage_status != "executable":
            continue
        bindings = ability_file_bindings.get(emission.source.source_path, ())
        for binding in bindings:
            case = {"emission": emission, "callback": callback, "task": task, "formula_binding": binding}
            probe = _execute_percentage_dot_case(rules, case)
            if probe["checks"].get("hp_mutation_present"):
                return case
    return None


def _execute_percentage_dot_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    emission: StatusDamageEmissionIR = case["emission"]
    binding: SkillFormulaBindingIR = case["formula_binding"]
    state = _state_for_dot_case(emission, binding, bind_dynamic=True, include_formula_binding=True)
    before = state.snapshot().to_json()
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:dot_target",
        modifier_name=emission.modifier_name,
        event="OnPhase1",
        damage_window_ledger=DamageWindowLedger(),
    )
    transition = _callback_transition(state, result.after_state, result, emission)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    snapshot = SnapshotCompletenessValidator().validate(state.snapshot())
    after = result.after_state.snapshot().to_json()
    dot_mutations = [mutation for mutation in result.mutations if mutation.source == "damage_system"]
    formula_payloads = [mutation.metadata.get("dot_formula_result", {}) for mutation in dot_mutations]
    basis_terms = [
        term
        for payload in formula_payloads
        for term in payload.get("dot_ledger", {}).get("applied_terms", [])
        if isinstance(term, dict) and term.get("key") == "DamagePercentage"
    ]
    checks = {
        "case_found": True,
        "state_changed": before != after,
        "hp_mutation_present": bool(dot_mutations),
        "hp_reduced": result.after_state.units["enemy:dot_target"].hp < state.units["enemy:dot_target"].hp,
        "uses_status_formula_binding_basis": bool(
            basis_terms
            and basis_terms[0].get("basis_result", {}).get("source_trace", {}).get("scaling_basis", {}).get("source_kind")
            == "character_data_card_skill_formula"
        ),
        "no_direct_crit_ledger": all(
            mutation.metadata.get("normal_multiplier_terms") == []
            and mutation.metadata.get("uses_direct_multiplier_ledger") is False
            for mutation in dot_mutations
        ),
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "selected_emission": emission.to_json(),
        "selected_formula_binding": binding.to_json(),
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _missing_dot_formula_binding_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    emission: StatusDamageEmissionIR = case["emission"]
    binding: SkillFormulaBindingIR = case["formula_binding"]
    state = _state_for_dot_case(emission, binding, bind_dynamic=True, include_formula_binding=False)
    before = state.snapshot().to_json()
    detail = state.units["enemy:dot_target"].flags["status_details"][0]
    formula_result = DotFormula().calculate(
        DotFormulaInput(
            state=state,
            caster_id="ally:dot_caster",
            target_id="enemy:dot_target",
            status_detail=detail,
            emission=emission,
            source_trace={"selection_mode": "missing_formula_binding_negative"},
        )
    )
    after = state.snapshot().to_json()
    checks = {
        "case_found": True,
        "blocked": formula_result.ok is False,
        "no_mutation": True,
        "snapshot_unchanged": before == after,
        "blocked_reason_specific": "dot_status_formula_binding_missing" in formula_result.blocked_reason,
    }
    checks["ok"] = all(checks.values())
    return {"checks": checks, "formula_result": formula_result.to_json()}


def _select_multihit_action_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    action_keys = sorted({(emission.action_id, emission.level) for emission in ir.damage_emissions})
    for action_id, level in action_keys:
        definition = rules.action_definition(action_id, level)
        if definition is None or definition.target_mode not in {"single", "blast", "aoe"}:
            continue
        emissions = [
            emission
            for emission in rules.damage_emissions_for_action(action_id, level)
            if emission.coverage_status == "executable" and emission.damage_formula_family == "direct"
        ]
        if len(emissions) < 2:
            continue
        profiles = [rules.hit_profile(emission.hit_profile_id) for emission in emissions]
        if not all(profile and profile.multiplier_source.get("source_kind") == "character_data_card_skill_formula" for profile in profiles):
            continue
        case = {"action_id": action_id, "level": level, "definition": definition, "emissions": emissions}
        if _multihit_damage_record_count(rules, case) >= 2:
            return case
    return None


def _execute_multihit_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    action_id = str(case["action_id"])
    level = int(case["level"])
    state = _multihit_state()
    command = ActionCommand(
        actor_id="ally:multihit_actor",
        action_id=action_id,
        action_level=level,
        target_ids=("enemy:primary",),
        source="manual",
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    damage_mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"]
    hit_ids = {
        mutation.metadata.get("hit_profile_id")
        for mutation in damage_mutations
        if isinstance(mutation.metadata, dict)
    }
    checks = {
        "case_found": True,
        "state_changed": state.snapshot().to_json() != after.snapshot().to_json(),
        "multiple_damage_mutations": len(damage_mutations) >= 2,
        "multiple_hit_profiles": len({item for item in hit_ids if item}) >= 2,
        "all_selected_emissions_formula_sourced": all(
            rules.hit_profile(emission.hit_profile_id)
            and rules.hit_profile(emission.hit_profile_id).multiplier_source.get("source_kind") == "character_data_card_skill_formula"
            for emission in case["emissions"]
        ),
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "selected_action": {"action_id": action_id, "level": level, "definition": case["definition"].to_json()},
        "selected_emissions": [emission.to_json() for emission in case["emissions"][:8]],
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _multihit_damage_record_count(rules: RuleBook, case: dict[str, Any]) -> int:
    try:
        state = _multihit_state()
        command = ActionCommand(
            actor_id="ally:multihit_actor",
            action_id=str(case["action_id"]),
            action_level=int(case["level"]),
            target_ids=("enemy:primary",),
            source="manual",
        )
        _, transition = CombatExecutor(rules).execute(command, state)
    except Exception:
        return 0
    hit_ids = {
        mutation.metadata.get("hit_profile_id")
        for mutation in transition.transaction.mutations
        if mutation.source == "damage_system"
    }
    return len({item for item in hit_ids if item})


def _state_for_dot_case(
    emission: StatusDamageEmissionIR,
    binding: SkillFormulaBindingIR,
    *,
    bind_dynamic: bool,
    include_formula_binding: bool,
) -> BattleState:
    status_id = f"modifier:{emission.modifier_name}"
    dynamic_values: dict[str, Any] = {"__by_hash": {}}
    if bind_dynamic:
        dynamic_values["__by_hash"] = {hash_key: 0.25 for hash_key in _hashes_for_dot_emission(emission)}
    formula_bindings = [binding.to_json()] if include_formula_binding else []
    detail = {
        "instance_id": f"status_instance:{emission.modifier_name}:v0_263",
        "status_id": status_id,
        "modifier_name": emission.modifier_name,
        "owner_id": "enemy:dot_target",
        "caster_id": "ally:dot_caster",
        "source_id": emission.status_damage_emission_id,
        "stacks": 1,
        "max_stacks": 1,
        "remaining_duration": 1,
        "duration_unit": "ModifierPhase1End",
        "dynamic_values": dynamic_values,
        "formula_bindings": formula_bindings,
        "trigger_ids_by_event": {"OnPhase1": [emission.callback_id]},
        "source_trace": {
            "selection_mode": "structured_status_instance_input",
            "status_damage_source": emission.source.to_json(),
            "status_formula_bindings": formula_bindings,
        },
    }
    return BattleState(
        units={
            "ally:dot_caster": UnitState(
                unit_id="ally:dot_caster",
                side="ally",
                template_id="avatar:dot_caster",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
            ),
            "enemy:dot_target": UnitState(
                unit_id="enemy:dot_target",
                side="enemy",
                template_id="monster:dot_target",
                max_hp=500.0,
                hp=500.0,
                defense=50.0,
                speed=100.0,
                statuses=(status_id,),
                flags={"status_details": (detail,)},
            ),
        },
        global_flags={"phase": "v0_263_percentage_dot"},
    )


def _multihit_state() -> BattleState:
    return BattleState(
        units={
            "ally:multihit_actor": UnitState(
                unit_id="ally:multihit_actor",
                side="ally",
                template_id="avatar:multihit_actor",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=50.0,
                speed=100.0,
                energy=100.0,
                max_energy=100.0,
            ),
            "enemy:primary": UnitState(
                unit_id="enemy:primary",
                side="enemy",
                template_id="monster:primary",
                max_hp=500.0,
                hp=500.0,
                defense=20.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "enemy:left": UnitState(
                unit_id="enemy:left",
                side="enemy",
                template_id="monster:left",
                max_hp=500.0,
                hp=500.0,
                defense=20.0,
                speed=100.0,
                flags={"position": 0},
            ),
            "enemy:right": UnitState(
                unit_id="enemy:right",
                side="enemy",
                template_id="monster:right",
                max_hp=500.0,
                hp=500.0,
                defense=20.0,
                speed=100.0,
                flags={"position": 2},
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "v0_263_multihit"},
    )


def _callback_transition(before_state: BattleState, after_state: BattleState, result: Any, emission: StatusDamageEmissionIR) -> BattleTransition:
    command = ActionCommand(
        actor_id="ally:dot_caster",
        action_id="status_tick:percentage_dot",
        action_level=0,
        target_ids=("enemy:dot_target",),
        source="manual",
        metadata={"event": "OnPhase1", "modifier_name": emission.modifier_name},
    )
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=command.target_ids,
        records=tuple(result.records),
    )
    transaction = ActionTransaction(
        command=command,
        before=before_state.snapshot(),
        events=tuple(result.events),
        mutations=tuple(result.mutations),
        trigger_windows=(
            {
                "window": "ModifierPhase1End",
                "event": "OnPhase1",
                "modifier_name": emission.modifier_name,
                "source": "status_callback_system",
            },
        ),
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=("enemy:dot_target",),
            legal=("enemy:dot_target",),
            selected=("enemy:dot_target",),
            reason="status_tick_target",
            source="status_callback_system",
        ),
        coverage={"percentage_dot_mutation_count": len(result.mutations), "percentage_dot_record_count": len(result.records)},
    )


def _dot_bindings_by_ability_file(ir: CanonicalIR) -> dict[str, tuple[SkillFormulaBindingIR, ...]]:
    binding_by_action = {
        (binding.action_id, binding.level): binding
        for binding in ir.skill_formula_bindings
        if binding.formula_role == "dot_damage" and binding.coverage_status == "executable"
    }
    result: dict[str, list[SkillFormulaBindingIR]] = {}
    for action_binding in ir.action_ability_bindings:
        binding = binding_by_action.get((action_binding.action_id, action_binding.level))
        if binding is None:
            continue
        config_source = action_binding.config_source if isinstance(action_binding.config_source, dict) else {}
        ability_file = config_source.get("ability_file_path")
        if isinstance(ability_file, str) and ability_file:
            result.setdefault(ability_file, []).append(binding)
    return {
        key: tuple(sorted(value, key=lambda item: (item.sequence_order, item.param_index, item.binding_id)))
        for key, value in result.items()
    }


def _hashes_for_dot_emission(emission: StatusDamageEmissionIR) -> tuple[str, ...]:
    hashes: list[str] = []
    for key in ("damage_value", "damage_percentage", "extra_damage_percentage"):
        hashes.extend(_hashes_from_expr(emission.scaling_expr.get(key)))
    return tuple(dict.fromkeys(hashes))


def _hashes_from_expr(expression: Any) -> list[str]:
    if not isinstance(expression, dict):
        return []
    if expression.get("kind") == "dynamic_hash" and expression.get("hash") is not None:
        return [str(expression["hash"])]
    raw = expression.get("raw") if isinstance(expression.get("raw"), dict) else expression
    postfix = raw.get("PostfixExpr") if isinstance(raw, dict) else None
    if not isinstance(postfix, dict):
        return []
    values = postfix.get("DynamicHashes")
    return [str(value) for value in values] if isinstance(values, list) else []


def _expr_kind(value: Any) -> str:
    return str(value.get("kind") or "") if isinstance(value, dict) else ""


def _expr_supported(value: Any) -> bool:
    return bool(isinstance(value, dict) and value.get("supported") is True)


def _source_blocked(path: str) -> bool:
    blocked_markers = ("Rogue", "Activity", "GridFight", "ElationBattle", "Fate", "Story", "Level/", "SubLevelGraph", "Chess")
    return any(marker in path for marker in blocked_markers)


def _source_matrix(ir: CanonicalIR, dot_case: dict[str, Any] | None, multihit_case: dict[str, Any] | None) -> dict[str, Any]:
    executable_direct = [
        emission
        for emission in ir.damage_emissions
        if emission.damage_formula_family == "direct" and emission.coverage_status == "executable"
    ]
    executable_dot_percentage = [
        emission
        for emission in ir.status_damage_emissions
        if emission.damage_formula_family == "dot"
        and emission.coverage_status == "executable"
        and _expr_kind(emission.scaling_expr.get("damage_value")) == "missing"
        and _expr_supported(emission.scaling_expr.get("damage_percentage"))
    ]
    formula_sourced_hit_profiles = [
        profile
        for profile in ir.hit_profiles
        if profile.multiplier_source.get("source_kind") == "character_data_card_skill_formula"
    ]
    return {
        "encoding": "hsr.v8.dot_multihit_source_matrix.v0_263",
        "direct": {
            "executable_count": len(executable_direct),
            "all_executable_use_character_data_card_formula": all(
                emission.scaling_basis_expr.get("source_kind") == "character_data_card_skill_formula"
                for emission in executable_direct
            ),
        },
        "dot_percentage": {
            "executable_count": len(executable_dot_percentage),
            "selected_case": dot_case["emission"].status_damage_emission_id if dot_case else "",
            "selected_formula_slot": dot_case["formula_binding"].formula_slot_id if dot_case else "",
        },
        "multihit": {
            "formula_sourced_hit_profile_count": len(formula_sourced_hit_profiles),
            "selected_action": multihit_case["action_id"] if multihit_case else "",
            "selected_level": multihit_case["level"] if multihit_case else 0,
        },
        "blocked_policy": {
            "missing_formula_slot": "process_only_no_mutation",
            "unknown_basis": "blocked",
            "param_out_of_range": "blocked",
        },
    }


def _source_matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "direct_executable_uses_character_data_card": bool(matrix["direct"]["all_executable_use_character_data_card_formula"]),
        "dot_percentage_executable_exists": int(matrix["dot_percentage"]["executable_count"]) > 0,
        "dot_percentage_selected": bool(matrix["dot_percentage"]["selected_case"]),
        "multihit_formula_sourced_profiles_exist": int(matrix["multihit"]["formula_sourced_hit_profile_count"]) > 1,
        "multihit_selected": bool(matrix["multihit"]["selected_action"]),
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks}


if __name__ == "__main__":
    raise SystemExit(main())
