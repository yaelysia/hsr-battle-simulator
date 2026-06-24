from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..systems.damage import (
    DAMAGE_FAMILY_POLICIES,
    DamagePacket,
    DamageSourceFrame,
    DamageSystem,
    DamageWindowLedger,
)
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_256 import _damage_source_window_case


VALIDATION_VERSION = "v0_257"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    static_result = run_static_checks(package_root)
    family_matrix = _damage_family_matrix(ir)
    family_cases = _family_semantics_cases()
    source_window = _damage_source_window_case()
    checks = {
        "damage_family_matrix": _matrix_checks(family_matrix),
        "family_semantics": family_cases["checks"],
        "damage_source_window_regression": source_window["checks"],
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
                "family_matrix": "Full TBGD lowering count by family/source coverage, no fixed character/action/hash selection.",
                "family_semantics": "Unit-level DamageSystem policy cases for currently admitted amount semantics; mechanism admission remains matrix-driven.",
                "source_window": "Reuses v0_256 source-window regression for concrete kill credit and derived damage skip.",
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "damage_family_matrix": family_matrix,
        "family_semantics_cases": family_cases,
        "damage_source_window_case": source_window,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_257.json", result)
    write_json(output_dir / "damage_family_matrix_v0_257.json", family_matrix)
    write_json(output_dir / "damage_family_semantics_cases_v0_257.json", family_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 damage family closure and source-window policy.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _damage_family_matrix(ir) -> dict[str, Any]:
    damage_counts = _count_by_family(ir.damage_emissions)
    direct_basis_debt = _direct_scaling_basis_debt_count(ir)
    if direct_basis_debt:
        damage_counts["direct"]["executable_requires_skill_text_binding"] = direct_basis_debt
    status_damage_counts = _count_by_family(ir.status_damage_emissions)
    super_break_counts = _count_by_family(ir.super_break_emissions)
    formula_counts = _mechanic_formula_counts(ir)
    rows = {
        "direct": _family_entry(
            "direct",
            semantic_status=(
                "blocked"
                if direct_basis_debt
                else "trusted_for_current_scope" if damage_counts["direct"]["executable"] > 0 else "blocked"
            ),
            source_counts=damage_counts["direct"],
            blocking_dependency=(
                "direct_scaling_basis_requires_skill_text_param_binding"
                if direct_basis_debt
                else "" if damage_counts["direct"]["executable"] > 0 else "executable_damage_emission_missing"
            ),
            notes=(
                "Direct runtime formula is generic, but current executable direct emissions still carry an explicit "
                "current-scope attack basis that must be replaced by skill text/ParamList scaling-basis admission."
                if direct_basis_debt
                else ""
            ),
        ),
        "dot": _family_entry(
            "dot",
            semantic_status="trusted_for_current_scope" if status_damage_counts["dot"].get("executable", 0) > 0 else "blocked",
            source_counts=status_damage_counts["dot"],
            blocking_dependency="" if status_damage_counts["dot"].get("executable", 0) > 0 else "ordinary_dot_damage_value_formula_not_admitted",
            notes=(
                "Ordinary DOT is trusted only when StatusDamageEmissionIR is executable and the runtime formula can "
                "evaluate DamageValue/status-bound numeric input; break DOT remains covered by the break family."
            ),
        ),
        "break": _family_entry(
            "break",
            semantic_status="trusted_for_current_scope",
            source_counts=_merge_counts(_statusless_counts(ir.break_damage_emissions), status_damage_counts["break"]),
            blocking_dependency="",
        ),
        "super_break": _family_entry(
            "super_break",
            semantic_status="trusted_for_current_scope" if super_break_counts["super_break"]["executable"] > 0 else "blocked",
            source_counts=super_break_counts["super_break"],
            blocking_dependency="" if super_break_counts["super_break"]["executable"] > 0 else "executable_super_break_emission_missing",
        ),
        "true_damage": _family_entry(
            "true_damage",
            semantic_status="blocked",
            source_counts=formula_counts["true_damage"],
            blocking_dependency="admitted_executable_tbgd_true_damage_effect_or_emission_missing",
            notes="DamageSystem fixed-amount semantics are executable, but no trusted runtime source is admitted.",
        ),
        "hp_loss": _family_entry(
            "hp_loss",
            semantic_status="trusted_for_current_scope",
            source_counts=formula_counts["hp_loss"],
            blocking_dependency="",
        ),
        "elation": _family_entry(
            "elation",
            semantic_status="blocked",
            source_counts=formula_counts["elation"],
            blocking_dependency="elation_formula_inputs_not_admitted_from_tbgd",
        ),
    }
    return {
        "encoding": "hsr.v8.damage_family_matrix.v0_257",
        "families": rows,
        "summary": {
            "family_count": len(rows),
            "semantic_statuses": dict(Counter(row["semantic_status"] for row in rows.values())),
            "no_structural_only": all(row["semantic_status"] != "structural_only" for row in rows.values()),
            "all_have_policy": all(bool(row.get("runtime_policy")) for row in rows.values()),
        },
    }


def _family_entry(
    family: str,
    *,
    semantic_status: str,
    source_counts: dict[str, int],
    blocking_dependency: str,
    notes: str = "",
) -> dict[str, Any]:
    policy = DAMAGE_FAMILY_POLICIES[family].to_json()
    return {
        "family": family,
        "semantic_status": semantic_status,
        "runtime_policy": policy,
        "source_counts": source_counts,
        "blocking_dependency": blocking_dependency,
        "notes": notes,
    }


def _count_by_family(items: tuple[Any, ...]) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = {}
    for item in items:
        family = str(getattr(item, "damage_formula_family", "") or "unknown")
        status = str(getattr(item, "coverage_status", "") or "unknown")
        result.setdefault(family, Counter())[status] += 1
    return {family: dict(counter) for family, counter in result.items()} | {
        family: dict(result.get(family, Counter()))
        for family in ("direct", "dot", "break", "super_break", "true_damage", "hp_loss", "elation")
        if family not in result
    }


def _statusless_counts(items: tuple[Any, ...]) -> dict[str, int]:
    return dict(Counter(str(getattr(item, "coverage_status", "") or "unknown") for item in items))


def _direct_scaling_basis_debt_count(ir) -> int:
    return sum(
        1
        for emission in ir.damage_emissions
        if emission.damage_formula_family == "direct"
        and emission.coverage_status == "executable"
        and isinstance(emission.scaling_basis_expr, dict)
        and emission.scaling_basis_expr.get("requires_skill_text_binding") is True
    )


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


def _matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    families = matrix["families"]
    required = {"direct", "dot", "break", "super_break", "true_damage", "hp_loss", "elation"}
    checks = {
        "all_required_families_present": required.issubset(families),
        "no_structural_only_status": all(row.get("semantic_status") != "structural_only" for row in families.values()),
        "all_blocked_have_dependency": all(
            row.get("semantic_status") != "blocked" or bool(row.get("blocking_dependency"))
            for row in families.values()
        ),
        "elation_blocked_with_dependency": families["elation"]["semantic_status"] == "blocked"
        and bool(families["elation"]["blocking_dependency"]),
        "dot_ordinary_formula_status_explicit": (
            families["dot"]["semantic_status"] == "trusted_for_current_scope"
            and families["dot"]["source_counts"].get("executable", 0) > 0
        )
        or (
            families["dot"]["semantic_status"] == "blocked"
            and "dot" in families["dot"]["blocking_dependency"]
        ),
        "direct_has_executable_source": families["direct"]["source_counts"].get("executable", 0) > 0,
        "hp_loss_not_structural": families["hp_loss"]["semantic_status"] == "trusted_for_current_scope",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _family_semantics_cases() -> dict[str, Any]:
    hp_loss_case = _fixed_family_case("hp_loss")
    true_damage_case = _fixed_family_case("true_damage")
    elation_case = _elation_blocked_case()
    dot_case = _dot_admitted_amount_case()
    checks = {
        "hp_loss": hp_loss_case["checks"],
        "true_damage": true_damage_case["checks"],
        "elation": elation_case["checks"],
        "dot_admitted_amount": dot_case["checks"],
    }
    ok = all(item["ok"] for item in checks.values())
    return {
        "checks": {"ok": ok, "checks": checks},
        "hp_loss": hp_loss_case,
        "true_damage": true_damage_case,
        "elation": elation_case,
        "dot_admitted_amount": dot_case,
    }


def _fixed_family_case(family: str) -> dict[str, Any]:
    state = _state_with_victim(hp=100.0)
    packet = _packet(
        "ally:source",
        "enemy:victim",
        25.0,
        family=family,
        source_id=f"unit:{family}",
        source_kind=family,
        sequence_id=f"seq:{family}",
    )
    result = DamageSystem().apply_packet(state, packet, window_ledger=DamageWindowLedger())
    record = result.records[0] if result.records else {}
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    mutation = result.mutations[0] if result.mutations else None
    checks = {
        "mutation_present": mutation is not None,
        "target_hp_reduced": mutation.after == 75.0 if mutation is not None else False,
        "no_direct_multiplier_terms": payload.get("normal_multiplier_terms") == [],
        "bypasses_policy_correct": payload.get("bypasses_normal_multipliers") is True,
        "source_frame_present": bool(payload.get("source_frame")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "result": result.to_json(),
        "note": "Unit-level DamageSystem semantics only; mechanism admission is decided by damage_family_matrix.",
    }


def _elation_blocked_case() -> dict[str, Any]:
    state = _state_with_victim(hp=100.0)
    result = DamageSystem().apply_packet(
        state,
        _packet(
            "ally:source",
            "enemy:victim",
            25.0,
            family="elation",
            source_id="unit:elation",
            source_kind="elation",
            sequence_id="seq:elation",
        ),
        window_ledger=DamageWindowLedger(),
    )
    record = result.records[0] if result.records else {}
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    checks = {
        "blocked": result.ok is False,
        "no_mutation": not result.mutations,
        "record_is_damage_blocked": record.get("record_type") == "damage_blocked",
        "blocked_reason_specific": "Elation" in str(payload.get("reason") or ""),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "result": result.to_json()}


def _dot_admitted_amount_case() -> dict[str, Any]:
    state = _state_with_victim(hp=30.0)
    reducer = MutationReducer()
    damage = DamageSystem()
    ledger = DamageWindowLedger()
    first = damage.apply_packet(
        state,
        _packet(
            "ally:dot_a",
            "enemy:victim",
            35.0,
            family="dot",
            source_id="dot:source_a",
            source_kind="dot",
            sequence_id="seq:dot:a",
            status_damage_emission_id="unit:dot:a",
        ),
        window_ledger=ledger,
    )
    after_first = reducer.apply_all(state, first.mutations)
    second = damage.apply_packet(
        after_first,
        _packet(
            "ally:dot_b",
            "enemy:victim",
            35.0,
            family="dot",
            source_id="dot:source_b",
            source_kind="dot",
            sequence_id="seq:dot:b",
            status_damage_emission_id="unit:dot:b",
        ),
        window_ledger=ledger,
    )
    first_record = first.records[0] if first.records else {}
    first_payload = first_record.get("payload", {}) if isinstance(first_record, dict) else {}
    second_record = second.records[0] if second.records else {}
    defeat_events = [event for event in first.events if event.event_type == "unit.defeated"]
    checks = {
        "first_dot_mutates_hp": bool(first.mutations),
        "first_record_type_dot": first_record.get("record_type") == "dot_damage",
        "first_dot_no_direct_ledger": first_payload.get("normal_multiplier_terms") == [],
        "first_dot_kill_credit_source": bool(defeat_events and defeat_events[0].payload.get("kill_credit_source_id") == "dot:source_a"),
        "second_dot_skipped": second_record.get("record_type") == "damage_source_skipped",
        "second_dot_no_mutation": not second.mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "first_result": first.to_json(),
        "second_result": second.to_json(),
        "ledger": ledger.to_json(),
    }


def _state_with_victim(*, hp: float) -> BattleState:
    return BattleState(
        units={
            "ally:source": UnitState(unit_id="ally:source", template_id="unit:source", side="ally", hp=1000.0, max_hp=1000.0, attack=100.0, defense=100.0, speed=100.0),
            "ally:dot_a": UnitState(unit_id="ally:dot_a", template_id="unit:dot_a", side="ally", hp=1000.0, max_hp=1000.0, attack=100.0, defense=100.0, speed=100.0),
            "ally:dot_b": UnitState(unit_id="ally:dot_b", template_id="unit:dot_b", side="ally", hp=1000.0, max_hp=1000.0, attack=100.0, defense=100.0, speed=100.0),
            "enemy:victim": UnitState(unit_id="enemy:victim", template_id="unit:victim", side="enemy", hp=hp, max_hp=100.0, attack=50.0, defense=100.0, speed=90.0),
        },
        skill_points=3,
        max_skill_points=5,
    )


def _packet(
    attacker_id: str,
    target_id: str,
    amount: float,
    *,
    family: str,
    source_id: str,
    source_kind: str,
    sequence_id: str,
    status_damage_emission_id: str = "",
) -> DamagePacket:
    return DamagePacket(
        attacker_id=attacker_id,
        target_id=target_id,
        attack_type="DOT" if family == "dot" else family,
        damage_formula_family=family,
        amount=amount,
        damage_kind="hp_damage" if family != "hp_loss" else "hp_loss",
        status_damage_emission_id=status_damage_emission_id,
        source_frame=DamageSourceFrame(
            owner_id=attacker_id,
            source_id=source_id,
            source_kind=source_kind,
            sequence_id=sequence_id,
            target_id=target_id,
            can_continue_after_lethal=False,
            source_trace={"validation": "v0_257_unit_family_semantics"},
        ),
        source_trace={"validation": "v0_257_unit_family_semantics"},
        metadata={
            "damage_formula_family": family,
            "damage_source_owner_id": attacker_id,
            "damage_source_id": source_id,
            "damage_source_kind": source_kind,
            "damage_sequence_id": sequence_id,
            "can_continue_after_lethal": False,
            "source_trace": {"validation": "v0_257_unit_family_semantics"},
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
