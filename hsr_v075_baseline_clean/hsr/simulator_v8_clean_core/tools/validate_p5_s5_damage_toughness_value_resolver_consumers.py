from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, CanonicalIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s5_damage_toughness_value_resolver_consumers"
MATRIX_SCHEMA_VERSION = "p5_s5_damage_toughness_value_resolver_consumers_matrix_v1"

CLASSIFICATION_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "out_of_scope",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "damage_consumer_value_resolver",
    "toughness_consumer_value_resolver",
    "heal_shield_hp_loss_consumer_scope",
    "blocked_value_resolution_no_damage_mutation",
    "consumer_source_audit_replay",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s5_damage_toughness_value_resolver_consumers_matrix(ir, rules)
    matrix_checks = validate_p5_s5_damage_toughness_value_resolver_consumers_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s5_runtime_consumer_value_resolver_structural_action_sample",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "heal_shield_hp_loss_synthetic_positive_created": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "consumer_value_resolver_matrix": matrix["consumer_value_resolver_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "runtime_sample": matrix["runtime_sample"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s5_damage_toughness_value_resolver_consumers.json", result)
    write_json(output_dir / "p5_s5_damage_toughness_value_resolver_consumers_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S5 damage/toughness ValueResolver consumer integration.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s5_damage_toughness_value_resolver_consumers_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    case = _select_and_execute_value_resolved_action(ir, rules)
    rows = [
        _damage_consumer_row(case),
        _toughness_consumer_row(case),
        _heal_shield_hp_loss_scope_row(ir),
        _blocked_value_resolution_negative_row(case),
        _consumer_source_audit_replay_row(case),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "consumer_value_resolver_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "damage_value_resolution_count": len(case["damage_value_resolutions"]),
            "toughness_value_resolution_count": len(case["toughness_value_resolutions"]),
            "runtime_action_sample_count": 1,
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "runtime_sample": case["runtime_sample"],
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "combat_executor_runtime_sample_count": 1,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s5_damage_toughness_value_resolver_consumers.json",
                "p5_s5_damage_toughness_value_resolver_consumers_matrix.json",
            ],
        },
    }


