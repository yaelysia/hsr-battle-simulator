from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import EffectIR, StatusCallbackIR, StatusCallbackTaskIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..systems.status_callbacks import StatusCallbackExecutionResult, StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p2_status_coverage import (
    build_p2_status_coverage_matrix,
    validate_p2_ir_rulebook_integrity_matrix,
    validate_p2_status_inventory_matrix,
)
from .static_checks import run_static_checks
from .validate_p1_4_status_system import _effect_sample, _snapshot_hash
from .validate_p2_s8_status_damage import (
    _select_true_damage_emission,
    _state_for_status_damage_emission,
)


VALIDATION_VERSION = "p2_s10_status_callback_coverage"
OWNER_ID = "ally:status_owner"
CASTER_ID = "ally:status_caster"
TARGET_ID = "enemy:status_target"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    event_matrix = _event_family_matrix(ir, rules)
    task_matrix = _task_opcode_matrix(ir, rules)
    callback_source_case = _executable_callback_source_case(ir, rules)
    add_case = _effect_mutation_case(ir, rules, "AddModifier")
    remove_case = _effect_mutation_case(ir, rules, "RemoveModifier")
    remove_self_case = _effect_mutation_case(ir, rules, "RemoveSelfModifier")
    dynamic_case = _effect_mutation_case(ir, rules, "SetDynamicValue")
    queue_case = _queue_insert_case(ir, rules)
    delay_case = _action_delay_case(ir, rules)
    status_damage_case = _status_damage_case(ir, rules)
    missing_status_case = _missing_status_case(ir, rules)
    missing_event_source_case = _missing_event_source_case(rules)
    missing_wave_payload_case = _missing_wave_payload_case(rules)
    missing_condition_case = _missing_condition_case(ir, rules)
    missing_target_case = _missing_target_case(ir, rules)
    unsupported_task_case = _unsupported_task_case(ir, rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "event_family_matrix": event_matrix["checks"],
        "task_opcode_matrix": task_matrix["checks"],
        "executable_callback_sources": callback_source_case["checks"],
        "add_modifier_callback": add_case["checks"],
        "remove_modifier_callback": remove_case["checks"],
        "remove_self_modifier_callback": remove_self_case["checks"],
        "dynamic_value_callback": dynamic_case["checks"],
        "queue_insert_callback": queue_case["checks"],
        "action_delay_callback": delay_case["checks"],
        "status_damage_callback": status_damage_case["checks"],
        "missing_status_blocked": missing_status_case["checks"],
        "missing_event_source_blocked": missing_event_source_case["checks"],
        "missing_wave_payload_blocked": missing_wave_payload_case["checks"],
        "missing_condition_blocked": missing_condition_case["checks"],
        "missing_target_blocked": missing_target_case["checks"],
        "unsupported_task_blocked": unsupported_task_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_callback_events_and_tasks",
                "runtime_behavior_changed": True,
                "runtime_change": (
                    "Status callback ParamEntity/CurrentActionTarget resolution no longer falls back "
                    "to the status owner when trigger payload is missing."
                ),
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "event_family_matrix": event_matrix["matrix"],
            "event_family_classification_counts": event_matrix["classification_counts"],
            "task_opcode_matrix": task_matrix["matrix"],
            "task_opcode_classification_counts": task_matrix["classification_counts"],
            "positive_cases": {
                "add_modifier": add_case["summary"],
                "remove_modifier": remove_case["summary"],
                "remove_self_modifier": remove_self_case["summary"],
                "dynamic_value": dynamic_case["summary"],
                "queue_insert": queue_case["summary"],
                "action_delay": delay_case["summary"],
                "status_damage": status_damage_case["summary"],
            },
            "negative_cases": {
                "missing_status": missing_status_case["summary"],
                "missing_event_source": missing_event_source_case["summary"],
                "missing_wave_payload": missing_wave_payload_case["summary"],
                "missing_condition": missing_condition_case["summary"],
                "missing_target": missing_target_case["summary"],
                "unsupported_task": unsupported_task_case["summary"],
            },
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "callback_source_sample": callback_source_case["case"],
            "add_modifier": add_case["case"],
            "remove_modifier": remove_case["case"],
            "remove_self_modifier": remove_self_case["case"],
            "dynamic_value": dynamic_case["case"],
            "queue_insert": queue_case["case"],
            "action_delay": delay_case["case"],
            "status_damage": status_damage_case["case"],
            "missing_status": missing_status_case["case"],
            "missing_event_source": missing_event_source_case["case"],
            "missing_wave_payload": missing_wave_payload_case["case"],
            "missing_condition": missing_condition_case["case"],
            "missing_target": missing_target_case["case"],
            "unsupported_task": unsupported_task_case["case"],
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s10_status_callback_coverage.json", result)
    return result


def _event_family_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    events_from_callbacks = {callback.event for callback in ir.status_callbacks}
    events_from_families = {family.callback_event for family in ir.status_event_families}
    family_counts = Counter((family.event_family, family.coverage_status) for family in ir.status_event_families)
    required_families = {
        "status_lifecycle",
        "hit",
        "death",
        "turn",
        "action_or_queue",
        "wave",
        "resource",
    }
    matrix: dict[str, Any] = {}
    for family in sorted(ir.status_event_families, key=lambda item: item.callback_event):
        reason = family.blocking_dependency or family.blocked_reason
        classification = "executable" if family.coverage_status == "executable" else "boundary_only"
        matrix[family.callback_event] = {
            "classification": classification,
            "event_family": family.event_family,
            "coverage_status": family.coverage_status,
            "admission_status": family.admission_status,
            "callback_count": family.callback_count,
            "task_count": family.task_count,
            "executable_callback_count": family.executable_callback_count,
            "blocked_callback_count": family.blocked_callback_count,
            "runtime_event_sources": list(family.runtime_event_sources),
            "blocked_reason": reason,
            "source_path": family.source.source_path,
        }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    executable_families = [family for family in ir.status_event_families if family.coverage_status == "executable"]
    blocked_families = [family for family in ir.status_event_families if family.coverage_status != "executable"]
    checks = {
        "families_cover_all_callback_events": events_from_callbacks == events_from_families,
        "required_event_families_present": required_families.issubset({family.event_family for family in ir.status_event_families}),
        "all_family_rulebook_visible": all(rules.status_event_family(family.callback_event) is not None for family in ir.status_event_families),
        "executable_families_have_runtime_sources": all(family.runtime_event_sources for family in executable_families),
        "blocked_families_have_reasons": all(family.blocking_dependency or family.blocked_reason for family in blocked_families),
        "event_family_source_trace_complete": all(family.source.source_path and family.source.raw_id for family in ir.status_event_families),
        "not_p1_only_event_support": len(executable_families) > 2 and any(family.callback_event not in {"OnPhase1", "OnAfterBeingAttacked"} for family in executable_families),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "family_coverage_counts": {f"{family}:{status}": count for (family, status), count in sorted(family_counts.items())},
        "classification_counts": dict(sorted(classifications.items())),
    }


def _task_opcode_matrix(ir, rules: RuleBook) -> dict[str, Any]:
    status_damage_tasks = {emission.source_task_id for emission in ir.status_damage_emissions}
    delay_tasks = {emission.source_task_id for emission in ir.action_delay_emissions}
    queue_tasks = {intent.source_task_id for intent in ir.queue_intents}
    damage_modifier_tasks = {modifier.source_task_id for modifier in ir.damage_modifiers}
    counts = Counter((task.opcode, task.coverage_status) for task in ir.status_callback_tasks)
    matrix: dict[str, Any] = {}
    unhandled_executable: list[StatusCallbackTaskIR] = []
    non_executable_without_reason: list[StatusCallbackTaskIR] = []
    for task in ir.status_callback_tasks:
        if task.coverage_status != "executable":
            if not task.blocked_reason and not (task.opcode == "PredicateTaskList" and task.coverage_status == "lowered"):
                non_executable_without_reason.append(task)
            continue
        if _task_runtime_category(task, status_damage_tasks, delay_tasks, queue_tasks, damage_modifier_tasks) == "unhandled":
            unhandled_executable.append(task)
    for opcode in sorted({task.opcode for task in ir.status_callback_tasks}):
        coverage = {status: count for (item_opcode, status), count in counts.items() if item_opcode == opcode}
        source_count = sum(coverage.values())
        executable_count = coverage.get("executable", 0)
        lowered_count = coverage.get("lowered", 0)
        blocked_count = source_count - executable_count - lowered_count
        if executable_count > 0:
            classification = "executable"
        elif opcode == "PredicateTaskList" and lowered_count > 0:
            classification = "executable_control"
        else:
            classification = "boundary_only"
        matrix[opcode] = {
            "classification": classification,
            "source_count": source_count,
            "coverage_counts": dict(sorted(coverage.items())),
            "blocked_count": blocked_count,
            "runtime_categories": dict(
                sorted(
                    Counter(
                        _task_runtime_category(task, status_damage_tasks, delay_tasks, queue_tasks, damage_modifier_tasks)
                        for task in ir.status_callback_tasks
                        if task.opcode == opcode and task.coverage_status == "executable"
                    ).items()
                )
            ),
        }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    required_opcodes = {
        "PredicateTaskList",
        "Retarget",
        "AddModifier",
        "RemoveModifier",
        "RemoveSelfModifier",
        "DispelStatus",
        "SetDynamicValue",
        "TurnInsertAbility",
        "SetActionDelay",
        "DamageByAttackProperty",
    }
    checks = {
        "required_callback_opcodes_seen": required_opcodes.issubset(matrix),
        "all_non_executable_tasks_have_reason_or_control_lowered": not non_executable_without_reason,
        "no_unhandled_executable_task": not unhandled_executable,
        "unsupported_opcode_sources_classified": any(
            item["classification"] == "boundary_only" and item["blocked_count"] > 0 for item in matrix.values()
        ),
        "dispel_callback_task_boundary_classified": matrix.get("DispelStatus", {}).get("classification") == "boundary_only",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {
            "ok": checks["ok"],
            "checks": checks,
            "unhandled_executable_samples": [_task_sample(task) for task in unhandled_executable[:10]],
            "non_executable_without_reason_samples": [_task_sample(task) for task in non_executable_without_reason[:10]],
        },
        "matrix": matrix,
        "classification_counts": dict(sorted(classifications.items())),
    }


def _task_runtime_category(
    task: StatusCallbackTaskIR,
    status_damage_tasks: set[str],
    delay_tasks: set[str],
    queue_tasks: set[str],
    damage_modifier_tasks: set[str],
) -> str:
    if task.opcode == "Retarget":
        return "retarget_control"
    if task.opcode == "SetDynamicValueByDamageDataProperty":
        return "dynamic_value_damage_property"
    if task.effect_id:
        return "effect_registry"
    if task.task_id in status_damage_tasks:
        return "status_damage"
    if task.task_id in delay_tasks:
        return "action_delay"
    if task.task_id in queue_tasks:
        return "queue_intent"
    if task.task_id in damage_modifier_tasks:
        return "damage_modifier_downstream"
    return "unhandled"


def _executable_callback_source_case(ir, rules: RuleBook) -> dict[str, Any]:
    executable_callbacks = [
        callback
        for callback in ir.status_callbacks
        if callback.coverage_status == "executable" and callback.admission_status == "executable"
    ]
    missing_source = [
        callback
        for callback in executable_callbacks
        if not callback.source.source_path
        or not callback.source.raw_id
        or callback.source.source_path.startswith("CanonicalIR/")
        or not isinstance(callback.source.evidence, dict)
        or callback.source.evidence.get("event") != callback.event
    ]
    missing_family = []
    missing_runtime_source = []
    for callback in executable_callbacks:
        family = rules.status_event_family(callback.event)
        if family is None:
            missing_family.append(callback)
            continue
        if family.coverage_status != "executable" or not family.runtime_event_sources:
            missing_runtime_source.append(callback)
    checks = {
        "executable_callbacks_seen": bool(executable_callbacks),
        "all_executable_callbacks_have_raw_source_evidence": not missing_source,
        "all_executable_callbacks_have_event_family": not missing_family,
        "all_executable_callbacks_have_runtime_event_source": not missing_runtime_source,
        "not_p1_only_callbacks": len({callback.event for callback in executable_callbacks}) > 2,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    sample = executable_callbacks[0] if executable_callbacks else None
    return {
        "checks": {
            "ok": checks["ok"],
            "checks": checks,
            "missing_source_samples": [callback.to_json() for callback in missing_source[:5]],
            "missing_runtime_source_samples": [callback.to_json() for callback in missing_runtime_source[:5]],
        },
        "summary": {
            "classification": "executable",
            "executable_callback_count": len(executable_callbacks),
            "event_count": len({callback.event for callback in executable_callbacks}),
        },
        "case": {"sample_callback": sample.to_json() if sample is not None else {}},
    }


def _effect_mutation_case(ir, rules: RuleBook, opcode: str) -> dict[str, Any]:
    last_error = ""
    for callback, task, effect in _iter_root_effect_tasks(ir, rules, opcode):
        state = _state_for_effect_task(callback, effect)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        if result.ok and result.mutations:
            transition = _callback_transition(state, result, f"p2_s10:{opcode}", actor_id=CASTER_ID, target_id=OWNER_ID)
            transition_checks = _transition_checks(rules, transition, before_state=state)
            checks = {
                "case_found": True,
                "result_ok": result.ok,
                "mutation_present": bool(result.mutations),
                "transition_contract": transition_checks["checks"]["transition_contract"],
                "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
                "source_audit": transition_checks["checks"]["source_audit"],
                "replay": transition_checks["checks"]["replay"],
                "source_trace_present": all(mutation.metadata for mutation in result.mutations),
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
                "summary": {
                    "classification": "executable",
                    "opcode": opcode,
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                    "mutation_count": len(result.mutations),
                },
                "case": {
                    "callback": callback.to_json(),
                    "task": task.to_json(),
                    "effect": _effect_sample(effect),
                    "transition": _compact_transition(transition),
                },
            }
        last_error = ",".join(result.errors)
    checks = {"case_found": False, "last_error": bool(last_error)}
    checks["ok"] = False
    return {
        "checks": {"ok": False, "checks": checks},
        "summary": {"classification": "implementation_missing", "opcode": opcode, "last_error": last_error},
        "case": {},
    }


def _queue_insert_case(ir, rules: RuleBook) -> dict[str, Any]:
    for callback, task in _iter_root_tasks(ir, rules, {"TurnInsertAbility", "TurnInsertAction"}):
        intents = tuple(
            intent
            for intent in rules.queue_intents_for_callback(callback.callback_id)
            if intent.source_task_id == task.task_id and intent.coverage_status == "executable"
        )
        if not intents:
            continue
        if not any((rules.queue_window_for_intent(intent.queue_intent_id) or None) for intent in intents):
            continue
        state = _state_for_callback(callback)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        if result.ok and any(mutation.source == "queue_system" for mutation in result.mutations):
            transition = _callback_transition(state, result, "p2_s10:queue_insert", actor_id=CASTER_ID, target_id=OWNER_ID)
            transition_checks = _transition_checks(rules, transition, before_state=state)
            checks = {
                "case_found": True,
                "result_ok": result.ok,
                "queue_mutation_present": any(mutation.source == "queue_system" for mutation in result.mutations),
                "queue_record_present": any(record.get("record_type") == "queue_enqueue" for record in result.records),
                "transition_contract": transition_checks["checks"]["transition_contract"],
                "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
                "source_audit": transition_checks["checks"]["source_audit"],
                "replay": transition_checks["checks"]["replay"],
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
                "summary": {
                    "classification": "executable",
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                    "queue_mutation_count": sum(1 for mutation in result.mutations if mutation.source == "queue_system"),
                },
                "case": {"callback": callback.to_json(), "task": task.to_json(), "transition": _compact_transition(transition)},
            }
    return _missing_positive_case("queue_insert")


def _action_delay_case(ir, rules: RuleBook) -> dict[str, Any]:
    for callback, task in _iter_root_tasks(ir, rules, {"SetActionDelay"}):
        emissions = tuple(
            emission
            for emission in rules.action_delay_emissions_for_callback(callback.callback_id)
            if emission.source_task_id == task.task_id and emission.coverage_status == "executable"
        )
        if not emissions:
            continue
        hashes = tuple(sorted({hash_key for emission in emissions for hash_key in _hashes_in(emission.delay_expr)}))
        state = _state_for_callback(callback, dynamic_hashes=hashes, dynamic_value=25.0)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        if any(tuple(mutation.path)[-1] == "action_value" for mutation in result.mutations):
            transition = _callback_transition(state, result, "p2_s10:action_delay", actor_id=CASTER_ID, target_id=OWNER_ID)
            transition_checks = _transition_checks(rules, transition, before_state=state)
            checks = {
                "case_found": True,
                "result_ok_or_blocked_branches_recorded": result.ok or _errors_recorded(result.errors, result.records),
                "action_value_mutation_present": any(tuple(mutation.path)[-1] == "action_value" for mutation in result.mutations),
                "action_delay_record_present": any(record.get("record_type") == "action_delay" for record in result.records),
                "transition_contract": transition_checks["checks"]["transition_contract"],
                "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
                "source_audit": transition_checks["checks"]["source_audit"],
                "replay": transition_checks["checks"]["replay"],
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
                "summary": {
                    "classification": "executable",
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                    "emission_count": len(emissions),
                },
                "case": {"callback": callback.to_json(), "task": task.to_json(), "transition": _compact_transition(transition)},
            }
    return _missing_positive_case("action_delay")


def _status_damage_case(ir, rules: RuleBook) -> dict[str, Any]:
    emission = _select_true_damage_emission(ir, rules)
    state = _state_for_status_damage_emission(emission, dynamic_value=43.0)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id=TARGET_ID,
        modifier_name=emission.modifier_name,
        event=emission.event,
    )
    transition = _callback_transition(state, result, "p2_s10:status_damage", actor_id=CASTER_ID, target_id=TARGET_ID)
    transition_checks = _transition_checks(rules, transition, before_state=state)
    checks = {
        "case_found": emission is not None,
        "result_ok": result.ok,
        "damage_mutation_present": any(mutation.source == "damage_system" for mutation in result.mutations),
        "status_damage_record_present": any(
            record.get("record_type") == "damage"
            and isinstance(record.get("payload"), dict)
            and isinstance(record["payload"].get("packet_metadata"), dict)
            and record["payload"]["packet_metadata"].get("status_damage_emission_id") == emission.status_damage_emission_id
            for record in result.records
        ),
        "transition_contract": transition_checks["checks"]["transition_contract"],
        "settlement_traceability": transition_checks["checks"]["settlement_traceability"],
        "source_audit": transition_checks["checks"]["source_audit"],
        "replay": transition_checks["checks"]["replay"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks, "transition": transition_checks},
        "summary": {
            "classification": "executable",
            "status_damage_emission_id": emission.status_damage_emission_id,
            "callback_id": emission.callback_id,
            "modifier_name": emission.modifier_name,
        },
        "case": {"selected_emission": emission.to_json(), "transition": _compact_transition(transition)},
    }


def _missing_status_case(ir, rules: RuleBook) -> dict[str, Any]:
    callback = _first_executable_callback(ir)
    state = _state_without_status(callback)
    before_hash = _snapshot_hash(state)
    result = StatusCallbackSystem(rules).execute(
        state,
        unit_id=OWNER_ID,
        modifier_name=callback.modifier_name,
        event=callback.event,
    )
    checks = {
        "blocked": not result.ok,
        "no_mutations": not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "status_detail_missing_reason": "status_detail_missing" in result.errors,
        "blocked_record_present": any(record.get("record_type") == "status_callback_blocked" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "missing status detail blocks callback"},
        "case": {"callback": callback.to_json(), "records": list(result.records)},
    }


def _missing_event_source_case(rules: RuleBook) -> dict[str, Any]:
    state = _state_without_status(None)
    before_hash = _snapshot_hash(state)
    event = GameEvent("validation.unmapped_event", source_id=CASTER_ID, target_id=OWNER_ID, window="validation")
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    checks = {
        "no_mutations": not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "event_alias_missing_recorded": any("event_alias_missing" in str(record) for record in result.listener_records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "missing event source stays process-only"},
        "case": {"records": list(result.records)},
    }


def _missing_wave_payload_case(rules: RuleBook) -> dict[str, Any]:
    state = _state_without_status(None)
    before_hash = _snapshot_hash(state)
    event = GameEvent("wave.monster", source_id="wave", target_id=TARGET_ID, window="OnWaveMonster", payload={})
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)
    checks = {
        "no_mutations": not result.mutations,
        "snapshot_unchanged": before_hash == _snapshot_hash(state),
        "payload_blocked_recorded": any("wave_monster_payload_incomplete" in str(record) for record in result.records),
        "errors_recorded": "wave_monster_payload_incomplete" in result.errors,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "summary": {"classification": "boundary_only", "reason": "wave payload incomplete blocks OnWaveMonster"},
        "case": {"records": list(result.records)},
    }


