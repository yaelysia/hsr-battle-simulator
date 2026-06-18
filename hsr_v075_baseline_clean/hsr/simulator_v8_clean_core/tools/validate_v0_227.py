from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleState, BattleTransition, GameEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .build_ir import build_outputs
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_214 import HEAL_OPCODES, SHIELD_OPCODES, _select_blocked_effect
from .validate_v0_225 import (
    _audit_transition_map,
    _cases_with_transitions,
    _existing_effect_cases,
    _source_audit_full_checks,
)


VALIDATION_VERSION = "v0_227"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    state = build_result.state
    command = build_result.commands[0]

    effect_cases = _existing_effect_cases(ir, rules, state, command)
    audit = _source_audit_full_checks(rules, _audit_transition_map(_cases_with_transitions(effect_cases)))
    heal_checks = _trusted_effect_checks(effect_cases.get("effect_heal"), "heal")
    shield_checks = _trusted_effect_checks(effect_cases.get("effect_shield"), "shield")
    blocked_checks = _blocked_formula_checks(ir, rules, state, command)
    lowering_checks = _lowering_default_checks(ir)
    actionability = _actionability_matrix(lowering_checks, heal_checks, shield_checks, blocked_checks)
    quality = _transition_quality_checks(effect_cases)
    static_result = run_static_checks(package_root)

    checks = {
        "lowering_default_full": lowering_checks,
        "heal_current_scope": heal_checks,
        "shield_current_scope": shield_checks,
        "unsupported_formula_negatives": blocked_checks,
        "actionability_matrix": _actionability_checks(actionability),
        "source_audit": _source_audit_summary(audit),
        "transition_quality": quality,
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "ir_effects": len(ir.effects),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_227.json", result)
    write_json(output_dir / "actionability_matrix_v0_227.json", actionability)
    write_json(output_dir / "sample_effect_heal_transition_v0_227.json", effect_cases["effect_heal"]["transition"].to_json())
    write_json(output_dir / "sample_effect_shield_transition_v0_227.json", effect_cases["effect_shield"]["transition"].to_json())
    write_json(output_dir / "sample_unsupported_formula_cases_v0_227.json", blocked_checks["cases"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_227 actionability and trust-matrix repairs.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--scenario", type=Path, default=None)
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    scenario_path = args.scenario or package_root / "scenarios" / "examples" / "identity_smoke_v0_204.json"
    result = run_validation(package_root, tbgd_root, args.output_dir, scenario_path)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _trusted_effect_checks(case: dict[str, Any] | None, record_type: str) -> dict[str, Any]:
    transition = case.get("transition") if isinstance(case, dict) else None
    selection = case.get("selection", {}) if isinstance(case, dict) else {}
    records = _records_of_type(transition, record_type)
    evaluations = [
        payload.get("numeric_evaluation")
        for payload in (record.get("payload", {}) for record in records if isinstance(record, dict))
        if isinstance(payload, dict)
    ]
    dynamic_evaluations = [
        evaluation
        for evaluation in evaluations
        if isinstance(evaluation, dict) and evaluation.get("expression_kind") == "dynamic_hash"
    ]
    checks = {
        "transition_exists": isinstance(transition, BattleTransition),
        "record_exists": bool(records),
        "selection_is_structured": isinstance(selection, dict) and selection.get("selection_mode") == "structured_predicate",
        "source_is_executable": isinstance(selection, dict) and selection.get("coverage_status") == "executable",
        "binding_from_status_instance": bool(dynamic_evaluations)
        and all(
            isinstance(evaluation.get("bindings"), dict)
            and evaluation["bindings"].get("source_type") == "status_instance"
            and isinstance(evaluation["bindings"].get("entry"), dict)
            and isinstance(evaluation["bindings"]["entry"].get("source_trace"), dict)
            for evaluation in dynamic_evaluations
        ),
        "no_manual_binding": all(
            not (
                isinstance(evaluation, dict)
                and isinstance(evaluation.get("bindings"), dict)
                and evaluation["bindings"].get("source_type") == "explicit_dynamic_values"
            )
            for evaluation in evaluations
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "selection": selection,
        "records": records,
    }


def _blocked_formula_checks(
    ir,
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    registry = EffectRegistry(StatusSystem(rules))
    cases = {
        "heal": _blocked_effect_case(registry, state, command, _select_blocked_effect(ir, HEAL_OPCODES), "heal_blocked"),
        "shield": _blocked_effect_case(registry, state, command, _select_blocked_effect(ir, SHIELD_OPCODES), "shield_blocked"),
    }
    checks: dict[str, bool] = {}
    for name, case in cases.items():
        transition = case.get("transition")
        before = case.get("before")
        after = case.get("after")
        checks[f"{name}_blocked_effect_selected"] = isinstance(case.get("effect"), EffectIR) and case["effect"].coverage_status != "executable"
        checks[f"{name}_transition_exists"] = isinstance(transition, BattleTransition)
        checks[f"{name}_no_mutations"] = isinstance(transition, BattleTransition) and not transition.transaction.mutations
        checks[f"{name}_snapshot_unchanged"] = isinstance(before, BattleState) and isinstance(after, BattleState) and before.snapshot().to_json() == after.snapshot().to_json()
        checks[f"{name}_blocked_reason_present"] = bool(case.get("unsupported"))
        checks[f"{name}_blocked_by_registry_coverage_gate"] = any(
            str(reason).startswith("effect_not_executable:")
            for reason in case.get("unsupported", ())
        )
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "cases": {name: _blocked_case_json(case) for name, case in cases.items()},
    }


def _blocked_effect_case(
    registry: EffectRegistry,
    state: BattleState,
    command: ActionCommand,
    effect: EffectIR | None,
    suffix: str,
) -> dict[str, Any]:
    if effect is None:
        return {"effect": None, "transition": None, "before": state, "after": state, "unsupported": ("missing blocked effect",)}
    result = registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{suffix}:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _effect_transition(command, state, after, effect, result, command.actor_id, suffix)
    return {
        "effect": effect,
        "transition": transition,
        "before": state,
        "after": after,
        "unsupported": result.unsupported,
    }


def _effect_transition(
    command: ActionCommand,
    before: BattleState,
    after: BattleState,
    effect: EffectIR,
    result,
    target_id: str,
    suffix: str,
) -> BattleTransition:
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=(target_id,),
        records=tuple(result.records),
    )
    transaction = ActionTransaction(
        command=command,
        before=before.snapshot(),
        events=(
            GameEvent(
                event_type=f"effect.{effect.opcode}",
                source_id=command.actor_id,
                target_id=target_id,
                event_id=f"event:{before.event_index}:{VALIDATION_VERSION}:{suffix}",
                window="effect_resolution",
                process_only=True,
                payload={"effect_id": effect.effect_id, "opcode": effect.opcode},
            ),
        ),
        mutations=result.mutations,
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after.snapshot(),
        target_resolution=TargetResolution(
            requested=(target_id,),
            legal=(target_id,),
            selected=(target_id,),
            reason="effect_target_alias",
            source="effect_system",
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode},
        ),
        coverage={
            "executor": f"{VALIDATION_VERSION}_{suffix}",
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "mutation_count": len(result.mutations),
            "unsupported": list(result.unsupported),
        },
    )


def _transition_quality_checks(effect_cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    validator = TransitionContractValidator()
    traceability = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name in ("effect_heal", "effect_shield"):
        case = effect_cases.get(name, {})
        transition = case.get("transition")
        before = case.get("before") or case.get("before_state")
        checks[f"{name}_transition_exists"] = isinstance(transition, BattleTransition)
        if not isinstance(transition, BattleTransition) or not isinstance(before, BattleState):
            continue
        after = reducer.apply_all(before, transition.transaction.mutations)
        replay = reducer.replay_snapshot(before, transition.transaction.mutations, after.snapshot().to_json())
        contract = validator.validate(transition)
        settlement = traceability.validate(transition.transaction.settlement, transition.transaction.mutations)
        checks[f"{name}_contract_ok"] = contract.ok
        checks[f"{name}_settlement_traceability_ok"] = settlement.ok
        checks[f"{name}_replay_ok"] = replay.ok
        details[name] = {
            "contract": contract.to_json(),
            "settlement_traceability": settlement.to_json(),
            "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _lowering_default_checks(ir) -> dict[str, Any]:
    sampled = ir.metadata.get("sampled", {})
    build_outputs_defaults = build_outputs.__defaults__ or ()
    build_outputs_default_max_ability_files = build_outputs_defaults[-1] if build_outputs_defaults else "missing"
    checks = {
        "metadata_sampled_present": isinstance(sampled, dict),
        "ability_files_not_sampled": isinstance(sampled, dict) and sampled.get("ability_files") is False,
        "callbacks_not_sampled": isinstance(sampled, dict) and sampled.get("callbacks") is False,
        "entity_tables_not_sampled": isinstance(sampled, dict) and sampled.get("entity_tables") is False,
        "build_ir_default_not_sampled": build_outputs_default_max_ability_files is None,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "sampled": sampled,
        "build_outputs_default_max_ability_files": build_outputs_default_max_ability_files,
    }


def _actionability_matrix(
    lowering_checks: dict[str, Any],
    heal_checks: dict[str, Any],
    shield_checks: dict[str, Any],
    blocked_checks: dict[str, Any],
) -> dict[str, Any]:
    entries = {
        "lowering_default_full_read": _fixed_now_entry(lowering_checks["ok"], "LoweringLimits defaults to full TBGD ability read"),
        "heal_fixed_or_status_bound": _fixed_now_entry(heal_checks["ok"], "Mainline executable HealHP is selected and audited through status dynamic binding"),
        "shield_fixed_or_status_bound": _fixed_now_entry(shield_checks["ok"], "Mainline executable InitShield is selected and audited through status dynamic binding"),
        "unsupported_heal_shield_formulas": _fixed_now_entry(blocked_checks["ok"], "Unsupported heal/shield formulas block without state mutation"),
        "hp_loss": _fixed_now_entry(True, "Covered by v0_226 LoseHPByRatio fixed/bound ratio path"),
        "condition_evaluator": {
            "current_actionability": "not_applicable",
            "repaired": True,
            "semantic_status": "trusted_for_current_scope",
            "source_audit_applicable": False,
            "reason": "condition-only checks do not produce mutation; source audit is not applicable",
            "blocking_dependency": "",
        },
        "trigger_window": _wait_entry("per-hit target context, global listener, and being-hit listener are not implemented"),
        "true_damage": _wait_entry("no admitted executable TBGD true-damage emission or effect source exists"),
        "queue": _wait_entry("no admitted executable queue opcode/effect lowering exists", semantic_status="blocked"),
    }
    return {
        "ok": all(
            entry.get("current_actionability") != "fixed_now" or bool(entry.get("repaired"))
            for entry in entries.values()
        )
        and all(
            entry.get("current_actionability") not in {"wait_for_dependency"} or bool(entry.get("blocking_dependency"))
            for entry in entries.values()
        ),
        "entries": entries,
    }


def _fixed_now_entry(repaired: bool, reason: str) -> dict[str, Any]:
    return {
        "current_actionability": "fixed_now",
        "repaired": repaired,
        "semantic_status": "trusted_for_current_scope" if repaired else "needs_fix",
        "reason": reason,
        "blocking_dependency": "" if repaired else "fix_now item is not repaired",
    }


def _wait_entry(dependency: str, *, semantic_status: str = "structural_only") -> dict[str, Any]:
    return {
        "current_actionability": "wait_for_dependency",
        "repaired": False,
        "semantic_status": semantic_status,
        "reason": "cannot be made trusted without the named dependency",
        "blocking_dependency": dependency,
    }


def _actionability_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    entries = matrix.get("entries", {})
    fix_now_unrepaired = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict)
        and entry.get("current_actionability") == "fixed_now"
        and not entry.get("repaired")
    }
    missing_dependencies = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict)
        and entry.get("current_actionability") == "wait_for_dependency"
        and not entry.get("blocking_dependency")
    }
    return {
        "ok": bool(matrix.get("ok")) and not fix_now_unrepaired and not missing_dependencies,
        "fix_now_unrepaired": fix_now_unrepaired,
        "missing_dependencies": missing_dependencies,
    }


def _source_audit_summary(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(audit.get("ok")),
        "checked_transition_count": audit.get("checked_transition_count", 0),
        "checked_mutation_count": audit.get("checked_mutation_count", 0),
        "failed_transitions": [
            name
            for name, result in audit.get("results", {}).items()
            if isinstance(result, dict) and not result.get("ok")
        ],
    }


def _records_of_type(transition: Any, record_type: str) -> list[dict[str, Any]]:
    if not isinstance(transition, BattleTransition) or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _blocked_case_json(case: dict[str, Any]) -> dict[str, Any]:
    effect = case.get("effect")
    transition = case.get("transition")
    return {
        "effect": effect.to_json() if isinstance(effect, EffectIR) else None,
        "unsupported": list(case.get("unsupported", ())),
        "mutation_count": len(transition.transaction.mutations) if isinstance(transition, BattleTransition) else None,
        "coverage": transition.coverage if isinstance(transition, BattleTransition) else {},
    }


if __name__ == "__main__":
    raise SystemExit(main())
