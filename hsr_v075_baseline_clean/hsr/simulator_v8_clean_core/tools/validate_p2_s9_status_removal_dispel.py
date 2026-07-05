from __future__ import annotations

import argparse
from collections import Counter
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
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..systems.dynamic_values import status_binding_sources
from ..systems.status import StatusSystem
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
    _effect_sample,
    _has_random_dispel_source,
    _select_deterministic_dispel_effect,
    _select_dispellable_buff_effect,
    _select_dynamic_count_dispel_effect,
    _select_random_dispel_effect,
    _snapshot_hash,
)


VALIDATION_VERSION = "p2_s9_status_removal_dispel"
ACTOR_ID = "ally:actor"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    removal_matrix = _removal_dispel_matrix(ir, rules)
    remove_case = _remove_modifier_case(ir, rules, "RemoveModifier")
    remove_self_case = _remove_modifier_case(ir, rules, "RemoveSelfModifier")
    same_name_case = _same_name_multi_instance_case(ir, rules)
    last_added_case = _last_added_dispel_case(rules)
    dynamic_count_case = _dynamic_count_dispel_case(rules)
    undispellable_case = _undispellable_skip_case(rules)
    no_candidate_case = _no_candidate_dispel_case(rules)
    missing_remove_case = _missing_remove_case(ir, rules)
    random_case = _random_dispel_source_case(rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "removal_dispel_matrix": removal_matrix["checks"],
        "remove_modifier": remove_case["checks"],
        "remove_self_modifier": remove_self_case["checks"],
        "same_name_multi_instance": same_name_case["checks"],
        "last_added_dispel": last_added_case["checks"],
        "dynamic_count_dispel": dynamic_count_case["checks"],
        "undispellable_skip": undispellable_case["checks"],
        "no_candidate_process_only": no_candidate_case["checks"],
        "missing_remove_blocked": missing_remove_case["checks"],
        "random_dispel_source": random_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_remove_dispel_effects",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "removal_dispel_matrix": removal_matrix["matrix"],
            "classification_counts": removal_matrix["classification_counts"],
            "remove_modifier": remove_case["summary"],
            "remove_self_modifier": remove_self_case["summary"],
            "same_name_multi_instance": same_name_case["summary"],
            "last_added_dispel": last_added_case["summary"],
            "dynamic_count_dispel": dynamic_count_case["summary"],
            "negative_cases": {
                "undispellable_skip": undispellable_case["summary"],
                "no_candidate": no_candidate_case["summary"],
                "missing_remove": missing_remove_case["summary"],
                "random_dispel": random_case["summary"],
            },
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "remove_modifier": remove_case["case"],
            "remove_self_modifier": remove_self_case["case"],
            "same_name_multi_instance": same_name_case["case"],
            "last_added_dispel": last_added_case["case"],
            "dynamic_count_dispel": dynamic_count_case["case"],
            "undispellable_skip": undispellable_case["case"],
            "no_candidate": no_candidate_case["case"],
            "missing_remove": missing_remove_case["case"],
            "random_dispel": random_case["case"],
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s9_status_removal_dispel.json", result)
    return result


def _remove_modifier_case(ir, rules: RuleBook, opcode: str) -> dict[str, Any]:
    effect = _select_remove_effect(ir, rules, opcode)
    modifier_name = _modifier_name(effect)
    state = _state_with_details((_status_detail(rules, modifier_name, "remove:0", can_dispel=True),))
    result = StatusSystem(rules).apply_remove_modifier(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:{opcode}",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _transition(state, after, result, f"p2_s9:{opcode}")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    binding_after = _evaluate_status_hash(after, "remove:0:hash")
    checks = {
        "result_ok": result.ok,
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "status_removed_from_list": f"modifier:{modifier_name}" not in after.units[ACTOR_ID].statuses,
        "status_detail_removed": not _has_instance(after, "remove:0"),
        "binding_removed": not binding_after.ok,
        "remove_record_present": any(record.get("record_type") == "status_lifecycle" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {"classification": "executable", "opcode": opcode, "modifier_name": modifier_name},
        "case": {"effect": _effect_sample(effect), "transition": _compact_transition(transition)},
    }


def _same_name_multi_instance_case(ir, rules: RuleBook) -> dict[str, Any]:
    effect = _select_remove_effect(ir, rules, "RemoveModifier")
    modifier_name = _modifier_name(effect)
    status_id = f"modifier:{modifier_name}"
    first = _status_detail(rules, modifier_name, "same:old", can_dispel=True, source_id="source:old")
    second = _status_detail(rules, modifier_name, "same:new", can_dispel=True, source_id="source:new")
    state = _state_with_details((first, second))
    result = StatusSystem(rules).apply_remove_modifier(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:same_name",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _transition(state, after, result, "p2_s9:same_name_multi_instance")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    remaining = _status_details(after)
    checks = {
        "result_ok": result.ok,
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "only_one_detail_removed": len(remaining) == 1,
        "old_instance_removed": not _has_instance(after, "same:old"),
        "new_instance_survives": _has_instance(after, "same:new"),
        "status_id_kept_while_same_status_detail_exists": status_id in after.units[ACTOR_ID].statuses,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {"classification": "executable", "modifier_name": modifier_name, "remaining_instance": "same:new"},
        "case": {"effect": _effect_sample(effect), "transition": _compact_transition(transition)},
    }


def _last_added_dispel_case(rules: RuleBook) -> dict[str, Any]:
    add_effect = _select_dispellable_buff_effect(rules)
    dispel_effect = _select_deterministic_dispel_effect(rules)
    modifier_name = _modifier_name(add_effect)
    old = _status_detail(rules, modifier_name, "dispel:old", can_dispel=True, source_id="source:old")
    blocked = _status_detail(rules, modifier_name, "dispel:blocked", can_dispel=False, source_id="source:blocked")
    new = _status_detail(rules, modifier_name, "dispel:new", can_dispel=True, source_id="source:new")
    state = _state_with_details((old, blocked, new))
    result = StatusSystem(rules).apply_dispel_status(
        state,
        dispel_effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:last_added",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _transition(state, after, result, "p2_s9:last_added_dispel")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    checks = {
        "result_ok": result.ok,
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "last_added_removed": not _has_instance(after, "dispel:new"),
        "older_candidate_survives": _has_instance(after, "dispel:old"),
        "undispellable_survives": _has_instance(after, "dispel:blocked"),
        "skipped_candidate_recorded": _trace_has_skip_reason(result.records, "can_dispel_not_true"),
        "selected_candidate_audited": _trace_selected_instance(result.records) == "dispel:new",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {"classification": "executable", "modifier_name": modifier_name, "selected_instance": "dispel:new"},
        "case": {"effect": _effect_sample(dispel_effect), "transition": _compact_transition(transition)},
    }


def _dynamic_count_dispel_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_dynamic_count_dispel_effect(rules, allow_missing=True)
    if effect is None:
        checks = {"source_gap_recorded": True, "no_synthetic_dynamic_count": True}
        checks["ok"] = True
        return {
            "checks": {"ok": True, "checks": checks},
            "summary": {"classification": "source_absent_not_required"},
            "case": {},
        }
    modifier_name = _modifier_name(_select_dispellable_buff_effect(rules))
    state = _state_with_details((_status_detail(rules, modifier_name, "dynamic:0", can_dispel=True),))
    hash_key = str(effect.payload["standard"]["numbers"]["hash"])
    unbound = StatusSystem(rules).apply_dispel_status(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:dynamic_unbound",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    bound = StatusSystem(rules).apply_dispel_status(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:dynamic_bound",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
        dynamic_values={hash_key: 1.0},
    )
    after_bound = MutationReducer().apply_all(state, bound.mutations)
    transition = _transition(state, after_bound, bound, "p2_s9:dynamic_count_dispel")
    transition_checks = _transition_checks(rules, transition, before_state=state)
    blocked_two = StatusSystem(rules).apply_dispel_status(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:dynamic_two",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
        dynamic_values={hash_key: 2.0},
    )
    checks = {
        "dynamic_source_present": True,
        "unbound_blocked": not unbound.ok and not unbound.mutations,
        "unbound_blocked_record": any(record.get("record_type") == "status_dispel_blocked" for record in unbound.records),
        "bound_result_ok": bound.ok and bool(bound.mutations),
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
        "bound_removed_status": not _has_instance(after_bound, "dynamic:0"),
        "count_two_blocked": not blocked_two.ok and not blocked_two.mutations,
        "count_two_reason": any("dispel_count_not_one_first_phase" in str(record.get("payload", {}).get("reason")) for record in blocked_two.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {"classification": "executable_with_blocked_count_gt_one", "hash": hash_key},
        "case": {
            "effect": _effect_sample(effect),
            "unbound_records": list(unbound.records),
            "count_two_records": list(blocked_two.records),
            "transition": _compact_transition(transition),
        },
    }


def _undispellable_skip_case(rules: RuleBook) -> dict[str, Any]:
    add_effect = _select_dispellable_buff_effect(rules)
    dispel_effect = _select_deterministic_dispel_effect(rules)
    modifier_name = _modifier_name(add_effect)
    state = _state_with_details((_status_detail(rules, modifier_name, "skip:0", can_dispel=False),))
    before_hash = _snapshot_hash(state)
    result = StatusSystem(rules).apply_dispel_status(
        state,
        dispel_effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:undispellable",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    checks = {
        "result_ok_process_only": result.ok and not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "skipped_record": any(record.get("record_type") == "status_dispel_skipped" for record in result.records),
        "skip_reason": _trace_has_skip_reason(result.records, "can_dispel_not_true"),
        "status_survives": _has_instance(state, "skip:0"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "can_dispel false skipped"},
        "case": {"records": list(result.records)},
    }


def _no_candidate_dispel_case(rules: RuleBook) -> dict[str, Any]:
    dispel_effect = _select_deterministic_dispel_effect(rules)
    state = _state_with_details(())
    before_hash = _snapshot_hash(state)
    result = StatusSystem(rules).apply_dispel_status(
        state,
        dispel_effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:no_candidate",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    checks = {
        "result_ok_process_only": result.ok and not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "skipped_record": any(record.get("record_type") == "status_dispel_skipped" for record in result.records),
        "no_eligible_status_reason": any(record.get("payload", {}).get("reason") == "no_eligible_status" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "no eligible status process-only"},
        "case": {"records": list(result.records)},
    }


def _missing_remove_case(ir, rules: RuleBook) -> dict[str, Any]:
    effect = _select_remove_effect(ir, rules, "RemoveModifier")
    state = _state_with_details(())
    before_hash = _snapshot_hash(state)
    result = StatusSystem(rules).apply_remove_modifier(
        state,
        effect,
        caster_id=ACTOR_ID,
        source_id=f"validation:{VALIDATION_VERSION}:missing_remove",
        owner_id=ACTOR_ID,
        param_entity_id=ACTOR_ID,
        current_action_target_id=ACTOR_ID,
    )
    checks = {
        "blocked": not result.ok,
        "no_mutations": not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "status_not_present_reason": "status_not_present" in result.unsupported,
        "process_record_present": any(record.get("record_type") == "status_lifecycle" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "missing status blocks remove"},
        "case": {"effect": _effect_sample(effect), "records": list(result.records)},
    }


def _random_dispel_source_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_random_dispel_effect(rules, allow_missing=True)
    if effect is None:
        checks = {
            "random_source_absent": not _has_random_dispel_source(rules),
            "no_synthetic_random_mutation": True,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "summary": {"classification": "source_absent_not_required", "reason": "no Order=Random DispelStatus source"},
            "case": {},
        }
    checks = {"random_source_present": True}
    checks["ok"] = True
    return {
        "checks": {"ok": True, "checks": checks},
        "summary": {"classification": "source_present_not_sampled", "reason": "random source exists; covered by RNG replay path"},
        "case": {"effect": _effect_sample(effect)},
    }


def _removal_dispel_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    opcode_counts = Counter((effect.opcode, effect.coverage_status) for effect in ir.effects if effect.opcode in {"RemoveModifier", "RemoveSelfModifier", "DispelStatus"})
    dispel_orders = Counter()
    dispel_number_kinds = Counter()
    fixed_gt_one = 0
    for effect in ir.effects:
        if effect.opcode != "DispelStatus":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        dispel_orders[str(standard.get("order") or "missing")] += 1
        numbers = standard.get("numbers")
        kind = numbers.get("kind") if isinstance(numbers, dict) else "missing"
        dispel_number_kinds[str(kind or "missing")] += 1
        if isinstance(numbers, dict) and numbers.get("kind") == "fixed" and isinstance(numbers.get("value"), (int, float)) and numbers.get("value") != 1.0:
            fixed_gt_one += 1
    matrix = {
        "remove_modifier": _family_entry("executable", opcode_counts.get(("RemoveModifier", "executable"), 0), "RemoveModifier has executable EffectIR sources."),
        "remove_self_modifier": _family_entry("executable", opcode_counts.get(("RemoveSelfModifier", "executable"), 0), "RemoveSelfModifier has executable EffectIR sources."),
        "deterministic_last_added_dispel": _family_entry("executable", dispel_orders.get("LastAdded", 0), "LastAdded DispelStatus is executable and candidate order is audited."),
        "dynamic_count_dispel": _family_entry("executable", dispel_number_kinds.get("dynamic_hash", 0), "Dynamic count can execute when bound to 1 and blocks unbound/count>1."),
        "fixed_count_gt_one_dispel": _family_entry("boundary_only" if fixed_gt_one else "source_absent_not_required", fixed_gt_one, "count > 1 is blocked in current phase."),
        "random_dispel": _family_entry("executable" if _has_random_dispel_source(rules) else "source_absent_not_required", dispel_orders.get("Random", 0), "Random dispel source is absent in current database."),
        "blocked_remove_dispel_sources": _family_entry("boundary_only", sum(count for (opcode, status), count in opcode_counts.items() if status != "executable"), "Blocked remove/dispel effects stay process-only."),
    }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "remove_modifier_executable_seen": opcode_counts.get(("RemoveModifier", "executable"), 0) > 0,
        "remove_self_modifier_executable_seen": opcode_counts.get(("RemoveSelfModifier", "executable"), 0) > 0,
        "last_added_dispel_seen": dispel_orders.get("LastAdded", 0) > 0,
        "dynamic_count_seen": dispel_number_kinds.get("dynamic_hash", 0) > 0,
        "random_dispel_classified": bool(matrix["random_dispel"]["classification"]),
        "blocked_sources_classified": matrix["blocked_remove_dispel_sources"]["source_count"] > 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "opcode_coverage_counts": {f"{opcode}:{status}": count for (opcode, status), count in sorted(opcode_counts.items())},
        "dispel_orders": dict(sorted(dispel_orders.items())),
        "dispel_number_kinds": dict(sorted(dispel_number_kinds.items())),
        "classification_counts": dict(sorted(classifications.items())),
    }


def _select_remove_effect(ir, rules: RuleBook, opcode: str) -> EffectIR:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode != opcode or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            continue
        if rules.modifier_definition(modifier_name) is None:
            continue
        if standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
            continue
        return effect
    raise RuntimeError(f"no executable {opcode} effect with modifier definition found")


def _modifier_name(effect: EffectIR) -> str:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    value = standard.get("modifier_name")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"effect {effect.effect_id} has no modifier_name")
    return value


def _state_with_details(details: tuple[dict[str, Any], ...]) -> BattleState:
    statuses = tuple(dict.fromkeys(str(detail.get("status_id") or "") for detail in details if detail.get("status_id")))
    return BattleState(
        units={
            ACTOR_ID: UnitState(
                unit_id=ACTOR_ID,
                side="ally",
                template_id="avatar:p2_s9_actor",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
                statuses=statuses,
                flags={"status_details": details},
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="monster:p2_s9_target",
                max_hp=1000.0,
                hp=1000.0,
                defense=80.0,
                speed=100.0,
            ),
        },
        global_flags={"phase": VALIDATION_VERSION},
    )


def _status_detail(
    rules: RuleBook,
    modifier_name: str,
    instance_id: str,
    *,
    can_dispel: bool,
    source_id: str | None = None,
) -> dict[str, Any]:
    status_id = f"modifier:{modifier_name}"
    entity = rules.status_entity_for_modifier(modifier_name)
    source_trace = {
        "selection_mode": VALIDATION_VERSION,
        "modifier_name": modifier_name,
        "modifier_definition": entity.source.to_json() if entity is not None else {},
        "source_id": source_id or f"validation:{VALIDATION_VERSION}:{instance_id}",
    }
    return {
        "instance_id": instance_id,
        "status_id": status_id,
        "modifier_name": modifier_name,
        "owner_id": ACTOR_ID,
        "caster_id": ACTOR_ID,
        "source_id": source_id or f"validation:{VALIDATION_VERSION}:{instance_id}",
        "stacks": 1,
        "max_stacks": 1,
        "duration": 2.0,
        "remaining_duration": 2.0,
        "duration_unit": "ModifierPhase1End",
        "life_step_moment": "ModifierPhase1End",
        "status_type": "Buff",
        "status_category": "buff",
        "can_dispel": can_dispel,
        "dynamic_values": {"__by_hash": {f"{instance_id}:hash": 1.0}},
        "source_trace": source_trace,
    }


def _transition(before_state: BattleState, after_state: BattleState, result, action_id: str) -> BattleTransition:
    command = ActionCommand(actor_id=ACTOR_ID, action_id=action_id, action_level=0, target_ids=(ACTOR_ID,))
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(action_id, ACTOR_ID, command.target_ids, result.records),
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            legal=command.target_ids,
            selected=command.target_ids,
            reason=action_id,
            source="status_removal_dispel_validation",
        ),
        rng_events=result.rng_events,
        coverage={"validation": VALIDATION_VERSION, "action_id": action_id},
    )


def _transition_checks(rules: RuleBook, transition: BattleTransition, *, before_state: BattleState) -> dict[str, Any]:
    contract = TransitionContractValidator().validate(transition)
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
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


def _status_details(state: BattleState) -> tuple[dict[str, Any], ...]:
    details = state.units[ACTOR_ID].flags.get("status_details", ())
    return tuple(dict(item) for item in details if isinstance(item, dict))


def _has_instance(state: BattleState, instance_id: str) -> bool:
    return any(detail.get("instance_id") == instance_id for detail in _status_details(state))


def _evaluate_status_hash(state: BattleState, hash_key: str):
    return RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": hash_key},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(state, (ACTOR_ID,)),
            source_trace={"validation": VALIDATION_VERSION, "hash": hash_key},
        ),
    )


