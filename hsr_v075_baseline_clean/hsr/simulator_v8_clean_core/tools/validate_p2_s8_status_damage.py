from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import ExecutionNodeResult, classify_transition_outcome
from ..rules.ir import StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.scheduler import CombatScheduler
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p2_status_coverage import (
    build_p2_status_coverage_matrix,
    validate_p2_ir_rulebook_integrity_matrix,
    validate_p2_status_inventory_matrix,
)
from .static_checks import run_static_checks
from .validate_p1_4_status_system import (
    _dot_bindings_by_ability_file,
    _effect_sample,
    _expr_kind,
    _expr_supported,
    _first_status_detail,
    _hashes_for_dot_emission,
    _select_lifecycle_dot_case,
    _snapshot_hash,
    _state_for_lifecycle_dot_case,
)


VALIDATION_VERSION = "p2_s8_status_damage"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    damage_matrix = _status_damage_matrix(ir, rules)
    ordinary_dot_case = _ordinary_dot_lifecycle_case(ir, rules)
    break_dot_case = _break_dot_case(ir, rules)
    true_damage_case = _true_damage_case(ir, rules)
    multi_dot_case = _multi_dot_case(ir, rules)
    dead_target_case = _dead_target_skip_case(ir, rules)
    missing_status_case = _missing_status_negative_case(ir, rules)
    missing_formula_case = _missing_dot_formula_negative_case(ir, rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "status_damage_matrix": damage_matrix["checks"],
        "ordinary_dot_lifecycle": ordinary_dot_case["checks"],
        "break_dot": break_dot_case["checks"],
        "true_damage": true_damage_case["checks"],
        "multi_dot": multi_dot_case["checks"],
        "dead_target_skip": dead_target_case["checks"],
        "missing_status_blocked": missing_status_case["checks"],
        "missing_dot_formula_blocked": missing_formula_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_damage_sources",
                "runtime_behavior_changed": True,
                "runtime_change": "DamageSystem skips non-damageable targets even without a DamageWindowLedger.",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "status_damage_matrix": damage_matrix["matrix"],
            "classification_counts": damage_matrix["classification_counts"],
            "ordinary_dot": ordinary_dot_case["summary"],
            "break_dot": break_dot_case["summary"],
            "true_damage": true_damage_case["summary"],
            "multi_dot": multi_dot_case["summary"],
            "negative_cases": {
                "dead_target_skip": dead_target_case["summary"],
                "missing_status": missing_status_case["summary"],
                "missing_dot_formula": missing_formula_case["summary"],
            },
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "ordinary_dot_lifecycle": ordinary_dot_case["case"],
            "break_dot": break_dot_case["case"],
            "true_damage": true_damage_case["case"],
            "multi_dot": multi_dot_case["case"],
            "dead_target_skip": dead_target_case["case"],
            "missing_status": missing_status_case["case"],
            "missing_dot_formula": missing_formula_case["case"],
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s8_status_damage.json", result)
    return result


def _ordinary_dot_lifecycle_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_lifecycle_dot_case(ir, rules)
    if selected is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_dot_tick_mutation": True,
        }
        checks["ok"] = True
        return {
            "checks": {"ok": True, "checks": checks},
            "summary": {"classification": "source_gap_blocked", "reason": "no executable lifecycle DoT case found"},
            "case": {"coverage_gap": "no executable lifecycle DoT case found"},
        }
    emission: StatusDamageEmissionIR = selected["emission"]
    state = _state_for_lifecycle_dot_case(
        emission,
        selected["formula_binding"],
        selected["add_effect"],
        selected["duration_admission"],
    )
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(state, "ModifierPhase1End", actor_id="enemy:dot_target")
    transition = _sweep_transition(state, sweep.after_state, sweep, "p2_s8:ordinary_dot")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    dot_mutations = _damage_mutations(sweep.mutations, family="dot")
    dot_records = _records_of_type(sweep.records, "dot_damage")
    detail_after = _first_status_detail(sweep.after_state)
    damage_index = _first_index(sweep.mutations, lambda mutation: mutation.source == "damage_system")
    lifecycle_index = _first_index(
        sweep.mutations,
        lambda mutation: mutation.source == "status_system" and tuple(mutation.path)[-1] == "status_details",
    )
    frame = _source_frame(dot_mutations[0]) if dot_mutations else {}
    checks = {
        "case_found": True,
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "dot_damage_mutation_present": bool(dot_mutations),
        "dot_damage_record_present": bool(dot_records),
        "damage_hit_event_emitted": any(event.event_type == "damage.hit" for event in sweep.events),
        "duration_tick_after_damage": damage_index >= 0 and lifecycle_index >= 0 and damage_index < lifecycle_index,
        "remaining_duration_decremented": detail_after.get("remaining_duration") == 1.0,
        "source_frame_owner_is_caster": frame.get("owner_id") == "ally:dot_caster",
        "source_frame_target_is_holder": frame.get("target_id") == "enemy:dot_target",
        "source_frame_kind_is_dot": frame.get("source_kind") == "dot",
        "status_source_metadata_present": all(
            mutation.metadata.get("status_damage_emission_id")
            and mutation.metadata.get("status_callback_id")
            and mutation.metadata.get("status_instance_id")
            and mutation.metadata.get("dot_formula_result")
            for mutation in dot_mutations
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "executable",
            "status_damage_emission_id": emission.status_damage_emission_id,
            "modifier_name": emission.modifier_name,
            "record_count": len(dot_records),
            "mutation_count": len(dot_mutations),
        },
        "case": {
            "selected_emission": emission.to_json(),
            "selected_add_modifier_effect": _effect_sample(selected["add_effect"]),
            "selected_formula_binding": selected["formula_binding"].to_json() if selected["formula_binding"] is not None else {},
            "transition": _compact_transition(transition),
        },
    }


