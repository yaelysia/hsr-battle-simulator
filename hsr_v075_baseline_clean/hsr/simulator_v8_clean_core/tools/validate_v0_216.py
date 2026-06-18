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
from ..systems.dynamic_values import binding_source_from_store, store_from_state
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


VALIDATION_VERSION = "v0_216"
NON_MAINLINE_PREFIXES = (
    "Config/ConfigAbility/Activity",
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
)
DYNAMIC_VALUE_OPCODES = ("SetDynamicValue", "SetDynamicValueByModifierValue")


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
        write_json(output_dir / "canonical_ir_v0_216.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_216.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_216.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_216.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = build_result.state
    command = build_result.commands[0]
    registry = EffectRegistry(StatusSystem(rules))

    dynamic_effect = _select_dynamic_value_store_effect(ir)
    dynamic_case = _dynamic_value_store_case(registry, base_state, command, dynamic_effect)
    blocked_effect = _select_blocked_dynamic_value_effect(ir)
    evaluator_cases = _numeric_evaluator_cases(dynamic_case)

    formula_state = _formula_test_state(base_state)
    status_ledger_transition = _status_ledger_transition(ir, rules, formula_state, _with_crit_mode(command, "crit"))
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, command)

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    transition_checks = _transition_quality_checks({"dynamic_value_store": dynamic_case})
    checks = {
        "dynamic_value_store": _dynamic_value_store_checks(dynamic_case),
        "numeric_evaluator_store_binding": _numeric_evaluator_checks(evaluator_cases),
        "blocked_dynamic_value_payload": _blocked_dynamic_value_checks(blocked_effect),
        "coverage": _coverage_checks(coverage.to_json()),
        "selection_guard": _selection_guard_checks(dynamic_case),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
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

    write_json(output_dir / "validation_summary_v0_216.json", result)
    write_json(output_dir / "sample_numeric_evaluator_cases_v0_216.json", evaluator_cases)
    write_json(output_dir / "sample_dynamic_value_store_case_v0_216.json", _case_json(dynamic_case))
    transition = dynamic_case.get("transition")
    if transition is not None:
        write_json(output_dir / "sample_dynamic_value_store_transition_v0_216.json", transition.to_json())
    if blocked_effect is not None:
        write_json(output_dir / "sample_blocked_dynamic_value_effect_v0_216.json", blocked_effect.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_216.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_216.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 DynamicValueStore and real dynamic binding spine.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_216"))
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
    effect_status_counts: dict[str, dict[str, int]] = {}
    for effect in ir.effects:
        effect_opcode_counts[effect.opcode] = effect_opcode_counts.get(effect.opcode, 0) + 1
        effect_status_counts.setdefault(effect.opcode, {})
        effect_status_counts[effect.opcode][effect.coverage_status] = (
            effect_status_counts[effect.opcode].get(effect.coverage_status, 0) + 1
        )
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
        "effect_status_counts": dict(sorted(effect_status_counts.items())),
    }


def _select_dynamic_value_store_effect(ir: CanonicalIR) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.opcode, item.source.source_path, item.effect_id)):
        if effect.opcode != "SetDynamicValue":
            continue
        if effect.coverage_status != "executable" or not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        value_expr = standard.get("value_expr")
        if (
            standard.get("target_alias") in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
            and isinstance(standard.get("value_name"), str)
            and isinstance(value_expr, dict)
            and value_expr.get("kind") == "fixed"
        ):
            return effect
    return None


def _select_blocked_dynamic_value_effect(ir: CanonicalIR) -> EffectIR | None:
    for effect in sorted(ir.effects, key=lambda item: (item.opcode, item.source.source_path, item.effect_id)):
        if effect.opcode not in DYNAMIC_VALUE_OPCODES:
            continue
        if effect.coverage_status == "executable" or not _is_mainline_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str):
            return effect
    return None


