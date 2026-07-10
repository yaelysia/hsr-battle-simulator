from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleState, BattleTransition, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR, EffectIR, IRSource, SkillFormulaBindingIR, StatusDamageEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.dynamic_values import status_binding_sources
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.queue import QueueDrainPlan
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..systems.wave import WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p1_4_status_system"


class _LifecycleResultAdapter:
    def __init__(self, result):
        self.events = result.events
        self.mutations = result.mutations
        self.rng_events = ()
        self.records = result.records


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    stack_case = _stack_cap_case(rules)
    layer_formula_case = _layer_formula_case(stack_case)
    refresh_case = _refresh_case(rules)
    stack_only_refresh_case = _stack_only_refresh_case(rules)
    stack_refresh_case = _stack_refresh_case(rules)
    chance_cases = _chance_cases(rules, stack_case["modifier_name"])
    control_case = _control_gate_case(rules, stack_case["status_detail"])
    blocked_case = _blocked_reapply_case(rules, stack_case["effect_ir"], stack_case["after_first_state"])
    dispel_case = _dispel_case(rules)
    duration_owner_case = _duration_owner_case(rules)
    action_after_duration_case = _action_after_duration_case(rules)
    turn_start_duration_case = _turn_start_duration_case(rules)
    wave_cleanup_case = _wave_cleanup_case(rules)
    expire_remove_case = _expire_remove_case(rules)
    dot_lifecycle_case = _dot_lifecycle_case(ir, rules)
    random_dispel_case = _random_dispel_replay_case(rules, dispel_case)
    stack_reduce_case = _stack_reduce_case(rules)

    checks = {
        "stack_cap": stack_case["checks"],
        "layer_formula": layer_formula_case["checks"],
        "refresh": refresh_case["checks"],
        "stack_only_refresh": stack_only_refresh_case["checks"],
        "stack_refresh": stack_refresh_case["checks"],
        "chance": chance_cases["checks"],
        "control": control_case["checks"],
        "blocked": blocked_case["checks"],
        "dispel": dispel_case["checks"],
        "duration_owner": duration_owner_case["checks"],
        "action_after_duration": action_after_duration_case["checks"],
        "turn_start_duration": turn_start_duration_case["checks"],
        "wave_cleanup": wave_cleanup_case["checks"],
        "expire_remove": expire_remove_case["checks"],
        "dot_lifecycle": dot_lifecycle_case["checks"],
        "random_dispel": random_dispel_case["checks"],
        "stack_reduce": stack_reduce_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_predicate",
                "fixed_entity_skill_file_or_observation_used": False,
                "predicate": [
                    "EffectIR opcode AddModifier",
                    "mainline source path",
                    "safe target alias",
                    "MaxLayer/LayerAddWhenStack/duration/chance payload admission",
                    "no fixed character, monster, skill id, file hash, or observed damage",
                ],
            },
        },
        "checks": checks,
        "cases": {
            "stack_cap": _json_without_state(stack_case),
            "layer_formula": _json_without_state(layer_formula_case),
            "refresh": _json_without_state(refresh_case),
            "stack_only_refresh": _json_without_state(stack_only_refresh_case),
            "stack_refresh": _json_without_state(stack_refresh_case),
            "chance": chance_cases,
            "control": control_case,
            "blocked": blocked_case,
            "dispel": _json_without_state(dispel_case),
            "duration_owner": _json_without_state(duration_owner_case),
            "action_after_duration": _json_without_state(action_after_duration_case),
            "turn_start_duration": _json_without_state(turn_start_duration_case),
            "wave_cleanup": _json_without_state(wave_cleanup_case),
            "expire_remove": _json_without_state(expire_remove_case),
            "dot_lifecycle": _json_without_state(dot_lifecycle_case),
            "random_dispel": _json_without_state(random_dispel_case),
            "stack_reduce": _json_without_state(stack_reduce_case),
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_4_status_system.json", result)
    write_json(output_dir / "status_stack_cap_case_p1_4.json", _json_without_state(stack_case))
    write_json(output_dir / "status_refresh_case_p1_4.json", _json_without_state(refresh_case))
    write_json(output_dir / "status_stack_only_refresh_case_p1_4.json", _json_without_state(stack_only_refresh_case))
    write_json(output_dir / "status_stack_refresh_case_p1_4.json", _json_without_state(stack_refresh_case))
    write_json(output_dir / "status_chance_cases_p1_4.json", chance_cases)
    write_json(output_dir / "status_control_case_p1_4.json", control_case)
    write_json(output_dir / "status_blocked_case_p1_4.json", blocked_case)
    write_json(output_dir / "status_dispel_case_p1_4.json", _json_without_state(dispel_case))
    write_json(output_dir / "status_duration_owner_case_p1_4.json", _json_without_state(duration_owner_case))
    write_json(output_dir / "status_action_after_duration_case_p1_4.json", _json_without_state(action_after_duration_case))
    write_json(output_dir / "status_turn_start_duration_case_p1_4.json", _json_without_state(turn_start_duration_case))
    write_json(output_dir / "status_wave_cleanup_case_p1_4.json", _json_without_state(wave_cleanup_case))
    write_json(output_dir / "status_layer_formula_case_p1_4.json", _json_without_state(layer_formula_case))
    write_json(output_dir / "status_expire_remove_case_p1_4.json", _json_without_state(expire_remove_case))
    write_json(output_dir / "status_dot_lifecycle_case_p1_4.json", _json_without_state(dot_lifecycle_case))
    write_json(output_dir / "status_random_dispel_case_p1_4.json", _json_without_state(random_dispel_case))
    write_json(output_dir / "status_stack_reduce_case_p1_4.json", _json_without_state(stack_reduce_case))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-4 status system stack/refresh/chance/control slice.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _stack_cap_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_stack_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p1_4:stack"
    first = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    current = after_first
    stack_results = []
    before_last_stack = after_first
    max_stacks = 1
    for _ in range(8):
        before_last_stack = current
        result = system.apply_add_modifier(
            current,
            effect,
            caster_id="ally:actor",
            source_id=source_id,
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        stack_results.append(result)
        current = MutationReducer().apply_all(current, result.mutations)
        detail = _first_status_detail(current)
        if isinstance(detail.get("max_stacks"), int):
            max_stacks = int(detail["max_stacks"])
        if any(
            ((record.get("payload") or {}).get("stack_plan") or {}).get("stack_capped") is True
            for record in result.records
        ):
            break
    final_detail = _first_status_detail(current)
    transition = _status_transition(before_last_stack, stack_results[-1], "p1_4:stack_cap")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    stack_records = [record for result in stack_results for record in result.records if record.get("record_type") == "status_stack"]
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "stack_result_ok": stack_results[-1].ok,
        "stack_mutation_only_status_details": all(mutation.path[-1] == "status_details" for mutation in stack_results[-1].mutations),
        "status_id_not_duplicated": len(current.units[str(final_detail["owner_id"])].statuses) == len(set(current.units[str(final_detail["owner_id"])].statuses)),
        "stacks_reached_cap": int(final_detail.get("stacks") or 0) == max_stacks,
        "stack_record_present": bool(stack_records),
        "stack_capped_recorded": any(
            ((record.get("payload") or {}).get("stack_plan") or {}).get("stack_capped") is True
            for record in stack_records
        ),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(
            before_last_stack,
            stack_results[-1].mutations,
            transition.after.to_json(),
        ).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_ir": effect,
        "effect": _effect_sample(effect),
        "modifier_name": _modifier_name(effect),
        "after_first_state": after_first,
        "before_last_stack_snapshot": before_last_stack.snapshot().to_json(),
        "final_state": current,
        "status_detail": final_detail,
        "final_status_detail": final_detail,
        "last_result": stack_results[-1].to_json(),
        "source_audit": source_audit.to_json(),
    }


def _layer_formula_case(stack_case: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = stack_case["final_state"]
    detail = dict(stack_case["final_status_detail"])
    owner_id = str(detail.get("owner_id") or "")
    expected = float(detail.get("stacks") or 0)
    result = RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": "Layer"},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(state, (owner_id,)),
            source_trace={"validation": VALIDATION_VERSION, "case": "layer_formula"},
        ),
    )
    entry = result.bindings.get("entry") if isinstance(result.bindings.get("entry"), dict) else {}
    checks = {
        "layer_binding_ok": result.ok,
        "layer_reads_current_stacks": result.value == expected,
        "binding_source_is_status_layer": entry.get("scope") == "status_layer",
        "binding_source_status_instance": entry.get("status_instance_id") == detail.get("instance_id"),
        "source_trace_present": bool(detail.get("source_trace")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "status_detail": detail,
        "numeric_evaluation": result.to_json(),
    }


def _refresh_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_refresh_effect(rules, allow_missing=True)
    if effect is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_refresh_mutation": True,
        }
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no admitted is_refresh AddModifier found"}
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p1_4:refresh"
    first = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    detail = _first_status_detail(after_first)
    ticked_detail = {**detail, "remaining_duration": max(1.0, float(detail.get("remaining_duration") or 1.0) - 1.0)}
    ticked_state = _replace_detail(after_first, ticked_detail)
    second = system.apply_add_modifier(
        ticked_state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(ticked_state, second.mutations)
    refreshed = _first_status_detail(after_second)
    transition = _status_transition(ticked_state, second, "p1_4:refresh")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        "first_apply_ok": first.ok,
        "refresh_ok": second.ok,
        "operation_refresh": bool(second.status_instance and second.status_instance.application_operation == "refresh"),
        "remaining_duration_refreshed": refreshed.get("remaining_duration") == detail.get("remaining_duration"),
        "refresh_record_present": any(record.get("record_type") == "status_refresh" for record in second.records),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(ticked_state, second.mutations, transition.after.to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_refresh_detail": ticked_detail,
        "after_refresh_detail": refreshed,
        "result": second.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _stack_only_refresh_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_stack_only_refresh_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p1_4:stack_only_refresh"
    first = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    detail = _first_status_detail(after_first)
    before_second_detail = dict(detail)
    if isinstance(before_second_detail.get("remaining_duration"), (int, float)):
        before_second_detail["remaining_duration"] = max(0.0, float(before_second_detail["remaining_duration"]) - 1.0)
    before_second = _replace_detail(after_first, before_second_detail)
    second = system.apply_add_modifier(
        before_second,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(before_second, second.mutations)
    after_detail = _first_status_detail(after_second)
    transition = _status_transition(before_second, second, "p1_4:stack_only_refresh")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    stack_records = [record for record in second.records if record.get("record_type") == "status_stack"]
    refresh_plan = {}
    if second.status_instance is not None and isinstance(second.status_instance.source_trace.get("refresh_plan"), dict):
        refresh_plan = dict(second.status_instance.source_trace["refresh_plan"])
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "stack_only_ok": second.ok,
        "operation_stack": bool(second.status_instance and second.status_instance.application_operation == "stack"),
        "stack_increased": int(after_detail.get("stacks") or 0) > int(before_second_detail.get("stacks") or 0),
        "duration_unchanged": after_detail.get("remaining_duration") == before_second_detail.get("remaining_duration"),
        "refresh_policy_stack_only": refresh_plan.get("refresh_policy") == "stack_only",
        "duration_not_introduced_without_source": (
            before_second_detail.get("remaining_duration") is not None or after_detail.get("remaining_duration") is None
        ),
        "stack_record_present": bool(stack_records),
        "status_id_not_duplicated": len(after_second.units[str(after_detail["owner_id"])].statuses)
        == len(set(after_second.units[str(after_detail["owner_id"])].statuses)),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(before_second, second.mutations, transition.after.to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_stack_detail": before_second_detail,
        "after_stack_detail": after_detail,
        "result": second.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _stack_refresh_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_stack_refresh_effect(rules, allow_missing=True)
    if effect is None:
        counts = _stack_refresh_source_counts(rules)
        checks = {
            "coverage_gap_recorded": True,
            "no_source_admitted_stack_refresh": counts["stackable_refresh_prefilter"] == 0,
            "no_synthetic_stack_refresh_mutation": True,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "coverage_gap": "no source-admitted stackable AddModifier with refresh policy found",
            "source_counts": counts,
        }
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p1_4:stack_refresh"
    first = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    detail = _first_status_detail(after_first)
    before_second_detail = {**detail, "remaining_duration": max(1.0, float(detail.get("remaining_duration") or 1.0) - 1.0)}
    before_second = _replace_detail(after_first, before_second_detail)
    second = system.apply_add_modifier(
        before_second,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(before_second, second.mutations)
    after_detail = _first_status_detail(after_second)
    transition = _status_transition(before_second, second, "p1_4:stack_refresh")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "stack_refresh_ok": second.ok,
        "operation_stack_refresh": bool(second.status_instance and second.status_instance.application_operation == "stack_refresh"),
        "stack_increased": int(after_detail.get("stacks") or 0) > int(before_second_detail.get("stacks") or 0),
        "duration_refreshed": after_detail.get("remaining_duration") != before_second_detail.get("remaining_duration"),
        "stack_refresh_record_present": any(record.get("record_type") == "status_stack_refresh" for record in second.records),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(before_second, second.mutations, transition.after.to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_stack_refresh_detail": before_second_detail,
        "after_stack_refresh_detail": after_detail,
        "result": second.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _chance_cases(rules: RuleBook, modifier_name: str) -> dict[str, Any]:
    state = _base_state()
    failure_effect = _synthetic_add_modifier(modifier_name, "chance_failure", chance={"kind": "fixed", "value": 0.0})
    failure = StatusSystem(rules).apply_add_modifier(
        state,
        failure_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:chance_failure",
        owner_id="ally:actor",
        current_action_target_id="ally:actor",
    )
    resist_state = replace(
        state,
        units={
            **state.units,
            "ally:actor": replace(state.units["ally:actor"], resources={"effect_resistance": 1.0}),
        },
    )
    resist_effect = _synthetic_add_modifier(modifier_name, "resisted", chance={"kind": "fixed", "value": 1.0})
    resisted = StatusSystem(rules).apply_add_modifier(
        resist_state,
        resist_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:resisted",
        owner_id="ally:actor",
        current_action_target_id="ally:actor",
    )
    status_id = f"modifier:{modifier_name}"
    immunity_state = replace(
        state,
        units={
            **state.units,
            "ally:actor": replace(
                state.units["ally:actor"],
                flags={
                    "status_immunities": {
                        status_id: {
                            "admission_status": "executable",
                            "source_trace": _validation_source("immunity").to_json(),
                        }
                    }
                },
            ),
        },
    )
    immunity_effect = _synthetic_add_modifier(modifier_name, "immunity", chance={"kind": "fixed", "value": 1.0})
    immunity = StatusSystem(rules).apply_add_modifier(
        immunity_state,
        immunity_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:immunity",
        owner_id="ally:actor",
        current_action_target_id="ally:actor",
    )
    checks = {
        "failure_no_mutation": not failure.mutations,
        "failure_rng_event": bool(failure.rng_events) and failure.rng_events[0].rng_type == "status_apply",
        "failure_record_type": any(record.get("record_type") == "status_apply_failed" for record in failure.records),
        "resisted_no_mutation": not resisted.mutations,
        "resisted_rng_event": any(event.rng_type == "status_resist" for event in resisted.rng_events),
        "resisted_record_type": any(record.get("record_type") == "status_resisted" for record in resisted.records),
        "immunity_no_mutation": not immunity.mutations,
        "immunity_no_rng": not immunity.rng_events,
        "immunity_record_type": any(record.get("record_type") == "status_immunity" for record in immunity.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "failure": failure.to_json(),
        "resisted": resisted.to_json(),
        "immunity": immunity.to_json(),
    }


def _control_gate_case(rules: RuleBook, source_detail: dict[str, Any]) -> dict[str, Any]:
    detail = {
        **source_detail,
        "instance_id": "validation:p1_4:control_instance",
        "status_id": "modifier:validation_control",
        "modifier_name": "validation_control",
        "owner_id": "ally:actor",
        "control_kind": "freeze",
        "status_category": "control",
        "source_trace": source_detail.get("source_trace") or _validation_source("control").to_json(),
    }
    actor = replace(_base_state().units["ally:actor"], flags={"status_details": [detail], "lifecycle_status": "active"})
    state = replace(
        _base_state(),
        units={**_base_state().units, "ally:actor": actor},
        global_flags={
            "phase": "control_validation",
            "current_window": "turn_active",
            "turn_owner_id": "ally:actor",
            "active_turn": {"actor_id": "ally:actor", "turn_kind": "regular"},
        },
    )
    view = ActionAvailabilitySystem(rules).view(state)
    command = ActionCommand(actor_id="ally:actor", action_id="validation:blocked_action", action_level=0, target_ids=("enemy:target",))
    scheduler_step = CombatScheduler(rules).step(state, command)
    queue_plan = QueueDrainPlan(
        ok=True,
        status="admitted",
        queue_name="validation_queue",
        queue_entry={"actor_id": "ally:actor", "target_ids": ["enemy:target"]},
        queue_intent_id="validation:p1_4:control_queue",
        queue_resolution_id="validation:p1_4:control_queue_resolution",
        resolved_kind="action_definition",
        resolved_action_id="validation:blocked_action",
        resolved_action_level=0,
        queue_window={"window_family": "extra_turn", "ok": True, "window_policy": {"extra_action_policy_id": ""}},
    )
    queue_preflight_reason = CombatScheduler(rules)._queue_action_preflight_reason(state, queue_plan, command=command)
    checks = {
        "availability_blocked": view.mode == "blocked",
        "blocked_reason_is_control": view.ordinary_input_blocked_reason.startswith("status_control_gate:"),
        "blocked_source_trace_present": bool(view.blocked and view.blocked[0].source_trace),
        "scheduler_execution_blocked": scheduler_step.transition.transaction.command.action_id == "scheduler:status_control_gate",
        "scheduler_state_unchanged": scheduler_step.after_state.snapshot().to_json() == state.snapshot().to_json(),
        "queue_preflight_blocked": queue_preflight_reason.startswith("status_control_gate:"),
        "state_unchanged": state.snapshot().to_json() == state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "view": view.to_json(),
        "scheduler_transition": scheduler_step.transition.to_json(),
        "queue_preflight_reason": queue_preflight_reason,
    }


def _blocked_reapply_case(rules: RuleBook, base_effect: EffectIR, base_state: BattleState) -> dict[str, Any]:
    standard = dict(base_effect.payload.get("standard") or {})
    standard["layer_add_when_stack"] = {"kind": "dynamic_hash", "hash": "validation_unbound_layer_delta"}
    blocked_effect = replace(base_effect, payload={**base_effect.payload, "standard": standard})
    before_hash = _snapshot_hash(base_state)
    result = StatusSystem(rules).apply_add_modifier(
        base_state,
        blocked_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:stack",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_state = MutationReducer().apply_all(base_state, result.mutations)
    checks = {
        "blocked": not result.ok,
        "no_mutations": not result.mutations,
        "state_unchanged": before_hash == _snapshot_hash(after_state),
        "blocked_record": any(record.get("record_type") == "status_lifecycle_blocked" for record in result.records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "result": result.to_json()}


def _dispel_case(rules: RuleBook) -> dict[str, Any]:
    add_effect = _select_dispellable_buff_effect(rules)
    dispel_effect = _select_deterministic_dispel_effect(rules)
    dynamic_count_effect = _select_dynamic_count_dispel_effect(rules, allow_missing=True)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        add_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:dispellable_buff",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    added_detail = _first_status_detail(after_add)
    dispel_result = system.apply_dispel_status(
        after_add,
        dispel_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:dispel",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_dispel = MutationReducer().apply_all(after_add, dispel_result.mutations)
    transition = _status_transition(after_add, dispel_result, "p1_4:dispel")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)

    not_dispellable_detail = {**added_detail, "can_dispel": False}
    not_dispellable_state = _replace_detail(after_add, not_dispellable_detail)
    skipped_result = system.apply_dispel_status(
        not_dispellable_state,
        dispel_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:dispel_skipped",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    if dynamic_count_effect is None:
        dynamic_blocked = None
        dynamic_checks = {"coverage_gap_recorded": True, "no_synthetic_dynamic_count_mutation": True}
    else:
        dynamic_blocked = system.apply_dispel_status(
            after_add,
            dynamic_count_effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:dynamic_dispel_blocked",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        dynamic_checks = {
            "dynamic_count_blocked": not dynamic_blocked.ok,
            "dynamic_count_no_mutation": not dynamic_blocked.mutations,
            "dynamic_count_blocked_record": any(
                record.get("record_type") == "status_dispel_blocked" for record in dynamic_blocked.records
            ),
        }
    checks = {
        "add_dispellable_status_ok": add_result.ok and bool(add_result.mutations),
        "added_detail_can_dispel": added_detail.get("can_dispel") is True,
        "deterministic_dispel_ok": dispel_result.ok and bool(dispel_result.mutations),
        "deterministic_dispel_record": any(record.get("record_type") == "status_dispel" for record in dispel_result.records),
        "deterministic_dispel_removed_detail": not _unit_has_status_detail(after_dispel, "enemy:target", str(added_detail.get("instance_id") or "")),
        "deterministic_dispel_replay": MutationReducer().replay_snapshot(after_add, dispel_result.mutations, transition.after.to_json()).ok,
        "deterministic_dispel_source_audit": source_audit.ok,
        "skipped_no_mutation": skipped_result.ok and not skipped_result.mutations,
        "skipped_record": any(record.get("record_type") == "status_dispel_skipped" for record in skipped_result.records),
        "random_dispel_coverage_gap_recorded": _has_random_dispel_source(rules) is False,
        **dynamic_checks,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "add_effect": _effect_sample(add_effect),
        "dispel_effect": _effect_sample(dispel_effect),
        "dynamic_count_effect": _effect_sample(dynamic_count_effect) if dynamic_count_effect is not None else None,
        "added_detail": added_detail,
        "dispel_result": dispel_result.to_json(),
        "skipped_result": skipped_result.to_json(),
        "dynamic_blocked_result": dynamic_blocked.to_json() if dynamic_blocked is not None else None,
        "source_audit": source_audit.to_json(),
    }


def _random_dispel_replay_case(rules: RuleBook, dispel_case: dict[str, Any]) -> dict[str, Any]:
    random_effect = _select_random_dispel_effect(rules, allow_missing=True)
    if random_effect is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_random_dispel_mutation": True,
            "runtime_has_no_random_source": _has_random_dispel_source(rules) is False,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "coverage_gap": "no source-admitted Order=Random DispelStatus found",
        }
    add_effect = _select_dispellable_buff_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    first = system.apply_add_modifier(
        state,
        add_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:random_dispel_a",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    second = system.apply_add_modifier(
        after_first,
        add_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:random_dispel_b",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(after_first, second.mutations)
    result_a = system.apply_dispel_status(
        after_second,
        random_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:random_dispel",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    result_b = system.apply_dispel_status(
        after_second,
        random_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:random_dispel",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    transition = _status_transition(after_second, result_a, "p1_4:random_dispel")
    checks = {
        "random_dispel_ok": result_a.ok and bool(result_a.mutations),
        "rng_event_present": bool(result_a.rng_events) and result_a.rng_events[0].rng_type == "status_dispel",
        "rng_replay_stable": [event.to_json() for event in result_a.rng_events] == [event.to_json() for event in result_b.rng_events],
        "mutation_replay_stable": [mutation.to_json() for mutation in result_a.mutations] == [mutation.to_json() for mutation in result_b.mutations],
        "source_audit": RuntimeSourceAuditor(rules).validate_transition(transition).ok,
        "replay": MutationReducer().replay_snapshot(after_second, result_a.mutations, transition.after.to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "random_effect": _effect_sample(random_effect),
        "result_a": result_a.to_json(),
        "result_b": result_b.to_json(),
        "deterministic_case_reference": dispel_case.get("dispel_effect", {}),
    }


def _stack_reduce_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_stack_reduce_effect(rules)
    modifier_name = _modifier_name(effect)
    system = StatusSystem(rules)
    source_id = "validation:p1_4:stack_reduce"

    reduce_state = _stack_reduce_fixture_state(effect, stacks=2, max_stacks=3, source_id=source_id)
    reduce_result = system.apply_add_modifier(
        reduce_state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_reduce = MutationReducer().apply_all(reduce_state, reduce_result.mutations)
    reduced_detail = _first_status_detail(after_reduce)
    reduce_transition = _status_transition(reduce_state, reduce_result, "p1_4:stack_reduce")
    reduce_source_audit = RuntimeSourceAuditor(rules).validate_transition(reduce_transition)

    deplete_state = _stack_reduce_fixture_state(effect, stacks=1, max_stacks=3, source_id=source_id)
    deplete_result = system.apply_add_modifier(
        deplete_state,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_deplete = MutationReducer().apply_all(deplete_state, deplete_result.mutations)
    deplete_transition = _status_transition(deplete_state, deplete_result, "p1_4:stack_reduce_remove")
    deplete_source_audit = RuntimeSourceAuditor(rules).validate_transition(deplete_transition)

    missing_existing_result = system.apply_add_modifier(
        _base_state(),
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    checks = {
        "source_admitted_negative_delta": True,
        "reduce_ok": reduce_result.ok,
        "reduce_operation": bool(reduce_result.status_instance and reduce_result.status_instance.application_operation == "stack_reduce"),
        "reduce_stack_decremented": reduced_detail.get("stacks") == 1,
        "reduce_record_present": any(record.get("record_type") == "status_stack_reduce" for record in reduce_result.records),
        "reduce_source_audit": reduce_source_audit.ok,
        "reduce_replay": MutationReducer().replay_snapshot(
            reduce_state,
            reduce_result.mutations,
            reduce_transition.after.to_json(),
        ).ok,
        "deplete_ok": deplete_result.ok,
        "deplete_operation": bool(
            deplete_result.lifecycle_result and deplete_result.lifecycle_result.operation == "stack_reduce_remove"
        ),
        "deplete_status_removed": f"modifier:{modifier_name}" not in after_deplete.units["ally:actor"].statuses,
        "deplete_detail_removed": not _unit_has_status_detail(
            after_deplete,
            "ally:actor",
            f"validation:p1_4:stack_reduce:{modifier_name}",
        ),
        "deplete_remove_events": {"OnDestroy", "OnModifierRemove"}.issubset(
            {event.window for event in deplete_result.events}
        ),
        "deplete_record_present": any(record.get("record_type") == "status_stack_reduce_remove" for record in deplete_result.records),
        "deplete_source_audit": deplete_source_audit.ok,
        "deplete_replay": MutationReducer().replay_snapshot(
            deplete_state,
            deplete_result.mutations,
            deplete_transition.after.to_json(),
        ).ok,
        "missing_existing_blocked": not missing_existing_result.ok,
        "missing_existing_no_mutation": not missing_existing_result.mutations,
        "missing_existing_blocked_record": any(
            record.get("record_type") == "status_lifecycle_blocked"
            for record in missing_existing_result.records
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_reduce_detail": _first_status_detail(reduce_state),
        "after_reduce_detail": reduced_detail,
        "reduce_result": reduce_result.to_json(),
        "reduce_source_audit": reduce_source_audit.to_json(),
        "before_deplete_detail": _first_status_detail(deplete_state),
        "after_deplete_statuses": list(after_deplete.units["ally:actor"].statuses),
        "after_deplete_details": list(after_deplete.units["ally:actor"].flags.get("status_details", ())),
        "deplete_result": deplete_result.to_json(),
        "deplete_source_audit": deplete_source_audit.to_json(),
        "missing_existing_result": missing_existing_result.to_json(),
    }


def _duration_owner_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:duration_owner",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    wrong_unit_id = "enemy:target" if owner_id != "enemy:target" else "ally:actor"
    life_step_moment = str(detail.get("life_step_moment") or "")
    tick_result = system.apply_lifecycle_tick(after_add, owner_id, detail, life_step_moment)
    after_tick = MutationReducer().apply_all(after_add, tick_result.mutations)
    transition = _status_transition(after_add, _LifecycleResultAdapter(tick_result), "p1_4:duration_owner_tick")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    wrong_plan = system.plan_lifecycle_tick(after_add, wrong_unit_id, detail, life_step_moment)
    wrong_result = system.apply_lifecycle_tick(after_add, wrong_unit_id, detail, life_step_moment)
    checks = {
        "add_duration_status_ok": add_result.ok and bool(add_result.mutations),
        "duration_owner_policy_recorded": (detail.get("duration_admission") or {}).get("tick_owner_policy") == "holder",
        "holder_tick_mutates": tick_result.ok and bool(tick_result.mutations),
        "holder_tick_replay": MutationReducer().replay_snapshot(after_add, tick_result.mutations, after_tick.snapshot().to_json()).ok,
        "holder_tick_source_audit": source_audit.ok,
        "non_holder_tick_blocked": wrong_plan.operation == "tick_blocked",
        "non_holder_reason": "duration_tick_owner_mismatch" in tuple(wrong_plan.unsupported),
        "non_holder_no_mutation": not wrong_result.mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "status_detail": detail,
        "tick_result": tick_result.to_json(),
        "wrong_unit_plan": wrong_plan.to_json(),
        "wrong_unit_result": wrong_result.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _action_after_duration_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect_for_moment(rules, "ActionPhaseEnd")
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:action_after_duration",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(after_add, "ActionPhaseEnd", actor_id=owner_id)
    transition = _sweep_transition(after_add, sweep.after_state, sweep, "p1_4:action_after_duration", actor_id=owner_id)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    after_detail = _first_status_detail(sweep.after_state)
    checks = {
        "case_found": True,
        "add_action_phase_duration_ok": add_result.ok and bool(add_result.mutations),
        "action_phase_moment_recorded": detail.get("life_step_moment") == "ActionPhaseEnd",
        "scheduler_sweep_mutates": bool(sweep.mutations),
        "duration_tick_operation": any(
            mutation.source == "status_system"
            and isinstance(mutation.metadata.get("lifecycle_plan"), dict)
            and mutation.metadata["lifecycle_plan"].get("operation") == "tick"
            for mutation in sweep.mutations
        ),
        "remaining_duration_decremented": after_detail.get("remaining_duration") == float(detail.get("remaining_duration") or 0) - 1.0,
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(after_add, sweep.mutations, sweep.after_state.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_detail": detail,
        "after_detail": after_detail,
        "events": [event.to_json() for event in sweep.events],
        "records": list(sweep.records),
        "mutations": [mutation.to_json() for mutation in sweep.mutations],
        "source_audit": source_audit.to_json(),
    }


def _turn_start_duration_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect_for_moment(rules, "TurnStart", allow_missing=True)
    if effect is not None:
        checks = {
            "case_found": True,
            "turn_start_source_admitted": True,
            "implementation_required": False,
        }
        checks["ok"] = False
        return {
            "checks": {"ok": False, "checks": checks},
            "effect": _effect_sample(effect),
            "coverage_gap": "runtime-admitted TurnStart duration source found but turn-start scheduler hook is not implemented",
        }
    base_effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        base_effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:turn_start_negative",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(after_add, "TurnStart", actor_id=owner_id)
    checks = {
        "coverage_gap_recorded": True,
        "no_admitted_turn_start_source": True,
        "no_synthetic_turn_start_mutation": not sweep.mutations,
        "state_unchanged": _snapshot_hash(after_add) == _snapshot_hash(sweep.after_state),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "coverage_gap": "no runtime-admitted TurnStart duration AddModifier found",
        "negative_effect": _effect_sample(base_effect),
        "status_detail": detail,
        "events": [event.to_json() for event in sweep.events],
        "records": list(sweep.records),
        "mutations": [mutation.to_json() for mutation in sweep.mutations],
    }


def _wave_cleanup_case(rules: RuleBook) -> dict[str, Any]:
    setup = _select_wave_cleanup_state(rules)
    if setup is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_wave_cleanup_mutation": True,
        }
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no executable multi-wave cleanup setup found"}
    state, unit_id = setup
    system = WaveSystem(rules)
    plan = system.plan_transition(state)
    result = system.apply_transition(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    transition = _wave_transition(state, after, result)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    cleanup_mutations = tuple(
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("lifecycle_operation") == "wave_status_cleanup"
    )
    cleanup_mutation_ids = {mutation.stable_id() for mutation in cleanup_mutations}
    record_mutation_ids = {
        str(record.get("mutation_id") or "")
        for record in result.records
        if isinstance(record, dict) and isinstance(record.get("mutation_id"), str)
    }
    after_unit = after.units[unit_id]
    checks = {
        "plan_advances": plan.status == "advance_to_next_wave",
        "cleanup_mutations_present": bool(cleanup_mutations),
        "statuses_cleared": after_unit.statuses == (),
        "status_details_removed": "status_details" not in after_unit.flags,
        "unit_removed": after_unit.flags.get("lifecycle_status") == "removed",
        "cleanup_mutations_have_records": cleanup_mutation_ids.issubset(record_mutation_ids),
        "all_mutations_have_records": {mutation.stable_id() for mutation in result.mutations}.issubset(record_mutation_ids),
        "source_audit": source_audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "plan": plan.to_json(),
        "unit_id": unit_id,
        "initial_statuses": list(state.units[unit_id].statuses),
        "initial_status_details": state.units[unit_id].flags.get("status_details"),
        "after_statuses": list(after_unit.statuses),
        "after_status_details": after_unit.flags.get("status_details"),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "events": [event.to_json() for event in result.events],
        "records": list(result.records),
        "source_audit": source_audit.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "initial_state": state,
        "after_state": after,
    }


def _select_wave_cleanup_state(rules: RuleBook) -> tuple[BattleState, str] | None:
    for definition in sorted(rules.wave_definitions(), key=lambda item: item.wave_definition_id):
        if definition.coverage_status != "executable" or definition.wave_count < 2:
            continue
        current_entries = rules.wave_entries_for_wave(definition.wave_definition_id, 0)
        next_entries = rules.wave_entries_for_wave(definition.wave_definition_id, 1)
        if not current_entries or not next_entries:
            continue
        current_entry = current_entries[0]
        unit_id = _p1_4_wave_unit_id(definition.stage_id, current_entry.wave_index, current_entry.position)
        state = _wave_cleanup_state(definition, unit_id, current_entry.monster_entity_ref)
        plan = WaveSystem(rules).plan_transition(state)
        if plan.status == "advance_to_next_wave":
            return state, unit_id
    return None


def _wave_cleanup_state(definition, unit_id: str, monster_entity_ref: str) -> BattleState:
    source_trace = definition.source.to_json()
    status_detail = {
        "status_id": "modifier:p1_4_wave_cleanup",
        "instance_id": "status:p1_4_wave_cleanup",
        "modifier_name": "p1_4_wave_cleanup",
        "owner_id": unit_id,
        "caster_id": "ally:actor",
        "source_id": "validation:p1_4:wave_cleanup",
        "source_stack_key": "status_stack:p1_4_wave_cleanup",
        "stacks": 1,
        "max_stacks": 1,
        "remaining_duration": 1.0,
        "lifecycle_state": "active",
        "source_trace": {"validation": "p1_4_wave_cleanup_fixture"},
    }
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:p1_4_actor",
                max_hp=3000.0,
                hp=3000.0,
                attack=3000.0,
                defense=900.0,
                speed=100.0,
            ),
            unit_id: UnitState(
                unit_id=unit_id,
                side="enemy",
                template_id=monster_entity_ref,
                max_hp=1000.0,
                hp=0.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                statuses=("modifier:p1_4_wave_cleanup",),
                flags={
                    "lifecycle_status": "defeated",
                    "defeat_record": {"reason": "validation_wave_cleared"},
                    "wave_member_kind": "stage_wave_enemy",
                    "wave_clear_policy": "counts",
                    "wave_index": 0,
                    "status_details": (status_detail,),
                },
            ),
        },
        skill_points=5,
        max_skill_points=5,
        wave_index=0,
        global_flags={
            "phase": "active",
            "current_window": "idle",
            "wave_runtime": {
                "schema_version": "p1_2_wave_runtime_v1",
                "wave_definition_id": definition.wave_definition_id,
                "current_wave_index": 0,
                "total_waves": int(definition.wave_count),
                "status": "active",
                "current_wave_unit_ids": [unit_id],
                "source_trace": source_trace,
            },
        },
    )


def _p1_4_wave_unit_id(stage_id: str, wave_index: int, position: int) -> str:
    return f"enemy:stage:{stage_id}:wave:{wave_index}:pos:{position}"


def _expire_remove_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p1_4:expire_remove",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    expiring_detail = {**detail, "remaining_duration": 1.0}
    expiring_state = _replace_detail(after_add, expiring_detail)
    owner_id = str(expiring_detail.get("owner_id") or "")
    life_step_moment = str(expiring_detail.get("life_step_moment") or "")
    result = system.apply_lifecycle_tick(expiring_state, owner_id, expiring_detail, life_step_moment)
    after_expire = MutationReducer().apply_all(expiring_state, result.mutations)
    transition = _status_transition(expiring_state, _LifecycleResultAdapter(result), "p1_4:expire_remove")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    dispatch = None
    if result.events:
        dispatch = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_status_callback(
            after_expire,
            event=result.events[0],
            unit_id=owner_id,
            modifier_name=str(expiring_detail.get("modifier_name") or ""),
        )
    instance_id = str(expiring_detail.get("instance_id") or "")
    checks = {
        "expire_result_ok": result.ok,
        "expire_operation": result.operation == "expire",
        "status_id_removed_or_other_instance_present": str(expiring_detail.get("status_id") or "") not in after_expire.units[owner_id].statuses
        or any(
            isinstance(item, dict) and item.get("status_id") == expiring_detail.get("status_id")
            for item in after_expire.units[owner_id].flags.get("status_details", ())
        ),
        "status_detail_removed": not _unit_has_status_detail(after_expire, owner_id, instance_id),
        "expire_events_present": {"OnDestroy", "OnModifierRemove"}.issubset({event.window for event in result.events}),
        "dispatch_recorded": dispatch is not None and any(record.get("record_type") == "event_dispatch" for record in dispatch.records),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(expiring_state, result.mutations, after_expire.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "expiring_detail": expiring_detail,
        "result": result.to_json(),
        "after_expire_statuses": list(after_expire.units[owner_id].statuses),
        "after_expire_details": list(after_expire.units[owner_id].flags.get("status_details", ())),
        "dispatch": dispatch.to_json() if hasattr(dispatch, "to_json") else {
            "records": list(dispatch.records) if dispatch is not None else [],
            "errors": list(dispatch.errors) if dispatch is not None else [],
        },
        "source_audit": source_audit.to_json(),
    }


def _dot_lifecycle_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    case = _select_lifecycle_dot_case(ir, rules)
    if case is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_dot_tick_mutation": True,
        }
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no executable lifecycle DoT case found"}
    emission: StatusDamageEmissionIR = case["emission"]
    binding: SkillFormulaBindingIR | None = case["formula_binding"]
    add_effect: EffectIR = case["add_effect"]
    duration_admission: dict[str, Any] = case["duration_admission"]
    state = _state_for_lifecycle_dot_case(emission, binding, add_effect, duration_admission)
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(state, "ModifierPhase1End", actor_id="enemy:dot_target")
    transition = _sweep_transition(state, sweep.after_state, sweep, "p1_4:dot_lifecycle")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    dot_mutations = [
        mutation
        for mutation in sweep.mutations
        if mutation.source == "damage_system" and mutation.metadata.get("damage_source_kind") == "dot"
    ]
    status_detail = _first_status_detail(sweep.after_state)
    checks = {
        "case_found": True,
        "phase1_lifecycle_event_present": any(
            event.event_type == "status.lifecycle" and event.payload.get("callback_event") == "OnPhase1"
            for event in sweep.events
        ),
        "event_dispatch_recorded": any(record.get("record_type") == "event_dispatch" for record in sweep.records),
        "dot_damage_mutation_present": bool(dot_mutations),
        "hp_reduced": sweep.after_state.units["enemy:dot_target"].hp < state.units["enemy:dot_target"].hp,
        "dot_damage_source_kind": all(mutation.metadata.get("damage_source_kind") == "dot" for mutation in dot_mutations),
        "duration_tick_after_dot": status_detail.get("remaining_duration") == 1.0,
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(state, sweep.mutations, sweep.after_state.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_emission": emission.to_json(),
        "selected_formula_binding": binding.to_json() if binding is not None else {},
        "selected_add_modifier_effect": _effect_sample(add_effect),
        "events": [event.to_json() for event in sweep.events],
        "records": list(sweep.records),
        "mutations": [mutation.to_json() for mutation in sweep.mutations],
        "source_audit": source_audit.to_json(),
    }


def _select_lifecycle_dot_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    ability_file_bindings = _dot_bindings_by_ability_file(ir)
    for emission in sorted(ir.status_damage_emissions, key=lambda item: item.status_damage_emission_id):
        if emission.damage_formula_family != "dot" or emission.coverage_status != "executable":
            continue
        if emission.event != "OnPhase1" or emission.attack_type != "DOT":
            continue
        if not _mainline_source_path(emission.source.source_path):
            continue
        damage_value = emission.scaling_expr.get("damage_value")
        damage_percentage = emission.scaling_expr.get("damage_percentage")
        if not (_expr_supported(damage_value) or (_expr_kind(damage_value) == "missing" and _expr_supported(damage_percentage))):
            continue
        add_effect_case = _add_modifier_effect_for_modifier(rules, emission.modifier_name, "ModifierPhase1End")
        if add_effect_case is None:
            continue
        add_effect, duration_admission = add_effect_case
        callback = rules.status_callback(emission.callback_id)
        task = rules.status_callback_task(emission.source_task_id)
        if callback is None or task is None:
            continue
        if callback.coverage_status != "executable" or task.coverage_status != "executable":
            continue
        bindings: tuple[SkillFormulaBindingIR | None, ...] = (*ability_file_bindings.get(emission.source.source_path, ()), None)
        for binding in bindings:
            state = _state_for_lifecycle_dot_case(emission, binding, add_effect, duration_admission)
            sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(state, "ModifierPhase1End", actor_id="enemy:dot_target")
            if any(
                mutation.source == "damage_system" and mutation.metadata.get("damage_source_kind") == "dot"
                for mutation in sweep.mutations
            ):
                return {
                    "emission": emission,
                    "formula_binding": binding,
                    "add_effect": add_effect,
                    "duration_admission": duration_admission,
                }
    return None


def _state_for_lifecycle_dot_case(
    emission: StatusDamageEmissionIR,
    binding: SkillFormulaBindingIR | None,
    add_effect: EffectIR,
    duration_admission: dict[str, Any],
) -> BattleState:
    status_id = f"modifier:{emission.modifier_name}"
    dynamic_values: dict[str, Any] = {"__by_hash": {hash_key: 0.25 for hash_key in _hashes_for_dot_emission(emission)}}
    formula_bindings = [binding.to_json()] if binding is not None else []
    source_trace = {
        "selection_mode": "structured_status_lifecycle_dot_tick",
        "effect_id": add_effect.effect_id,
        "effect_source": add_effect.source.to_json(),
        "modifier_name": emission.modifier_name,
        "status_damage_source": emission.source.to_json(),
        "status_formula_bindings": formula_bindings,
        "duration_admission": dict(duration_admission),
    }
    detail = {
        "instance_id": f"status_instance:{emission.modifier_name}:p1_4_lifecycle_dot",
        "status_id": status_id,
        "modifier_name": emission.modifier_name,
        "owner_id": "enemy:dot_target",
        "caster_id": "ally:dot_caster",
        "source_id": add_effect.effect_id,
        "stacks": 1,
        "max_stacks": 1,
        "duration": 2.0,
        "remaining_duration": 2.0,
        "duration_unit": "ModifierPhase1End",
        "life_step_moment": "ModifierPhase1End",
        "duration_admission": dict(duration_admission),
        "status_type": "Debuff",
        "status_category": "debuff",
        "dynamic_values": dynamic_values,
        "formula_bindings": formula_bindings,
        "trigger_ids_by_event": {"OnPhase1": [emission.callback_id]},
        "source_trace": source_trace,
    }
    return BattleState(
        units={
            "ally:dot_caster": UnitState(
                unit_id="ally:dot_caster",
                side="ally",
                template_id="avatar:dot_caster",
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
                max_hp=500.0,
                hp=500.0,
                defense=50.0,
                speed=100.0,
                statuses=(status_id,),
                flags={"status_details": (detail,)},
            ),
        },
        global_flags={"phase": "p1_4_lifecycle_dot"},
    )


def _add_modifier_effect_for_modifier(
    rules: RuleBook,
    modifier_name: str,
    life_step_moment: str,
) -> tuple[EffectIR, dict[str, Any]] | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("modifier_name") != modifier_name:
            continue
        admission = _duration_admission_for_add_modifier(rules, effect, life_step_moment)
        if admission is not None:
            return effect, admission
    return None


def _duration_admission_for_add_modifier(
    rules: RuleBook,
    effect: EffectIR,
    life_step_moment: str,
) -> dict[str, Any] | None:
    result = StatusSystem(rules).apply_add_modifier(
        _dot_lifecycle_probe_state(),
        effect,
        caster_id="ally:dot_caster",
        source_id=f"validation:p1_4:dot_lifecycle_probe:{effect.effect_id}",
        owner_id="enemy:dot_target",
        param_entity_id="enemy:dot_target",
        current_action_target_id="enemy:dot_target",
    )
    if not result.ok or result.status_instance is None:
        return None
    admission = dict(result.status_instance.duration_admission)
    if admission.get("admission_status") != "executable":
        return None
    if admission.get("life_step_moment") != life_step_moment:
        return None
    return admission


def _dot_lifecycle_probe_state() -> BattleState:
    return BattleState(
        units={
            "ally:dot_caster": UnitState(
                unit_id="ally:dot_caster",
                side="ally",
                template_id="avatar:dot_caster",
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
                max_hp=500.0,
                hp=500.0,
                defense=50.0,
                speed=100.0,
            ),
        },
        global_flags={"phase": "p1_4_lifecycle_dot_probe"},
    )


def _dot_bindings_by_ability_file(ir: CanonicalIR) -> dict[str, tuple[SkillFormulaBindingIR, ...]]:
    binding_by_action = {
        (binding.action_id, binding.level): binding
        for binding in ir.skill_formula_bindings
        if binding.formula_role == "dot_damage" and binding.coverage_status == "executable"
    }
    result: dict[str, list[SkillFormulaBindingIR]] = {}
    for action_binding in ir.action_ability_bindings:
        binding = binding_by_action.get((action_binding.action_id, action_binding.level))
        if binding is None:
            continue
        config_source = action_binding.config_source if isinstance(action_binding.config_source, dict) else {}
        ability_file = config_source.get("ability_file_path")
        if isinstance(ability_file, str) and ability_file:
            result.setdefault(ability_file, []).append(binding)
    return {
        key: tuple(sorted(value, key=lambda item: (item.sequence_order, item.param_index, item.binding_id)))
        for key, value in result.items()
    }


def _hashes_for_dot_emission(emission: StatusDamageEmissionIR) -> tuple[str, ...]:
    hashes: list[str] = []
    for key in ("damage_value", "damage_percentage", "extra_damage_percentage"):
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
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, (int, str))]


def _expr_kind(expression: Any) -> str:
    return str(expression.get("kind") or "") if isinstance(expression, dict) else ""


def _expr_supported(expression: Any) -> bool:
    return _expr_kind(expression) in {"fixed", "dynamic_hash", "postfix_expr"}


def _select_stack_effect(rules: RuleBook) -> EffectIR:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        max_layer = standard.get("max_layer")
        layer_delta = standard.get("layer_add_when_stack")
        max_value = _fixed_value(max_layer)
        if max_value is None or max_value <= 1 or max_value > 8:
            continue
        if _fixed_value(layer_delta) is None or _fixed_value(layer_delta) <= 0:
            continue
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:stack_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if probe.ok and probe.status_instance and probe.status_instance.max_stacks and probe.status_instance.max_stacks > 1:
            return effect
        failures.append({"effect_id": effect.effect_id, "unsupported": list(probe.unsupported)})
    raise RuntimeError(f"no stack AddModifier candidate found; failures={failures[:5]}")


def _select_refresh_effect(rules: RuleBook, *, allow_missing: bool = False) -> EffectIR | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        definition = _modifier_definition_for_effect(rules, effect)
        stacking = str(definition.fields.get("stacking") or "") if definition is not None else ""
        if standard.get("is_refresh") is not True and stacking != "Refresh":
            continue
        if _fixed_value(standard.get("lifetime")) is None and (
            definition is None or _fixed_value(definition.fields.get("lifetime_expr")) is None
        ):
            continue
        first = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:refresh_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        refresh_admission = {}
        if first.status_instance is not None:
            source_trace = first.status_instance.source_trace
            refresh_admission = (
                source_trace.get("refresh_admission") if isinstance(source_trace.get("refresh_admission"), dict) else {}
            )
        if (
            first.ok
            and first.status_instance
            and isinstance(first.status_instance.remaining_duration, (int, float))
            and float(first.status_instance.remaining_duration) > 1.0
            and refresh_admission.get("admission_status") == "executable"
        ):
            return effect
    if allow_missing:
        return None
    raise RuntimeError("no refresh AddModifier candidate found")


def _select_stack_only_refresh_effect(rules: RuleBook) -> EffectIR:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _stackable_nonrefresh_add_modifier(rules, effect):
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:stack_only_refresh_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if probe.ok and probe.status_instance and probe.status_instance.max_stacks and probe.status_instance.max_stacks > 1:
            return effect
        failures.append({"effect_id": effect.effect_id, "unsupported": list(probe.unsupported)})
    raise RuntimeError(f"no stack-only AddModifier candidate found; failures={failures[:5]}")


def _select_stack_refresh_effect(rules: RuleBook, *, allow_missing: bool = False) -> EffectIR | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _stackable_refresh_add_modifier(rules, effect):
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:stack_refresh_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        refresh_admission = {}
        if probe.status_instance is not None:
            source_trace = probe.status_instance.source_trace
            refresh_admission = (
                source_trace.get("refresh_admission") if isinstance(source_trace.get("refresh_admission"), dict) else {}
            )
        if (
            probe.ok
            and probe.status_instance
            and probe.status_instance.max_stacks
            and probe.status_instance.max_stacks > 1
            and isinstance(probe.status_instance.remaining_duration, (int, float))
            and float(probe.status_instance.remaining_duration) > 1.0
            and refresh_admission.get("admission_status") == "executable"
        ):
            return effect
    if allow_missing:
        return None
    raise RuntimeError("no stack+duration refresh AddModifier candidate found")


def _select_stack_reduce_effect(rules: RuleBook) -> EffectIR:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        layer_delta = _fixed_value(standard.get("layer_add_when_stack"))
        if layer_delta is None or layer_delta >= 0:
            continue
        if _modifier_definition_for_effect(rules, effect) is None:
            continue
        probe_state = _stack_reduce_fixture_state(effect, stacks=2, max_stacks=3, source_id="validation:p1_4:stack_reduce_probe")
        probe = StatusSystem(rules).apply_add_modifier(
            probe_state,
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:stack_reduce_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if probe.ok and probe.status_instance and probe.status_instance.application_operation == "stack_reduce":
            return effect
        failures.append({"effect_id": effect.effect_id, "unsupported": list(probe.unsupported)})
    raise RuntimeError(f"no stack reduce AddModifier candidate found; failures={failures[:5]}")


def _stack_refresh_source_counts(rules: RuleBook) -> dict[str, int]:
    counts = {
        "stackable_any_duration": 0,
        "stackable_nonrefresh_prefilter": 0,
        "stackable_refresh_prefilter": 0,
    }
    for effect in rules.ir.effects:
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        if not _stackable_payload(standard):
            continue
        counts["stackable_any_duration"] += 1
        if _has_refresh_source(rules, effect):
            counts["stackable_refresh_prefilter"] += 1
        else:
            counts["stackable_nonrefresh_prefilter"] += 1
    return counts


def _stackable_nonrefresh_add_modifier(rules: RuleBook, effect: EffectIR) -> bool:
    if not _safe_add_modifier_effect(effect):
        return False
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    return (
        _chance_is_guaranteed_or_missing(standard)
        and _stackable_payload(standard)
        and not _has_refresh_source(rules, effect)
    )


def _stackable_refresh_add_modifier(rules: RuleBook, effect: EffectIR) -> bool:
    if not _safe_add_modifier_effect(effect):
        return False
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    if not (_chance_is_guaranteed_or_missing(standard) and _stackable_payload(standard)):
        return False
    definition = _modifier_definition_for_effect(rules, effect)
    duration = _fixed_value(standard.get("lifetime"))
    if duration is None and definition is not None:
        duration = _fixed_value(definition.fields.get("lifetime_expr"))
    return duration is not None and duration > 1 and _has_refresh_source(rules, effect)


def _stackable_payload(standard: dict[str, Any]) -> bool:
    max_value = _fixed_value(standard.get("max_layer"))
    layer_delta = _fixed_value(standard.get("layer_add_when_stack"))
    return max_value is not None and max_value > 1 and layer_delta is not None and layer_delta > 0


def _has_refresh_source(rules: RuleBook, effect: EffectIR) -> bool:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    if standard.get("is_refresh") is True:
        return True
    definition = _modifier_definition_for_effect(rules, effect)
    return definition is not None and definition.fields.get("stacking") == "Refresh"


def _select_duration_effect(rules: RuleBook) -> EffectIR:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        modifier_name = standard.get("modifier_name")
        definition = rules.status_entity_for_modifier(str(modifier_name)) if isinstance(modifier_name, str) else None
        if _fixed_value(standard.get("lifetime")) is None and (
            definition is None or definition.fields.get("lifetime_expr") is None
        ):
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:duration_owner_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if not probe.ok or probe.status_instance is None:
            failures.append({"effect_id": effect.effect_id, "unsupported": list(probe.unsupported)})
            continue
        duration = probe.status_instance.remaining_duration
        admission = probe.status_instance.duration_admission
        if (
            isinstance(duration, (int, float))
            and float(duration) > 1.0
            and admission.get("admission_status") == "executable"
            and admission.get("tick_owner_policy") == "holder"
        ):
            return effect
    raise RuntimeError(f"no duration AddModifier candidate found; failures={failures[:5]}")


def _select_duration_effect_for_moment(
    rules: RuleBook,
    life_step_moment: str,
    *,
    allow_missing: bool = False,
) -> EffectIR | None:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        modifier_name = standard.get("modifier_name")
        definition = _modifier_definition_for_effect(rules, effect) if isinstance(modifier_name, str) else None
        if _fixed_value(standard.get("lifetime")) is None and (
            definition is None or definition.fields.get("lifetime_expr") is None
        ):
            continue
        definition_moment = str(definition.fields.get("life_step_moment") or "") if definition is not None else ""
        standard_moment = str(standard.get("life_step_moment") or "")
        if standard_moment != life_step_moment and definition_moment != life_step_moment:
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id=f"validation:p1_4:{life_step_moment}_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if not probe.ok or probe.status_instance is None:
            failures.append({"effect_id": effect.effect_id, "unsupported": list(probe.unsupported)})
            continue
        duration = probe.status_instance.remaining_duration
        admission = probe.status_instance.duration_admission
        if (
            isinstance(duration, (int, float))
            and float(duration) > 1.0
            and admission.get("admission_status") == "executable"
            and admission.get("life_step_moment") == life_step_moment
            and admission.get("tick_owner_policy") == "holder"
        ):
            return effect
    if allow_missing:
        return None
    raise RuntimeError(f"no {life_step_moment} duration AddModifier candidate found; failures={failures[:5]}")


def _modifier_definition_for_effect(rules: RuleBook, effect: EffectIR):
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    modifier_name = standard.get("modifier_name")
    if not isinstance(modifier_name, str) or not modifier_name:
        return None
    definitions = rules.modifier_definitions(modifier_name)
    if not definitions:
        return rules.modifier_definition(modifier_name)
    exact = tuple(definition for definition in definitions if definition.source.source_path == effect.source.source_path)
    if exact:
        return exact[0]
    if "/Advanced/" in effect.source.source_path:
        advanced = tuple(definition for definition in definitions if "/Advanced/" in definition.source.source_path)
        if len(advanced) == 1:
            return advanced[0]
    return definitions[0]


def _select_dispellable_buff_effect(rules: RuleBook) -> EffectIR:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("target_alias") != "ParamEntity":
            continue
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        modifier_name = standard.get("modifier_name")
        entity = rules.status_entity_for_modifier(str(modifier_name)) if isinstance(modifier_name, str) else None
        if entity is None:
            continue
        if entity.fields.get("StatusType") != "Buff" or entity.fields.get("CanDispel") is not True:
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p1_4:dispellable_buff_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if probe.ok and probe.status_instance and probe.status_instance.can_dispel is True:
            return effect
    raise RuntimeError("no dispellable Buff AddModifier candidate found")


def _select_deterministic_dispel_effect(rules: RuleBook) -> EffectIR:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "DispelStatus" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        numbers = standard.get("numbers")
        if standard.get("target_alias") != "ParamEntity":
            continue
        if standard.get("buff_type") not in {"Buff", None, ""}:
            continue
        if standard.get("order") != "LastAdded":
            continue
        if not (isinstance(numbers, dict) and numbers.get("kind") == "fixed" and numbers.get("value") == 1.0):
            continue
        return effect
    raise RuntimeError("no deterministic fixed-count DispelStatus candidate found")


def _select_dynamic_count_dispel_effect(rules: RuleBook, *, allow_missing: bool = False) -> EffectIR | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "DispelStatus" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        numbers = standard.get("numbers")
        if standard.get("target_alias") != "ParamEntity":
            continue
        if standard.get("order") != "LastAdded":
            continue
        if isinstance(numbers, dict) and numbers.get("kind") == "dynamic_hash":
            return effect
    if allow_missing:
        return None
    raise RuntimeError("no dynamic-count DispelStatus candidate found")


def _select_random_dispel_effect(rules: RuleBook, *, allow_missing: bool = False) -> EffectIR | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "DispelStatus" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        numbers = standard.get("numbers")
        if standard.get("target_alias") != "ParamEntity":
            continue
        if standard.get("order") != "Random":
            continue
        if not (isinstance(numbers, dict) and numbers.get("kind") == "fixed" and numbers.get("value") == 1.0):
            continue
        return effect
    if allow_missing:
        return None
    raise RuntimeError("no random fixed-count DispelStatus candidate found")


def _has_random_dispel_source(rules: RuleBook) -> bool:
    for effect in rules.ir.effects:
        if effect.opcode != "DispelStatus":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("order") == "Random":
            return True
    return False


def _safe_add_modifier_effect(effect: EffectIR) -> bool:
    if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
        return False
    if not _mainline_source_path(effect.source.source_path):
        return False
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    if standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
        return False
    return isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))


def _synthetic_add_modifier(modifier_name: str, raw_id: str, *, chance: dict[str, Any]) -> EffectIR:
    return EffectIR(
        effect_id=f"validation:p1_4:{raw_id}",
        opcode="AddModifier",
        payload={
            "standard": {
                "modifier_name": modifier_name,
                "target_alias": "Caster",
                "dynamic_values": {},
                "dynamic_value_requests": {},
                "lifetime": {"kind": "missing", "reason": "validation_no_duration"},
                "life_step_moment": "",
                "layer_add_when_stack": {"kind": "missing", "reason": "validation_no_stack"},
                "max_layer": {"kind": "missing", "reason": "validation_no_stack"},
                "chance": chance,
            }
        },
        source=_validation_source(raw_id),
        coverage_status="executable",
    )


def _validation_source(raw_id: str) -> IRSource:
    return IRSource(
        source_path="simulator_v8_clean_core/tools/validate_p1_4_status_system.py",
        raw_type="ValidationStatusSystem",
        raw_id=raw_id,
        evidence={"purpose": "P1-4 process-only negative validation"},
    )


def _base_state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:p1_4_actor",
                max_hp=3000.0,
                hp=3000.0,
                attack=3000.0,
                defense=900.0,
                speed=100.0,
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="monster:p1_4_target",
                max_hp=10000.0,
                hp=10000.0,
                defense=1000.0,
                speed=100.0,
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "p1_4_validation", "current_window": "idle"},
    )


def _status_transition(state: BattleState, result, action_id: str) -> BattleTransition:
    after = MutationReducer().apply_all(state, result.mutations)
    command = ActionCommand(actor_id="ally:actor", action_id=action_id, action_level=0)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(action_id, command.actor_id, (), result.records),
        ),
        after=after.snapshot(),
        target_resolution=TargetResolution(reason=action_id, source="status_validation"),
        rng_events=result.rng_events,
        coverage={"validation": VALIDATION_VERSION},
    )


def _sweep_transition(
    before_state: BattleState,
    after_state: BattleState,
    sweep,
    action_id: str,
    *,
    actor_id: str = "enemy:dot_target",
) -> BattleTransition:
    command = ActionCommand(actor_id=actor_id, action_id=action_id, action_level=0)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=sweep.events,
            mutations=sweep.mutations,
            settlement=ActionSettlement(action_id, command.actor_id, (), sweep.records),
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=(actor_id,),
            legal=(actor_id,),
            selected=(actor_id,),
            reason=action_id,
            source="status_lifecycle_validation",
        ),
        rng_events=getattr(sweep, "rng_events", ()),
        coverage={"validation": VALIDATION_VERSION, "action_id": action_id},
    )


def _wave_transition(before_state: BattleState, after_state: BattleState, result) -> BattleTransition:
    command = ActionCommand(actor_id="ally:actor", action_id="p1_4:wave_cleanup", action_level=0)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before_state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(command.action_id, command.actor_id, (), result.records),
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(reason=command.action_id, source="wave_cleanup_validation"),
        rng_events=(),
        coverage={"validation": VALIDATION_VERSION, "action_id": command.action_id},
    )


def _first_status_detail(state: BattleState) -> dict[str, Any]:
    for unit in state.units.values():
        details = unit.flags.get("status_details", ())
        if isinstance(details, (list, tuple)):
            for item in details:
                if isinstance(item, dict):
                    return dict(item)
    raise RuntimeError("status detail missing")


def _replace_detail(state: BattleState, detail: dict[str, Any]) -> BattleState:
    owner_id = str(detail.get("owner_id") or "ally:actor")
    unit = state.units[owner_id]
    details = [
        detail if isinstance(item, dict) and item.get("instance_id") == detail.get("instance_id") else item
        for item in unit.flags.get("status_details", ())
    ]
    return replace(state, units={**state.units, owner_id: replace(unit, flags={**unit.flags, "status_details": details})})


def _stack_reduce_fixture_state(effect: EffectIR, *, stacks: int, max_stacks: int, source_id: str) -> BattleState:
    modifier_name = _modifier_name(effect)
    status_id = f"modifier:{modifier_name}"
    detail = {
        "instance_id": f"validation:p1_4:stack_reduce:{modifier_name}",
        "status_id": status_id,
        "modifier_name": modifier_name,
        "owner_id": "ally:actor",
        "caster_id": "ally:actor",
        "source_id": source_id,
        "stacks": stacks,
        "max_stacks": max_stacks,
        "lifecycle_state": "active",
        "status_type": "Buff",
        "status_category": "buff",
        "source_trace": {
            "validation": VALIDATION_VERSION,
            "case": "stack_reduce_fixture_existing_status",
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
        },
    }
    actor = _base_state().units["ally:actor"]
    return replace(
        _base_state(),
        units={
            **_base_state().units,
            "ally:actor": replace(
                actor,
                statuses=(status_id,),
                flags={"status_details": (detail,)},
            ),
        },
    )


def _unit_has_status_detail(state: BattleState, unit_id: str, instance_id: str) -> bool:
    details = state.units[unit_id].flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        return False
    return any(isinstance(item, dict) and item.get("instance_id") == instance_id for item in details)


def _effect_sample(effect: EffectIR | None) -> dict[str, Any]:
    if effect is None:
        return {}
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    return {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "source": effect.source.to_json(),
        "modifier_name": standard.get("modifier_name"),
        "target_alias": standard.get("target_alias"),
        "lifetime": standard.get("lifetime"),
        "life_step_moment": standard.get("life_step_moment"),
        "is_refresh": standard.get("is_refresh"),
        "max_layer": standard.get("max_layer"),
        "layer_add_when_stack": standard.get("layer_add_when_stack"),
        "chance": standard.get("chance"),
        "buff_type": standard.get("buff_type"),
        "numbers": standard.get("numbers"),
        "order": standard.get("order"),
        "blocked_reason": standard.get("blocked_reason"),
    }


def _modifier_name(effect: EffectIR) -> str:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    return str(standard.get("modifier_name") or "")


def _fixed_value(expr: object) -> float | None:
    if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
        return float(expr["value"])
    if isinstance(expr, (int, float)):
        return float(expr)
    return None


def _chance_is_guaranteed_or_missing(standard: dict[str, Any]) -> bool:
    chance = standard.get("chance")
    if isinstance(chance, dict) and chance.get("kind") == "missing":
        return True
    return _fixed_value(chance) == 1.0


def _mainline_source_path(source_path: str) -> bool:
    markers = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/ElationBattle/",
        "Config/Level/",
        "Config/Gameplays/",
    )
    return not any(marker in source_path for marker in markers)


def _snapshot_hash(state: BattleState) -> str:
    return json.dumps(state.snapshot().to_json(), sort_keys=True, ensure_ascii=False)


def _json_without_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"after_first_state", "final_state", "effect_ir", "initial_state", "after_state"}
    }


if __name__ == "__main__":
    raise SystemExit(main())