def _break_dot_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_break_dot_emission(ir, rules)
    if selected is None:
        executable_emissions = [
            emission
            for emission in ir.status_damage_emissions
            if emission.damage_formula_family == "break" and emission.coverage_status == "executable"
        ]
        linked_runtime_emissions = [
            emission
            for emission in executable_emissions
            if rules.status_callback(emission.callback_id) is not None
            and rules.status_callback_task(emission.source_task_id) is not None
            and rules.status_callback(emission.callback_id).coverage_status == "executable"
            and rules.status_callback_task(emission.source_task_id).coverage_status == "executable"
        ]
        return {
            "checks": {
                "ok": True,
                "checks": {
                    "gap_structured": True,
                    "no_synthetic_break_dot_mutation": True,
                    "executable_break_damage_emission_count": len(executable_emissions),
                    "runtime_linked_break_damage_emission_count": len(linked_runtime_emissions),
                },
            },
            "summary": {
                "classification": "source_link_gap_blocked",
                "reason": "no executable break status emission shares modifier_name with an executable break status damage callback",
            },
            "case": {
                "executable_break_damage_emission_ids": [
                    emission.status_damage_emission_id for emission in executable_emissions
                ],
                "runtime_linked_break_damage_emission_ids": [
                    emission.status_damage_emission_id for emission in linked_runtime_emissions
                ],
            },
        }
    emission: StatusDamageEmissionIR = selected["emission"]
    break_status = selected["break_status"]
    state = _state_for_status_damage_emission(
        emission,
        formula_bindings=(),
        dynamic_hashes=_hashes_for_status_damage(emission),
        dynamic_value=0.25,
        target_hp=5000.0,
    )
    state = _attach_break_status_source(state, emission, break_status)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:status_target",
        modifier_name=emission.modifier_name,
        event=emission.event,
    )
    transition = _callback_transition(state, result, "p2_s8:break_dot", actor_id="ally:status_caster", target_id="enemy:status_target")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    mutations = _damage_mutations(result.mutations, family="break")
    records = _records_of_type(result.records, "break_dot_tick")
    checks = {
        "selection_found": bool(selected),
        "callback_ok_or_blocked_branches_recorded": result.ok or _errors_recorded(result.errors, result.records),
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "break_dot_record": bool(records),
        "hp_mutation_present": bool(mutations),
        "hp_reduced": result.after_state.units["enemy:status_target"].hp < state.units["enemy:status_target"].hp,
        "status_damage_source_metadata": all(
            mutation.metadata.get("status_damage_emission_id")
            and mutation.metadata.get("status_callback_id")
            and mutation.metadata.get("numeric_evaluation")
            and mutation.metadata.get("break_base_damage_source")
            for mutation in mutations
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "executable",
            "status_damage_emission_id": emission.status_damage_emission_id,
            "modifier_name": emission.modifier_name,
        },
        "case": {
            "selected_emission": emission.to_json(),
            "selected_break_status_emission": break_status.to_json(),
            "transition": _compact_transition(transition),
        },
    }