def _missing_condition_case(ir, rules: RuleBook) -> dict[str, Any]:
    for callback, task in _iter_blocked_root_tasks(ir, rules, reason="missing_retarget_condition"):
        state = _state_for_callback(callback)
        before_hash = _snapshot_hash(state)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        if not result.mutations and "missing_retarget_condition" in " ".join(result.errors):
            checks = {
                "blocked": not result.ok,
                "no_mutations": not result.mutations,
                "snapshot_unchanged": before_hash == _snapshot_hash(state),
                "missing_condition_reason": "missing_retarget_condition" in " ".join(result.errors),
                "blocked_record_present": any(record.get("record_type") == "status_callback_task_blocked" for record in result.records),
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks},
                "summary": {"classification": "boundary_only", "callback_id": callback.callback_id, "task_id": task.task_id},
                "case": {"callback": callback.to_json(), "task": task.to_json(), "records": list(result.records)},
            }
    return _missing_negative_case("missing_condition")


def _missing_target_case(ir, rules: RuleBook) -> dict[str, Any]:
    for callback, task, effect in _iter_root_effect_tasks(ir, rules, "AddModifier", target_aliases={"ParamEntity", "CurrentActionTarget", "AbilityTargetEntity"}):
        state = _state_for_effect_task(callback, effect)
        before_hash = _snapshot_hash(state)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        reason_text = " ".join(str(error) for error in result.errors) + " " + " ".join(str(record) for record in result.records)
        if not result.mutations and ("target" in reason_text or "ParamEntity" in reason_text or "CurrentActionTarget" in reason_text):
            checks = {
                "blocked": not result.ok,
                "no_mutations": not result.mutations,
                "snapshot_unchanged": before_hash == _snapshot_hash(state),
                "missing_target_reason_recorded": (
                    "unsupported_or_missing_target_alias" in reason_text
                    or "target_not_resolved" in reason_text
                    or "list_target_alias_unresolved" in reason_text
                ),
                "no_payload_fallback_mutation": not result.mutations,
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks},
                "summary": {
                    "classification": "boundary_only",
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                    "target_alias": _effect_standard(effect).get("target_alias"),
                },
                "case": {"callback": callback.to_json(), "task": task.to_json(), "effect": _effect_sample(effect), "records": list(result.records)},
            }
    return _missing_negative_case("missing_target")


