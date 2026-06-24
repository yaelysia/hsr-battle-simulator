from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleState, BattleTransition, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DAMAGE_FAMILY_POLICIES, DamageWindowLedger
from ..systems.dot_formula import DotFormula, DotFormulaInput
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_258"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    dot_case = _select_dot_case(ir, rules, extra_formula_type="")
    by_defence_case = _select_dot_case(ir, rules, extra_formula_type="ByDefence")
    positive = _execute_dot_case(rules, dot_case, target_hp=500.0)
    by_defence = _execute_dot_case(rules, by_defence_case, target_hp=500.0) if by_defence_case else _blocked_missing_by_defence()
    unbound = _unbound_dynamic_case(rules, dot_case)
    unsupported_extra = _unsupported_extra_formula_case(rules, dot_case)
    order_case = _dot_order_case(rules, dot_case)
    family_matrix = _damage_family_matrix(ir, positive)
    static_result = run_static_checks(package_root)
    checks = {
        "selection": _selection_checks(dot_case, by_defence_case),
        "ordinary_dot_tick": positive["checks"],
        "by_defence_extra": by_defence["checks"],
        "unbound_dynamic": unbound["checks"],
        "unsupported_extra_formula": unsupported_extra["checks"],
        "dot_order": order_case["checks"],
        "family_matrix": _matrix_checks(family_matrix),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": (
                "Select executable mainline OnPhase1 AttackType=DOT StatusDamageEmissionIR by family/event/coverage/source; "
                "dynamic values are populated from selected expression hashes, not fixed character/action/hash."
            ),
            "selected_dot_emission": dot_case["emission"].to_json(),
            "selected_by_defence_emission": by_defence_case["emission"].to_json() if by_defence_case else None,
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "ordinary_dot_case": positive,
        "by_defence_case": by_defence,
        "negative_cases": {
            "unbound_dynamic": unbound,
            "unsupported_extra_formula": unsupported_extra,
            "dot_order": order_case,
        },
        "damage_family_matrix": family_matrix,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_258.json", result)
    write_json(output_dir / "sample_ordinary_dot_transition_v0_258.json", positive["transition"])
    write_json(output_dir / "ordinary_dot_negative_cases_v0_258.json", result["negative_cases"])
    write_json(output_dir / "damage_family_matrix_v0_258.json", family_matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 ordinary DoT formula admission and execution.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_dot_case(ir, rules: RuleBook, *, extra_formula_type: str) -> dict[str, Any] | None:
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "dot":
            continue
        if emission.coverage_status != "executable":
            continue
        if emission.event != "OnPhase1" or emission.attack_type != "DOT":
            continue
        if emission.source.source_path != "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json":
            continue
        if str(emission.scaling_expr.get("extra_formula_type") or "") != extra_formula_type:
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is None or task is None:
            continue
        if callback.coverage_status != "executable" or task.coverage_status != "executable":
            continue
        if not _hashes_for_emission(emission):
            continue
        return {"emission": emission, "callback": callback, "task": task}
    return None


def _execute_dot_case(rules: RuleBook, case: dict[str, Any] | None, *, target_hp: float) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    state = _state_for_emission(rules, case["emission"], target_hp=target_hp, bind_dynamic=True)
    before = state.snapshot().to_json()
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:dot_target",
        modifier_name=case["emission"].modifier_name,
        event="OnPhase1",
        damage_window_ledger=DamageWindowLedger(),
    )
    transition = _callback_transition(state, result.after_state, result, case["emission"])
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    snapshot = SnapshotCompletenessValidator().validate(state.snapshot())
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    mutations = transition.transaction.mutations
    dot_mutations = [mutation for mutation in mutations if mutation.source == "damage_system"]
    first_record = next((record for record in records if record.get("record_type") == "dot_damage"), {})
    payload = first_record.get("payload", {}) if isinstance(first_record, dict) else {}
    after = result.after_state.snapshot().to_json()
    checks = {
        "case_found": True,
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
        "state_changed": before != after,
        "dot_damage_record": bool(first_record),
        "hp_mutation_present": bool(dot_mutations),
        "hp_reduced": result.after_state.units["enemy:dot_target"].hp < state.units["enemy:dot_target"].hp,
        "no_direct_crit_ledger": payload.get("normal_multiplier_terms") == [] and payload.get("uses_direct_multiplier_ledger") is False,
        "metadata_has_formula_result": all(
            bool(mutation.metadata.get("dot_formula_result")) and bool(mutation.metadata.get("dot_ledger"))
            for mutation in dot_mutations
        ),
    }
    if str(case["emission"].scaling_expr.get("extra_formula_type") or "") == "ByDefence":
        checks["by_defence_extra_applied"] = any(
            term.get("key") == "ExtraFormulaType.ByDefence"
            for mutation in dot_mutations
            for term in mutation.metadata.get("dot_ledger", {}).get("applied_terms", [])
            if isinstance(term, dict)
        )
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "transition": transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _unbound_dynamic_case(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    emission: StatusDamageEmissionIR = case["emission"]
    state = _state_for_emission(rules, emission, target_hp=500.0, bind_dynamic=False)
    before = state.snapshot().to_json()
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:dot_target",
        modifier_name=emission.modifier_name,
        event="OnPhase1",
        damage_window_ledger=DamageWindowLedger(),
    )
    after = result.after_state.snapshot().to_json()
    checks = {
        "no_mutation": not result.mutations,
        "snapshot_unchanged": before == after,
        "blocked_reason_specific": any("dynamic_hash_unbound" in str(record.get("payload", {}).get("reason")) for record in result.records),
    }
    checks["ok"] = all(checks.values())
    return {"checks": checks, "records": list(result.records)}


