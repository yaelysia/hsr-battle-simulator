from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..core.model import BattleState, UnitState
from ..rules.ir import ActionDefinitionIR, IRSource, TargetExpressionIR, TargetExpressionNodeIR
from ..systems.damage_formula import DamageFormulaInput, DirectDamageFormula
from ..systems.rng import RNGOutcome, RNGRequest, choice_key_for_identity, resolve_rng_request
from ..systems.target import TargetSystem


VALIDATION_VERSION = "p1_7_rng_branch_system"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    _ = (package_root, tbgd_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = {
        "rng_helper": _rng_helper_cases(),
        "crit": _crit_cases(),
        "target_random": _target_random_cases(),
        "bounce": _bounce_cases(),
        "static_random": _static_random_check(),
        "surface_matrix": _surface_matrix(),
    }
    summary = {
        "validation": VALIDATION_VERSION,
        "ok": all(_case_ok(case) for case in cases.values()),
        "cases": {key: _case_summary(value) for key, value in cases.items()},
    }
    _write_json(output_dir / "validation_summary_p1_7_rng_branch_system.json", summary)
    _write_json(output_dir / "rng_schema_cases_p1_7.json", cases["rng_helper"])
    _write_json(output_dir / "rng_crit_cases_p1_7.json", cases["crit"])
    _write_json(output_dir / "rng_target_random_cases_p1_7.json", cases["target_random"])
    _write_json(output_dir / "rng_bounce_cases_p1_7.json", cases["bounce"])
    _write_json(output_dir / "rng_static_checks_p1_7.json", cases["static_random"])
    _write_json(output_dir / "rng_surface_matrix_p1_7.json", cases["surface_matrix"])
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root or package_root.parent.parent / "turnbasedgamedata-main"
    summary = run_validation(package_root, tbgd_root, Path(args.output_dir))
    print(f"v8 {VALIDATION_VERSION} validation ok={summary['ok']}")
    return 0 if summary["ok"] else 1


def _rng_helper_cases() -> dict[str, Any]:
    identity = {
        "decision_scope": "status_application",
        "decision_index": 0,
        "task_id": "validation:status",
        "status_id": "modifier:test",
        "target_id": "enemy:target",
        "derived_event_id": "rng:test:status_apply",
    }
    request = RNGRequest(
        rng_type="status_apply",
        purpose="base_chance",
        event_id="rng:test:status_apply",
        choice_key="status_apply:test",
        source="validation",
        before_state="seed:p1_7",
        decision_kind="probability",
        outcomes=(
            RNGOutcome("success", payload={"success": True, "value": "success"}, probability=0.25),
            RNGOutcome("fail", payload={"success": False, "value": "fail"}, probability=0.75),
        ),
        source_trace={"validation_source": "rng_helper_contract"},
        identity=identity,
    )
    missing = resolve_rng_request(request, rng_mode="explicit_ledger")
    invalid = resolve_rng_request(request, rng_mode="explicit_ledger", rng_choices={"status_apply:test": "bad"})
    explicit = resolve_rng_request(request, rng_mode="explicit_ledger", rng_choices={"status_apply:test": "fail"})
    deterministic_a = resolve_rng_request(request, rng_mode="deterministic_seed")
    deterministic_b = resolve_rng_request(request, rng_mode="deterministic_seed")
    forced = resolve_rng_request(request, forced_outcome_id="success")
    checks = {
        "missing_choice_blocked": not missing.ok and missing.blocked_reason == "requires_rng_choice",
        "missing_choice_has_available_outcomes": bool(missing.available_rng_outcomes().get("outcomes")),
        "invalid_choice_blocked": not invalid.ok and invalid.blocked_reason == "rng_choice_invalid",
        "explicit_choice_selects_fail": explicit.ok and explicit.selected_outcome_id == "fail",
        "deterministic_replay_stable": deterministic_a.event.to_json() == deterministic_b.event.to_json()
        if deterministic_a.event and deterministic_b.event
        else False,
        "forced_choice_selects_success": forced.ok and forced.selected_outcome_id == "success",
        "schema_fields_present": _rng_event_schema_ok(explicit.event.to_json() if explicit.event else {}),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "missing": missing.blocked_payload(),
        "invalid": invalid.blocked_payload(),
        "explicit": explicit.event.to_json() if explicit.event else {},
        "deterministic": deterministic_a.event.to_json() if deterministic_a.event else {},
        "forced": forced.event.to_json() if forced.event else {},
    }


def _crit_cases() -> dict[str, Any]:
    state = _state()
    action = _action_definition()
    source_trace = {"validation_source": "engine_convention_crit_resource"}
    crit_event_id = f"damage_crit:{state.event_index}:{action.definition_id}"
    crit_identity = {
        "decision_scope": "damage_crit",
        "decision_index": 0,
        "action_id": action.action_id,
        "action_level": action.level,
        "definition_id": action.definition_id,
        "task_id": "damage_formula",
        "phase_id": "damage",
        "hit_index": 0,
        "target_id": "enemy:target",
        "derived_event_id": crit_event_id,
    }
    choice_key = choice_key_for_identity("crit", crit_identity)
    crit = DirectDamageFormula().calculate(
        DamageFormulaInput(
            state=state,
            attacker_id="ally:actor",
            target_id="enemy:target",
            action_definition=action,
            attack_type="Normal",
            element_type="fire",
            scaling_ratio=1.0,
            scaling_basis={"kind": "fixed", "value": 100.0},
            source_trace=source_trace,
            rng_mode="explicit_ledger",
            rng_choices={choice_key: "crit"},
        )
    )
    noncrit = DirectDamageFormula().calculate(
        DamageFormulaInput(
            state=state,
            attacker_id="ally:actor",
            target_id="enemy:target",
            action_definition=action,
            attack_type="Normal",
            element_type="fire",
            scaling_ratio=1.0,
            scaling_basis={"kind": "fixed", "value": 100.0},
            source_trace=source_trace,
            rng_mode="explicit_ledger",
            rng_choices={choice_key: "noncrit"},
        )
    )
    deterministic_a = DirectDamageFormula().calculate(
        DamageFormulaInput(
            state=state,
            attacker_id="ally:actor",
            target_id="enemy:target",
            action_definition=action,
            attack_type="Normal",
            element_type="fire",
            scaling_ratio=1.0,
            scaling_basis={"kind": "fixed", "value": 100.0},
            source_trace=source_trace,
            rng_mode="deterministic_seed",
        )
    )
    deterministic_b = DirectDamageFormula().calculate(
        DamageFormulaInput(
            state=state,
            attacker_id="ally:actor",
            target_id="enemy:target",
            action_definition=action,
            attack_type="Normal",
            element_type="fire",
            scaling_ratio=1.0,
            scaling_basis={"kind": "fixed", "value": 100.0},
            source_trace=source_trace,
            rng_mode="deterministic_seed",
        )
    )
    checks = {
        "explicit_crit_event_schema": _rng_event_schema_ok(crit.rng_events[0].to_json()),
        "explicit_noncrit_event_schema": _rng_event_schema_ok(noncrit.rng_events[0].to_json()),
        "crit_damage_greater_than_noncrit": crit.final_damage > noncrit.final_damage,
        "selected_outcomes_recorded": _selected_outcome(crit) == "crit" and _selected_outcome(noncrit) == "noncrit",
        "deterministic_replay_stable": deterministic_a.to_json() == deterministic_b.to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "crit": crit.to_json(),
        "noncrit": noncrit.to_json(),
        "deterministic": deterministic_a.to_json(),
    }


def _target_random_cases() -> dict[str, Any]:
    state = _state()
    expression = TargetExpressionIR(
        target_expression_id="validation:target_shuffle",
        expression_kind="TargetSequence",
        alias="",
        payload={"audit_case": "target_shuffle"},
        source=IRSource("validation:target_expression", "TargetSequence", "validation"),
        node=TargetExpressionNodeIR(
            expression_kind="TargetSequence",
            children=(
                TargetExpressionNodeIR(expression_kind="TargetAlias", alias="AllEnemy"),
                TargetExpressionNodeIR(expression_kind="TargetShuffle"),
            ),
        ),
        coverage_status="executable",
    )
    identity_payload = {
        "actor_id": "ally:actor",
        "action_id": "validation:action",
        "action_level": 1,
        "task_id": "validation:target_task",
        "hit_index": 0,
        "rng_decision_index": 0,
    }
    discovery = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**identity_payload, "rng_mode": "deterministic_seed"},
    )
    random_key = str(discovery.rng_events[0].metadata.get("choice_key") or "") if discovery.rng_events else ""
    explicit = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**identity_payload, "rng_mode": "explicit_ledger", "rng_choices": {random_key: "enemy:left"}},
    )
    broad = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**identity_payload, "rng_mode": "explicit_ledger", "rng_choices": {"default": "enemy:right"}},
    )
    missing = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**identity_payload, "rng_mode": "explicit_ledger"},
    )
    invalid = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**identity_payload, "rng_mode": "explicit_ledger", "rng_choices": {random_key: "missing"}},
    )
    checks = {
        "explicit_choice_ok": explicit.ok and explicit.target_ids == ("enemy:left",),
        "broad_default_rejected": not broad.ok,
        "missing_choice_blocked": not missing.ok and missing.blocked_reason == "requires_rng_choice",
        "invalid_choice_blocked": not invalid.ok and invalid.blocked_reason == "target_random_choice_invalid",
        "available_outcomes_on_missing": _steps_have_available_outcomes(missing.to_json()),
        "rng_event_schema": bool(explicit.rng_events) and _rng_event_schema_ok(explicit.rng_events[0].to_json()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "explicit": explicit.to_json(),
        "broad": broad.to_json(),
        "missing": missing.to_json(),
        "invalid": invalid.to_json(),
    }


def _bounce_cases() -> dict[str, Any]:
    state = _state()
    policy = {
        "coverage_status": "executable",
        "selection_strategy": "prefer_unhit_then_random",
        "continue_on_all_defeated": True,
        "live_target_priority": True,
        "bounce_policy_id": "validation:bounce_policy",
        "source": {"validation_source": "bounce_policy_contract"},
    }
    bounce_event_id = f"rng:{state.event_index}:ally:actor:validation:action:1:bounce:1"
    bounce_identity = {
        "decision_scope": "bounce_target",
        "decision_index": 1,
        "action_id": "validation:action",
        "action_level": 1,
        "task_id": "bounce_policy",
        "hit_index": 1,
        "target_id": "enemy:target",
        "derived_event_id": bounce_event_id,
    }
    bounce_key = choice_key_for_identity("bounce_target", bounce_identity)
    deterministic_a = TargetSystem().resolve_bounce_hit_target(
        state,
        actor_id="ally:actor",
        primary_target_id="enemy:target",
        bounce_policy=policy,
        hit_index=1,
        previous_hit_targets=("enemy:target",),
        action_id="validation:action",
        action_level=1,
        event_payload={"rng_mode": "deterministic_seed"},
    )
    deterministic_b = TargetSystem().resolve_bounce_hit_target(
        state,
        actor_id="ally:actor",
        primary_target_id="enemy:target",
        bounce_policy=policy,
        hit_index=1,
        previous_hit_targets=("enemy:target",),
        action_id="validation:action",
        action_level=1,
        event_payload={"rng_mode": "deterministic_seed"},
    )
    explicit = TargetSystem().resolve_bounce_hit_target(
        state,
        actor_id="ally:actor",
        primary_target_id="enemy:target",
        bounce_policy=policy,
        hit_index=1,
        previous_hit_targets=("enemy:target",),
        action_id="validation:action",
        action_level=1,
        event_payload={
            "rng_mode": "explicit_ledger",
            "rng_choices": {bounce_key: "enemy:left"},
        },
    )
    invalid = TargetSystem().resolve_bounce_hit_target(
        state,
        actor_id="ally:actor",
        primary_target_id="enemy:target",
        bounce_policy=policy,
        hit_index=1,
        previous_hit_targets=("enemy:target",),
        action_id="validation:action",
        action_level=1,
        event_payload={
            "rng_mode": "explicit_ledger",
            "rng_choices": {bounce_key: "missing"},
        },
    )
    checks = {
        "deterministic_replay_stable": deterministic_a.metadata == deterministic_b.metadata,
        "explicit_choice_ok": explicit.ok and explicit.target_id == "enemy:left",
        "invalid_choice_blocked": not invalid.ok and invalid.error == "bounce_target_choice_invalid",
        "available_outcomes_on_invalid": bool(invalid.metadata.get("available_rng_outcomes")),
        "rng_event_schema": explicit.rng_event is not None and _rng_event_schema_ok(explicit.rng_event.to_json()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "deterministic": deterministic_a.metadata,
        "explicit": explicit.rng_event.to_json() if explicit.rng_event else {},
        "invalid": invalid.metadata,
    }


def _static_random_check() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    scan_roots = (root / "core", root / "systems")
    forbidden = ("random.random", "secrets.", "time.time", "SystemRandom", "os.urandom")
    hits: list[dict[str, Any]] = []
    for scan_root in scan_roots:
        for path in sorted(scan_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append({"path": str(path.relative_to(root)), "token": token})
    checks = {"no_process_random_used": not hits}
    checks["ok"] = checks["no_process_random_used"]
    return {"checks": checks, "hits": hits, "scanned_roots": [str(path.relative_to(root)) for path in scan_roots]}


def _surface_matrix() -> dict[str, Any]:
    rows = [
        {
            "surface": "crit",
            "status": "executable",
            "source_kind": "engine_convention_plus_actor_resources",
            "unified_schema": True,
            "ledger": "rng_choices or legacy crit_mode forced outcome",
        },
        {
            "surface": "target_random",
            "status": "executable_when_TargetShuffle_or_random_retarget_source_is_executable",
            "source_kind": "target_expression_ir",
            "unified_schema": True,
            "ledger": "exact choice_key or event_id only",
        },
        {
            "surface": "bounce_target",
            "status": "executable_when_bounce_policy_is_executable",
            "source_kind": "bounce_policy_ir",
            "unified_schema": True,
            "ledger": "rng_choices or deterministic_seed",
        },
        {
            "surface": "status_apply_chance",
            "status": "executable_when_AddModifier_chance_admission_is_executable",
            "source_kind": "effect_ir_standard_chance",
            "unified_schema": True,
            "ledger": "rng_choices or deterministic_seed",
        },
        {
            "surface": "status_resist",
            "status": "executable_when_effect_resistance_resource_is_present",
            "source_kind": "runtime_unit_resource_from_setup_or_cards",
            "unified_schema": True,
            "ledger": "rng_choices or deterministic_seed",
        },
        {
            "surface": "control_resist",
            "status": "admission_gap_blocked",
            "source_kind": "control_kind_metadata_present_but_complete_control_resist_formula_not_admitted",
            "unified_schema": False,
            "ledger": "not promoted to separate executable branch until status/control formula admission exists",
        },
        {
            "surface": "random_dispel",
            "status": "source_gap_blocked_without_Order_Random_source; guarded runtime path exists",
            "source_kind": "DispelStatus Order=Random when present",
            "unified_schema": True,
            "ledger": "rng_choices or deterministic_seed only after source admission",
        },
    ]
    checks = {
        "matrix_has_core_surfaces": len(rows) >= 7,
        "random_dispel_true_source_gap_recorded": any(
            row.get("surface") == "random_dispel" and "source_gap_blocked" in str(row.get("status") or "")
            for row in rows
        ),
        "control_resist_not_misclassified_as_source_gap": all(
            "source_gap_blocked" not in str(row.get("status") or "")
            for row in rows
            if row.get("surface") == "control_resist"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "rows": rows}


def _state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="validation:actor",
                attack=100.0,
                defense=0.0,
                resources={
                    "critical_chance": 0.5,
                    "critical_damage": 1.0,
                    "damage_added_ratio": 0.0,
                    "effect_hit_rate": 0.0,
                },
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:enemy",
                max_hp=1000.0,
                hp=1000.0,
                defense=0.0,
                resources={"effect_resistance": 0.0},
            ),
            "enemy:left": UnitState(
                unit_id="enemy:left",
                side="enemy",
                template_id="validation:enemy",
                max_hp=1000.0,
                hp=1000.0,
                defense=0.0,
            ),
            "enemy:right": UnitState(
                unit_id="enemy:right",
                side="enemy",
                template_id="validation:enemy",
                max_hp=1000.0,
                hp=1000.0,
                defense=0.0,
            ),
        },
        rng_state="p1_7_seed",
        event_index=7,
    )


def _action_definition() -> ActionDefinitionIR:
    return ActionDefinitionIR(
        definition_id="validation:action_def",
        action_id="validation:action",
        level=1,
        attack_type="Normal",
        skill_effect="Attack",
        target_mode="single",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=IRSource("validation:action", "ActionDefinition", "validation"),
        coverage_status="executable",
        damage_kind="hp_damage",
        damage_formula_family="direct",
        element_type="fire",
        source_mode="validation_contract",
    )


def _selected_outcome(result: Any) -> str:
    event_json = result.rng_events[0].to_json()
    event_result = event_json.get("result")
    return str(event_result.get("selected_outcome_id") or "") if isinstance(event_result, dict) else ""


def _steps_have_available_outcomes(result: dict[str, Any]) -> bool:
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return False
    for step in metadata.get("resolution_steps", []):
        if isinstance(step, dict) and step.get("available_rng_outcomes"):
            return True
    return False


def _rng_event_schema_ok(event: dict[str, Any]) -> bool:
    result = event.get("result")
    metadata = event.get("metadata")
    if not isinstance(result, dict) or not isinstance(metadata, dict):
        return False
    required_result = ("decision_kind", "purpose", "choice_key", "choice_source", "outcomes", "selected_outcome_id")
    required_metadata = ("decision_kind", "purpose", "choice_key", "choice_source", "available_rng_outcomes")
    return all(key in result for key in required_result) and all(key in metadata for key in required_metadata)


def _case_ok(case: dict[str, Any]) -> bool:
    checks = case.get("checks")
    return isinstance(checks, dict) and checks.get("ok") is True


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    checks = case.get("checks")
    return checks if isinstance(checks, dict) else {"ok": False}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