def _unsupported_task_case(ir, rules: RuleBook) -> dict[str, Any]:
    for callback, task in _iter_blocked_root_tasks(ir, rules, reason_prefix="status_callback_task_opcode_not_admitted:"):
        state = _state_for_callback(callback)
        before_hash = _snapshot_hash(state)
        result = StatusCallbackSystem(rules).execute(
            state,
            unit_id=OWNER_ID,
            modifier_name=callback.modifier_name,
            event=callback.event,
        )
        reason_text = " ".join(str(error) for error in result.errors) + " " + " ".join(str(record) for record in result.records)
        if not result.mutations and "status_callback_task_opcode_not_admitted" in reason_text:
            checks = {
                "blocked": not result.ok,
                "no_mutations": not result.mutations,
                "snapshot_unchanged": before_hash == _snapshot_hash(state),
                "unsupported_opcode_reason_recorded": "status_callback_task_opcode_not_admitted" in reason_text,
                "blocked_record_present": any(record.get("record_type") == "status_callback_task_blocked" for record in result.records),
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "checks": {"ok": checks["ok"], "checks": checks},
                "summary": {
                    "classification": "boundary_only",
                    "opcode": task.opcode,
                    "callback_id": callback.callback_id,
                    "task_id": task.task_id,
                },
                "case": {"callback": callback.to_json(), "task": task.to_json(), "records": list(result.records)},
            }
    return _missing_negative_case("unsupported_task")