def _true_damage_case(ir, rules: RuleBook) -> dict[str, Any]:
    emission = _select_true_damage_emission(ir, rules)
    state = _state_for_status_damage_emission(emission, dynamic_value=37.0)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:status_target",
        modifier_name=emission.modifier_name,
        event=emission.event,
    )
    transition = _callback_transition(state, result, "p2_s8:true_damage", actor_id="ally:status_caster", target_id="enemy:status_target")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    mutations = _damage_mutations(result.mutations, family="true_damage")
    records = [
        record
        for record in result.records
        if record.get("record_type") == "damage"
        and isinstance(record.get("payload"), dict)
        and isinstance(record["payload"].get("packet_metadata"), dict)
        and record["payload"]["packet_metadata"].get("status_damage_emission_id") == emission.status_damage_emission_id
    ]
    frame = _source_frame(mutations[0]) if mutations else {}
    checks = {
        "case_found": emission is not None,
        "callback_ok": result.ok,
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "true_damage_mutation_present": bool(mutations),
        "status_true_damage_record_present": bool(records),
        "hp_reduced_by_dynamic_value": state.units["enemy:status_target"].hp - result.after_state.units["enemy:status_target"].hp == 37.0,
        "source_frame_owner_is_caster": frame.get("owner_id") == "ally:status_caster",
        "source_frame_target_is_holder": frame.get("target_id") == "enemy:status_target",
        "source_frame_kind_is_status_true_damage": frame.get("source_kind") == "status_true_damage",
        "status_source_metadata_present": all(
            mutation.metadata.get("status_damage_emission_id")
            and mutation.metadata.get("status_callback_id")
            and mutation.metadata.get("status_instance_id")
            and mutation.metadata.get("numeric_evaluation", {}).get("ok") is True
            for mutation in mutations
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "executable",
            "status_damage_emission_id": emission.status_damage_emission_id,
            "modifier_name": emission.modifier_name,
            "damage_amount": 37.0,
        },
        "case": {
            "selected_emission": emission.to_json(),
            "transition": _compact_transition(transition),
        },
    }


