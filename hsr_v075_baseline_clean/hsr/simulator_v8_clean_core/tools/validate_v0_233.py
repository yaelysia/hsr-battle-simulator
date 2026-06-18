from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.settlement import SettlementTraceabilityValidator
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _scenario_dict
from .validate_v0_231 import _negative_cases, _state_with_dynamic_binding
from .validate_v0_232 import _select_break_case


VALIDATION_VERSION = "v0_233"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(TBGDDiscovery(tbgd_root).scan(), ir)
    case = _select_break_case(ir, rules)
    break_case = _execute_break_damage_case(rules, case)
    negative_cases = _negative_cases(break_case["initial_state"], case["emission"])
    evaluator_cases = _postfix_evaluator_cases(case["break_damage_emissions"][0])
    static_result = run_static_checks(package_root)
    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "break_damage_transition": _break_damage_transition_checks(break_case["transition"]),
        "source_audit": {"ok": bool(break_case["source_audit"].get("ok")), "source_audit": break_case["source_audit"]},
        "negative_cases": negative_cases["checks"],
        "postfix_evaluator": _postfix_evaluator_checks(evaluator_cases),
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all((static_result.ok, *(item["ok"] for item in checks.values()))),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selected_toughness_emission": case["emission"].to_json(),
            "selected_break_template": case["break_template"].to_json(),
            "selected_break_damage_emissions": [item.to_json() for item in case["break_damage_emissions"]],
            "selected_break_status_emissions": [item.to_json() for item in case["break_status_emissions"]],
            "sampled": ir.metadata.get("sampled", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audit": break_case["source_audit"],
        "trust_summary": _trust_summary(checks, case),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_233.json", result)
    write_json(output_dir / "sample_break_damage_transition_v0_233.json", break_case["transition"])
    write_json(output_dir / "sample_break_damage_evaluator_v0_233.json", evaluator_cases)
    write_json(output_dir / "sample_break_damage_negative_cases_v0_233.json", negative_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_233 normal break damage formula admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _execute_break_damage_case(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    action = case["action"]
    profile = case["profile"]
    avatar = case["avatar"]
    emission = case["emission"]
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(
            profile,
            action,
            avatar,
            enemy_panel={
                "max_hp": 100000.0,
                "hp": 100000.0,
            },
        )
    )
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    enemy = build_result.state.units["enemy:profile_target"]
    state = _state_with_dynamic_binding(build_result.state, emission, enemy.toughness)
    command = build_result.commands[0]
    after_state, transition = CombatExecutor(rules).execute(command, state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    transition_contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(state.snapshot())
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    return {
        "identity_ok": identity_result.ok,
        "initial_state": state,
        "after_state": after_state,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
        "contract": transition_contract.to_json(),
        "traceability": traceability.to_json(),
        "snapshot": snapshot.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    status = coverage_json.get("action_execution_status", {})
    break_base = status.get("break_base_damage", {})
    break_damage = status.get("break_damage_emissions", {})
    checks = {
        "break_base_damage_lowered": break_base.get("lowered", 0) >= 100,
        "break_base_damage_executable": break_base.get("executable", 0) >= 100,
        "break_damage_emissions_executable": break_damage.get("executable", 0) >= 7,
        "canonical_ir_has_break_base_damage": len(ir.break_base_damage) >= 100,
    }
    return {"ok": all(checks.values()), "checks": checks, "action_execution_status": status}


def _break_damage_transition_checks(transition: dict[str, Any]) -> dict[str, object]:
    mutations = transition.get("mutations", [])
    records = transition.get("settlement", {}).get("records", [])
    break_damage_mutations = [
        item
        for item in mutations
        if item.get("source") == "damage_system"
        and item.get("metadata", {}).get("damage_formula_family") == "break"
    ]
    hp_changed = any(float(item.get("after", 0.0)) < float(item.get("before", 0.0)) for item in break_damage_mutations)
    checks = {
        "break_damage_mutation_present": bool(break_damage_mutations),
        "break_damage_hp_changed": hp_changed,
        "break_damage_record_present": any(record.get("record_type") == "break_damage" for record in records),
        "break_damage_source_metadata_present": all(
            isinstance(item.get("metadata", {}).get("break_base_damage_source"), dict)
            and isinstance(item.get("metadata", {}).get("numeric_evaluation"), dict)
            and item.get("metadata", {}).get("break_damage_emission_id")
            for item in break_damage_mutations
        ),
        "no_direct_multiplier_ledger": all(
            item.get("metadata", {}).get("normal_multiplier_terms") == []
            for item in break_damage_mutations
        ),
        "coverage_count_present": transition.get("coverage", {}).get("break_damage_mutation_count", 0) > 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "break_damage_mutations": break_damage_mutations}


def _postfix_evaluator_cases(emission) -> dict[str, Any]:
    expr = emission.scaling_expr
    hashes = _dynamic_hashes(expr)
    evaluator = RuleEvaluator()
    source = {
        "source_type": "break_template_runtime_value",
        "entries": {
            "base": {
                "scope": "validation",
                "owner_id": "ally:actor",
                "name": "CasterBreakBaseDamage",
                "hash": str(hashes[0]) if hashes else "",
                "value": 100.0,
                "source_trace": {"selection_mode": "structured_postfix_validation"},
            },
            "stance": {
                "scope": "validation",
                "owner_id": "enemy:target",
                "name": "TargetStance",
                "hash": str(hashes[1]) if len(hashes) > 1 else "",
                "value": 50.0,
                "source_trace": {"selection_mode": "structured_postfix_validation"},
            },
        },
        "by_hash": {},
        "by_name": {},
    }
    source["by_hash"] = {
        item["hash"]: [key]
        for key, item in source["entries"].items()
        if isinstance(item.get("hash"), str) and item.get("hash")
    }
    source["by_name"] = {
        item["name"]: [key]
        for key, item in source["entries"].items()
        if isinstance(item.get("name"), str) and item.get("name")
    }
    unsupported = {
        "kind": "postfix_expr",
        "raw": {
            "PostfixExpr": {
                "OpCodes": "Bg==",
                "FixedValues": [],
                "DynamicHashes": [],
            }
        },
    }
    return {
        "admitted": evaluator.evaluate_numeric(
            expr,
            NumericEvaluationContext(binding_sources=(source,), source_trace=emission.source.to_json()),
        ).to_json(),
        "unbound": evaluator.evaluate_numeric(
            expr,
            NumericEvaluationContext(source_trace=emission.source.to_json()),
        ).to_json(),
        "unsupported_opcode": evaluator.evaluate_numeric(
            unsupported,
            NumericEvaluationContext(source_trace=emission.source.to_json()),
        ).to_json(),
    }


def _postfix_evaluator_checks(cases: dict[str, Any]) -> dict[str, object]:
    checks = {
        "admitted_postfix_ok": cases["admitted"].get("ok") is True
        and cases["admitted"].get("expression_kind") == "postfix_expr",
        "admitted_has_dynamic_operands": bool(cases["admitted"].get("bindings", {}).get("dynamic_operands")),
        "unbound_postfix_blocked": cases["unbound"].get("ok") is False
        and "dynamic_hash_unbound" in str(cases["unbound"].get("blocked_reason")),
        "unsupported_opcode_blocked": cases["unsupported_opcode"].get("ok") is False
        and cases["unsupported_opcode"].get("blocked_reason") == "unsupported_postfix_opcode",
    }
    return {"ok": all(checks.values()), "checks": checks, "cases": cases}


def _dynamic_hashes(expr: dict[str, Any]) -> list[Any]:
    raw = expr.get("raw")
    postfix = raw.get("PostfixExpr") if isinstance(raw, dict) else None
    hashes = postfix.get("DynamicHashes") if isinstance(postfix, dict) else None
    return list(hashes) if isinstance(hashes, list) else []


def _trust_summary(checks: dict[str, Any], case: dict[str, Any]) -> dict[str, object]:
    return {
        "toughness_execution": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "executable ToughnessEmissionIR from ability task AttackProperty.StanceValue",
        },
        "normal_break_lifecycle": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "toughness depletion enters broken state through executable BreakTemplateIR",
        },
        "break_status": {
            "semantic_status": "trusted_for_current_scope",
            "scope": "executable break AddModifier status creation only; tick lifecycle remains separate",
        },
        "break_damage": {
            "semantic_status": "trusted_for_current_scope" if checks["break_damage_transition"]["ok"] else "blocked",
            "scope": "BreakDamageEmissionIR ByBreakDamage with admitted PostfixExpr and AvatarBreakDamage base table",
            "emission_count": len(case["break_damage_emissions"]),
        },
        "break_dot_tick": {
            "semantic_status": "blocked",
            "blocking_dependency": "break-applied status callback tick formula admission is not implemented in v0_233",
        },
        "break_delay_recovery": {
            "semantic_status": "blocked",
            "blocking_dependency": "delay/recovery source task admission is not implemented in v0_233",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