def _dynamic_value_store_case(
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
    effect: EffectIR | None,
) -> dict[str, Any]:
    if effect is None:
        return {"effect": None, "transition": None, "error": "missing executable mainline SetDynamicValue effect"}
    result = _execute_effect(registry, base_state, effect, command)
    after = MutationReducer().apply_all(base_state, result.mutations)
    target_id = _target_id_for_effect(effect, command)
    transition = _effect_transition(
        command=command,
        before_state=base_state,
        after_state=after,
        effect=effect,
        effect_result=result,
        target_id=target_id,
        coverage_id="v0_216_dynamic_value_store",
    )
    return {
        "effect": effect,
        "before_state": base_state,
        "after_state": after,
        "result": result,
        "transition": transition,
        "selection": {
            "selection_mode": "structured_predicate",
            "opcode": effect.opcode,
            "mainline_source": _is_mainline_source(effect.source.source_path),
            "coverage_status": effect.coverage_status,
            "payload_shape": _payload_shape(effect),
            "source_trace": effect.source.to_json(),
        },
    }


def _execute_effect(registry: EffectRegistry, state: BattleState, effect: EffectIR, command: ActionCommand):
    return registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:dynamic_value_store:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
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


def _numeric_evaluator_cases(case: dict[str, Any]) -> dict[str, Any]:
    evaluator = RuleEvaluator()
    cases = {
        "unbound_dynamic_hash": evaluator.evaluate_numeric(
            {"kind": "dynamic_hash", "hash": "validation_unbound_dynamic_key"},
            NumericEvaluationContext(),
        ).to_json(),
        "unsupported_postfix": evaluator.evaluate_numeric(
            {"kind": "postfix_expr", "reason": "unsupported_postfix_expr", "raw": {"OpCodes": "AQABAQIR"}},
            NumericEvaluationContext(),
        ).to_json(),
    }
    after_state = case.get("after_state")
    effect = case.get("effect")
    if isinstance(after_state, BattleState) and isinstance(effect, EffectIR):
        standard = effect.payload.get("standard")
        value_name = standard.get("value_name") if isinstance(standard, dict) else None
        store = store_from_state(after_state)
        if isinstance(value_name, str) and value_name:
            cases["store_bound_dynamic_key"] = evaluator.evaluate_numeric(
                {"kind": "dynamic_hash", "hash": value_name},
                NumericEvaluationContext(binding_sources=(binding_source_from_store(store),)),
            ).to_json()
    return cases