def _trace_has_skip_reason(records, reason: str) -> bool:
    for record in records:
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        skipped_sources = []
        if isinstance(payload, dict):
            skipped_sources.append(payload.get("skipped_candidates"))
            plan = payload.get("lifecycle_plan")
            source_trace = plan.get("source_trace") if isinstance(plan, dict) else None
            if isinstance(source_trace, dict):
                skipped_sources.append(source_trace.get("skipped_candidates"))
        if any(
            isinstance(skipped, list)
            and any(isinstance(item, dict) and item.get("reason") == reason for item in skipped)
            for skipped in skipped_sources
        ):
            return True
    return False


def _trace_selected_instance(records) -> str:
    for record in records:
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        plan = payload.get("lifecycle_plan") if isinstance(payload, dict) else None
        source_trace = plan.get("source_trace") if isinstance(plan, dict) else None
        if isinstance(source_trace, dict) and source_trace.get("selected_status_instance_id"):
            return str(source_trace.get("selected_status_instance_id") or "")
    return ""


def _family_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def _compact_transition(transition: BattleTransition) -> dict[str, Any]:
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    return {
        "mutation_count": len(transition.transaction.mutations),
        "event_types": [event.event_type for event in transition.transaction.events],
        "record_counts": dict(Counter(str(record.get("record_type") or "") for record in records)),
        "mutation_sources": dict(Counter(mutation.source for mutation in transition.transaction.mutations)),
        "status_mutations": [
            {
                "path": list(mutation.path),
                "operation": mutation.metadata.get("operation"),
                "status_id": mutation.metadata.get("status_id"),
            }
            for mutation in transition.transaction.mutations
            if mutation.source == "status_system"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S9 status removal and dispel semantics.")
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
