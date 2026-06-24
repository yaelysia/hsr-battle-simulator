from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR, SkillFormulaBindingIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..tbgd.character_cards import skill_formula_bindings_from_row
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_218 import _multi_enemy_state, _with_crit_mode
from .validate_v0_222 import _target_ids_for_definition
from .validate_v0_223 import _execute_definition_case, _sorted_emissions


VALIDATION_VERSION = "v0_261"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    scenario = ScenarioLoader().load_path(package_root / "scenarios/examples/identity_smoke_v0_204.json")
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = _multi_enemy_state(build_result.state)
    command = _with_crit_mode(build_result.commands[0], "noncrit")
    direct_case = _execute_direct_skill_text_case(ir, rules, state, command)
    dot_binding = _select_dot_text_binding(ir)
    negatives = _synthetic_negative_bindings()
    static_result = run_static_checks(package_root)
    checks = {
        "ir_shape": _ir_shape_checks(ir, rules),
        "direct_runtime": _direct_runtime_checks(rules, state, direct_case),
        "dot_binding": _dot_binding_checks(dot_binding),
        "synthetic_negative_bindings": _negative_binding_checks(negatives),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": (
                "Structured selection by executable DamageEmissionIR whose scaling basis source_kind is "
                "character_data_card_skill_formula; no character name, action id, file name, or hash fixed selector."
            ),
            "skill_formula_binding_counts": _binding_counts(ir),
            "avatar_profile_count": len(ir.avatar_profiles),
        },
        "checks": checks,
        "direct_case": _direct_case_json(direct_case),
        "dot_text_binding_sample": dot_binding.to_json() if dot_binding else None,
        "synthetic_negative_bindings": negatives,
        "skill_formula_binding_samples": _binding_samples(ir),
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_261.json", result)
    if direct_case.get("transition") is not None:
        write_json(output_dir / "sample_skill_text_direct_transition_v0_261.json", direct_case["transition"].to_json())
    write_json(output_dir / "skill_formula_binding_samples_v0_261.json", result["skill_formula_binding_samples"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 skill text scaling basis binding.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _execute_direct_skill_text_case(ir: CanonicalIR, rules: RuleBook, state, command) -> dict[str, Any]:
    for emission in _sorted_emissions(ir.damage_emissions):
        if emission.damage_formula_family != "direct" or emission.coverage_status != "executable":
            continue
        if emission.scaling_basis_expr.get("source_kind") != "character_data_card_skill_formula":
            continue
        definition = rules.action_definition(emission.action_id, emission.level)
        if definition is None:
            continue
        target_ids = _target_ids_for_definition(definition, command.actor_id)
        if target_ids is None:
            continue
        case = _execute_definition_case(rules, state, command, definition, target_ids=target_ids)
        transition = case.get("transition")
        if transition is None:
            continue
        if any(
            record.get("payload", {}).get("damage_emission_id") == emission.damage_emission_id
            for record in transition.transaction.settlement.records
            if isinstance(record, dict)
        ):
            case["selected_emission"] = emission
            case["selected_binding"] = _binding_for_emission(rules, emission)
            case["selection"] = {
                "selection_mode": "structured_predicate",
                "reason": "executable direct damage with character data card formula basis",
                "source_trace": emission.scaling_basis_expr.get("source_trace"),
            }
            return case
    return {"transition": None, "selected_emission": None, "selected_binding": None, "error": "skill_text_direct_case_missing"}


def _binding_for_emission(rules: RuleBook, emission) -> SkillFormulaBindingIR | None:
    param_index = int(emission.scaling_basis_expr.get("param_index", 0) or 0)
    bindings = rules.skill_formula_bindings_for_action_param(
        emission.action_id,
        emission.level,
        param_index,
        "direct_damage",
    )
    for binding in bindings:
        if binding.coverage_status == "executable":
            return binding
    return bindings[0] if bindings else None


def _select_dot_text_binding(ir: CanonicalIR) -> SkillFormulaBindingIR | None:
    for binding in sorted(ir.skill_formula_bindings, key=lambda item: item.binding_id):
        if binding.coverage_status == "executable" and binding.formula_role == "dot_damage":
            return binding
    return None


def _ir_shape_checks(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    executable_direct = [
        emission
        for emission in ir.damage_emissions
        if emission.damage_formula_family == "direct" and emission.coverage_status == "executable"
    ]
    checks = {
        "skill_formula_bindings_exist": bool(ir.skill_formula_bindings),
        "executable_direct_binding_exists": any(
            binding.coverage_status == "executable" and binding.formula_role == "direct_damage"
            for binding in ir.skill_formula_bindings
        ),
        "executable_dot_binding_exists": any(
            binding.coverage_status == "executable" and binding.formula_role == "dot_damage"
            for binding in ir.skill_formula_bindings
        ),
        "no_executable_direct_requires_skill_text_binding_flag": all(
            emission.scaling_basis_expr.get("requires_skill_text_binding") is not True for emission in executable_direct
        ),
        "no_current_scope_attack_basis": all(
            emission.scaling_basis_expr.get("source_kind") != "current_direct_damage_admission"
            for emission in executable_direct
        ),
        "executable_direct_has_skill_text_source": all(
            emission.scaling_basis_expr.get("source_kind") == "character_data_card_skill_formula"
            and bool(emission.scaling_basis_expr.get("character_data_card_id"))
            for emission in executable_direct
        ),
        "avatar_profile_exists": any(profile.coverage_status == "executable" for profile in ir.avatar_profiles),
        "avatar_profile_rulebook_lookup": any(
            profile.coverage_status == "executable" and rules.avatar_profile(profile.avatar_id) is not None
            for profile in ir.avatar_profiles[:20]
        ),
        "avatar_action_set_exists": any(
            action_set.entity_ref.startswith("avatar:") and action_set.coverage_status == "executable"
            for action_set in ir.combatant_action_sets
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _direct_runtime_checks(rules: RuleBook, before_state, case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    emission = case.get("selected_emission")
    binding = case.get("selected_binding")
    if transition is None or emission is None:
        return {"ok": False, "checks": {"case_found": False}, "case": _direct_case_json(case)}
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
    snapshot = SnapshotCompletenessValidator().validate(before_state.snapshot())
    damage_mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"]
    checks = {
        "case_found": True,
        "binding_found": isinstance(binding, SkillFormulaBindingIR) and binding.coverage_status == "executable",
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
        "damage_mutation_present": bool(damage_mutations),
        "mutation_has_skill_text_basis": all(
            mutation.metadata.get("formula_result", {})
            .get("scaling", {})
            .get("basis_result", {})
            .get("source_trace", {})
            .get("scaling_basis", {})
            .get("source_kind")
            == "character_data_card_skill_formula"
            for mutation in damage_mutations
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "source_audit": source_audit.to_json(),
        "case": _direct_case_json(case),
    }


def _dot_binding_checks(binding: SkillFormulaBindingIR | None) -> dict[str, Any]:
    checks = {
        "dot_text_binding_found": isinstance(binding, SkillFormulaBindingIR),
        "dot_text_binding_executable": isinstance(binding, SkillFormulaBindingIR) and binding.coverage_status == "executable",
        "dot_binding_has_basis": isinstance(binding, SkillFormulaBindingIR)
        and binding.scaling_basis_expr.get("source_kind") == "character_data_card_skill_formula",
        "dot_binding_role_is_not_runtime_claim": isinstance(binding, SkillFormulaBindingIR)
        and binding.formula_role == "dot_damage",
    }
    return {"ok": all(checks.values()), "checks": checks}


def _synthetic_negative_bindings() -> dict[str, Any]:
    text_map = {
        "1": "造成等同于测试#2%攻击力的火属性伤害。",
        "2": "造成等同于测试#1%未知值的火属性伤害。",
        "3": "造成等同于测试#1%攻击力的火属性伤害。",
        "4": "提高测试#1%的持续伤害。",
    }
    cases = {
        "param_out_of_range": {
            "SkillID": 1,
            "Level": 1,
            "SkillDesc": {"Hash": 1},
            "ParamList": [{"Value": 1.0}],
        },
        "unknown_basis_or_missing_match": {
            "SkillID": 2,
            "Level": 1,
            "SkillDesc": {"Hash": 2},
            "ParamList": [{"Value": 1.0}],
        },
        "param_not_numeric": {
            "SkillID": 3,
            "Level": 1,
            "SkillDesc": {"Hash": 3},
            "ParamList": [{"Hash": 123}],
        },
        "non_damage_text": {
            "SkillID": 4,
            "Level": 1,
            "SkillDesc": {"Hash": 4},
            "ParamList": [{"Value": 1.0}],
        },
    }
    result: dict[str, Any] = {}
    for name, row in cases.items():
        bindings = skill_formula_bindings_from_row(
            relative_path="synthetic_negative/AvatarSkillConfig.json",
            entity_type="avatar_skill",
            id_key="SkillID",
            row_index=0,
            row=row,
            text_map=text_map,
            skill_to_card={"1": "character_data_card:avatar:synthetic"},
        )
        result[name] = [binding.to_json() for binding in bindings]
    return result


def _negative_binding_checks(negatives: dict[str, Any]) -> dict[str, Any]:
    checks = {
        name: all(
            isinstance(binding, dict)
            and binding.get("coverage_status") == "blocked"
            and bool(binding.get("blocked_reason"))
            for binding in bindings
            if isinstance(bindings, list)
        )
        for name, bindings in negatives.items()
    }
    checks["all_negative_cases_present"] = set(negatives) == {
        "param_out_of_range",
        "unknown_basis_or_missing_match",
        "param_not_numeric",
        "non_damage_text",
    }
    return {"ok": all(checks.values()), "checks": checks}


def _binding_counts(ir: CanonicalIR) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    for binding in ir.skill_formula_bindings:
        role_counts = counts.setdefault(binding.formula_role, {})
        role_counts[binding.coverage_status] = role_counts.get(binding.coverage_status, 0) + 1
    return counts


def _binding_samples(ir: CanonicalIR) -> dict[str, Any]:
    samples: dict[str, list[dict[str, Any]]] = {}
    for binding in sorted(ir.skill_formula_bindings, key=lambda item: item.binding_id):
        key = f"{binding.formula_role}:{binding.coverage_status}"
        samples.setdefault(key, [])
        if len(samples[key]) < 5:
            samples[key].append(binding.to_json())
    return samples


def _direct_case_json(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    emission = case.get("selected_emission")
    binding = case.get("selected_binding")
    return {
        "selection": case.get("selection", {}),
        "error": case.get("error", ""),
        "selected_emission": emission.to_json() if emission else None,
        "selected_binding": binding.to_json() if binding else None,
        "transition": transition.to_json() if transition is not None else None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