def _multi_dot_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_multi_dot_execution(ir, rules)
    if selected is None:
        checks = {
            "multi_source_exists": _multi_status_damage_callback_count(ir) > 0,
            "multi_execution_gap_recorded": True,
            "no_synthetic_multi_mutation": True,
        }
        checks["ok"] = False
        return {
            "checks": {"ok": False, "checks": checks},
            "summary": {
                "classification": "validation_or_payload_gap",
                "reason": "multi status damage callbacks exist but no executable runtime case was found",
            },
            "case": {},
        }
    result = selected["result"]
    state = selected["state"]
    transition = _callback_transition(state, result, "p2_s8:multi_dot", actor_id="ally:dot_caster", target_id="enemy:dot_target")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    mutations = _damage_mutations(result.mutations, family="dot")
    emission_ids = tuple(str(mutation.metadata.get("status_damage_emission_id") or "") for mutation in mutations)
    checks = {
        "multi_source_exists": selected["source_emission_count"] >= 2,
        "callback_ok_or_blocked_branches_recorded": result.ok or _errors_recorded(result.errors, result.records),
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "multiple_damage_mutations": len(mutations) >= 2,
        "multiple_unique_emissions": len(set(emission_ids)) >= 2,
        "multiple_dot_records": len(_records_of_type(result.records, "dot_damage")) >= 2,
        "all_source_frames_are_dot": all(_source_frame(mutation).get("source_kind") == "dot" for mutation in mutations),
        "partial_errors_recorded_when_present": _errors_recorded(result.errors, result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "executable",
            "callback_id": selected["callback_id"],
            "modifier_name": selected["modifier_name"],
            "source_emission_count": selected["source_emission_count"],
            "executed_damage_count": len(mutations),
        },
        "case": {
            "callback_id": selected["callback_id"],
            "modifier_name": selected["modifier_name"],
            "executed_emission_ids": list(emission_ids),
            "transition": _compact_transition(transition),
        },
    }


def _dead_target_skip_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_lifecycle_dot_case(ir, rules)
    if selected is None:
        checks = {"coverage_gap_recorded": True, "ok": True}
        return {"checks": {"ok": True, "checks": checks}, "summary": {"classification": "source_gap_blocked"}, "case": {}}
    emission: StatusDamageEmissionIR = selected["emission"]
    state = _state_for_lifecycle_dot_case(
        emission,
        selected["formula_binding"],
        selected["add_effect"],
        selected["duration_admission"],
    )
    target = state.units["enemy:dot_target"]
    defeated = replace(target, hp=0.0, flags={**target.flags, "lifecycle_status": "defeated"})
    state = replace(state, units={**state.units, "enemy:dot_target": defeated})
    before_hash = _snapshot_hash(state)
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(state, "ModifierPhase1End", actor_id="enemy:dot_target")
    transition = _sweep_transition(state, sweep.after_state, sweep, "p2_s8:dead_target_skip")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    skip_records = _records_of_type(sweep.records, "damage_source_skipped")
    checks = {
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "skip_record_present": bool(skip_records),
        "skip_reason_not_alive": any(record.get("payload", {}).get("reason") == "damage_source_target_not_alive" for record in skip_records),
        "no_damage_mutation": not _damage_mutations(sweep.mutations),
        "no_damage_hit_event": not any(event.event_type == "damage.hit" for event in sweep.events),
        "snapshot_unchanged": before_hash == _snapshot_hash(sweep.after_state),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "boundary_only",
            "reason": "defeated status damage target is skipped process-only",
        },
        "case": {
            "selected_emission_id": emission.status_damage_emission_id,
            "records": skip_records,
            "transition": _compact_transition(transition),
        },
    }


def _missing_status_negative_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_lifecycle_dot_case(ir, rules)
    if selected is None:
        checks = {"coverage_gap_recorded": True, "ok": True}
        return {"checks": {"ok": True, "checks": checks}, "summary": {"classification": "source_gap_blocked"}, "case": {}}
    emission: StatusDamageEmissionIR = selected["emission"]
    state = _state_for_lifecycle_dot_case(
        emission,
        selected["formula_binding"],
        selected["add_effect"],
        selected["duration_admission"],
    )
    target = state.units["enemy:dot_target"]
    empty_target = replace(target, statuses=(), flags={**target.flags, "status_details": ()})
    state = replace(state, units={**state.units, "enemy:dot_target": empty_target})
    before_hash = _snapshot_hash(state)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:dot_target",
        modifier_name=emission.modifier_name,
        event=emission.event,
    )
    checks = {
        "blocked": not result.ok,
        "status_detail_missing": "status_detail_missing" in result.errors,
        "no_mutations": not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(result.after_state),
        "blocked_record_present": any(record.get("payload", {}).get("reason") == "status_detail_missing" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "missing source status blocks callback execution"},
        "case": {"selected_emission_id": emission.status_damage_emission_id, "records": list(result.records)},
    }