def _iter_root_tasks(ir, rules: RuleBook, opcodes: set[str]) -> list[tuple[StatusCallbackIR, StatusCallbackTaskIR]]:
    selected: list[tuple[StatusCallbackIR, StatusCallbackTaskIR]] = []
    for task in sorted(ir.status_callback_tasks, key=lambda item: (item.source.source_path, item.task_id)):
        callback = rules.status_callback(task.callback_id)
        if callback is None or task.opcode not in opcodes or task.parent_task_id:
            continue
        if callback.coverage_status != "executable" or callback.admission_status != "executable":
            continue
        if task.coverage_status != "executable":
            continue
        selected.append((callback, task))
    return selected


def _iter_root_effect_tasks(
    ir,
    rules: RuleBook,
    opcode: str,
    *,
    target_aliases: set[str] | None = None,
) -> list[tuple[StatusCallbackIR, StatusCallbackTaskIR, EffectIR]]:
    selected: list[tuple[StatusCallbackIR, StatusCallbackTaskIR, EffectIR]] = []
    for callback, task in _iter_root_tasks(ir, rules, {opcode}):
        if not task.effect_id:
            continue
        effect = rules.effect(task.effect_id)
        if effect is None or effect.coverage_status != "executable":
            continue
        standard = _effect_standard(effect)
        if target_aliases is not None and str(standard.get("target_alias") or "") not in target_aliases:
            continue
        selected.append((callback, task, effect))
    return selected


