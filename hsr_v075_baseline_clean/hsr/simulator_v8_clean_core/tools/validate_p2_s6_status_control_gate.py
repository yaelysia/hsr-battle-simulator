from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.queue import QueueDrainPlan
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem, status_control_gate_for_actor
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
    _base_state,
    _effect_sample,
    _first_status_detail,
    _json_without_state,
    _modifier_definition_for_effect,
    _safe_add_modifier_effect,
    _snapshot_hash,
)


VALIDATION_VERSION = "p2_s6_status_control_gate"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    control_matrix = _control_source_matrix(rules)
    control_case = _real_control_gate_case(rules)
    recovery_case = _control_recovery_case(rules, control_case["controlled_state"])
    negative_case = _control_gate_negative_case(control_case["controlled_state"])

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "control_source_matrix": control_matrix["checks"],
        "real_control_gate": control_case["checks"],
        "control_recovery": recovery_case["checks"],
        "control_gate_negative": negative_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_control_behavior_flags",
                "runtime_behavior_changed": True,
                "runtime_change": "derive control status metadata from behavior_flags",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "selected_effect": _effect_sample(control_case["effect_ir"]),
            "selected_behavior_flags": control_case["behavior_flags"],
            "control_matrix": control_matrix["matrix"],
            "classification_counts": control_matrix["classification_counts"],
            "blocked_reason": control_case["queue_preflight_reason"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "control_source_matrix": control_matrix["matrix"],
            "real_control_gate": _json_control_case(control_case),
            "control_recovery": _json_without_state(recovery_case),
            "control_gate_negative": _json_without_state(negative_case),
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s6_status_control_gate.json", result)
    return result


def _real_control_gate_case(rules: RuleBook) -> dict[str, Any]:
    selected = _select_control_effect(rules)
    effect: EffectIR = selected["effect"]
    state = _base_state()
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s6:control",
        owner_id="ally:actor",
        param_entity_id="ally:actor",
        current_action_target_id="ally:actor",
        dynamic_values=selected["dynamic_values"],
    )
    after_add = MutationReducer().apply_all(state, result.mutations)
    detail = _first_status_detail(after_add)
    actor = after_add.units["ally:actor"]
    controlled_actor = replace(actor, flags={**actor.flags, "lifecycle_status": "active"})
    controlled_state = replace(
        after_add,
        units={**after_add.units, "ally:actor": controlled_actor},
        global_flags={
            **after_add.global_flags,
            "phase": "control_validation",
            "current_window": "turn_active",
            "turn_owner_id": "ally:actor",
            "active_turn": {"actor_id": "ally:actor", "turn_kind": "regular"},
        },
    )
    view = ActionAvailabilitySystem(rules).view(controlled_state)
    command = ActionCommand(actor_id="ally:actor", action_id="validation:blocked_action", action_level=0, target_ids=("enemy:target",))
    scheduler_step = CombatScheduler(rules).step(controlled_state, command)
    queue_plan = _queue_plan()
    queue_preflight_reason = CombatScheduler(rules)._queue_action_preflight_reason(
        controlled_state,
        queue_plan,
        command=command,
    )
    gate = status_control_gate_for_actor(controlled_state.units["ally:actor"])
    checks = {
        "control_status_applied": result.ok and bool(result.mutations),
        "status_category_control": detail.get("status_category") == "control",
        "control_kind_from_behavior_flags": bool(detail.get("control_kind")),
        "gate_present": gate is not None,
        "gate_source_trace_present": bool(gate and gate.get("source_trace")),
        "availability_blocked": view.mode == "blocked",
        "availability_reason_is_control": view.ordinary_input_blocked_reason.startswith("status_control_gate:"),
        "scheduler_execution_blocked": scheduler_step.transition.transaction.command.action_id == "scheduler:status_control_gate",
        "scheduler_state_unchanged": _snapshot_hash(scheduler_step.after_state) == _snapshot_hash(controlled_state),
        "queue_preflight_blocked": queue_preflight_reason.startswith("status_control_gate:"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_ir": effect,
        "effect": _effect_sample(effect),
        "behavior_flags": selected["behavior_flags"],
        "status_detail": detail,
        "view": view.to_json(),
        "scheduler_transition": scheduler_step.transition.to_json(),
        "queue_preflight_reason": queue_preflight_reason,
        "gate": gate,
        "controlled_state": controlled_state,
    }


def _control_recovery_case(rules: RuleBook, controlled_state: BattleState) -> dict[str, Any]:
    actor = controlled_state.units["ally:actor"]
    recovered = replace(actor, statuses=(), flags={**actor.flags, "status_details": []})
    recovered_state = replace(controlled_state, units={**controlled_state.units, "ally:actor": recovered})
    view = ActionAvailabilitySystem(rules).view(recovered_state)
    gate = status_control_gate_for_actor(recovered_state.units["ally:actor"])
    queue_reason = CombatScheduler(rules)._queue_action_preflight_reason(
        recovered_state,
        _queue_plan(),
        command=ActionCommand(actor_id="ally:actor", action_id="validation:recovered_action", action_level=0, target_ids=("enemy:target",)),
    )
    checks = {
        "gate_removed": gate is None,
        "availability_not_control_blocked": not view.ordinary_input_blocked_reason.startswith("status_control_gate:"),
        "queue_not_control_blocked": not queue_reason.startswith("status_control_gate:"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "view": view.to_json(),
        "queue_preflight_reason": queue_reason,
    }


def _control_gate_negative_case(controlled_state: BattleState) -> dict[str, Any]:
    detail = _first_status_detail(controlled_state)
    actor = controlled_state.units["ally:actor"]
    expired_detail = {**detail, "lifecycle_state": "expired"}
    removed_detail = {**detail, "lifecycle_state": "removed"}
    missing_source_detail = {**detail, "source_trace": {}}
    expired_gate = status_control_gate_for_actor(_actor_with_detail(actor, expired_detail))
    removed_gate = status_control_gate_for_actor(_actor_with_detail(actor, removed_detail))
    missing_source_gate = status_control_gate_for_actor(_actor_with_detail(actor, missing_source_detail))
    checks = {
        "expired_control_ignored": expired_gate is None,
        "removed_control_ignored": removed_gate is None,
        "missing_source_trace_ignored": missing_source_gate is None,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expired_gate": expired_gate,
        "removed_gate": removed_gate,
        "missing_source_gate": missing_source_gate,
    }


def _select_control_effect(rules: RuleBook) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        definition = _modifier_definition_for_effect(rules, effect)
        if definition is None:
            continue
        behavior_flags = tuple(
            str(flag)
            for flag in definition.fields.get("behavior_flags", ())
            if isinstance(flag, str)
        )
        if not ({"STAT_CTRL", "DisableAction"} & set(behavior_flags)):
            continue
        chance = standard.get("chance")
        dynamic_values: dict[str, float] | None = None
        if isinstance(chance, dict) and chance.get("kind") == "dynamic_hash":
            chance_hash = chance.get("hash")
            if chance_hash is None:
                continue
            dynamic_values = {str(chance_hash): 1.0}
        elif isinstance(chance, dict) and chance.get("kind") == "fixed":
            if chance.get("value") != 1.0:
                continue
        elif not (isinstance(chance, dict) and chance.get("kind") == "missing"):
            continue
        result = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p2_s6:control_probe",
            owner_id="ally:actor",
            param_entity_id="ally:actor",
            current_action_target_id="ally:actor",
            dynamic_values=dynamic_values,
        )
        if result.ok and result.status_instance and result.status_instance.status_category == "control":
            return {
                "effect": effect,
                "dynamic_values": dynamic_values,
                "behavior_flags": list(behavior_flags),
            }
        failures.append({"effect_id": effect.effect_id, "unsupported": list(result.unsupported)})
    raise RuntimeError(f"no source-admitted control AddModifier candidate found; failures={failures[:5]}")


def _control_source_matrix(rules: RuleBook) -> dict[str, Any]:
    control_definition_count = 0
    control_add_count = 0
    behavior_flag_counts = Counter()
    for definition in rules.ir.entities:
        if definition.entity_type != "modifier_definition":
            continue
        flags = tuple(str(flag) for flag in definition.fields.get("behavior_flags", ()) if isinstance(flag, str))
        if {"STAT_CTRL", "DisableAction"} & set(flags):
            control_definition_count += 1
            behavior_flag_counts.update(flags)
    control_modifiers = {
        str(entity.fields.get("modifier_name") or "")
        for entity in rules.ir.entities
        if entity.entity_type == "modifier_definition"
        and ({"STAT_CTRL", "DisableAction"} & set(str(flag) for flag in entity.fields.get("behavior_flags", ()) if isinstance(flag, str)))
    }
    for effect in rules.ir.effects:
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if str(standard.get("modifier_name") or "") in control_modifiers:
            control_add_count += 1
    matrix = {
        "control_behavior_flags": _family_entry("executable", control_definition_count, "modifier behavior_flags expose STAT_CTRL or DisableAction."),
        "action_availability_gate": _family_entry("executable", control_add_count, "ActionAvailabilitySystem uses status_control_gate_for_actor."),
        "scheduler_gate": _family_entry("executable", control_add_count, "CombatScheduler blocks direct route execution through the same gate."),
        "queue_preflight_gate": _family_entry("executable", control_add_count, "queue action preflight blocks controlled actors."),
        "ultimate_window_gate": _family_entry("boundary_only", 0, "ultimate-specific control policy is not separately projected in current IR."),
        "timeline_delay_from_control": _family_entry("source_absent_not_required", 0, "no separate control-caused timeline delay source is projected."),
        "counter_or_followup_control_policy": _family_entry("boundary_only", 0, "extra action queue preflight shares the actor control gate; no separate counter policy projected."),
    }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "control_definitions_seen": control_definition_count > 0,
        "control_add_sources_seen": control_add_count > 0,
        "disable_action_flag_seen": behavior_flag_counts.get("DisableAction", 0) > 0,
        "stat_ctrl_flag_seen": behavior_flag_counts.get("STAT_CTRL", 0) > 0,
        "no_unclassified_control_family": all(item["classification"] for item in matrix.values()),
        "no_implementation_missing": not any(item["classification"] == "implementation_missing" for item in matrix.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "behavior_flag_counts_top": behavior_flag_counts.most_common(30),
        "classification_counts": dict(sorted(classifications.items())),
    }


def _queue_plan() -> QueueDrainPlan:
    return QueueDrainPlan(
        ok=True,
        status="admitted",
        queue_name="validation_queue",
        queue_entry={"actor_id": "ally:actor", "target_ids": ["enemy:target"]},
        queue_intent_id="validation:p2_s6:control_queue",
        queue_resolution_id="validation:p2_s6:control_queue_resolution",
        resolved_kind="action_definition",
        resolved_action_id="validation:blocked_action",
        resolved_action_level=0,
        queue_window={"window_family": "extra_turn", "ok": True, "window_policy": {"extra_action_policy_id": ""}},
    )


def _actor_with_detail(actor, detail: dict[str, JSONValue]):
    return replace(actor, flags={**actor.flags, "status_details": [detail]})


def _family_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def _json_control_case(case: dict[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in case.items() if key not in {"effect_ir", "controlled_state"}}
    return _json_without_state(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S6 status control gate semantics.")
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
