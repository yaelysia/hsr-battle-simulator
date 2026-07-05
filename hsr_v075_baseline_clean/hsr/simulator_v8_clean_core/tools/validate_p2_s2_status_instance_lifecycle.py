from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
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
    _base_state,
    _chance_is_guaranteed_or_missing,
    _effect_sample,
    _first_status_detail,
    _fixed_value,
    _json_without_state,
    _modifier_definition_for_effect,
    _replace_detail,
    _safe_add_modifier_effect,
    _select_refresh_effect,
    _snapshot_hash,
    _status_transition,
)


VALIDATION_VERSION = "p2_s2_status_instance_lifecycle"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    refresh_case = _default_refresh_identity_case(rules)
    different_source_case = _different_source_same_status_blocked_case(rules, refresh_case["effect_ir"])
    missing_target_case = _missing_target_negative_case(rules)
    missing_definition_case = _missing_definition_negative_case(rules, refresh_case["effect_ir"])
    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "default_refresh_identity": refresh_case["checks"],
        "different_source_same_status_blocked": different_source_case["checks"],
        "missing_target_negative": missing_target_case["checks"],
        "missing_definition_negative": missing_definition_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_instance_lifecycle_predicates",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "negative_cases_are_state_unchanged": True,
            },
        },
        "checks": checks,
        "summary": {
            "refresh_effect": _effect_sample(refresh_case["effect_ir"]),
            "refresh_source_kind": refresh_case["refresh_source_kind"],
            "status_instance_required_fields": refresh_case["status_instance_required_fields"],
            "different_source_blocked_reason": different_source_case["blocked_reason"],
            "missing_target_reason": missing_target_case["blocked_reason"],
            "missing_definition_reason": missing_definition_case["blocked_reason"],
            "classification_counts": matrix["classification_counts"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "default_refresh_identity": _json_without_state(refresh_case),
            "different_source_same_status_blocked": different_source_case,
            "missing_target_negative": missing_target_case,
            "missing_definition_negative": missing_definition_case,
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s2_status_instance_lifecycle.json", result)
    return result


def _default_refresh_identity_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_definition_stacking_refresh_effect(rules) or _select_refresh_effect(rules)
    if effect is None:
        raise RuntimeError("no refresh AddModifier candidate found")
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p2_s2:default_refresh"
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
    before_detail = _first_status_detail(after_first)
    ticked_detail = {
        **before_detail,
        "remaining_duration": max(1.0, float(before_detail.get("remaining_duration") or 1.0) - 1.0),
    }
    before_second = _replace_detail(after_first, ticked_detail)
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
    transition = _status_transition(before_second, second, "p2_s2:default_refresh_identity")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(before_second, second.mutations, transition.after.to_json())
    required_fields = {
        key: key in after_detail
        for key in (
            "instance_id",
            "status_id",
            "modifier_name",
            "owner_id",
            "source_id",
            "caster_id",
            "stacks",
            "remaining_duration",
            "source_trace",
            "stack_policy",
            "refresh_policy",
            "status_type",
            "status_category",
            "source_stack_key",
        )
    }
    source_trace = second.status_instance.source_trace if second.status_instance is not None else {}
    refresh_admission = source_trace.get("refresh_admission") if isinstance(source_trace.get("refresh_admission"), dict) else {}
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "second_apply_refresh_ok": second.ok and bool(second.mutations),
        "operation_refresh": bool(second.status_instance and second.status_instance.application_operation == "refresh"),
        "same_instance_id": before_detail.get("instance_id") == after_detail.get("instance_id"),
        "same_source_stack_key": before_detail.get("source_stack_key") == after_detail.get("source_stack_key"),
        "status_id_not_duplicated": len(after_second.units[str(after_detail["owner_id"])].statuses)
        == len(set(after_second.units[str(after_detail["owner_id"])].statuses)),
        "ordinary_reapply_not_stacked": after_detail.get("stacks") == before_detail.get("stacks") == 1,
        "remaining_duration_refreshed": after_detail.get("remaining_duration") == before_detail.get("remaining_duration"),
        "refresh_record_present": any(record.get("record_type") == "status_refresh" for record in second.records),
        "required_fields_present": all(required_fields.values()),
        "source_trace_has_definition": bool(source_trace.get("modifier_definition")),
        "refresh_source_kind_recorded": refresh_admission.get("source_kind") in {"modifier_definition_stacking", "effect_is_refresh"},
        "source_audit": source_audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_ir": effect,
        "effect": _effect_sample(effect),
        "before_detail": before_detail,
        "after_detail": after_detail,
        "refresh_source_kind": str(refresh_admission.get("source_kind") or ""),
        "status_instance_required_fields": required_fields,
        "result": second.to_json(),
        "source_audit": source_audit.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _different_source_same_status_blocked_case(rules: RuleBook, effect: EffectIR) -> dict[str, Any]:
    system = StatusSystem(rules)
    state = _base_state()
    first = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s2:source_a",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_first = MutationReducer().apply_all(state, first.mutations)
    before_hash = _snapshot_hash(after_first)
    second = system.apply_add_modifier(
        after_first,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s2:source_b",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(after_first, second.mutations)
    reasons = tuple(second.unsupported)
    blocked_reason = reasons[0] if reasons else ""
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "different_source_blocked": not second.ok,
        "blocked_reason": blocked_reason == "coexist_unsupported:different_source_same_status",
        "blocked_record": any(record.get("record_type") == "status_lifecycle_blocked" for record in second.records),
        "no_mutations": not second.mutations,
        "state_unchanged": before_hash == _snapshot_hash(after_second),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reason": blocked_reason,
        "result": second.to_json(),
    }


def _missing_target_negative_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_param_entity_add_modifier_effect(rules)
    state = _base_state()
    before_hash = _snapshot_hash(state)
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s2:missing_target",
        owner_id="ally:actor",
        param_entity_id=None,
        current_action_target_id=None,
    )
    after_state = MutationReducer().apply_all(state, result.mutations)
    blocked_reason = result.unsupported[0] if result.unsupported else ""
    checks = {
        "blocked": not result.ok,
        "blocked_reason": blocked_reason.startswith("unsupported_or_missing_target_alias:"),
        "process_record": any(record.get("record_type") == "status_unsupported" for record in result.records),
        "no_mutations": not result.mutations,
        "state_unchanged": before_hash == _snapshot_hash(after_state),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "blocked_reason": blocked_reason,
        "result": result.to_json(),
    }


def _missing_definition_negative_case(rules: RuleBook, effect: EffectIR) -> dict[str, Any]:
    standard = dict(effect.payload.get("standard") or {})
    standard["modifier_name"] = "validation_missing_modifier_definition"
    missing_effect = replace(effect, payload={**effect.payload, "standard": standard})
    state = _base_state()
    before_hash = _snapshot_hash(state)
    result = StatusSystem(rules).apply_add_modifier(
        state,
        missing_effect,
        caster_id="ally:actor",
        source_id="validation:p2_s2:missing_definition",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_state = MutationReducer().apply_all(state, result.mutations)
    blocked_reason = result.unsupported[0] if result.unsupported else ""
    checks = {
        "blocked": not result.ok,
        "blocked_reason": blocked_reason.startswith("unknown modifier definition"),
        "process_record": any(record.get("record_type") == "status_unsupported" for record in result.records),
        "no_mutations": not result.mutations,
        "state_unchanged": before_hash == _snapshot_hash(after_state),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reason": blocked_reason,
        "result": result.to_json(),
    }


def _select_definition_stacking_refresh_effect(rules: RuleBook) -> EffectIR | None:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        definition = _modifier_definition_for_effect(rules, effect)
        if definition is None or definition.fields.get("stacking") != "Refresh":
            continue
        if standard.get("is_refresh") is True:
            continue
        if _fixed_value(standard.get("lifetime")) is None and _fixed_value(definition.fields.get("lifetime_expr")) is None:
            continue
        probe = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p2_s2:definition_refresh_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if not (probe.ok and probe.status_instance):
            continue
        source_trace = probe.status_instance.source_trace
        refresh_admission = source_trace.get("refresh_admission") if isinstance(source_trace.get("refresh_admission"), dict) else {}
        if refresh_admission.get("source_kind") == "modifier_definition_stacking":
            return effect
    return None


def _select_param_entity_add_modifier_effect(rules: RuleBook) -> EffectIR:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("target_alias") != "ParamEntity":
            continue
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        return effect
    raise RuntimeError("no ParamEntity AddModifier candidate found")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S2 status instance identity and default lifecycle semantics.")
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