def _iter_blocked_root_tasks(
    ir,
    rules: RuleBook,
    *,
    reason: str | None = None,
    reason_prefix: str | None = None,
) -> list[tuple[StatusCallbackIR, StatusCallbackTaskIR]]:
    selected: list[tuple[StatusCallbackIR, StatusCallbackTaskIR]] = []
    for task in sorted(ir.status_callback_tasks, key=lambda item: (item.source.source_path, item.task_id)):
        callback = rules.status_callback(task.callback_id)
        if callback is None or task.parent_task_id:
            continue
        if callback.coverage_status != "executable" or callback.admission_status != "executable":
            continue
        if task.coverage_status == "executable":
            continue
        if reason is not None and task.blocked_reason != reason:
            continue
        if reason_prefix is not None and not task.blocked_reason.startswith(reason_prefix):
            continue
        selected.append((callback, task))
    return selected


def _state_for_effect_task(callback: StatusCallbackIR, effect: EffectIR) -> BattleState:
    standard = _effect_standard(effect)
    modifier_names = {callback.modifier_name}
    target_modifier = standard.get("modifier_name")
    if isinstance(target_modifier, str) and target_modifier:
        modifier_names.add(target_modifier)
    return _state_for_callback(
        callback,
        extra_details=tuple(
            _status_detail(name, callback.event, callback.callback_id if name == callback.modifier_name else "")
            for name in sorted(modifier_names)
            if name != callback.modifier_name
        ),
        dynamic_hashes=_hashes_in(standard),
        dynamic_value=1.0,
    )