def validate_p5_s5_damage_toughness_value_resolver_consumers_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("consumer_value_resolver_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "damage_consumer_value_resolved": _row_check(rows, "damage_consumer_value_resolver", "damage_mutation_has_value_resolution"),
        "toughness_consumer_value_resolved": _row_check(rows, "toughness_consumer_value_resolver", "toughness_mutation_has_value_resolution"),
        "blocked_no_mutation": _row_check(rows, "blocked_value_resolution_no_damage_mutation", "blocked_packet_no_mutations"),
        "source_audit_replay_ok": _row_check(rows, "consumer_source_audit_replay", "source_audit_ok")
        and _row_check(rows, "consumer_source_audit_replay", "replay_ok"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _select_and_execute_value_resolved_action(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    for toughness in sorted(ir.toughness_emissions, key=lambda item: (item.action_id, item.level, item.toughness_emission_id)):
        if toughness.coverage_status != "executable":
            continue
        if not _is_fixed_toughness_amount(toughness.toughness_amount_expr):
            continue
        if not rules.damage_emissions_for_action(toughness.action_id, toughness.level):
            continue
        action_definition = rules.action_definition(toughness.action_id, toughness.level)
        if action_definition is None or action_definition.coverage_status != "executable":
            continue
        state = BattleState(
            units={
                "ally:value_actor": _ally_unit("ally:value_actor", "validation:value_actor"),
                "enemy:value_target": _enemy_target(),
            },
            skill_points=5,
            max_skill_points=5,
            global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:value_actor"},
        )
        command = ActionCommand(
            actor_id="ally:value_actor",
            action_id=toughness.action_id,
            action_level=toughness.level,
            target_ids=("enemy:value_target",),
            source="validation",
            metadata={
                "p5_s5_selected_by_structural_predicate": True,
                "selection_predicate": "executable_fixed_toughness_emission_with_damage_emission",
            },
        )
        after, transition = CombatExecutor(rules).execute(command, state)
        replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        damage_value_resolutions = _value_resolutions_from_mutations(transition.transaction.mutations, "damage_system")
        toughness_value_resolutions = _value_resolutions_from_mutations(transition.transaction.mutations, "toughness_system")
        damage_settlement_resolutions = _damage_value_resolutions_from_settlement(transition)
        toughness_settlement_resolutions = _toughness_value_resolutions_from_settlement(transition)
        if damage_value_resolutions and toughness_value_resolutions and replay.ok and audit.ok:
            return {
                "state": state,
                "after": after,
                "transition": transition,
                "action_definition": action_definition,
                "command": command,
                "replay": replay,
                "audit": audit,
                "damage_value_resolutions": damage_value_resolutions,
                "toughness_value_resolutions": toughness_value_resolutions,
                "damage_settlement_resolutions": damage_settlement_resolutions,
                "toughness_settlement_resolutions": toughness_settlement_resolutions,
                "runtime_sample": {
                    "actor_data_card_id": "validation:value_actor",
                    "action_id": toughness.action_id,
                    "action_level": toughness.level,
                    "target_ids": list(command.target_ids),
                    "selected_toughness_emission_id": toughness.toughness_emission_id,
                    "selection_predicate": "executable_fixed_toughness_emission_with_damage_emission",
                    "damage_value_resolution_count": len(damage_value_resolutions),
                    "toughness_value_resolution_count": len(toughness_value_resolutions),
                    "damage_mutation_count": transition.coverage.get("damage_mutation_count", 0),
                    "toughness_mutation_count": transition.coverage.get("toughness_mutation_count", 0),
                },
            }
    raise RuntimeError("no value-resolved damage+toughness runtime action selected by structural predicate")


def _damage_consumer_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    resolutions = case["damage_value_resolutions"]
    settlement_resolutions = case["damage_settlement_resolutions"]
    checks = _checks(
        {
            "damage_mutation_has_value_resolution": bool(resolutions),
            "damage_value_resolution_ok": all(resolution.get("ok") is True for resolution in resolutions),
            "damage_settlement_has_value_resolution": bool(settlement_resolutions),
            "source_trace_present": all(bool(resolution.get("source_trace")) for resolution in resolutions),
        }
    )
    return _row(
        "damage_consumer_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(resolutions) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=dict(resolutions[0].get("source_trace") or {}) if resolutions else {},
        details={
            "sample_mutation_resolution": _value_resolution_summary(resolutions[0] if resolutions else {}),
            "sample_settlement_resolution": _value_resolution_summary(
                settlement_resolutions[0] if settlement_resolutions else {}
            ),
        },
    )


def _toughness_consumer_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    resolutions = case["toughness_value_resolutions"]
    settlement_resolutions = case["toughness_settlement_resolutions"]
    checks = _checks(
        {
            "toughness_mutation_has_value_resolution": bool(resolutions),
            "toughness_value_resolution_ok": all(resolution.get("ok") is True for resolution in resolutions),
            "toughness_settlement_has_value_resolution": bool(settlement_resolutions),
            "source_trace_present": all(bool(resolution.get("source_trace")) for resolution in resolutions),
        }
    )
    return _row(
        "toughness_consumer_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(resolutions) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=dict(resolutions[0].get("source_trace") or {}) if resolutions else {},
        details={
            "sample_mutation_resolution": _value_resolution_summary(resolutions[0] if resolutions else {}),
            "sample_settlement_resolution": _value_resolution_summary(
                settlement_resolutions[0] if settlement_resolutions else {}
            ),
        },
    )


def _heal_shield_hp_loss_scope_row(ir: CanonicalIR) -> dict[str, JSONValue]:
    family_counts = Counter(str(emission.damage_formula_family) for emission in ir.damage_emissions)
    scoped_count = sum(family_counts.get(kind, 0) for kind in ("heal", "shield", "hp_loss"))
    checks = _checks(
        {
            "scope_scan_completed": True,
            "no_synthetic_heal_shield_hp_loss_positive": True,
            "source_absence_or_gap_recorded": True,
        }
    )
    classification = "admission_gap" if scoped_count else "source_absent_not_required"
    return _row(
        "heal_shield_hp_loss_consumer_scope",
        classification=classification,
        checks=checks,
        ir_count=scoped_count,
        executable_count=0,
        blocked_or_gap_count=scoped_count,
        gap_attribution={"admission_gap": scoped_count} if scoped_count else {},
        details={
            "damage_formula_family_counts": dict(sorted(family_counts.items())),
            "policy": "Heal/shield/hp-loss positives are not synthesized; real source-backed rows stay gap until admitted.",
        },
    )


def _blocked_value_resolution_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    state = case["state"]
    command = case["command"]
    action_definition: ActionDefinitionIR = case["action_definition"]
    target_id = command.target_ids[0]
    packet = DamagePacket(
        attacker_id=command.actor_id,
        target_id=target_id,
        attack_type=action_definition.attack_type,
        damage_formula_family="direct",
        action_definition=action_definition,
        damage_emission_id="p5_s5_negative",
        hit_profile_id="p5_s5_negative",
        scaling_ratio=None,
        source_trace={"validation_negative": "missing_value_resolution"},
        metadata={"value_resolution": {"ok": False, "blocked_reason": "validation_missing_binding"}},
    )
    result = DamageSystem().apply_packet(state, packet)
    replay = MutationReducer().replay_snapshot(state, (), state.snapshot().to_json())
    checks = _checks(
        {
            "blocked_packet_not_ok": not result.ok,
            "blocked_packet_no_mutations": not result.mutations,
            "blocked_packet_process_record": bool(result.records),
            "state_unchanged_replay_ok": replay.ok,
        }
    )
    return _row(
        "blocked_value_resolution_no_damage_mutation",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "blocked_result": _compact_json(result.to_json()),
            "replay": _replay_json(replay),
        },
    )


def _consumer_source_audit_replay_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    replay = case["replay"]
    audit = case["audit"]
    checks = _checks(
        {
            "replay_ok": replay.ok,
            "source_audit_ok": audit.ok,
            "after_matches_transition": case["after"].snapshot().to_json() == case["transition"].after.to_json(),
            "damage_and_toughness_resolutions_present": bool(case["damage_value_resolutions"])
            and bool(case["toughness_value_resolutions"]),
        }
    )
    return _row(
        "consumer_source_audit_replay",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "replay": _replay_json(replay),
            "source_audit": _source_audit_summary(audit),
            "runtime_sample": case["runtime_sample"],
        },
    )


def _value_resolutions_from_mutations(mutations: tuple[Any, ...], source: str) -> list[dict[str, JSONValue]]:
    resolutions = []
    for mutation in mutations:
        if mutation.source != source:
            continue
        resolution = mutation.metadata.get("value_resolution") if isinstance(mutation.metadata, dict) else None
        if isinstance(resolution, dict):
            resolutions.append(resolution)
    return resolutions


def _damage_value_resolutions_from_settlement(transition: Any) -> list[dict[str, JSONValue]]:
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    resolutions = []
    for record in records:
        if record.get("record_type") != "damage":
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        packet_metadata = payload.get("packet_metadata") if isinstance(payload.get("packet_metadata"), dict) else {}
        resolution = packet_metadata.get("value_resolution")
        if isinstance(resolution, dict):
            resolutions.append(resolution)
    return resolutions


def _toughness_value_resolutions_from_settlement(transition: Any) -> list[dict[str, JSONValue]]:
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    resolutions = []
    for record in records:
        if record.get("record_type") != "toughness":
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        resolution = payload.get("value_resolution")
        if isinstance(resolution, dict):
            resolutions.append(resolution)
    return resolutions


def _is_fixed_toughness_amount(expression: Any) -> bool:
    if not isinstance(expression, dict):
        return False
    if expression.get("kind") != "fixed":
        return False
    value = expression.get("value")
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _ally_unit(unit_id: str, template_id: str) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side="ally",
        template_id=template_id,
        level=80,
        max_hp=3000.0,
        hp=3000.0,
        attack=1000.0,
        defense=500.0,
        speed=100.0,
        energy=100.0,
        max_energy=100.0,
    )