def _missing_dot_formula_negative_case(ir, rules: RuleBook) -> dict[str, Any]:
    selected = _select_formula_required_dot_emission(ir, rules)
    state = _state_for_status_damage_emission(selected, formula_bindings=())
    before_hash = _snapshot_hash(state)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id="enemy:status_target",
        modifier_name=selected.modifier_name,
        event=selected.event,
    )
    reason_text = " ".join(str(record.get("payload", {}).get("reason") or "") for record in result.records)
    checks = {
        "case_found": selected is not None,
        "blocked": not result.ok,
        "formula_missing_reason": "dot_status_formula_binding_missing" in reason_text,
        "no_damage_mutations": not _damage_mutations(result.mutations),
        "snapshot_unchanged": before_hash == _snapshot_hash(result.after_state),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "DoT formula binding missing blocks damage"},
        "case": {"selected_emission": selected.to_json(), "records": list(result.records)},
    }


def _status_damage_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    family_counts = Counter((emission.damage_formula_family, emission.coverage_status) for emission in ir.status_damage_emissions)
    executable_by_callback: dict[str, list[StatusDamageEmissionIR]] = defaultdict(list)
    for emission in ir.status_damage_emissions:
        if emission.coverage_status == "executable":
            executable_by_callback[emission.callback_id].append(emission)
    hp_loss_tasks = []
    for task in ir.status_callback_tasks:
        if not task.effect_id:
            continue
        effect = rules.effect(task.effect_id)
        if effect is not None and effect.opcode == "LoseHPByRatio":
            hp_loss_tasks.append((task, effect))
    matrix = {
        "ordinary_dot": _family_entry(
            "executable" if family_counts.get(("dot", "executable"), 0) > 0 else "implementation_missing",
            family_counts.get(("dot", "executable"), 0),
            "StatusDamageEmissionIR dot family has executable OnPhase1/runtime samples.",
        ),
        "break_dot": _family_entry(
            "executable" if family_counts.get(("break", "executable"), 0) > 0 else "implementation_missing",
            family_counts.get(("break", "executable"), 0),
            "StatusDamageEmissionIR break family covers break DoT tick through status callback.",
        ),
        "status_true_damage": _family_entry(
            "executable" if family_counts.get(("true_damage", "executable"), 0) > 0 else "implementation_missing",
            family_counts.get(("true_damage", "executable"), 0),
            "StatusDamageEmissionIR true_damage family has a mainline avatar callback source.",
        ),
        "status_hp_loss_effects": _family_entry(
            "admission_gap_blocked" if hp_loss_tasks else "source_absent_not_required",
            len(hp_loss_tasks),
            "LoseHPByRatio appears under status callback tasks, but current callback task admission keeps it blocked.",
        ),
        "multi_status_damage": _family_entry(
            "executable" if any(len(items) > 1 for items in executable_by_callback.values()) else "source_absent_not_required",
            sum(1 for items in executable_by_callback.values() if len(items) > 1),
            "Callbacks with multiple executable StatusDamageEmissionIR entries are present and sampled separately.",
        ),
        "blocked_status_damage": _family_entry(
            "boundary_only",
            sum(1 for emission in ir.status_damage_emissions if emission.coverage_status != "executable"),
            "Blocked status damage emissions remain process-only and must not mutate HP.",
        ),
    }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "dot_executable_seen": family_counts.get(("dot", "executable"), 0) > 0,
        "break_dot_executable_seen": family_counts.get(("break", "executable"), 0) > 0,
        "true_damage_executable_seen": family_counts.get(("true_damage", "executable"), 0) > 0,
        "hp_loss_callback_tasks_blocked": not hp_loss_tasks or all(task.coverage_status != "executable" for task, _effect in hp_loss_tasks),
        "multi_status_damage_source_seen": any(len(items) > 1 for items in executable_by_callback.values()),
        "blocked_status_damage_seen": any(emission.coverage_status != "executable" for emission in ir.status_damage_emissions),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "family_coverage_counts": {f"{family}:{status}": count for (family, status), count in sorted(family_counts.items())},
        "classification_counts": dict(sorted(classifications.items())),
    }