def _state_for_callback(
    callback: StatusCallbackIR,
    *,
    extra_details: tuple[dict[str, Any], ...] = (),
    dynamic_hashes: tuple[str, ...] = (),
    dynamic_value: float = 1.0,
) -> BattleState:
    detail = _status_detail(callback.modifier_name, callback.event, callback.callback_id, dynamic_hashes=dynamic_hashes, dynamic_value=dynamic_value)
    details = (detail, *extra_details)
    statuses = tuple(dict.fromkeys(f"modifier:{detail['modifier_name']}" for detail in details))
    return BattleState(
        units={
            OWNER_ID: UnitState(
                unit_id=OWNER_ID,
                side="ally",
                template_id="avatar:p2_s10_owner",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
                action_value=100.0,
                statuses=statuses,
                flags={"status_details": details},
            ),
            CASTER_ID: UnitState(
                unit_id=CASTER_ID,
                side="ally",
                template_id="avatar:p2_s10_caster",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
                action_value=100.0,
            ),
            TARGET_ID: UnitState(
                unit_id=TARGET_ID,
                side="enemy",
                template_id="monster:p2_s10_target",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
                action_value=100.0,
            ),
        },
        global_flags={"phase": VALIDATION_VERSION},
    )


def _state_without_status(callback: StatusCallbackIR | None) -> BattleState:
    return BattleState(
        units={
            OWNER_ID: UnitState(
                unit_id=OWNER_ID,
                side="ally",
                template_id="avatar:p2_s10_owner",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
                action_value=100.0,
                statuses=(f"modifier:{callback.modifier_name}",) if callback is not None else (),
                flags={"status_details": ()},
            ),
            CASTER_ID: UnitState(
                unit_id=CASTER_ID,
                side="ally",
                template_id="avatar:p2_s10_caster",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=80.0,
                speed=100.0,
            ),
        },
        global_flags={"phase": VALIDATION_VERSION},
    )