def _unsupported_extra_formula_case(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    emission: StatusDamageEmissionIR = case["emission"]
    synthetic_emission = replace(
        emission,
        scaling_expr={**emission.scaling_expr, "extra_formula_type": "UnsupportedExtraFormulaForNegativeCase"},
    )
    state = _state_for_emission(rules, emission, target_hp=500.0, bind_dynamic=True)
    detail = state.units["enemy:dot_target"].flags["status_details"][0]
    before = state.snapshot().to_json()
    formula_result = DotFormula().calculate(
        DotFormulaInput(
            state=state,
            caster_id="ally:dot_caster",
            target_id="enemy:dot_target",
            status_detail=detail,
            emission=synthetic_emission,
            source_trace={"selection_mode": "synthetic_negative", "status_damage_source": emission.source.to_json()},
        )
    )
    after = state.snapshot().to_json()
    checks = {
        "blocked": formula_result.ok is False,
        "blocked_reason_specific": "dot_extra_formula_type_not_admitted" in formula_result.blocked_reason,
        "snapshot_unchanged": before == after,
    }
    checks["ok"] = all(checks.values())
    return {"checks": checks, "formula_result": formula_result.to_json(), "selection_mode": "synthetic_negative"}


def _dot_order_case(rules: RuleBook, case: dict[str, Any]) -> dict[str, Any]:
    emission: StatusDamageEmissionIR = case["emission"]
    state = _state_for_emission(rules, emission, target_hp=20.0, bind_dynamic=True, dynamic_value=10.0)
    ledger = DamageWindowLedger()
    first = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:dot_target",
        modifier_name=emission.modifier_name,
        event="OnPhase1",
        damage_window_ledger=ledger,
    )
    second = StatusCallbackSystem(rules).execute(
        first.after_state,
        unit_id="enemy:dot_target",
        modifier_name=emission.modifier_name,
        event="OnPhase1",
        damage_window_ledger=ledger,
    )
    first_defeat = [event for event in first.events if event.event_type == "unit.defeated"]
    checks = {
        "first_dot_lethal": bool(first.mutations and first_defeat),
        "kill_credit_is_dot_source": bool(first_defeat and str(first_defeat[0].payload.get("kill_credit_source_kind")) == "dot"),
        "second_dot_skipped": any(record.get("record_type") == "damage_source_skipped" for record in second.records),
        "second_no_mutation": not second.mutations,
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "first_records": list(first.records),
        "second_records": list(second.records),
        "defeat_events": [event.to_json() for event in first_defeat],
    }


def _state_for_emission(
    rules: RuleBook,
    emission: StatusDamageEmissionIR,
    *,
    target_hp: float,
    bind_dynamic: bool,
    dynamic_value: float = 5.0,
) -> BattleState:
    status_id = f"modifier:{emission.modifier_name}"
    modifier = rules.modifier_definition(emission.modifier_name)
    source_trace = {
        "modifier_definition_source": modifier.source.to_json() if modifier else {},
        "status_damage_source": emission.source.to_json(),
        "selection_mode": "structured_status_instance_input",
    }
    dynamic_values: dict[str, Any] = {"__by_hash": {}}
    if bind_dynamic:
        dynamic_values["__by_hash"] = {hash_key: dynamic_value for hash_key in _hashes_for_emission(emission)}
    detail = {
        "instance_id": f"status_instance:{emission.modifier_name}:dot_validation",
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
        "trigger_ids_by_event": {"OnPhase1": [emission.callback_id]},
        "source_trace": source_trace,
    }
    return BattleState(
        units={
            "ally:dot_caster": UnitState(
                unit_id="ally:dot_caster",
                side="ally",
                template_id="avatar:dot_caster",
                level=80,
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
                level=80,
                max_hp=target_hp,
                hp=target_hp,
                defense=100.0,
                speed=100.0,
                statuses=(status_id,),
                flags={"status_details": (detail,)},
            ),
        },
        global_flags={"phase": "validation"},
    )


def _hashes_for_emission(emission: StatusDamageEmissionIR) -> tuple[str, ...]:
    hashes: list[str] = []
    for key in ("damage_value", "extra_damage_percentage"):
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


def _callback_transition(before_state, after_state, result, emission: StatusDamageEmissionIR) -> BattleTransition:
    command = ActionCommand(
        actor_id="ally:dot_caster",
        action_id="status_tick:ordinary_dot",
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
        coverage={"ordinary_dot_mutation_count": len(result.mutations), "ordinary_dot_record_count": len(result.records)},
    )


