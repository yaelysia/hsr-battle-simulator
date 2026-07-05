from __future__ import annotations

import argparse
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
    _json_without_state,
    _modifier_definition_for_effect,
    _safe_add_modifier_effect,
    _stack_cap_case,
    _stack_only_refresh_case,
    _stack_reduce_case,
    _stack_refresh_case,
    _refresh_case,
    _status_transition,
)
from .validate_p2_s2_status_instance_lifecycle import (
    _different_source_same_status_blocked_case,
    _missing_target_negative_case,
)


VALIDATION_VERSION = "p2_s3_status_application_semantics"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    stack_case = _stack_cap_case(rules)
    refresh_case = _refresh_case(rules)
    stack_only_case = _stack_only_refresh_case(rules)
    stack_refresh_case = _stack_refresh_case(rules)
    stack_reduce_case = _stack_reduce_case(rules)
    replace_case = _replace_case(rules)
    different_source_case = _different_source_same_status_blocked_case(rules, replace_case["effect_ir"])
    failed_apply_case = _missing_target_negative_case(rules)
    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "first_apply_and_stack_cap": stack_case["checks"],
        "refresh": refresh_case["checks"],
        "stack_only_refresh": stack_only_case["checks"],
        "stack_refresh": stack_refresh_case["checks"],
        "stack_reduce": stack_reduce_case["checks"],
        "replace": replace_case["checks"],
        "different_source_same_status_blocked": different_source_case["checks"],
        "failed_apply_process_record": failed_apply_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_application_semantics",
                "runtime_behavior_changed": True,
                "runtime_change": "source-admitted same-source replace lifecycle operation",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "replace_effect": _effect_sample(replace_case["effect_ir"]),
            "replace_stacking": replace_case["stacking"],
            "replace_record_type": replace_case["record_type"],
            "stack_refresh_status": "coverage_gap" if stack_refresh_case.get("coverage_gap") else "executable",
            "different_source_blocked_reason": different_source_case["blocked_reason"],
            "failed_apply_reason": failed_apply_case["blocked_reason"],
            "classification_counts": matrix["classification_counts"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "stack_cap": _json_without_state(stack_case),
            "refresh": _json_without_state(refresh_case),
            "stack_only_refresh": _json_without_state(stack_only_case),
            "stack_refresh": _json_without_state(stack_refresh_case),
            "stack_reduce": _json_without_state(stack_reduce_case),
            "replace": _json_without_state(replace_case),
            "different_source_same_status_blocked": different_source_case,
            "failed_apply_process_record": failed_apply_case,
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s3_status_application_semantics.json", result)
    return result


def _replace_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_replace_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    source_id = "validation:p2_s3:replace"
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
    second = system.apply_add_modifier(
        after_first,
        effect,
        caster_id="ally:actor",
        source_id=source_id,
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_second = MutationReducer().apply_all(after_first, second.mutations)
    after_detail = _first_status_detail(after_second)
    transition = _status_transition(after_first, second, "p2_s3:replace")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(after_first, second.mutations, transition.after.to_json())
    record_types = tuple(str(record.get("record_type") or "") for record in second.records)
    definition = _modifier_definition_for_effect(rules, effect)
    stacking = str(definition.fields.get("stacking") or "") if definition is not None else ""
    checks = {
        "first_apply_ok": first.ok and bool(first.mutations),
        "replace_ok": second.ok and bool(second.mutations),
        "operation_replace": bool(second.status_instance and second.status_instance.application_operation == "replace"),
        "replace_record_present": "status_replace" in record_types,
        "status_id_not_duplicated": len(after_second.units[str(after_detail["owner_id"])].statuses)
        == len(set(after_second.units[str(after_detail["owner_id"])].statuses)),
        "same_instance_replaced": before_detail.get("instance_id") == after_detail.get("instance_id"),
        "source_trace_has_modifier_definition": bool(second.status_instance and second.status_instance.source_trace.get("modifier_definition")),
        "source_audit": source_audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_ir": effect,
        "effect": _effect_sample(effect),
        "stacking": stacking,
        "record_type": "status_replace" if "status_replace" in record_types else "",
        "before_detail": before_detail,
        "after_detail": after_detail,
        "result": second.to_json(),
        "source_audit": source_audit.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _select_replace_effect(rules: RuleBook) -> EffectIR:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if not _chance_is_guaranteed_or_missing(standard):
            continue
        definition = _modifier_definition_for_effect(rules, effect)
        stacking = str(definition.fields.get("stacking") or "") if definition is not None else ""
        if stacking != "Replace":
            continue
        first = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p2_s3:replace_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        if first.ok and first.status_instance is not None:
            return effect
    raise RuntimeError("no source-admitted Replace AddModifier candidate found")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S3 status apply/stack/refresh/replace semantics.")
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