def _status_detail(
    modifier_name: str,
    event: str,
    callback_id: str,
    *,
    dynamic_hashes: tuple[str, ...] = (),
    dynamic_value: float = 1.0,
) -> dict[str, Any]:
    trigger_ids = {event: [callback_id]} if callback_id else {}
    return {
        "instance_id": f"status_instance:{modifier_name}:p2_s10",
        "status_id": f"modifier:{modifier_name}",
        "modifier_name": modifier_name,
        "owner_id": OWNER_ID,
        "caster_id": CASTER_ID,
        "source_id": f"validation:{VALIDATION_VERSION}:{modifier_name}",
        "stacks": 1,
        "max_stacks": 99,
        "duration": 2.0,
        "remaining_duration": 2.0,
        "duration_unit": "ModifierPhase1End",
        "life_step_moment": "ModifierPhase1End",
        "status_type": "Buff",
        "status_category": "buff",
        "can_dispel": True,
        "dynamic_values": {"__by_hash": {hash_key: float(dynamic_value) for hash_key in dynamic_hashes}},
        "trigger_ids_by_event": trigger_ids,
        "source_trace": {
            "selection_mode": VALIDATION_VERSION,
            "modifier_name": modifier_name,
            "callback_id": callback_id,
        },
    }


def _first_executable_callback(ir) -> StatusCallbackIR:
    for callback in sorted(ir.status_callbacks, key=lambda item: (item.source.source_path, item.callback_id)):
        if callback.coverage_status == "executable" and callback.admission_status == "executable":
            return callback
    raise RuntimeError("no executable status callback found")