def _damage_family_matrix(ir, positive_case: dict[str, Any]) -> dict[str, Any]:
    status_counts = _count_by_family(ir.status_damage_emissions)
    damage_counts = _count_by_family(ir.damage_emissions)
    super_counts = _count_by_family(ir.super_break_emissions)
    break_counts = Counter(str(getattr(item, "coverage_status", "") or "unknown") for item in ir.break_damage_emissions)
    formula_counts = _mechanic_formula_counts(ir)
    rows = {
        "direct": _family_row(
            "direct",
            "trusted_for_current_scope" if damage_counts["direct"].get("executable", 0) > 0 else "blocked",
            damage_counts["direct"],
            "" if damage_counts["direct"].get("executable", 0) > 0 else "executable_damage_emission_missing",
        ),
        "dot": _family_row(
            "dot",
            "trusted_for_current_scope" if positive_case["checks"]["ok"] else "blocked",
            status_counts["dot"],
            "" if positive_case["checks"]["ok"] else "ordinary_dot_positive_case_failed",
            trusted_scope="AttackType=DOT OnPhase1 StatusDamageEmissionIR using DamageValue and admitted ByDefence extra formula.",
            blocked_formula_branches={
                "damage_percentage": "damage_percentage_base_not_admitted",
                "other_extra_formula": "extra_formula_type_not_supported",
            },
        ),
        "break": _family_row(
            "break",
            "trusted_for_current_scope",
            _merge_counts(dict(break_counts), status_counts["break"]),
            "",
        ),
        "super_break": _family_row(
            "super_break",
            "trusted_for_current_scope" if super_counts["super_break"].get("executable", 0) > 0 else "blocked",
            super_counts["super_break"],
            "" if super_counts["super_break"].get("executable", 0) > 0 else "executable_super_break_emission_missing",
        ),
        "true_damage": _family_row(
            "true_damage",
            "blocked",
            formula_counts["true_damage"],
            "admitted_executable_tbgd_true_damage_effect_or_emission_missing",
        ),
        "hp_loss": _family_row("hp_loss", "trusted_for_current_scope", formula_counts["hp_loss"], ""),
        "elation": _family_row(
            "elation",
            "blocked",
            formula_counts["elation"],
            "elation_formula_inputs_not_admitted_from_tbgd",
        ),
    }
    return {
        "encoding": "hsr.v8.damage_family_matrix.v0_258",
        "families": rows,
        "summary": {
            "dot_executable_status_damage_count": status_counts["dot"].get("executable", 0),
            "dot_trusted": rows["dot"]["semantic_status"] == "trusted_for_current_scope",
        },
    }


def _family_row(
    family: str,
    semantic_status: str,
    source_counts: dict[str, int],
    blocking_dependency: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "family": family,
        "semantic_status": semantic_status,
        "runtime_policy": DAMAGE_FAMILY_POLICIES[family].to_json(),
        "source_counts": source_counts,
        "blocking_dependency": blocking_dependency,
        **extra,
    }


def _count_by_family(items: tuple[Any, ...]) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = {}
    for item in items:
        family = str(getattr(item, "damage_formula_family", "") or "unknown")
        status = str(getattr(item, "coverage_status", "") or "unknown")
        result.setdefault(family, Counter())[status] += 1
    defaults = {family: dict(result.get(family, Counter())) for family in DAMAGE_FAMILY_POLICIES}
    return {family: dict(counter) for family, counter in result.items()} | defaults


def _merge_counts(*values: dict[str, int]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in values:
        counter.update(value)
    return dict(counter)


def _mechanic_formula_counts(ir) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = {family: Counter() for family in ("true_damage", "hp_loss", "elation")}
    for formula in ir.formulas:
        expression = formula.expression if isinstance(formula.expression, dict) else {}
        family = expression.get("damage_formula_family")
        if family in result:
            result[str(family)][str(formula.coverage_status)] += 1
    return {family: dict(counter) for family, counter in result.items()}


def _selection_checks(dot_case: dict[str, Any] | None, by_defence_case: dict[str, Any] | None) -> dict[str, Any]:
    checks = {
        "ordinary_dot_case_found": dot_case is not None,
        "ordinary_selection_structured": dot_case is not None
        and dot_case["emission"].source.source_path == "Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json"
        and dot_case["emission"].coverage_status == "executable",
        "by_defence_case_found": by_defence_case is not None,
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    dot = matrix["families"]["dot"]
    checks = {
        "dot_trusted": dot["semantic_status"] == "trusted_for_current_scope",
        "dot_has_executable_source": dot["source_counts"].get("executable", 0) > 0,
        "blocked_branches_specific": bool(dot.get("blocked_formula_branches")),
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _blocked_missing_by_defence() -> dict[str, Any]:
    return {
        "checks": {
            "ok": False,
            "case_found": False,
            "blocking_dependency": "no_mainline_executable_dot_by_defence_case_found",
        }
    }


if __name__ == "__main__":
    raise SystemExit(main())