def _select_true_damage_emission(ir, rules: RuleBook) -> StatusDamageEmissionIR:
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "true_damage" or emission.coverage_status != "executable":
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is not None and task is not None and callback.coverage_status == task.coverage_status == "executable":
            return emission
    raise RuntimeError("no executable true_damage status damage emission found")


def _select_break_dot_emission(ir, rules: RuleBook) -> dict[str, Any] | None:
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "break" or emission.coverage_status != "executable":
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is None or task is None or callback.coverage_status != "executable" or task.coverage_status != "executable":
            continue
        for break_status in rules.break_status_emissions():
            if break_status.coverage_status != "executable" or break_status.modifier_name != emission.modifier_name:
                continue
            template = rules.break_template(break_status.template_id)
            if template is not None and template.coverage_status == "executable":
                return {"emission": emission, "break_status": break_status}
    return None


def _select_formula_required_dot_emission(ir, rules: RuleBook) -> StatusDamageEmissionIR:
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "dot" or emission.coverage_status != "executable":
            continue
        if _expr_kind(emission.scaling_expr.get("damage_value")) != "missing":
            continue
        if not _expr_supported(emission.scaling_expr.get("damage_percentage")):
            continue
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is not None and task is not None and callback.coverage_status == task.coverage_status == "executable":
            return emission
    raise RuntimeError("no executable DoT emission requiring status formula binding found")


def _select_multi_dot_execution(ir, rules: RuleBook) -> dict[str, Any] | None:
    by_callback: dict[str, list[StatusDamageEmissionIR]] = defaultdict(list)
    for emission in ir.status_damage_emissions:
        if emission.coverage_status == "executable" and emission.damage_formula_family == "dot" and emission.event == "OnPhase1":
            by_callback[emission.callback_id].append(emission)
    bindings_by_file = _dot_bindings_by_ability_file(ir)
    for callback_id, emissions in sorted(by_callback.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(emissions) < 2:
            continue
        emission = emissions[0]
        formula_bindings = [binding.to_json() for binding in bindings_by_file.get(emission.source.source_path, ())]
        state = _state_for_status_damage_emission(
            emission,
            target_id="enemy:dot_target",
            caster_id="ally:dot_caster",
            formula_bindings=formula_bindings,
            trigger_callback_id=callback_id,
            dynamic_hashes=tuple(sorted({hash_key for item in emissions for hash_key in _hashes_for_status_damage(item)})),
            max_stacks=99,
            target_hp=5000.0,
        )
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id="enemy:dot_target",
            modifier_name=emission.modifier_name,
            event=emission.event,
        )
        mutations = _damage_mutations(result.mutations, family="dot")
        if len(mutations) >= 2 and (result.ok or _errors_recorded(result.errors, result.records)):
            return {
                "callback_id": callback_id,
                "modifier_name": emission.modifier_name,
                "source_emission_count": len(emissions),
                "state": state,
                "result": result,
            }
    return None


def _multi_status_damage_callback_count(ir) -> int:
    by_callback: dict[str, int] = defaultdict(int)
    for emission in ir.status_damage_emissions:
        if emission.coverage_status == "executable":
            by_callback[emission.callback_id] += 1
    return sum(1 for count in by_callback.values() if count > 1)