def _dynamic_value_store_checks(case: dict[str, Any]) -> dict[str, object]:
    transition = case.get("transition")
    after_state = case.get("after_state")
    effect = case.get("effect")
    records = _records_of_type(transition, "dynamic_value_store")
    store = store_from_state(after_state) if isinstance(after_state, BattleState) else {}
    entries = store.get("entries") if isinstance(store, dict) else {}
    standard = effect.payload.get("standard") if isinstance(effect, EffectIR) else {}
    value_name = standard.get("value_name") if isinstance(standard, dict) else None
    checks = {
        "real_effect_selected": isinstance(effect, EffectIR) and effect.opcode == "SetDynamicValue",
        "mutation_exists": bool(transition is not None and transition.transaction.mutations),
        "record_exists": bool(records),
        "store_has_entry": isinstance(entries, dict) and bool(entries),
        "store_indexed_by_name": isinstance(value_name, str)
        and isinstance(store.get("by_name"), dict)
        and value_name in store["by_name"],
        "mutation_path_is_global_store": bool(
            transition is not None
            and any(tuple(mutation.path) == ("global_flags", "dynamic_value_store") for mutation in transition.transaction.mutations)
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "records": records, "store": store}


def _numeric_evaluator_checks(cases: dict[str, Any]) -> dict[str, object]:
    checks = {
        "store_bound_dynamic_key_ok": cases.get("store_bound_dynamic_key", {}).get("ok") is True,
        "store_binding_source_recorded": cases.get("store_bound_dynamic_key", {}).get("bindings", {}).get("source_type")
        == "dynamic_value_store",
        "unbound_dynamic_hash_blocked": cases["unbound_dynamic_hash"].get("ok") is False
        and "dynamic_hash_unbound" in str(cases["unbound_dynamic_hash"].get("blocked_reason")),
        "unsupported_postfix_blocked": cases["unsupported_postfix"].get("ok") is False
        and cases["unsupported_postfix"].get("blocked_reason") == "unsupported_postfix_expr",
    }
    return {"ok": all(checks.values()), "checks": checks, "cases": cases}


def _blocked_dynamic_value_checks(effect: EffectIR | None) -> dict[str, object]:
    standard = effect.payload.get("standard") if isinstance(effect, EffectIR) else None
    checks = {
        "blocked_effect_selected": isinstance(effect, EffectIR),
        "blocked_reason_present": isinstance(standard, dict) and isinstance(standard.get("blocked_reason"), str),
        "source_trace_present": isinstance(effect, EffectIR) and bool(effect.source.source_path),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "effect": effect.to_json() if isinstance(effect, EffectIR) else None,
    }


def _coverage_checks(coverage_json: dict[str, Any]) -> dict[str, object]:
    modifier_status = coverage_json.get("modifier_status", {})
    dynamic_status = modifier_status.get("dynamic_value_store", {}) if isinstance(modifier_status, dict) else {}
    set_dynamic = dynamic_status.get("set_dynamic_value", {}) if isinstance(dynamic_status, dict) else {}
    by_modifier = dynamic_status.get("set_dynamic_value_by_modifier_value", {}) if isinstance(dynamic_status, dict) else {}
    opcode_status = coverage_json.get("opcode_status", {})
    checks = {
        "set_dynamic_value_lowered": set_dynamic.get("lowered", 0) > 0,
        "set_dynamic_value_executable": set_dynamic.get("executable", 0) > 0,
        "set_dynamic_value_by_modifier_value_lowered": by_modifier.get("lowered", 0) > 0,
        "opcode_status_present": all(opcode in opcode_status for opcode in DYNAMIC_VALUE_OPCODES),
    }
    return {"ok": all(checks.values()), "checks": checks, "dynamic_value_store": dynamic_status}


def _selection_guard_checks(case: dict[str, Any]) -> dict[str, object]:
    selection = case.get("selection")
    checks = {
        "structured_predicate": isinstance(selection, dict)
        and selection.get("selection_mode") == "structured_predicate",
        "source_trace_output": isinstance(selection, dict)
        and isinstance(selection.get("source_trace"), dict),
        "payload_shape_output": isinstance(selection, dict)
        and isinstance(selection.get("payload_shape"), dict),
    }
    return {"ok": all(checks.values()), "checks": checks, "selection": selection}


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


def _records_of_type(transition, record_type: str) -> list[dict[str, Any]]:
    if transition is None or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _payload_shape(effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return {"has_standard": False}
    return {
        "has_standard": True,
        "target_alias": standard.get("target_alias"),
        "value_name_present": isinstance(standard.get("value_name"), str) and bool(standard.get("value_name")),
        "value_expr_kind": standard.get("value_expr", {}).get("kind") if isinstance(standard.get("value_expr"), dict) else None,
    }


def _target_id_for_effect(effect: EffectIR, command: ActionCommand) -> str:
    standard = effect.payload.get("standard")
    alias = standard.get("target_alias") if isinstance(standard, dict) else None
    if alias in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
        return command.actor_id
    return command.actor_id


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _is_mainline_source(source_path: str) -> bool:
    return not source_path.startswith(NON_MAINLINE_PREFIXES)


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif hasattr(value, "to_json"):
            encoded[key] = value.to_json()
        elif key == "result":
            encoded[key] = _effect_result_json(value)
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
