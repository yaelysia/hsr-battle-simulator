from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.fidelity import build_fidelity_matrix
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    TargetResolution,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR, EffectIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_213 import (
    _damage_semantics_regression_checks,
    _formula_test_state,
    _status_ledger_transition,
    _status_modifier_ledger_regression_checks,
)


VALIDATION_VERSION = "v0_215"
NON_MAINLINE_PREFIXES = (
    "Config/ConfigAbility/Activity",
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
)


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
    write_full_ir: bool = False,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    if write_full_ir:
        write_json(output_dir / "canonical_ir_v0_215.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_215.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_215.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_215.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = build_result.state
    command = build_result.commands[0]
    registry = EffectRegistry(StatusSystem(rules))

    shield_case = _dynamic_shield_case(ir, registry, base_state, command)
    heal_case = _unsupported_heal_case(ir, registry, base_state, command)
    resource_case = _modify_sp_case(ir, registry, base_state, command)
    evaluator_cases = _numeric_evaluator_cases(_selected_dynamic_hash(shield_case, resource_case))
    formula_state = _formula_test_state(base_state)
    status_ledger_transition = _status_ledger_transition(ir, rules, formula_state, _with_crit_mode(command, "crit"))
    damage_regression_transition = status_ledger_transition
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, command)

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    transition_checks = _transition_quality_checks(
        {
            "dynamic_shield": shield_case,
            "modify_sp": resource_case,
        }
    )
    checks = {
        "numeric_evaluator": _numeric_evaluator_checks(evaluator_cases),
        "dynamic_shield": _dynamic_shield_checks(shield_case),
        "unsupported_dynamic_heal_blocked": _unsupported_heal_checks(heal_case),
        "modify_sp_new": _modify_sp_checks(resource_case, coverage.to_json()),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(damage_regression_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
        "transition_quality": transition_checks,
    }
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                snapshot_result.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_effects": len(ir.effects),
                "ir_formulas": len(ir.formulas),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "target_ids": list(command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }

    write_json(output_dir / "validation_summary_v0_215.json", result)
    write_json(output_dir / "sample_numeric_evaluator_cases_v0_215.json", evaluator_cases)
    for name, case in (
        ("dynamic_shield", shield_case),
        ("unsupported_dynamic_heal", heal_case),
        ("modify_sp_new", resource_case),
    ):
        write_json(output_dir / f"sample_{name}_case_v0_215.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{name}_transition_v0_215.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_215.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_215.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 numeric formula and DynamicValue evaluation spine.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_215"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
    parser.add_argument("--write-full-ir", action="store_true")
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    scenario_path = args.scenario or package_root / "scenarios/examples/identity_smoke_v0_204.json"
    result = run_validation(
        package_root,
        tbgd_root,
        args.output_dir,
        scenario_path,
        max_ability_files=args.max_ability_files,
        write_full_ir=args.write_full_ir,
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    effect_opcode_counts: dict[str, int] = {}
    for effect in ir.effects:
        effect_opcode_counts[effect.opcode] = effect_opcode_counts.get(effect.opcode, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "effect_opcode_counts": dict(sorted(effect_opcode_counts.items())),
    }


def _numeric_evaluator_cases(dynamic_hash: str) -> dict[str, Any]:
    evaluator = RuleEvaluator()
    hash_expr: dict[str, Any] = {"kind": "dynamic_hash", "hash": dynamic_hash}
    cases = {
        "fixed": evaluator.evaluate_numeric({"kind": "fixed", "value": 12.5}, NumericEvaluationContext()).to_json(),
        "bound_dynamic_hash": evaluator.evaluate_numeric(
            hash_expr,
            NumericEvaluationContext(dynamic_values={dynamic_hash: 321.0}),
        ).to_json(),
        "unbound_dynamic_hash": evaluator.evaluate_numeric(
            hash_expr,
            NumericEvaluationContext(),
        ).to_json(),
        "unsupported_postfix": evaluator.evaluate_numeric(
            {"kind": "postfix_expr", "reason": "unsupported_postfix_expr", "raw": {"OpCodes": "AQABAQIR"}},
            NumericEvaluationContext(),
        ).to_json(),
    }
    return cases


def _dynamic_shield_case(
    ir: CanonicalIR,
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    effect = _select_dynamic_shield_effect(ir)
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing executable mainline dynamic shield effect"}
    amount_expr = effect.payload["standard"]["amount"]
    hash_key = str(amount_expr.get("hash")) if isinstance(amount_expr, dict) else ""
    bound_result = _execute_effect(
        registry,
        base_state,
        effect,
        command,
        source_suffix="dynamic_shield_bound",
        dynamic_values={hash_key: 321.0},
    )
    bound_after = MutationReducer().apply_all(base_state, bound_result.mutations)
    transition = _effect_transition(
        command=command,
        before_state=base_state,
        after_state=bound_after,
        effect=effect,
        effect_result=bound_result,
        target_id=command.actor_id,
        coverage_id="v0_215_dynamic_shield",
    )
    unbound_result = _execute_effect(
        registry,
        base_state,
        effect,
        command,
        source_suffix="dynamic_shield_unbound",
    )
    return {
        "effect": effect,
        "before_state": base_state,
        "result": bound_result,
        "transition": transition,
        "unbound_result": unbound_result,
        "bound_hash": hash_key,
        "bound_value": 321.0,
    }


def _unsupported_heal_case(
    ir: CanonicalIR,
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    effect = _select_unsupported_heal_effect(ir)
    if effect is None:
        return {"effect": None, "result": None, "error": "missing mainline unsupported HealHP effect"}
    standard = effect.payload.get("standard", {})
    bindings: dict[str, float] = {}
    if isinstance(standard, dict):
        for key in ("amount", "percentage"):
            expr = standard.get(key)
            if isinstance(expr, dict) and expr.get("kind") == "dynamic_hash":
                bindings[str(expr.get("hash"))] = 123.0 if key == "amount" else 0.2
    result = _execute_effect(
        registry,
        base_state,
        effect,
        command,
        source_suffix="unsupported_heal_blocked",
        dynamic_values=bindings,
    )
    return {"effect": effect, "result": result, "dynamic_values": bindings}


def _modify_sp_case(
    ir: CanonicalIR,
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    effect = _select_modify_sp_effect(ir)
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing ModifySPNew effect"}
    amount_expr = effect.payload["standard"]["amount"]
    hash_key = str(amount_expr.get("hash")) if isinstance(amount_expr, dict) else ""
    result = _execute_effect(
        registry,
        base_state,
        effect,
        command,
        source_suffix="modify_sp_bound",
        dynamic_values={hash_key: 1.0},
    )
    after = MutationReducer().apply_all(base_state, result.mutations)
    transition = _effect_transition(
        command=command,
        before_state=base_state,
        after_state=after,
        effect=effect,
        effect_result=result,
        target_id=command.actor_id,
        coverage_id="v0_215_modify_sp_new",
    )
    return {
        "effect": effect,
        "before_state": base_state,
        "result": result,
        "transition": transition,
        "bound_hash": hash_key,
        "bound_value": 1.0,
    }


def _execute_effect(
    registry: EffectRegistry,
    state: BattleState,
    effect: EffectIR,
    command: ActionCommand,
    *,
    source_suffix: str,
    dynamic_values: dict[str, float] | None = None,
):
    return registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{source_suffix}:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
            dynamic_values=dynamic_values,
        ),
    )


def _effect_transition(
    *,
    command: ActionCommand,
    before_state: BattleState,
    after_state: BattleState,
    effect: EffectIR,
    effect_result,
    target_id: str,
    coverage_id: str,
) -> BattleTransition:
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=(target_id,),
        records=tuple(effect_result.records),
    )
    transaction = ActionTransaction(
        command=replace(command, metadata={**command.metadata, "effect_id": effect.effect_id, "opcode": effect.opcode}),
        before=before_state.snapshot(),
        events=(
            GameEvent(
                event_type=f"effect.{effect.opcode}",
                source_id=command.actor_id,
                target_id=target_id,
                event_id=f"event:{before_state.event_index}:{coverage_id}",
                window="effect_resolution",
                process_only=True,
                payload={"effect_id": effect.effect_id, "opcode": effect.opcode},
            ),
        ),
        mutations=effect_result.mutations,
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=(target_id,),
            legal=(target_id,),
            selected=(target_id,),
            reason="effect_target_alias",
            source="effect_system",
            metadata={"effect_id": effect.effect_id, "opcode": effect.opcode},
        ),
        coverage={
            "executor": coverage_id,
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "mutation_count": len(effect_result.mutations),
            "unsupported": list(effect_result.unsupported),
        },
    )


def _fixed_damage_family_cases(state: BattleState, command: ActionCommand) -> dict[str, Any]:
    target_id = command.target_ids[0] if command.target_ids else command.actor_id
    true_result = DamageSystem().apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=target_id,
            attack_type="true_damage_validation",
            damage_formula_family="true_damage",
            amount=100.0,
            source_trace={"validation": VALIDATION_VERSION},
        ),
    )
    hp_loss_result = DamageSystem().apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=target_id,
            attack_type="hp_loss_validation",
            damage_formula_family="hp_loss",
            amount=50.0,
            source_trace={"validation": VALIDATION_VERSION},
        ),
    )
    return {"true_damage": true_result, "hp_loss": hp_loss_result}