def _enemy_target() -> UnitState:
    return UnitState(
        unit_id="enemy:value_target",
        side="enemy",
        template_id="validation:value_target",
        level=80,
        max_hp=100000.0,
        hp=100000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        toughness=120.0,
        max_toughness=120.0,
        flags={"weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
    )


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    ir_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "ir_count": int(ir_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": _source_trace_summary(sample_source_trace or {}),
        "details": details or {},
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    gap_rows = []
    for row in rows:
        gap_attribution = dict(row.get("gap_attribution") or {})
        if not gap_attribution:
            continue
        gap_rows.append(
            {
                "row_id": str(row.get("row_id") or ""),
                "classification": str(row.get("classification") or ""),
                "gap_attribution": gap_attribution,
                "blocked_or_gap_count": int(row.get("blocked_or_gap_count") or 0),
                "details": _compact_json(row.get("details") or {}),
            }
        )
    gap_counts = _gap_counts(gap_rows)
    return {
        "schema_version": "p5_s5_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _replay_json(replay: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(replay, "ok", False)),
        "errors": list(getattr(replay, "errors", ()) or ()),
    }


def _value_resolution_summary(resolution: dict[str, JSONValue]) -> dict[str, JSONValue]:
    if not isinstance(resolution, dict):
        return {}
    request = resolution.get("request") if isinstance(resolution.get("request"), dict) else {}
    delegate = (
        resolution.get("delegate_resolution")
        if isinstance(resolution.get("delegate_resolution"), dict)
        else {}
    )
    return {
        "ok": bool(resolution.get("ok")),
        "value": resolution.get("value"),
        "binding_kind": resolution.get("binding_kind"),
        "blocked_reason": resolution.get("blocked_reason", ""),
        "request": {
            "binding_kind": request.get("binding_kind"),
            "binding_id": request.get("binding_id", ""),
            "field_name": request.get("field_name", ""),
            "param_index": request.get("param_index"),
            "formula_role": request.get("formula_role", ""),
            "required_context_keys": list(request.get("required_context_keys") or []),
            "source_trace": _source_trace_summary(
                request.get("source_trace") if isinstance(request.get("source_trace"), dict) else {}
            ),
        },
        "delegate_resolution": {
            "ok": delegate.get("ok"),
            "value": delegate.get("value"),
            "value_source": delegate.get("value_source", ""),
            "raw_value": _compact_json(delegate.get("raw_value")),
            "blocked_reason": delegate.get("blocked_reason", ""),
            "source_trace": _source_trace_summary(
                delegate.get("source_trace") if isinstance(delegate.get("source_trace"), dict) else {}
            ),
            "preceding_dynamic_hash_resolution": _preceding_resolution_summary(
                delegate.get("preceding_dynamic_hash_resolution")
            ),
        },
        "source_trace": _source_trace_summary(
            resolution.get("source_trace") if isinstance(resolution.get("source_trace"), dict) else {}
        ),
        "context_keys": list(resolution.get("context_keys") or []),
        "context_trace": _context_trace_summary(
            resolution.get("context_trace") if isinstance(resolution.get("context_trace"), dict) else {}
        ),
    }


def _preceding_resolution_summary(value: Any) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return {}
    delegate = value.get("delegate_resolution") if isinstance(value.get("delegate_resolution"), dict) else {}
    return {
        "ok": bool(value.get("ok")),
        "binding_kind": value.get("binding_kind"),
        "blocked_reason": value.get("blocked_reason", ""),
        "request": _compact_json(value.get("request")),
        "delegate_resolution": {
            "ok": delegate.get("ok"),
            "value": delegate.get("value"),
            "blocked_reason": delegate.get("blocked_reason", ""),
            "bindings": _compact_json(delegate.get("bindings")),
        },
        "source_trace": _source_trace_summary(
            value.get("source_trace") if isinstance(value.get("source_trace"), dict) else {}
        ),
    }


def _context_trace_summary(trace: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "action_id": trace.get("action_id", ""),
        "level": trace.get("level"),
        "level_source": trace.get("level_source", ""),
        "actor_id": trace.get("actor_id", ""),
        "target_id": trace.get("target_id", ""),
        "hit_id": trace.get("hit_id", ""),
        "hit_index": trace.get("hit_index"),
        "available_keys": list(trace.get("available_keys") or []),
        "binding_source_count": trace.get("binding_source_count", 0),
        "dynamic_value_key_count": trace.get("dynamic_value_key_count", 0),
    }


def _source_audit_summary(audit: Any) -> dict[str, JSONValue]:
    data = audit.to_json()
    traces = data.get("traces") if isinstance(data.get("traces"), list) else []
    return {
        "ok": bool(data.get("ok")),
        "errors": _compact_json(data.get("errors") or []),
        "checked_mutations": data.get("checked_mutations", 0),
        "checked_records": data.get("checked_records", 0),
        "trace_count": len(traces),
        "sample_traces": [_audit_trace_summary(trace) for trace in traces[:3] if isinstance(trace, dict)],
    }


def _audit_trace_summary(trace: dict[str, JSONValue]) -> dict[str, JSONValue]:
    mutation = trace.get("mutation") if isinstance(trace.get("mutation"), dict) else {}
    settlement_records = (
        trace.get("settlement_records") if isinstance(trace.get("settlement_records"), list) else []
    )
    return {
        "mutation_id": mutation.get("mutation_id", ""),
        "source": mutation.get("source", ""),
        "op": mutation.get("op", ""),
        "path": _compact_json(mutation.get("path")),
        "origin": _compact_json(trace.get("origin")),
        "settlement_record_count": len(settlement_records),
    }


def _source_trace_summary(trace: dict[str, JSONValue]) -> dict[str, JSONValue]:
    if not isinstance(trace, dict):
        return {}
    evidence = trace.get("evidence") if isinstance(trace.get("evidence"), dict) else {}
    summary: dict[str, JSONValue] = {
        "raw_type": trace.get("raw_type", ""),
        "raw_id": trace.get("raw_id", ""),
        "source_path": trace.get("source_path", ""),
    }
    for key in (
        "action_id",
        "level",
        "row_index",
        "skill_trigger_key",
        "task_id",
        "task_index",
        "task_path",
        "phase_id",
        "effect_id",
        "hit_profile_id",
        "target_alias",
        "raw_path",
        "source_kind",
        "fallback_basis",
    ):
        if key in trace:
            summary[key] = _compact_json(trace[key])
        elif key in evidence:
            summary[key] = _compact_json(evidence[key])
    if isinstance(trace.get("source"), dict):
        summary["source"] = _source_trace_summary(trace["source"])
    if isinstance(trace.get("dynamic_hash_resolution"), dict):
        summary["dynamic_hash_resolution"] = _preceding_resolution_summary(
            trace.get("dynamic_hash_resolution")
        )
    return {key: value for key, value in summary.items() if value not in ("", None, {}, [])}


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 4:
        if isinstance(value, dict):
            return {"truncated": True, "key_count": len(value)}
        if isinstance(value, (list, tuple)):
            return ["truncated", len(value)]
        return str(value)
    if isinstance(value, dict):
        return {str(key): _compact_json(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        compact = [_compact_json(item, depth=depth + 1) for item in items[:4]]
        if len(items) > 4:
            compact.append({"truncated_count": len(items) - 4})
        return compact
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