def _attach_break_status_source(state: BattleState, emission: StatusDamageEmissionIR, break_status) -> BattleState:
    target_id = "enemy:status_target"
    target = state.units[target_id]
    detail = dict(target.flags["status_details"][0])
    source_trace = dict(detail.get("source_trace") or {})
    effect_source = break_status.source.to_json()
    evidence = dict(effect_source.get("evidence") or {})
    evidence["break_status_emission_id"] = break_status.break_status_emission_id
    evidence["status_damage_emission_id"] = emission.status_damage_emission_id
    effect_source["evidence"] = evidence
    source_trace["effect_source"] = effect_source
    source_trace["break_status_source"] = break_status.source.to_json()
    detail["source_trace"] = source_trace
    patched = replace(
        target,
        flags={**target.flags, "status_details": (detail,)},
    )
    return replace(state, units={**state.units, target_id: patched})


def _state_for_status_damage_emission(
    emission: StatusDamageEmissionIR,
    *,
    target_id: str = "enemy:status_target",
    caster_id: str = "ally:status_caster",
    formula_bindings: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    trigger_callback_id: str | None = None,
    dynamic_hashes: tuple[str, ...] | None = None,
    dynamic_value: float = 0.25,
    max_stacks: int = 1,
    target_hp: float = 500.0,
) -> BattleState:
    hashes = tuple(dynamic_hashes) if dynamic_hashes is not None else _hashes_for_status_damage(emission)
    bindings = list(formula_bindings or [])
    detail = {
        "instance_id": f"status_instance:{emission.modifier_name}:p2_s8",
        "status_id": f"modifier:{emission.modifier_name}",
        "modifier_name": emission.modifier_name,
        "owner_id": target_id,
        "caster_id": caster_id,
        "source_id": f"validation:p2_s8:{emission.status_damage_emission_id}",
        "stacks": 1,
        "max_stacks": max_stacks,
        "duration": 2.0,
        "remaining_duration": 2.0,
        "duration_unit": "ModifierPhase1End",
        "life_step_moment": "ModifierPhase1End",
        "status_type": "Debuff",
        "status_category": "debuff",
        "dynamic_values": {"__by_hash": {hash_key: float(dynamic_value) for hash_key in hashes}},
        "formula_bindings": bindings,
        "trigger_ids_by_event": {emission.event: [trigger_callback_id or emission.callback_id]},
        "source_trace": {
            "selection_mode": VALIDATION_VERSION,
            "status_damage_source": emission.source.to_json(),
            "status_formula_bindings": bindings,
        },
    }
    return BattleState(
        units={
            caster_id: UnitState(
                unit_id=caster_id,
                side="ally",
                template_id="avatar:p2_s8_status_caster",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
            ),
            target_id: UnitState(
                unit_id=target_id,
                side="enemy",
                template_id="monster:p2_s8_status_target",
                max_hp=target_hp,
                hp=target_hp,
                defense=50.0,
                speed=100.0,
                statuses=(f"modifier:{emission.modifier_name}",),
                flags={"status_details": (detail,)},
            ),
        },
        global_flags={"phase": VALIDATION_VERSION},
    )


def _hashes_for_status_damage(emission: StatusDamageEmissionIR) -> tuple[str, ...]:
    hashes = set(_hashes_for_dot_emission(emission)) if emission.damage_formula_family == "dot" else set()
    hashes.update(_hashes_in(emission.scaling_expr))
    return tuple(sorted(hash_key for hash_key in hashes if hash_key))


def _hashes_in(value: object) -> set[str]:
    hashes: set[str] = set()
    if isinstance(value, dict):
        if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
            hashes.add(str(value.get("hash")))
        raw = value.get("raw")
        if isinstance(raw, dict):
            hashes.update(_hashes_in(raw))
        dynamic_hashes = value.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            hashes.update(str(item) for item in dynamic_hashes if isinstance(item, int))
        for item in value.values():
            hashes.update(_hashes_in(item))
    elif isinstance(value, list):
        for item in value:
            hashes.update(_hashes_in(item))
    return hashes