def _numeric_evaluator_checks(cases: dict[str, Any]) -> dict[str, object]:
    checks = {
        "fixed_ok": cases["fixed"].get("ok") is True and cases["fixed"].get("value") == 12.5,
        "bound_dynamic_hash_ok": cases["bound_dynamic_hash"].get("ok") is True
        and cases["bound_dynamic_hash"].get("value") == 321.0,
        "unbound_dynamic_hash_blocked": cases["unbound_dynamic_hash"].get("ok") is False
        and "dynamic_hash_unbound" in str(cases["unbound_dynamic_hash"].get("blocked_reason")),
        "unsupported_postfix_blocked": cases["unsupported_postfix"].get("ok") is False
        and cases["unsupported_postfix"].get("blocked_reason") == "unsupported_postfix_expr",
    }
    return {"ok": all(checks.values()), "checks": checks, "cases": cases}


def _dynamic_shield_checks(case: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    records = _records_of_type(transition, "shield")
    unbound_result = case.get("unbound_result")
    unbound_reasons = list(unbound_result.unsupported) if unbound_result is not None else []
    checks = {
        "real_dynamic_shield_effect_selected": _effect_matches_structured_dynamic_shield(case.get("effect")),
        "bound_transition_exists": transition is not None,
        "bound_has_shield_record": bool(records),
        "bound_has_numeric_evaluation": any(
            isinstance(record.get("payload"), dict) and isinstance(record["payload"].get("numeric_evaluation"), dict)
            for record in records
        ),
        "bound_has_shield_mutation": bool(transition is not None and transition.transaction.mutations),
        "unbound_dynamic_hash_blocked": any("dynamic_hash_unbound" in reason for reason in unbound_reasons),
    }
    return {"ok": all(checks.values()), "checks": checks, "records": records, "unbound_reasons": unbound_reasons}


def _unsupported_heal_checks(case: dict[str, Any]) -> dict[str, object]:
    result = case.get("result")
    reasons = list(result.unsupported) if result is not None else []
    records = list(result.records) if result is not None else []
    effect = case.get("effect")
    standard = effect.payload.get("standard") if isinstance(effect, EffectIR) else {}
    formula_type = standard.get("formula_type") if isinstance(standard, dict) else ""
    checks = {
        "real_unsupported_heal_effect_selected": _effect_matches_structured_unsupported_heal(effect),
        "formula_type_blocked": bool(
            isinstance(formula_type, str)
            and formula_type
            and any(f"formula_type_not_supported:{formula_type}" in reason for reason in reasons)
        ),
        "no_heal_mutation": bool(result is not None and not result.mutations),
        "unsupported_record_exists": any(record.get("record_type") == "effect_unsupported" for record in records),
    }
    return {"ok": all(checks.values()), "checks": checks, "reasons": reasons, "records": records}


def _modify_sp_checks(case: dict[str, Any], coverage_json: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    records = _records_of_type(transition, "resource_delta")
    opcode_status = coverage_json.get("opcode_status", {}).get("ModifySPNew", {})
    checks = {
        "modify_sp_lowered": opcode_status.get("lowered", 0) > 0,
        "real_modify_sp_effect_selected": isinstance(case.get("effect"), EffectIR)
        and case["effect"].opcode == "ModifySPNew",
        "transition_exists": transition is not None,
        "skill_point_mutation": bool(
            transition is not None
            and any(tuple(mutation.path) == ("skill_points",) for mutation in transition.transaction.mutations)
        ),
        "record_has_numeric_evaluation": any(
            isinstance(record.get("payload"), dict) and isinstance(record["payload"].get("numeric_evaluation"), dict)
            for record in records
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "opcode_status": opcode_status, "records": records}


def _fixed_damage_family_checks(cases: dict[str, Any]) -> dict[str, object]:
    details: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, result in cases.items():
        records = list(result.records)
        payloads = [record.get("payload", {}) for record in records if isinstance(record, dict)]
        checks[f"{name}_ok"] = result.ok
        checks[f"{name}_bypasses_normal_multipliers"] = any(
            payload.get("bypasses_normal_multipliers") is True for payload in payloads if isinstance(payload, dict)
        )
        checks[f"{name}_no_normal_multiplier_terms"] = all(
            payload.get("normal_multiplier_terms") == [] for payload in payloads if isinstance(payload, dict)
        )
        details[name] = result.to_json()
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _transition_quality_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in cases.items():
        transition = case.get("transition")
        before_state = case.get("before_state")
        if transition is None or not isinstance(before_state, BattleState):
            checks[f"{name}_transition_exists"] = False
            continue
        contract = transition_validator.validate(transition)
        traceability = settlement_validator.validate(transition.transaction.settlement, transition.transaction.mutations)
        replay = reducer.replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
        checks[f"{name}_contract_ok"] = contract.ok
        checks[f"{name}_traceability_ok"] = traceability.ok
        checks[f"{name}_replay_ok"] = replay.ok
        details[name] = {
            "contract": contract.to_json(),
            "traceability": traceability.to_json(),
            "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _select_dynamic_shield_effect(ir: CanonicalIR) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode not in {"InitShield", "StackShield", "ModifyShield"}:
            continue
        standard = effect.payload.get("standard")
        if not _is_mainline_source(effect.source.source_path):
            continue
        if effect.coverage_status != "executable":
            continue
        if (
            isinstance(standard, dict)
            and _is_supported_shield_formula_type(standard.get("formula_type"))
            and _is_dynamic_hash_expr(standard.get("amount"))
        ):
            return effect
    return None


def _select_unsupported_heal_effect(ir: CanonicalIR) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode != "HealHP":
            continue
        if not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if (
            isinstance(standard, dict)
            and isinstance(standard.get("formula_type"), str)
            and str(standard.get("formula_type"))
            and effect.coverage_status != "executable"
        ):
            return effect
    return None


def _select_modify_sp_effect(ir: CanonicalIR) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode != "ModifySPNew":
            continue
        if not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and isinstance(standard.get("amount"), dict):
            return effect
    return None


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _records_of_type(transition, record_type: str) -> list[dict[str, Any]]:
    if transition is None or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _effect_matches_structured_dynamic_shield(effect: object) -> bool:
    if not isinstance(effect, EffectIR):
        return False
    standard = effect.payload.get("standard")
    return (
        effect.opcode in {"InitShield", "StackShield", "ModifyShield"}
        and effect.coverage_status == "executable"
        and _is_mainline_source(effect.source.source_path)
        and isinstance(standard, dict)
        and _is_supported_shield_formula_type(standard.get("formula_type"))
        and _is_dynamic_hash_expr(standard.get("amount"))
    )


def _effect_matches_structured_unsupported_heal(effect: object) -> bool:
    if not isinstance(effect, EffectIR):
        return False
    standard = effect.payload.get("standard")
    return (
        effect.opcode == "HealHP"
        and effect.coverage_status != "executable"
        and _is_mainline_source(effect.source.source_path)
        and isinstance(standard, dict)
        and isinstance(standard.get("formula_type"), str)
        and bool(standard.get("formula_type"))
    )


def _is_dynamic_hash_expr(value: object) -> bool:
    return isinstance(value, dict) and value.get("kind") == "dynamic_hash" and value.get("hash") not in (None, "")


def _is_supported_shield_formula_type(value: object) -> bool:
    return value in {None, "", "ShieldByBaseValue"}


def _selected_dynamic_hash(*cases: dict[str, Any]) -> str:
    for case in cases:
        effect = case.get("effect")
        if not isinstance(effect, EffectIR):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        for key in ("amount", "percentage"):
            expr = standard.get(key)
            if _is_dynamic_hash_expr(expr):
                return str(expr.get("hash"))
    return "manual_input_binding_smoke_dynamic_hash"


def _is_mainline_source(source_path: str) -> bool:
    return not source_path.startswith(NON_MAINLINE_PREFIXES)


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif hasattr(value, "to_json"):
            encoded[key] = value.to_json()
        elif key == "result" or key == "unbound_result":
            encoded[key] = _effect_result_json(value)
        elif key.endswith("_state"):
            continue
        else:
            encoded[key] = value
    return encoded


def _effect_result_json(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    return {
        "events": [event.to_json() for event in effect_result.events],
        "mutations": [mutation.to_json() for mutation in effect_result.mutations],
        "records": list(effect_result.records),
        "unsupported": list(effect_result.unsupported),
    }


def _damage_case_json(cases: dict[str, Any]) -> dict[str, Any]:
    return {name: result.to_json() for name, result in cases.items()}


if __name__ == "__main__":
    raise SystemExit(main())
