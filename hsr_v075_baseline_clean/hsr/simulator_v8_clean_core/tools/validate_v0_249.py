from __future__ import annotations

import argparse
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
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
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import ConditionIR, EffectIR
from ..rules.rulebook import RuleBook
from ..systems.dynamic_values import status_binding_sources
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_235 import _transition_checks
from .validate_v0_248 import _manual_ultimate_execution_case


VALIDATION_VERSION = "v0_249"
CONDITION_OPCODES = (
    "ByAnd",
    "ByAny",
    "ByCompareDynamicValue",
    "ByCompareModifierValue",
    "ByCompareHPRatio",
)

SPECIAL_SOURCE_MARKERS = (
    "Config/ConfigAbility/Activity",
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
    "Avatar_AetherDivide",
    "Monster_AetherDivide",
    "ElationBattle",
    "GridFight",
    "Story",
    "Level/",
    "SubLevelGraph",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    manual_ultimate = _manual_ultimate_execution_case(ir, rules)
    base_state: BattleState = manual_ultimate["initial_state"]
    command: ActionCommand = manual_ultimate["command"]

    condition_cases = _condition_cases(ir, base_state, command.actor_id)
    effect_cases = {
        "heal_new_formula": _positive_effect_case(
            rules,
            base_state,
            command,
            _select_heal_effect(ir),
            "heal_new_formula",
            dynamic_value=0.20,
            actor_overrides={"max_hp": 10000.0, "hp": 4000.0},
        ),
        "shield_new_formula": _positive_effect_case(
            rules,
            base_state,
            command,
            _select_shield_effect(ir),
            "shield_new_formula",
            dynamic_value=0.40,
            actor_overrides={"defense": 2500.0},
        ),
        "modify_sp_new_branch": _positive_effect_case(
            rules,
            replace(base_state, skill_points=1, max_skill_points=5),
            command,
            _select_modify_sp_effect(ir),
            "modify_sp_new_branch",
            dynamic_value=0.50,
        ),
        "hp_loss_floor": _positive_effect_case(
            rules,
            base_state,
            command,
            _select_hp_loss_floor_effect(ir),
            "hp_loss_floor",
            dynamic_value=0.333,
            actor_overrides={"max_hp": 1001.0, "hp": 777.0},
        ),
    }
    negative_cases = _negative_effect_cases(rules, base_state, command, effect_cases)
    actionability = _actionability_matrix(manual_ultimate, condition_cases, effect_cases, negative_cases, rules)
    checks = {
        "ultimate_energy_cost": _ultimate_energy_checks(manual_ultimate, rules),
        "condition_vm_common": _condition_checks(condition_cases),
        "effect_positive_cases": _effect_positive_checks(effect_cases),
        "effect_negative_cases": _negative_checks(negative_cases),
        "actionability_matrix": _actionability_checks(actionability),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "conditions": "mainline executable ConditionIR selected by opcode and source_mode; no character/action/file/hash fixed selector",
                "effects": "mainline executable EffectIR selected by opcode, formula family, standard payload and coverage_status",
                "ultimate": "manual battle input request, but action/resource execution resolves through Canonical IR and ResourceRuleIR",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "samples": {
            "selected_conditions": {name: case["condition"].to_json() for name, case in condition_cases.items()},
            "selected_effects": {name: case["effect"].to_json() for name, case in effect_cases.items()},
            "manual_ultimate": {
                "selected_action": manual_ultimate["selected_action"],
                "energy_mutation": _ultimate_energy_mutation_json(manual_ultimate),
            },
        },
        "source_audits": {
            "ultimate_drain": manual_ultimate["drain_source_audit"],
            "effects": {name: case["source_audit"] for name, case in effect_cases.items()},
        },
        "actionability_matrix": actionability,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_249.json", result)
    write_json(output_dir / "actionability_matrix_v0_249.json", actionability)
    write_json(output_dir / "sample_manual_ultimate_energy_transition_v0_249.json", manual_ultimate["drain_transition"])
    write_json(
        output_dir / "sample_effect_transitions_v0_249.json",
        {name: case["transition"].to_json() for name, case in effect_cases.items()},
    )
    write_json(output_dir / "sample_condition_cases_v0_249.json", _condition_cases_json(condition_cases))
    write_json(output_dir / "sample_negative_cases_v0_249.json", negative_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_249 immediate fix closure.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _condition_cases(ir, base_state: BattleState, actor_id: str) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    evaluator = RuleEvaluator()
    for opcode in CONDITION_OPCODES:
        condition = _select_condition(ir, opcode)
        state, status_detail = _state_for_condition(base_state, actor_id, condition)
        context = EvaluationContext(
            state=state,
            actor_id=actor_id,
            target_id=actor_id,
            owner_id=actor_id,
            param_entity_id=actor_id,
            current_action_target_id=actor_id,
            status_detail=status_detail,
            event_payload={
                "SkillType": "Skill",
                "AttackType": "Ultra",
                "attack_type": "Ultra",
                "action_id": "validation:v0_249",
                "action_level": 1,
                "actor_id": actor_id,
                "primary_target_id": actor_id,
            },
            binding_sources=status_binding_sources(state, (actor_id,)),
        )
        result = evaluator.evaluate_condition_result(condition, context)
        cases[opcode] = {
            "condition": condition,
            "result": result.to_json(),
            "state": state,
            "status_detail": status_detail,
            "selection": _selection(condition),
        }
    negative = _select_condition(ir, "ByCompareDynamicValue")
    negative_context = EvaluationContext(
        state=base_state,
        actor_id=actor_id,
        target_id=actor_id,
        owner_id=actor_id,
        param_entity_id=actor_id,
        current_action_target_id=actor_id,
        event_payload={"SkillType": "Skill", "AttackType": "Ultra"},
        binding_sources=(),
    )
    negative_result = evaluator.evaluate_condition_result(negative, negative_context)
    cases["negative_unbound_dynamic"] = {
        "condition": negative,
        "result": negative_result.to_json(),
        "selection": _selection(negative),
    }
    return cases


def _state_for_condition(
    state: BattleState,
    actor_id: str,
    condition: ConditionIR,
) -> tuple[BattleState, dict[str, Any]]:
    keys = set(_condition_dynamic_keys(condition.payload))
    hashes = set(_dynamic_hashes(condition.payload))
    modifiers = tuple(_condition_modifier_names(condition.payload))
    dynamic_values: dict[str, Any] = {key: 1.0 for key in keys}
    if hashes:
        dynamic_values["__by_hash"] = {str(key): 1.0 for key in hashes}
    detail_base = {
        "owner_id": actor_id,
        "source_trace": {
            "selection_mode": "structured_condition_binding_state",
            "condition_id": condition.condition_id,
            "condition_source": condition.source.to_json(),
        },
        "dynamic_values": dynamic_values,
        "stacks": 2,
        "remaining_duration": 2,
    }
    details: list[dict[str, Any]] = []
    for index, modifier_name in enumerate(modifiers or ("validation_condition_modifier",)):
        details.append(
            {
                **detail_base,
                "instance_id": f"validation_status:{VALIDATION_VERSION}:condition:{index}",
                "status_id": f"modifier:{modifier_name}",
                "modifier_name": modifier_name,
            }
        )
    actor = state.units[actor_id]
    actor = replace(
        actor,
        max_hp=max(actor.max_hp, 1000.0),
        hp=max(1.0, max(actor.max_hp, 1000.0) * 0.6),
        flags={**actor.flags, "status_details": tuple(details)},
        statuses=tuple(detail["status_id"] for detail in details),
    )
    return replace(state, units={**state.units, actor_id: actor}), details[0]


def _positive_effect_case(
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
    effect: EffectIR,
    suffix: str,
    *,
    dynamic_value: float,
    actor_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    actor_overrides = actor_overrides or {}
    prepared = _state_with_effect_dynamic_binding(state, command.actor_id, effect, dynamic_value, actor_overrides)
    registry = EffectRegistry(StatusSystem(rules))
    result = registry.execute(
        effect,
        EffectExecutionContext(
            state=prepared,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{suffix}:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
        ),
    )
    after = MutationReducer().apply_all(prepared, result.mutations)
    transition = _effect_transition(command, prepared, after, effect, result, command.actor_id, suffix)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = _transition_checks(transition, prepared)
    checks.update(
        {
            "source_audit": audit.ok,
            "mutation_present": bool(result.mutations),
            "unsupported_empty": not result.unsupported,
            "structured_selection": _selection(effect).get("selection_mode") == "structured_predicate",
            "mainline_source": _is_mainline_avatar_source(effect.source.source_path),
            "executable_source": effect.coverage_status == "executable",
            "dynamic_binding_not_manual": _no_manual_numeric_binding(transition),
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "effect": effect,
        "transition": transition,
        "source_audit": audit.to_json(),
        "unsupported": list(result.unsupported),
        "selection": _selection(effect),
    }


def _state_with_effect_dynamic_binding(
    state: BattleState,
    actor_id: str,
    effect: EffectIR,
    value: float,
    actor_overrides: dict[str, float],
) -> BattleState:
    standard = _standard(effect)
    hashes = set(_dynamic_hashes(standard.get("amount"))) | set(_dynamic_hashes(standard.get("delta"))) | set(_dynamic_hashes(standard.get("ratio")))
    hashes |= set(_dynamic_hashes(standard.get("percentage"))) | set(_dynamic_hashes(standard.get("shield_value"))) | set(_dynamic_hashes(standard.get("modify_value")))
    by_hash = {str(item): float(value) for item in hashes}
    digest = hashlib.sha1(effect.effect_id.encode("utf-8")).hexdigest()[:12]
    detail = {
        "instance_id": f"validation_status:{VALIDATION_VERSION}:{effect.opcode}:{digest}",
        "status_id": f"modifier:validation_{VALIDATION_VERSION}_dynamic_binding",
        "modifier_name": f"validation_{VALIDATION_VERSION}_dynamic_binding",
        "owner_id": actor_id,
        "source_trace": {
            "selection_mode": "current_battle_state_status_dynamic_binding",
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "binding_reason": "validation supplies current battle status dynamic value; rule source remains EffectIR",
        },
        "dynamic_values": {"__by_hash": by_hash},
        "stacks": 1,
        "remaining_duration": 2,
    }
    unit = state.units[actor_id]
    updates: dict[str, Any] = {}
    for key, raw in actor_overrides.items():
        if hasattr(unit, key):
            updates[key] = raw
    unit = replace(
        unit,
        **updates,
        flags={**unit.flags, "status_details": tuple([detail])},
        statuses=(str(detail["status_id"]),),
    )
    return replace(state, units={**state.units, actor_id: unit})


def _negative_effect_cases(
    rules: RuleBook,
    base_state: BattleState,
    command: ActionCommand,
    positive_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    registry = EffectRegistry(StatusSystem(rules))
    cases: dict[str, Any] = {}
    for name, positive in positive_cases.items():
        effect: EffectIR = positive["effect"]
        standard = _standard(effect)
        if not _has_dynamic_numeric(standard):
            continue
        state = _state_without_effect_binding(base_state, command.actor_id, effect)
        result = registry.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=command.actor_id,
                source_id=f"validation:{VALIDATION_VERSION}:negative:{name}:{effect.effect_id}",
                owner_id=command.actor_id,
                param_entity_id=command.actor_id,
                current_action_target_id=command.actor_id,
            ),
        )
        after = MutationReducer().apply_all(state, result.mutations)
        transition = _effect_transition(command, state, after, effect, result, command.actor_id, f"negative_{name}")
        cases[name] = {
            "effect_id": effect.effect_id,
            "opcode": effect.opcode,
            "unsupported": list(result.unsupported),
            "mutation_count": len(result.mutations),
            "snapshot_unchanged": state.snapshot().to_json() == after.snapshot().to_json(),
            "records": list(result.records),
            "transition": transition.to_json(),
        }
    return cases


def _state_without_effect_binding(state: BattleState, actor_id: str, effect: EffectIR) -> BattleState:
    unit = state.units[actor_id]
    return replace(
        state,
        units={
            **state.units,
            actor_id: replace(
                unit,
                flags={**unit.flags, "status_details": ()},
                statuses=(),
            ),
        },
    )


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


def _ultimate_energy_checks(case: dict[str, Any], rules: RuleBook) -> dict[str, Any]:
    rule = rules.default_ultimate_energy_cost_rule()
    mutation = _ultimate_energy_mutation_json(case)
    records = case["drain_transition"].get("settlement", {}).get("records", ())
    energy_records = [record for record in records if isinstance(record, dict) and record.get("record_type") == "ultimate_energy_cost"]
    checks = {
        "manual_ultimate_execution_ok": bool(case["checks"].get("ok")),
        "drain_source_audit": bool(case["drain_source_audit"].get("ok")),
        "resource_rule_present": rule.rule_kind == "ultimate_energy_cost",
        "resource_rule_engine_convention": rule.source_kind == "engine_convention",
        "energy_mutation_present": isinstance(mutation, dict),
        "energy_mutation_source": isinstance(mutation, dict) and mutation.get("source") == "combat_executor.resources",
        "energy_set_to_zero": isinstance(mutation, dict) and float(mutation.get("after", -1.0)) == 0.0,
        "energy_was_positive": isinstance(mutation, dict) and float(mutation.get("before", 0.0)) > 0.0,
        "resource_rule_id_on_mutation": isinstance(mutation, dict)
        and mutation.get("metadata", {}).get("resource_rule_id") == rule.resource_rule_id,
        "energy_record_present": bool(energy_records),
    }
    return {"ok": all(checks.values()), "checks": checks, "resource_rule": rule.to_json(), "energy_mutation": mutation}


def _condition_checks(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for opcode in CONDITION_OPCODES:
        case = cases.get(opcode, {})
        result = case.get("result", {})
        checks[f"{opcode}_selected"] = isinstance(case.get("condition"), ConditionIR)
        checks[f"{opcode}_mainline"] = _is_mainline_avatar_source(case.get("condition").source.source_path) if isinstance(case.get("condition"), ConditionIR) else False
        checks[f"{opcode}_executable"] = isinstance(case.get("condition"), ConditionIR) and case["condition"].coverage_status == "executable"
        checks[f"{opcode}_evaluation_ok"] = isinstance(result, dict) and result.get("ok") is True and isinstance(result.get("result"), bool)
    negative = cases.get("negative_unbound_dynamic", {}).get("result", {})
    checks["unbound_dynamic_condition_blocked"] = isinstance(negative, dict) and negative.get("ok") is False
    checks["unbound_dynamic_not_default_true"] = isinstance(negative, dict) and negative.get("result") is None
    checks["unbound_dynamic_reason_specific"] = isinstance(negative, dict) and "dynamic_value_blocked" in str(negative.get("reason", ""))
    return {"ok": all(checks.values()), "checks": checks}


def _effect_positive_checks(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in cases.items():
        checks[f"{name}_ok"] = bool(case.get("checks", {}).get("ok"))
        records = _records(case["transition"])
        mutation_jsons = [mutation.to_json() for mutation in case["transition"].transaction.mutations]
        details[name] = {
            "checks": case.get("checks", {}),
            "records": records,
            "mutations": mutation_jsons,
            "source_audit": case.get("source_audit", {}),
        }
    heal_record = _first_record(cases["heal_new_formula"]["transition"], "heal")
    shield_record = _first_record(cases["shield_new_formula"]["transition"], "shield")
    energy_record = _first_record(cases["modify_sp_new_branch"]["transition"], "resource_delta")
    hp_loss_record = _first_record(cases["hp_loss_floor"]["transition"], "hp_loss")
    checks["heal_new_formula_base"] = _formula_base(cases["heal_new_formula"]["transition"]) in {"caster.max_hp", "target.max_hp"}
    checks["shield_new_formula_base"] = _formula_base(cases["shield_new_formula"]["transition"]) in {
        "caster.max_hp",
        "caster.defense",
        "target.max_hp",
    }
    checks["modify_sp_new_resource_record"] = bool(energy_record) and energy_record.get("resource") == "energy"
    checks["modify_sp_new_scale_or_set"] = _sp_formula_detail(cases["modify_sp_new_branch"]["transition"]) in {"max_energy", "set"}
    checks["hp_loss_record_present"] = bool(hp_loss_record)
    checks["hp_loss_floor_policy"] = _hp_loss_rounding_policy(cases["hp_loss_floor"]["transition"]) == "floor_from_tbgd_flag"
    checks["hp_loss_no_direct_multiplier_ledger"] = _hp_loss_no_direct_ledger(cases["hp_loss_floor"]["transition"])
    checks["heal_record_present"] = bool(heal_record)
    checks["shield_record_present"] = bool(shield_record)
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _negative_checks(cases: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "negative_cases_present": bool(cases),
        "all_negative_no_mutations": all(case.get("mutation_count") == 0 for case in cases.values()),
        "all_negative_snapshot_unchanged": all(case.get("snapshot_unchanged") is True for case in cases.values()),
        "all_negative_reasons_present": all(case.get("unsupported") for case in cases.values()),
    }
    return {"ok": all(checks.values()), "checks": checks, "cases": cases}


def _actionability_matrix(
    ultimate_case: dict[str, Any],
    condition_cases: dict[str, dict[str, Any]],
    effect_cases: dict[str, dict[str, Any]],
    negative_cases: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    entries = {
        "ultimate_energy_cost": _fixed_now_entry(_ultimate_energy_checks(ultimate_case, rules)["ok"], "Manual admitted ultimate spends all actor energy through ResourceRuleIR engine convention"),
        "condition_vm_common": _fixed_now_entry(_condition_checks(condition_cases)["ok"], "ByAnd/ByAny/ByCompareDynamicValue/ByCompareModifierValue/ByCompareHPRatio are evaluated conservatively"),
        "heal_formula_current_scope": _fixed_now_entry(effect_cases["heal_new_formula"]["checks"]["ok"], "HealByTargetMaxHP/HealByHealerMaxHP current fixed/status-bound numeric scope is executable"),
        "shield_formula_current_scope": _fixed_now_entry(effect_cases["shield_new_formula"]["checks"]["ok"], "ShieldByCasterMaxHP/ShieldByCasterDefence/ShieldByTargetMaxHP current fixed/status-bound numeric scope is executable"),
        "modify_sp_new_current_scope": _fixed_now_entry(effect_cases["modify_sp_new_branch"]["checks"]["ok"], "ModifySPNew fixed/status-bound energy add/set/max-ratio current scope is executable"),
        "hp_loss_floor": _fixed_now_entry(effect_cases["hp_loss_floor"]["checks"]["ok"], "LoseHPByRatio Floor=true applies floor rounding without direct multiplier ledger"),
        "unsupported_dynamic_or_formula_negatives": _fixed_now_entry(_negative_checks(negative_cases)["ok"], "Unbound dynamic numeric paths remain blocked and do not mutate state"),
        "true_damage": _wait_entry("requires admitted executable TBGD true-damage emission/effect source"),
        "enemy_ai": _wait_entry("requires enemy action selection and AI policy admission", semantic_status="blocked"),
        "complete_actor_profile": _wait_entry("requires avatar promotion/equipment/relic/light-cone panel source chain"),
        "assistant_summon": _wait_entry("requires assistant/summon actor identity and action source admission", semantic_status="blocked"),
        "bounce_rng": _wait_entry("requires bounce target RNG source and per-hit target order admission", semantic_status="blocked"),
    }
    return {
        "ok": all(
            entry.get("current_actionability") != "fixed_now" or bool(entry.get("repaired"))
            for entry in entries.values()
        )
        and all(
            entry.get("current_actionability") != "wait_for_dependency" or bool(entry.get("blocking_dependency"))
            for entry in entries.values()
        ),
        "entries": entries,
    }


def _fixed_now_entry(repaired: bool, reason: str) -> dict[str, Any]:
    return {
        "current_actionability": "fixed_now",
        "repaired": bool(repaired),
        "semantic_status": "trusted_for_current_scope" if repaired else "needs_fix",
        "reason": reason,
        "blocking_dependency": "" if repaired else "fix_now item is not repaired",
    }


def _wait_entry(dependency: str, *, semantic_status: str = "structural_only") -> dict[str, Any]:
    return {
        "current_actionability": "wait_for_dependency",
        "repaired": False,
        "semantic_status": semantic_status,
        "reason": "not currently repairable without the named dependency",
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


def _select_condition(ir, opcode: str) -> ConditionIR:
    candidates = [
        condition
        for condition in ir.conditions
        if condition.opcode == opcode
        and condition.coverage_status == "executable"
        and _is_mainline_avatar_source(condition.source.source_path)
    ]
    if not candidates:
        raise RuntimeError(f"missing mainline executable condition sample for {opcode}")
    return sorted(candidates, key=lambda item: (item.source.source_path, item.condition_id))[0]


def _select_heal_effect(ir) -> EffectIR:
    return _select_effect(
        ir,
        lambda effect, standard: effect.opcode == "HealHP"
        and standard.get("formula_type") in {"HealByTargetMaxHP", "HealByHealerMaxHP"},
        "heal new formula",
    )


def _select_shield_effect(ir) -> EffectIR:
    return _select_effect(
        ir,
        lambda effect, standard: effect.opcode in {"Shield", "InitShield", "StackShield", "ModifyShield"}
        and standard.get("formula_type") in {"ShieldByCasterMaxHP", "ShieldByCasterDefence", "ShieldByTargetMaxHP"},
        "shield new formula",
    )


def _select_modify_sp_effect(ir) -> EffectIR:
    return _select_effect(
        ir,
        lambda effect, standard: effect.opcode == "ModifySPNew"
        and _has_dynamic_numeric(standard)
        and (
            standard.get("scale_basis") == "max_energy"
            or standard.get("operation") == "set"
            or standard.get("formula_type") in {"SetValue", "FixedSetValue", "AddMaxSPRatio", "FixedAddMaxSPRatio", "SetMaxSPRatio", "FixedSetMaxSPRatio"}
        ),
        "ModifySPNew add/set/max-ratio formula",
    )


def _select_hp_loss_floor_effect(ir) -> EffectIR:
    return _select_effect(
        ir,
        lambda effect, standard: effect.opcode == "LoseHPByRatio" and standard.get("floor") is True,
        "LoseHPByRatio floor",
    )


def _select_effect(ir, predicate, description: str) -> EffectIR:
    candidates = []
    for effect in ir.effects:
        standard = _standard(effect)
        if (
            effect.coverage_status == "executable"
            and _is_mainline_avatar_source(effect.source.source_path)
            and predicate(effect, standard)
        ):
            candidates.append(effect)
    if not candidates:
        raise RuntimeError(f"missing mainline executable effect sample for {description}")
    return sorted(candidates, key=lambda item: (item.source.source_path, item.effect_id))[0]


def _standard(effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard")
    return standard if isinstance(standard, dict) else {}


def _is_mainline_avatar_source(source_path: object) -> bool:
    if not isinstance(source_path, str):
        return False
    return source_path.startswith("Config/ConfigAbility/Avatar/") and not any(
        marker in source_path for marker in SPECIAL_SOURCE_MARKERS
    )


def _selection(node: ConditionIR | EffectIR) -> dict[str, Any]:
    return {
        "selection_mode": "structured_predicate",
        "source_path": node.source.source_path,
        "raw_type": node.source.raw_type,
        "raw_id": node.source.raw_id,
        "coverage_status": node.coverage_status,
    }


def _condition_dynamic_keys(payload: object) -> list[str]:
    keys: list[str] = []
    if isinstance(payload, dict):
        dynamic_key = payload.get("DynamicKey")
        if isinstance(dynamic_key, dict) and isinstance(dynamic_key.get("Value"), str):
            keys.append(dynamic_key["Value"])
        for value in payload.values():
            keys.extend(_condition_dynamic_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            keys.extend(_condition_dynamic_keys(item))
    return keys


def _condition_modifier_names(payload: object) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        modifier = payload.get("ModifierName")
        if isinstance(modifier, dict) and isinstance(modifier.get("Value"), str):
            names.append(modifier["Value"])
        for value in payload.values():
            names.extend(_condition_modifier_names(value))
    elif isinstance(payload, list):
        for item in payload:
            names.extend(_condition_modifier_names(item))
    return names


def _dynamic_hashes(value: object) -> list[Any]:
    hashes: list[Any] = []
    if isinstance(value, dict):
        if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
            hashes.append(value["hash"])
        raw = value.get("raw")
        if isinstance(raw, dict):
            hashes.extend(_dynamic_hashes(raw))
        postfix = value.get("PostfixExpr")
        if isinstance(postfix, dict):
            dynamic_hashes = postfix.get("DynamicHashes")
            if isinstance(dynamic_hashes, list):
                hashes.extend(dynamic_hashes)
        for nested in value.values():
            if nested is not raw and nested is not postfix:
                hashes.extend(_dynamic_hashes(nested))
    elif isinstance(value, list):
        for item in value:
            hashes.extend(_dynamic_hashes(item))
    return hashes


def _has_dynamic_numeric(standard: dict[str, Any]) -> bool:
    return bool(
        _dynamic_hashes(standard.get("amount"))
        or _dynamic_hashes(standard.get("delta"))
        or _dynamic_hashes(standard.get("ratio"))
    )


def _no_manual_numeric_binding(transition: BattleTransition) -> bool:
    for mutation in transition.transaction.mutations:
        evaluation = mutation.metadata.get("numeric_evaluation")
        if isinstance(evaluation, dict):
            bindings = evaluation.get("bindings")
            if isinstance(bindings, dict) and bindings.get("source_type") == "explicit_dynamic_values":
                return False
    return True


def _records(transition: BattleTransition) -> list[dict[str, Any]]:
    if transition.transaction.settlement is None:
        return []
    return [record for record in transition.transaction.settlement.records if isinstance(record, dict)]


def _first_record(transition: BattleTransition, record_type: str) -> dict[str, Any]:
    for record in _records(transition):
        if record.get("record_type") == record_type:
            payload = record.get("payload")
            return payload if isinstance(payload, dict) else record
    return {}


def _formula_base(transition: BattleTransition) -> str:
    for mutation in transition.transaction.mutations:
        details = mutation.metadata.get("formula_details")
        if isinstance(details, dict):
            return str(details.get("formula_base") or "")
    return ""


def _sp_formula_detail(transition: BattleTransition) -> str:
    for mutation in transition.transaction.mutations:
        details = mutation.metadata.get("formula_details")
        if isinstance(details, dict):
            if details.get("operation") == "set":
                return "set"
            return str(details.get("scale_basis") or "")
    return ""


def _hp_loss_rounding_policy(transition: BattleTransition) -> str:
    for mutation in transition.transaction.mutations:
        if mutation.metadata.get("damage_formula_family") == "hp_loss":
            return str(mutation.metadata.get("rounding_policy") or "")
    return ""


def _hp_loss_no_direct_ledger(transition: BattleTransition) -> bool:
    for mutation in transition.transaction.mutations:
        if mutation.metadata.get("damage_formula_family") == "hp_loss":
            terms = mutation.metadata.get("normal_multiplier_terms")
            return terms == [] or terms is None
    return False


def _ultimate_energy_mutation_json(case: dict[str, Any]) -> dict[str, Any]:
    for mutation in case["drain_transition"].get("mutations", ()):
        if (
            isinstance(mutation, dict)
            and mutation.get("source") == "combat_executor.resources"
            and mutation.get("metadata", {}).get("resource_operation") == "ultimate_energy_cost"
        ):
            return mutation
    return {}


def _condition_cases_json(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, case in cases.items():
        condition = case.get("condition")
        result[name] = {
            "condition": condition.to_json() if isinstance(condition, ConditionIR) else None,
            "result": case.get("result", {}),
            "selection": case.get("selection", {}),
        }
    return result


if __name__ == "__main__":
    raise SystemExit(main())