def _transition_checks(rules: RuleBook, transition: BattleTransition, *, before_state: BattleState) -> dict[str, Any]:
    contract = TransitionContractValidator().validate(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(
        before_state,
        transition.transaction.mutations,
        transition.after.to_json(),
    )
    checks = {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "source_audit": source_audit.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _sweep_transition(before_state: BattleState, after_state: BattleState, sweep, action_id: str) -> BattleTransition:
    command = ActionCommand(actor_id="enemy:dot_target", action_id=action_id, action_level=0, target_ids=("enemy:dot_target",))
    node_results = (
        ExecutionNodeResult("status_lifecycle", action_id, "complete"),
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=sweep.events,
            mutations=sweep.mutations,
            settlement=ActionSettlement(action_id, command.actor_id, command.target_ids, sweep.records),
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            legal=command.target_ids,
            selected=command.target_ids,
            reason=action_id,
            source="status_lifecycle_validation",
        ),
        rng_events=getattr(sweep, "rng_events", ()),
        outcome=classify_transition_outcome(
            node_results,
            state_changed=before_state.snapshot().to_json() != after_state.snapshot().to_json(),
            mutation_count=len(sweep.mutations),
        ),
        coverage={"validation": VALIDATION_VERSION, "action_id": action_id},
    )


def _callback_transition(
    before_state: BattleState,
    result,
    action_id: str,
    *,
    actor_id: str,
    target_id: str,
) -> BattleTransition:
    command = ActionCommand(actor_id=actor_id, action_id=action_id, action_level=0, target_ids=(target_id,))
    node_results = tuple(getattr(result, "node_results", ())) or (
        ExecutionNodeResult("status_callback", action_id, "complete" if result.ok else "blocked", "" if result.ok else ",".join(result.errors)),
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(action_id, actor_id, command.target_ids, result.records),
        ),
        after=result.after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            legal=command.target_ids,
            selected=command.target_ids,
            reason=action_id,
            source="status_callback_validation",
        ),
        rng_events=result.rng_events,
        outcome=classify_transition_outcome(
            node_results,
            state_changed=before_state.snapshot().to_json() != result.after_state.snapshot().to_json(),
            mutation_count=len(result.mutations),
            preflight_blocked=not result.ok and not result.mutations,
            preflight_reason=",".join(result.errors),
        ),
        coverage={"validation": VALIDATION_VERSION, "action_id": action_id},
    )


def _damage_mutations(mutations, *, family: str | None = None) -> list[Any]:
    result = [mutation for mutation in mutations if mutation.source == "damage_system" and tuple(mutation.path)[-1] == "hp"]
    if family is not None:
        result = [mutation for mutation in result if mutation.metadata.get("damage_formula_family") == family]
    return result


def _records_of_type(records, record_type: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("record_type") == record_type]


def _errors_recorded(errors, records) -> bool:
    if not errors:
        return True
    reason_text = " ".join(str(record.get("payload", {}).get("reason") or "") for record in records)
    return all(str(error) in reason_text for error in errors)


def _source_frame(mutation) -> dict[str, Any]:
    frame = mutation.metadata.get("source_frame") if isinstance(mutation.metadata, dict) else {}
    return frame if isinstance(frame, dict) else {}


def _first_index(items, predicate) -> int:
    for index, item in enumerate(items):
        if predicate(item):
            return index
    return -1


def _family_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def _compact_transition(transition: BattleTransition) -> dict[str, Any]:
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    return {
        "mutation_count": len(transition.transaction.mutations),
        "event_types": [event.event_type for event in transition.transaction.events],
        "record_counts": dict(Counter(str(record.get("record_type") or "") for record in records)),
        "mutation_sources": dict(Counter(mutation.source for mutation in transition.transaction.mutations)),
        "damage_mutations": [
            {
                "path": list(mutation.path),
                "damage_formula_family": mutation.metadata.get("damage_formula_family"),
                "status_damage_emission_id": mutation.metadata.get("status_damage_emission_id"),
                "source_frame": mutation.metadata.get("source_frame"),
                "final_damage": mutation.metadata.get("final_damage"),
            }
            for mutation in transition.transaction.mutations
            if mutation.source == "damage_system"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S8 status damage semantics.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
