from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR, ConditionIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.dynamic_values import binding_source_from_store, store_from_state, upsert_dynamic_value
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


VALIDATION_VERSION = "v0_217"
NON_MAINLINE_PREFIXES = (
    "Config/ConfigAbility/Activity",
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
    "Config/ConfigAbility/Avatar/Avatar_AetherDivide",
    "Config/ConfigAbility/Monster/Monster_AetherDivide",
)
CONDITION_OPCODES = (
    "ByCurrentSkillType",
    "ByAttackType",
    "ByTargetTeam",
    "ByIsContainModifier",
    "ByCompareHPRatio",
    "ByCompareDynamicValue",
    "ByCompareModifierValue",
    "ByCompareTarget",
    "ByAnd",
    "ByAny",
    "ByNot",
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
        write_json(output_dir / "canonical_ir_v0_217.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_217.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_217.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_217.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = build_result.state
    command = build_result.commands[0]

    condition_cases = _condition_cases(ir, rules, base_state, command)
    blocked_case = _blocked_condition_case(ir, base_state, command)
    formula_state = _formula_test_state(base_state)
    status_ledger_transition = _status_ledger_transition(ir, rules, formula_state, _with_crit_mode(command, "crit"))
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, command)

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    checks = {
        "condition_evaluator": _condition_case_checks(condition_cases),
        "condition_blocked": _blocked_condition_checks(blocked_case),
        "condition_coverage": _coverage_checks(coverage.to_json()),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
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
                "ir_conditions": len(ir.conditions),
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
    write_json(output_dir / "validation_summary_v0_217.json", result)
    write_json(output_dir / "sample_condition_cases_v0_217.json", _condition_cases_json(condition_cases))
    write_json(output_dir / "sample_blocked_condition_case_v0_217.json", blocked_case)
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_217.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_217.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 structured condition evaluation spine.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_217"))
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
    condition_opcode_counts: dict[str, int] = {}
    condition_status_counts: dict[str, dict[str, int]] = {}
    for condition in ir.conditions:
        condition_opcode_counts[condition.opcode] = condition_opcode_counts.get(condition.opcode, 0) + 1
        condition_status_counts.setdefault(condition.opcode, {})
        condition_status_counts[condition.opcode][condition.coverage_status] = (
            condition_status_counts[condition.opcode].get(condition.coverage_status, 0) + 1
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
        "condition_opcode_counts": dict(sorted(condition_opcode_counts.items())),
        "condition_status_counts": dict(sorted(condition_status_counts.items())),
    }


def _condition_cases(
    ir: CanonicalIR,
    rules: RuleBook,
    base_state: BattleState,
    command: ActionCommand,
) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    definition = rules.require_action_definition(command.action_id, command.action_level)
    for opcode in CONDITION_OPCODES:
        condition = _select_condition(ir, opcode)
        if condition is None:
            cases[opcode] = {"condition": None, "result": None, "error": "missing executable mainline condition"}
            continue
        state, context = _condition_context(base_state, command, definition.to_json(), condition)
        result = RuleEvaluator().evaluate_condition_result(condition, context)
        cases[opcode] = {
            "condition": condition,
            "state": state,
            "result": result.to_json(),
            "selection": {
                "selection_mode": "structured_predicate",
                "opcode": opcode,
                "coverage_status": condition.coverage_status,
                "source_trace": condition.source.to_json(),
                "payload_keys": sorted(condition.payload),
            },
        }
    return cases


def _blocked_condition_case(ir: CanonicalIR, base_state: BattleState, command: ActionCommand) -> dict[str, Any]:
    condition = _select_blocked_condition(ir)
    if condition is None:
        return {"condition": None, "result": None, "error": "missing blocked mainline condition"}
    action_payload = {
        "skill_effect": "Unknown",
        "attack_type": "Unknown",
        "damage_kind": "unknown",
        "damage_formula_family": "unknown",
    }
    _, context = _condition_context(base_state, command, action_payload, condition)
    result = RuleEvaluator().evaluate_condition_result(condition, context)
    return {"condition": condition.to_json(), "result": result.to_json()}


def _condition_context(
    base_state: BattleState,
    command: ActionCommand,
    action_definition: dict[str, Any],
    condition: ConditionIR,
) -> tuple[BattleState, EvaluationContext]:
    primary_target = command.target_ids[0] if command.target_ids else command.actor_id
    state = _state_with_condition_inputs(base_state, command, primary_target, condition)
    owner_id = _target_id(condition.payload.get("TargetType"), command, primary_target) or command.actor_id
    return state, EvaluationContext(
        state=state,
        actor_id=command.actor_id,
        target_id=primary_target,
        owner_id=owner_id,
        param_entity_id=primary_target,
        current_action_target_id=primary_target,
        status_detail=_first_status_detail(state, owner_id),
        event_payload={
            "SkillType": action_definition.get("skill_effect"),
            "AttackType": action_definition.get("attack_type"),
            "attack_type": action_definition.get("attack_type"),
            "damage_kind": action_definition.get("damage_kind"),
            "damage_formula_family": action_definition.get("damage_formula_family"),
            "action_id": command.action_id,
            "action_level": command.action_level,
            "actor_id": command.actor_id,
            "primary_target_id": primary_target,
        },
        binding_sources=(binding_source_from_store(store_from_state(state)),),
    )


def _state_with_condition_inputs(
    state: BattleState,
    command: ActionCommand,
    primary_target: str,
    condition: ConditionIR,
) -> BattleState:
    payload = condition.payload
    units = dict(state.units)
    dynamic_store = store_from_state(state)
    modifier_names = {condition.source.raw_id, *_modifier_names(payload)}
    target_ids = {
        command.actor_id,
        primary_target,
        _target_id(payload.get("TargetType"), command, primary_target) or command.actor_id,
    }
    for target_id in target_ids:
        unit = units.get(target_id)
        if unit is None:
            continue
        details = list(unit.flags.get("status_details", ())) if isinstance(unit.flags.get("status_details", ()), (list, tuple)) else []
        existing = {str(item.get("modifier_name")) for item in details if isinstance(item, dict)}
        for modifier_name in modifier_names:
            if modifier_name in existing:
                continue
            details.append(_status_detail(target_id, modifier_name))
        units[target_id] = replace(unit, flags={**unit.flags, "status_details": details})
    for key in _dynamic_keys(payload):
        dynamic_store = upsert_dynamic_value(
            dynamic_store,
            scope="condition_validation",
            owner_id=command.actor_id,
            value=1.0,
            value_name=key,
            source_trace={"validation": VALIDATION_VERSION, "condition_payload": payload},
        )
    return replace(state, units=units, global_flags={**state.global_flags, "dynamic_value_store": dynamic_store})


def _status_detail(owner_id: str, modifier_name: str) -> dict[str, Any]:
    return {
        "instance_id": f"validation:{VALIDATION_VERSION}:{owner_id}:{modifier_name}",
        "status_id": f"modifier:{modifier_name}",
        "modifier_name": modifier_name,
        "owner_id": owner_id,
        "source_id": f"validation:{VALIDATION_VERSION}",
        "caster_id": owner_id,
        "stacks": 1,
        "duration": 1.0,
        "remaining_duration": 1.0,
        "dynamic_values": {},
        "source_trace": {"validation": VALIDATION_VERSION, "modifier_name": modifier_name},
        "modifiers": [],
        "trigger_ids_by_event": {},
        "unsupported": [],
        "lifecycle_state": "active",
    }


def _select_condition(ir: CanonicalIR, opcode: str) -> ConditionIR | None:
    for condition in sorted(ir.conditions, key=lambda item: (item.source.source_path, item.condition_id)):
        if condition.opcode != opcode or condition.coverage_status != "executable":
            continue
        if not _is_mainline_source(condition.source.source_path):
            continue
        if opcode in {"ByCompareDynamicValue", "ByCompareModifierValue"} and not _has_fixed_compare_value(condition.payload):
            continue
        return condition
    return None


def _select_blocked_condition(ir: CanonicalIR) -> ConditionIR | None:
    for condition in sorted(ir.conditions, key=lambda item: (item.source.source_path, item.condition_id)):
        if condition.coverage_status == "executable":
            continue
        if not _is_mainline_source(condition.source.source_path):
            continue
        return condition
    return None


def _has_fixed_compare_value(payload: dict[str, Any]) -> bool:
    value = payload.get("CompareValue")
    return isinstance(value, dict) and isinstance(value.get("FixedValue"), dict)


def _target_id(alias_value: object, command: ActionCommand, primary_target: str) -> str | None:
    alias = _target_alias(alias_value)
    if alias == "Caster":
        return command.actor_id
    if alias == "ModifierOwnerEntity":
        return command.actor_id
    if alias in {"ParamEntity", "CurrentActionTarget"}:
        return primary_target
    return None


def _target_alias(value: object) -> str | None:
    if isinstance(value, dict):
        alias = value.get("Alias")
        if isinstance(alias, str):
            return alias
    return None


def _modifier_names(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        modifier = _value_field(value.get("ModifierName"))
        if isinstance(modifier, str) and modifier:
            names.add(modifier)
        for nested in value.values():
            names.update(_modifier_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_modifier_names(nested))
    return names


def _dynamic_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        key = _value_field(value.get("DynamicKey"))
        if isinstance(key, str) and key:
            keys.add(key)
        for nested in value.values():
            keys.update(_dynamic_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_dynamic_keys(nested))
    return keys


def _value_field(value: object) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return value.get("Value")
    return value


def _first_status_detail(state: BattleState, unit_id: str) -> dict[str, Any] | None:
    unit = state.units.get(unit_id)
    if unit is None:
        return None
    details = unit.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return None
    for detail in details:
        if isinstance(detail, dict):
            return detail
    return None


def _condition_case_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for opcode in CONDITION_OPCODES:
        case = cases.get(opcode, {})
        result = case.get("result")
        checks[f"{opcode}_selected"] = isinstance(case.get("condition"), ConditionIR)
        checks[f"{opcode}_evaluated"] = isinstance(result, dict) and result.get("ok") is True and isinstance(result.get("result"), bool)
        checks[f"{opcode}_structured_details"] = isinstance(result, dict) and isinstance(result.get("details"), dict)
        details[opcode] = _case_json(case)
    return {"ok": all(checks.values()), "checks": checks, "cases": details}


def _blocked_condition_checks(case: dict[str, Any]) -> dict[str, object]:
    result = case.get("result")
    checks = {
        "blocked_condition_selected": isinstance(case.get("condition"), dict),
        "blocked_condition_not_ok": isinstance(result, dict) and result.get("ok") is False,
        "blocked_reason_present": isinstance(result, dict) and isinstance(result.get("reason"), str) and bool(result.get("reason")),
    }
    return {"ok": all(checks.values()), "checks": checks, "case": case}


def _coverage_checks(coverage_json: dict[str, Any]) -> dict[str, object]:
    opcode_status = coverage_json.get("opcode_status", {})
    checks = {}
    details = {}
    for opcode in CONDITION_OPCODES:
        status = opcode_status.get(opcode, {})
        checks[f"{opcode}_lowered"] = status.get("lowered", 0) > 0
        checks[f"{opcode}_executable"] = status.get("executable", 0) > 0
        details[opcode] = status
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


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _is_mainline_source(source_path: str) -> bool:
    return not source_path.startswith(NON_MAINLINE_PREFIXES)


def _condition_cases_json(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: _case_json(value) for key, value in cases.items()}


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif isinstance(value, ConditionIR):
            encoded[key] = value.to_json()
        else:
            encoded[key] = value
    return encoded


def _damage_case_json(cases: dict[str, Any]) -> dict[str, Any]:
    return {name: result.to_json() for name, result in cases.items()}


if __name__ == "__main__":
    raise SystemExit(main())
