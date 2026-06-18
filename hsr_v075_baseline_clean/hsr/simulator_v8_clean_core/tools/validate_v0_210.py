from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
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
from ..rules.ir import CanonicalIR, EffectIR, RuleEntity
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_209 import _damage_emission_command


VALIDATION_VERSION = "v0_210"
SUPPORTED_ADD_MODIFIER_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
SUPPORTED_STACK_PROPERTIES = {
    "AllDamageTypeAddedRatio",
    "PhysicalAddedRatio",
    "FireAddedRatio",
    "IceAddedRatio",
    "ThunderAddedRatio",
    "WindAddedRatio",
    "QuantumAddedRatio",
    "ImaginaryAddedRatio",
    "PhysicalResistanceDelta",
    "FireResistanceDelta",
    "IceResistanceDelta",
    "ThunderResistanceDelta",
    "WindResistanceDelta",
    "QuantumResistanceDelta",
    "ImaginaryResistanceDelta",
    "AllResistanceDelta",
    "DamageTakenRatio",
    "AllDamageTakenRatio",
    "DefenceReduce",
    "DefenseReduce",
    "DefenceReduction",
    "DefenseReduction",
    "DefenceIgnore",
    "DefenseIgnore",
}


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
        write_json(output_dir / "canonical_ir_v0_210.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_210.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_210.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_210.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    formula_state = _formula_test_state(build_result.state)
    base_command = _with_crit_mode(_damage_emission_command(ir, rules, build_result.commands[0]), "crit")

    status_effect = _select_status_damage_bonus_effect(ir, rules)
    unsupported_alias_effect = _select_unsupported_target_alias_effect(ir, rules)
    unsupported_property_effect = _select_unsupported_property_effect(ir, rules)
    unsupported_formula_effect = _select_unsupported_formula_effect(ir, rules)

    reducer = MutationReducer()
    status_transition = None
    status_after = formula_state
    effect_result = None
    if status_effect is not None:
        registry = EffectRegistry(StatusSystem(rules))
        effect_result = registry.execute(
            status_effect,
            EffectExecutionContext(
                state=formula_state,
                caster_id=base_command.actor_id,
                source_id=f"validation:{VALIDATION_VERSION}:{status_effect.effect_id}",
                owner_id=base_command.actor_id,
                param_entity_id=base_command.actor_id,
                current_action_target_id=base_command.target_ids[0] if base_command.target_ids else None,
            ),
        )
        status_after = reducer.apply_all(formula_state, effect_result.mutations)
        status_transition = _status_transition(
            command=base_command,
            before_state=formula_state,
            after_state=status_after,
            effect=status_effect,
            effect_result=effect_result,
        )

    executor = CombatExecutor(rules)
    baseline_after, baseline_transition = executor.execute(base_command, formula_state)
    action_after, action_transition = executor.execute(base_command, status_after)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    snapshot_result = snapshot_validator.validate(status_after.snapshot())
    status_contract = (
        transition_validator.validate(status_transition)
        if status_transition is not None
        else None
    )
    action_contract = transition_validator.validate(action_transition)
    status_traceability = (
        settlement_validator.validate(status_transition.transaction.settlement, status_transition.transaction.mutations)
        if status_transition is not None
        else None
    )
    action_traceability = settlement_validator.validate(action_transition.transaction.settlement, action_transition.transaction.mutations)
    status_replay = (
        reducer.replay_snapshot(formula_state, status_transition.transaction.mutations, status_after.snapshot().to_json())
        if status_transition is not None
        else None
    )
    action_replay = reducer.replay_snapshot(status_after, action_transition.transaction.mutations, action_after.snapshot().to_json())

    unsupported_results = _unsupported_checks(
        rules,
        formula_state,
        base_command,
        unsupported_alias_effect,
        unsupported_property_effect,
        unsupported_formula_effect,
    )
    checks = {
        "modifier_coverage": _modifier_coverage_checks(coverage.to_json(), ir),
        "add_modifier_selection": _effect_selection_checks(status_effect, rules),
        "add_modifier_runtime": _add_modifier_runtime_checks(effect_result, status_after),
        "status_snapshot_sync": _status_snapshot_sync_checks(status_after, effect_result),
        "direct_damage_status_ledger": _status_ledger_checks(
            baseline_transition,
            action_transition,
            baseline_after,
            action_after,
        ),
        "unsupported_paths": unsupported_results,
        "damage_semantics_regression": _damage_semantics_regression_checks(action_transition),
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
                status_contract.ok if status_contract else False,
                action_contract.ok,
                status_traceability.ok if status_traceability else False,
                action_traceability.ok,
                status_replay.ok if status_replay else False,
                action_replay.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_entities": len(ir.entities),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_effects": len(ir.effects),
                "ir_formulas": len(ir.formulas),
                "sampled": ir.metadata.get("sampled", {}),
                "modifier_status": coverage.to_json().get("modifier_status", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "status_transition_contract": status_contract.to_json() if status_contract else {"ok": False, "errors": ["missing status transition"]},
        "action_transition_contract": action_contract.to_json(),
        "status_settlement_traceability": status_traceability.to_json() if status_traceability else {"ok": False, "errors": ["missing status transition"]},
        "action_settlement_traceability": action_traceability.to_json(),
        "status_replay": _replay_json(status_replay),
        "action_replay": _replay_json(action_replay),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_210.json", result)
    if status_transition is not None:
        write_json(output_dir / "sample_add_modifier_status_transition_v0_210.json", status_transition.to_json())
    write_json(output_dir / "sample_executor_transition_with_status_v0_210.json", action_transition.to_json())
    write_json(output_dir / "sample_executor_transition_without_status_v0_210.json", baseline_transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 TBGD modifier status pipeline.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_210"))
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


def _formula_test_state(state: BattleState) -> BattleState:
    actor = state.units["ally:saber"]
    target = state.units["enemy:target"]
    actor = replace(
        actor,
        resources={
            **actor.resources,
            "critical_chance": 0.5,
            "critical_damage": 1.0,
            "damage_added_ratio": 0.2,
            "Wind_damage_added_ratio": 0.1,
            "def_ignore": 0.1,
            "Wind_res_pen": 0.05,
            "all_res_pen": 0.02,
        },
    )
    target = replace(
        target,
        toughness=60.0,
        max_toughness=60.0,
        resources={
            **target.resources,
            "def_reduction": 0.2,
            "Wind_resistance": 0.2,
            "damage_taken_ratio": 0.15,
            "damage_reduction": 0.1,
        },
        flags={**target.flags, "broken": False},
    )
    return replace(state, units={**state.units, actor.unit_id: actor, target.unit_id: target})


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    entity_type_counts: dict[str, int] = {}
    effect_opcode_counts: dict[str, int] = {}
    for entity in ir.entities:
        entity_type_counts[entity.entity_type] = entity_type_counts.get(entity.entity_type, 0) + 1
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
        "entity_type_counts": dict(sorted(entity_type_counts.items())),
        "effect_opcode_counts": dict(sorted(effect_opcode_counts.items())),
        "sample_modifier_definitions": [
            entity.to_json()
            for entity in ir.entities
            if entity.entity_type == "modifier_definition"
        ][:5],
        "sample_add_modifier_effects": [
            effect.to_json()
            for effect in ir.effects
            if effect.opcode == "AddModifier"
        ][:5],
    }


def _select_status_damage_bonus_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard:
            continue
        if standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        definition = rules.modifier_definition(str(standard.get("modifier_name") or ""))
        if definition is None:
            continue
        for item in _stack_properties(definition):
            if item.get("property") != "AllDamageTypeAddedRatio":
                continue
            value = _fixed_value(item.get("value_expr"))
            if value is not None and value > 0:
                return effect
    return None


def _select_unsupported_target_alias_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard:
            continue
        if standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        if rules.modifier_definition(str(standard.get("modifier_name") or "")) is not None:
            return effect
    return None


def _select_unsupported_property_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard or standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        definition = rules.modifier_definition(str(standard.get("modifier_name") or ""))
        if definition is None:
            continue
        if any(str(item.get("property") or "") not in SUPPORTED_STACK_PROPERTIES for item in _stack_properties(definition)):
            return effect
    return None


def _select_unsupported_formula_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard or standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        definition = rules.modifier_definition(str(standard.get("modifier_name") or ""))
        if definition is None:
            continue
        for item in _stack_properties(definition):
            if str(item.get("property") or "") not in SUPPORTED_STACK_PROPERTIES:
                continue
            expr = item.get("value_expr")
            if isinstance(expr, dict) and expr.get("kind") in {"dynamic_hash", "unsupported_postfix"}:
                return effect
    return None


def _standard_payload(effect: EffectIR) -> dict[str, Any] | None:
    if effect.opcode != "AddModifier":
        return None
    standard = effect.payload.get("standard")
    return standard if isinstance(standard, dict) else None


def _stack_properties(definition: RuleEntity) -> list[dict[str, Any]]:
    items = definition.fields.get("stack_properties")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _fixed_value(expr: object) -> float | None:
    if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
        return float(expr["value"])
    return None


def _status_transition(
    *,
    command: ActionCommand,
    before_state: BattleState,
    after_state: BattleState,
    effect: EffectIR,
    effect_result,
) -> BattleTransition:
    target_id = _status_owner_id(effect_result) or command.actor_id
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=(target_id,),
        records=tuple(effect_result.records),
    )
    transaction = ActionTransaction(
        command=replace(command, metadata={**command.metadata, "effect_id": effect.effect_id}),
        before=before_state.snapshot(),
        events=(
            GameEvent(
                event_type="effect.add_modifier",
                source_id=command.actor_id,
                target_id=target_id,
                event_id=f"event:{before_state.event_index}:v0_210_add_modifier",
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
            reason="add_modifier_target_alias",
            source="status_system",
            metadata={"effect_id": effect.effect_id},
        ),
        coverage={
            "executor": "v0_210_add_modifier_status",
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "mutation_count": len(effect_result.mutations),
            "unsupported": list(effect_result.unsupported),
        },
    )


def _modifier_coverage_checks(coverage_json: dict[str, Any], ir: CanonicalIR) -> dict[str, object]:
    modifier_status = coverage_json.get("modifier_status", {})
    add_modifier = modifier_status.get("add_modifier", {}) if isinstance(modifier_status, dict) else {}
    modifier_entities = [entity for entity in ir.entities if entity.entity_type == "modifier_definition"]
    checks = {
        "has_modifier_definitions": int(modifier_status.get("modifier_definitions", 0)) > 0 if isinstance(modifier_status, dict) else False,
        "has_global_modifier_definitions": int(modifier_status.get("global_modifier_definitions", 0)) > 0 if isinstance(modifier_status, dict) else False,
        "has_stack_property_definitions": int(modifier_status.get("definitions_with_stack_properties", 0)) > 0 if isinstance(modifier_status, dict) else False,
        "add_modifier_lowered": int(add_modifier.get("lowered", 0)) > 0,
        "add_modifier_executable": int(add_modifier.get("executable", 0)) > 0,
        "entities_include_modifier_definition": bool(modifier_entities),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "modifier_status": modifier_status,
        "sample_modifier_definition": modifier_entities[0].to_json() if modifier_entities else None,
    }


def _effect_selection_checks(effect: EffectIR | None, rules: RuleBook) -> dict[str, object]:
    if effect is None:
        return {"ok": False, "checks": {"found_real_add_modifier": False}}
    standard = _standard_payload(effect) or {}
    definition = rules.modifier_definition(str(standard.get("modifier_name") or ""))
    checks = {
        "found_real_add_modifier": effect.opcode == "AddModifier",
        "has_standard_payload": bool(standard),
        "target_alias_supported": standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES,
        "modifier_definition_exists": definition is not None,
        "definition_has_all_damage_ratio": bool(definition)
        and any(item.get("property") == "AllDamageTypeAddedRatio" for item in _stack_properties(definition)),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "effect": effect.to_json(),
        "modifier_definition": definition.to_json() if definition else None,
    }


def _add_modifier_runtime_checks(effect_result, status_after: BattleState) -> dict[str, object]:
    status_instance = _status_instance(effect_result)
    owner_id = str(status_instance.get("owner_id") or "") if status_instance else ""
    unit = status_after.units.get(owner_id)
    checks = {
        "effect_result_has_mutations": bool(effect_result and effect_result.mutations),
        "has_status_instance": bool(status_instance),
        "has_runtime_modifiers": bool(status_instance and status_instance.get("modifiers")),
        "status_mutation_present": bool(effect_result)
        and any(tuple(mutation.path[-1:]) == ("statuses",) for mutation in effect_result.mutations),
        "status_details_mutation_present": bool(effect_result)
        and any(tuple(mutation.path[-2:]) == ("flags", "status_details") for mutation in effect_result.mutations),
        "unit_contains_status_id": bool(unit and status_instance and status_instance.get("status_id") in unit.statuses),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "status_instance": status_instance,
        "records": list(effect_result.records) if effect_result else [],
        "unsupported": list(effect_result.unsupported) if effect_result else [],
    }


def _status_snapshot_sync_checks(status_after: BattleState, effect_result) -> dict[str, object]:
    status_instance = _status_instance(effect_result)
    if not status_instance:
        return {"ok": False, "checks": {"has_status_instance": False}}
    owner_id = str(status_instance.get("owner_id") or "")
    unit_snapshot = status_after.snapshot().to_json()["units"].get(owner_id, {})
    details = unit_snapshot.get("status_details", []) if isinstance(unit_snapshot, dict) else []
    detail_ids = {
        item.get("instance_id")
        for item in details
        if isinstance(item, dict)
    }
    checks = {
        "status_id_in_snapshot_statuses": status_instance.get("status_id") in unit_snapshot.get("statuses", []),
        "status_instance_in_snapshot_details": status_instance.get("instance_id") in detail_ids,
        "status_details_has_modifiers": any(
            isinstance(item, dict) and item.get("instance_id") == status_instance.get("instance_id") and item.get("modifiers")
            for item in details
        ),
    }
    return {"ok": all(checks.values()), "checks": checks, "unit_snapshot": unit_snapshot}


def _status_ledger_checks(baseline_transition, action_transition, baseline_after, action_after) -> dict[str, object]:
    baseline_damage = _final_damage(baseline_transition)
    status_damage = _final_damage(action_transition)
    terms = _modifier_terms(action_transition)
    status_terms = [
        term for term in terms if term.get("source_type") in {"actor.status", "target.status"}
    ]
    checks = {
        "has_status_source_term": bool(status_terms),
        "has_damage_bonus_status_term": any(term.get("bucket") == "damage_bonus" for term in status_terms),
        "status_damage_greater_than_baseline": status_damage > baseline_damage,
        "status_after_hp_not_higher_than_baseline": action_after.units["enemy:target"].hp <= baseline_after.units["enemy:target"].hp,
        "status_terms_have_instance_ids": all(str(term.get("source_id", "")).startswith("status:") for term in status_terms),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "baseline_final_damage": baseline_damage,
        "status_final_damage": status_damage,
        "status_terms": status_terms,
    }


def _unsupported_checks(
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
    unsupported_alias_effect: EffectIR | None,
    unsupported_property_effect: EffectIR | None,
    unsupported_formula_effect: EffectIR | None,
) -> dict[str, object]:
    registry = EffectRegistry(StatusSystem(rules))
    context = EffectExecutionContext(
        state=state,
        caster_id=command.actor_id,
        source_id=f"validation:{VALIDATION_VERSION}:unsupported",
        owner_id=command.actor_id,
        param_entity_id=command.actor_id,
        current_action_target_id=command.target_ids[0] if command.target_ids else None,
    )
    alias_result = registry.execute(unsupported_alias_effect, context) if unsupported_alias_effect else None
    property_result = registry.execute(unsupported_property_effect, context) if unsupported_property_effect else None
    formula_result = registry.execute(unsupported_formula_effect, context) if unsupported_formula_effect else None
    checks = {
        "found_unsupported_target_alias": unsupported_alias_effect is not None,
        "target_alias_has_reason": bool(alias_result and _contains_reason(alias_result.unsupported, "unsupported_or_missing_target_alias")),
        "target_alias_process_only_record": bool(alias_result and alias_result.records and alias_result.records[0].get("process_only")),
        "found_unsupported_property": unsupported_property_effect is not None,
        "property_has_reason": bool(property_result and _contains_reason(property_result.unsupported, "unsupported_property")),
        "found_unsupported_formula": unsupported_formula_effect is not None,
        "formula_has_reason": bool(formula_result and _contains_reason(formula_result.unsupported, "unsupported_formula")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "effects": {
            "unsupported_alias": unsupported_alias_effect.to_json() if unsupported_alias_effect else None,
            "unsupported_property": unsupported_property_effect.to_json() if unsupported_property_effect else None,
            "unsupported_formula": unsupported_formula_effect.to_json() if unsupported_formula_effect else None,
        },
        "results": {
            "unsupported_alias": _effect_result_json(alias_result),
            "unsupported_property": _effect_result_json(property_result),
            "unsupported_formula": _effect_result_json(formula_result),
        },
    }


def _damage_semantics_regression_checks(action_transition) -> dict[str, object]:
    record = _damage_record(action_transition)
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    ledger = payload.get("modifier_ledger", {}) if isinstance(payload, dict) else {}
    checks = {
        "direct_damage_has_ledger": isinstance(ledger, dict) and ledger.get("formula_family") == "direct",
        "direct_damage_not_bypassing": payload.get("bypasses_normal_multipliers") is False,
        "normal_terms_present": bool(payload.get("normal_multiplier_terms")),
        "no_follow_up_family": payload.get("damage_formula_family") != "follow_up",
    }
    return {"ok": all(checks.values()), "checks": checks}


def _status_owner_id(effect_result) -> str | None:
    status_instance = _status_instance(effect_result)
    if not status_instance:
        return None
    owner_id = status_instance.get("owner_id")
    return str(owner_id) if isinstance(owner_id, str) else None


def _status_instance(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    for record in effect_result.records:
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        status_instance = payload.get("status_instance") if isinstance(payload, dict) else None
        if isinstance(status_instance, dict):
            return status_instance
    return None


def _contains_reason(reasons: tuple[str, ...], needle: str) -> bool:
    return any(needle in reason for reason in reasons)


def _effect_result_json(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    return {
        "events": [event.to_json() for event in effect_result.events],
        "mutations": [mutation.to_json() for mutation in effect_result.mutations],
        "records": list(effect_result.records),
        "unsupported": list(effect_result.unsupported),
    }


def _damage_record(transition) -> dict[str, Any]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    for record in records:
        if record.get("record_type") == "damage":
            return record
    return {}


def _formula_result(transition) -> dict[str, Any]:
    record = _damage_record(transition)
    payload = record.get("payload", {})
    formula = payload.get("formula_result", {}) if isinstance(payload, dict) else {}
    return formula if isinstance(formula, dict) else {}


def _final_damage(transition) -> float:
    formula = _formula_result(transition)
    value = formula.get("final_damage")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _modifier_terms(transition) -> list[dict[str, Any]]:
    ledger = _formula_result(transition).get("modifier_ledger", {})
    terms = ledger.get("applied_terms", []) if isinstance(ledger, dict) else []
    return [term for term in terms if isinstance(term, dict)]


def _replay_json(replay) -> dict[str, Any]:
    if replay is None:
        return {"ok": False, "errors": ["missing replay"]}
    return {"ok": replay.ok, "errors": list(replay.errors)}


if __name__ == "__main__":
    raise SystemExit(main())