def _effect_standard(effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
    return standard if isinstance(standard, dict) else {}


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


def _callback_transition(
    before_state: BattleState,
    result: StatusCallbackExecutionResult,
    action_id: str,
    *,
    actor_id: str,
    target_id: str,
) -> BattleTransition:
    command = ActionCommand(actor_id=actor_id, action_id=action_id, action_level=0, target_ids=(target_id,))
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
            source="status_callback_coverage_validation",
        ),
        rng_events=result.rng_events,
        coverage={"validation": VALIDATION_VERSION, "action_id": action_id},
    )


def _compact_transition(transition: BattleTransition) -> dict[str, Any]:
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    return {
        "mutation_count": len(transition.transaction.mutations),
        "event_types": [event.event_type for event in transition.transaction.events],
        "record_counts": dict(Counter(str(record.get("record_type") or "") for record in records)),
        "mutation_sources": dict(Counter(mutation.source for mutation in transition.transaction.mutations)),
        "mutation_paths": [list(mutation.path) for mutation in transition.transaction.mutations],
    }


def _errors_recorded(errors: tuple[str, ...], records: tuple[dict[str, Any], ...]) -> bool:
    if not errors:
        return True
    record_text = " ".join(str(record.get("payload", {}).get("reason") or "") for record in records)
    record_text += " " + " ".join(str(record.get("payload", {}).get("blocking_dependency") or "") for record in records)
    return all(str(error) in record_text for error in errors)


def _task_sample(task: StatusCallbackTaskIR) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "callback_id": task.callback_id,
        "event": task.event,
        "modifier_name": task.modifier_name,
        "opcode": task.opcode,
        "coverage_status": task.coverage_status,
        "blocked_reason": task.blocked_reason,
        "source": task.source.to_json(),
    }


def _hashes_in(value: object) -> tuple[str, ...]:
    hashes: set[str] = set()
    if isinstance(value, dict):
        if value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
            hashes.add(str(value.get("hash")))
        raw = value.get("raw")
        if isinstance(raw, dict):
            hashes.update(_hashes_in(raw))
        postfix = value.get("PostfixExpr")
        if isinstance(postfix, dict):
            dynamic_hashes = postfix.get("DynamicHashes")
            if isinstance(dynamic_hashes, list):
                hashes.update(str(item) for item in dynamic_hashes if isinstance(item, (int, str)))
        dynamic_hashes = value.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            hashes.update(str(item) for item in dynamic_hashes if isinstance(item, (int, str)))
        for item in value.values():
            hashes.update(_hashes_in(item))
    elif isinstance(value, list):
        for item in value:
            hashes.update(_hashes_in(item))
    return tuple(sorted(hashes))


def _missing_positive_case(name: str) -> dict[str, Any]:
    checks = {"case_found": False}
    checks["ok"] = False
    return {
        "checks": {"ok": False, "checks": checks},
        "summary": {"classification": "implementation_missing", "name": name},
        "case": {},
    }


def _missing_negative_case(name: str) -> dict[str, Any]:
    checks = {"case_found": False}
    checks["ok"] = False
    return {
        "checks": {"ok": False, "checks": checks},
        "summary": {"classification": "validation_gap", "name": name},
        "case": {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S10 status callback event and task coverage.")
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
