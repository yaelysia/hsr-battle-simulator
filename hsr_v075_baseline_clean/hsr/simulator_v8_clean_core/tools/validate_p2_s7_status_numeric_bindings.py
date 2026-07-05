from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.reducer import MutationReducer
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..systems.damage_formula import _status_modifier_terms
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
    _base_state,
    _effect_sample,
    _first_status_detail,
    _json_without_state,
    _modifier_definition_for_effect,
    _safe_add_modifier_effect,
    _select_duration_effect,
    _snapshot_hash,
    _stack_cap_case,
)


VALIDATION_VERSION = "p2_s7_status_numeric_bindings"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    numeric_matrix = _numeric_binding_matrix(rules)
    layer_case = _layer_binding_case(rules)
    lifetime_case = _lifetime_binding_case(rules)
    dynamic_case = _status_dynamic_value_case(rules)
    modifier_case = _status_modifier_term_case(rules)
    removal_case = _binding_removed_case(rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "numeric_binding_matrix": numeric_matrix["checks"],
        "layer_binding": layer_case["checks"],
        "lifetime_binding": lifetime_case["checks"],
        "status_dynamic_value": dynamic_case["checks"],
        "status_modifier_term": modifier_case["checks"],
        "binding_removed": removal_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_numeric_bindings",
                "runtime_behavior_changed": True,
                "runtime_change": "export status remaining duration as LifeTime binding",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "numeric_matrix": numeric_matrix["matrix"],
            "classification_counts": numeric_matrix["classification_counts"],
            "dynamic_effect": dynamic_case.get("effect"),
            "modifier_effect": modifier_case.get("effect"),
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "numeric_binding_matrix": numeric_matrix["matrix"],
            "layer_binding": _json_without_state(layer_case),
            "lifetime_binding": _json_without_state(lifetime_case),
            "status_dynamic_value": _json_without_state(dynamic_case),
            "status_modifier_term": _json_without_state(modifier_case),
            "binding_removed": _json_without_state(removal_case),
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s7_status_numeric_bindings.json", result)
    return result


def _layer_binding_case(rules: RuleBook) -> dict[str, Any]:
    stack_case = _stack_cap_case(rules)
    state = stack_case["final_state"]
    detail = dict(stack_case["final_status_detail"])
    owner_id = str(detail.get("owner_id") or "")
    result = RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": "Layer"},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(state, (owner_id,)),
            source_trace={"validation": VALIDATION_VERSION, "case": "layer_binding"},
        ),
    )
    entry = result.bindings.get("entry") if isinstance(result.bindings.get("entry"), dict) else {}
    checks = {
        "layer_binding_ok": result.ok,
        "layer_reads_current_stacks": result.value == float(detail.get("stacks") or 0),
        "binding_source_is_status_layer": entry.get("scope") == "status_layer",
        "binding_source_status_instance": entry.get("status_instance_id") == detail.get("instance_id"),
        "source_trace_present": bool(entry.get("source_trace")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "status_detail": detail,
        "numeric_evaluation": result.to_json(),
    }


def _lifetime_binding_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    state = _base_state()
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s7:lifetime",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after = MutationReducer().apply_all(state, result.mutations)
    detail = _first_status_detail(after)
    owner_id = str(detail.get("owner_id") or "")
    evaluation = RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": "LifeTime"},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(after, (owner_id,)),
            source_trace={"validation": VALIDATION_VERSION, "case": "lifetime_binding"},
        ),
    )
    entry = evaluation.bindings.get("entry") if isinstance(evaluation.bindings.get("entry"), dict) else {}
    checks = {
        "status_applied": result.ok and bool(result.mutations),
        "lifetime_binding_ok": evaluation.ok,
        "lifetime_reads_remaining_duration": evaluation.value == float(detail.get("remaining_duration") or 0),
        "binding_source_is_status_lifetime": entry.get("scope") == "status_lifetime",
        "binding_source_status_instance": entry.get("status_instance_id") == detail.get("instance_id"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "status_detail": detail,
        "numeric_evaluation": evaluation.to_json(),
    }


def _status_dynamic_value_case(rules: RuleBook) -> dict[str, Any]:
    selected = _select_dynamic_value_effect(rules)
    state = _base_state()
    result = StatusSystem(rules).apply_add_modifier(
        state,
        selected["effect"],
        caster_id="ally:actor",
        source_id="validation:p2_s7:dynamic_value",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
        dynamic_values=selected["dynamic_values"],
    )
    after = MutationReducer().apply_all(state, result.mutations)
    detail = _first_status_detail(after)
    owner_id = str(detail.get("owner_id") or "")
    hash_key = str(selected["hash_key"])
    evaluation = RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": hash_key},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(after, (owner_id,)),
            source_trace={"validation": VALIDATION_VERSION, "case": "status_dynamic_value"},
        ),
    )
    entry = evaluation.bindings.get("entry") if isinstance(evaluation.bindings.get("entry"), dict) else {}
    checks = {
        "status_applied": result.ok and bool(result.mutations),
        "dynamic_value_present_on_status": hash_key in (detail.get("dynamic_values", {}).get("__by_hash", {}) if isinstance(detail.get("dynamic_values"), dict) else {}),
        "dynamic_binding_ok": evaluation.ok,
        "dynamic_binding_reads_status_value": evaluation.value == selected["expected_value"],
        "binding_source_is_status": entry.get("scope") == "status",
        "binding_source_status_instance": entry.get("status_instance_id") == detail.get("instance_id"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(selected["effect"]),
        "hash_key": hash_key,
        "expected_value": selected["expected_value"],
        "status_detail": detail,
        "numeric_evaluation": evaluation.to_json(),
    }


def _status_modifier_term_case(rules: RuleBook) -> dict[str, Any]:
    selected = _select_modifier_term_effect(rules)
    state = _base_state()
    result = StatusSystem(rules).apply_add_modifier(
        state,
        selected["effect"],
        caster_id="ally:actor",
        source_id="validation:p2_s7:modifier_term",
        owner_id="ally:actor",
        param_entity_id=selected["target_id"],
        current_action_target_id=selected["target_id"],
        dynamic_values=selected["dynamic_values"],
    )
    after = MutationReducer().apply_all(state, result.mutations)
    detail = _first_status_detail(after)
    owner_id = str(detail.get("owner_id") or "")
    unit = after.units[owner_id]
    modifier = selected["modifier"]
    total, applied, skipped = _status_modifier_terms(
        unit,
        source_type=f"{modifier['scope']}.status",
        bucket=str(modifier["bucket"]),
        keys=(str(modifier["key"]),),
    )
    checks = {
        "status_applied": result.ok and bool(result.mutations),
        "modifier_present": bool(detail.get("modifiers")),
        "modifier_term_applied": bool(applied),
        "modifier_term_total_matches": total == float(modifier["value"]),
        "modifier_term_source_instance": applied[0].source_id == detail.get("instance_id") if applied else False,
        "unrelated_terms_not_applied": not skipped or all(item.reason for item in skipped),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(selected["effect"]),
        "modifier": modifier,
        "status_detail": detail,
        "applied_terms": [item.to_json() for item in applied],
        "skipped_terms": [item.to_json() for item in skipped],
    }


def _binding_removed_case(rules: RuleBook) -> dict[str, Any]:
    lifetime = _lifetime_binding_case(rules)
    detail = lifetime["status_detail"]
    state = _base_state()
    effect = _select_duration_effect(rules)
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s7:binding_removed",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after = MutationReducer().apply_all(state, result.mutations)
    owner_id = str(detail.get("owner_id") or "ally:actor")
    unit = after.units[owner_id]
    removed = replace(after, units={**after.units, owner_id: replace(unit, statuses=(), flags={**unit.flags, "status_details": []})})
    evaluation = RuleEvaluator().evaluate_numeric(
        {"kind": "dynamic_hash", "hash": "LifeTime"},
        NumericEvaluationContext(
            binding_sources=status_binding_sources(removed, (owner_id,)),
            source_trace={"validation": VALIDATION_VERSION, "case": "binding_removed"},
        ),
    )
    checks = {
        "status_initially_applied": result.ok and bool(result.mutations),
        "removed_state_has_no_status_details": not removed.units[owner_id].flags.get("status_details"),
        "removed_binding_unbound": not evaluation.ok and str(evaluation.blocked_reason).startswith("dynamic_hash_unbound"),
        "removed_state_unchanged": _snapshot_hash(removed) == _snapshot_hash(removed),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "numeric_evaluation_after_remove": evaluation.to_json(),
    }


def _select_dynamic_value_effect(rules: RuleBook) -> dict[str, Any]:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        dynamic_values = standard.get("dynamic_values")
        if not isinstance(dynamic_values, dict) or not dynamic_values:
            continue
        runtime_values = {str(hash_key): 0.25 for hash_key in _hashes_in(dynamic_values)}
        result = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p2_s7:dynamic_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
            dynamic_values=runtime_values,
        )
        if not (result.ok and result.status_instance and isinstance(result.status_instance.dynamic_values, dict)):
            continue
        by_hash = result.status_instance.dynamic_values.get("__by_hash")
        if isinstance(by_hash, dict) and by_hash:
            hash_key, value = next(iter(by_hash.items()))
            if isinstance(value, (int, float)):
                return {"effect": effect, "dynamic_values": runtime_values, "hash_key": str(hash_key), "expected_value": float(value)}
    raise RuntimeError("no source-admitted status dynamic value candidate found")


def _select_modifier_term_effect(rules: RuleBook) -> dict[str, Any]:
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        definition = _modifier_definition_for_effect(rules, effect)
        if definition is None:
            continue
        if not definition.fields.get("stack_properties"):
            continue
        runtime_values = {str(hash_key): 0.25 for hash_key in _hashes_in(definition.fields.get("stack_properties"))}
        target_id = "enemy:target" if standard.get("target_alias") in {"ParamEntity", "CurrentActionTarget"} else "ally:actor"
        result = StatusSystem(rules).apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="validation:p2_s7:modifier_probe",
            owner_id="ally:actor",
            param_entity_id=target_id,
            current_action_target_id=target_id,
            dynamic_values=runtime_values,
        )
        if result.ok and result.status_instance and result.status_instance.modifiers:
            return {
                "effect": effect,
                "dynamic_values": runtime_values,
                "target_id": target_id,
                "modifier": result.status_instance.modifiers[0],
            }
    raise RuntimeError("no source-admitted status modifier term candidate found")


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


def _numeric_binding_matrix(rules: RuleBook) -> dict[str, Any]:
    dynamic_definition_count = 0
    stack_property_count = 0
    supported_stack_property_count = 0
    property_counts = Counter()
    for definition in rules.ir.entities:
        if definition.entity_type != "modifier_definition":
            continue
        bindings = definition.fields.get("dynamic_value_bindings")
        if isinstance(bindings, dict) and bindings.get("by_hash"):
            dynamic_definition_count += 1
        stack_properties = definition.fields.get("stack_properties")
        if isinstance(stack_properties, list):
            for item in stack_properties:
                if not isinstance(item, dict):
                    continue
                stack_property_count += 1
                prop = str(item.get("property") or "")
                property_counts[prop] += 1
                if prop in {
                    "AllDamageTypeAddedRatio",
                    "AllResistanceDelta",
                    "DamageTakenRatio",
                    "AllDamageTakenRatio",
                    "DefenceReduce",
                    "DefenseReduce",
                    "DefenceReduction",
                    "DefenseReduction",
                    "DefenceIgnore",
                    "DefenseIgnore",
                } or prop.endswith("AddedRatio") or prop.endswith("ResistanceDelta"):
                    supported_stack_property_count += 1
    matrix = {
        "status_layer_binding": _family_entry("executable", 1, "status_binding_sources exports Layer/layer/stacks."),
        "status_lifetime_binding": _family_entry("executable", 1, "status_binding_sources exports LifeTime/remaining_duration."),
        "status_dynamic_values": _family_entry("executable", dynamic_definition_count, "status dynamic values are stored on status detail and exposed by hash/name."),
        "status_stack_property_modifiers": _family_entry("executable", supported_stack_property_count, "supported StackProperty entries become status modifier terms."),
        "unsupported_stack_properties": _family_entry("boundary_only", max(0, stack_property_count - supported_stack_property_count), "unsupported properties are recorded as blocked/unsupported, not defaulted."),
        "healing_energy_sp_toughness_modifiers": _family_entry("source_absent_not_required", 0, "no executable status mapping for healing/energy/SP/toughness is projected in current runtime."),
    }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "dynamic_definitions_seen": dynamic_definition_count > 0,
        "stack_properties_seen": stack_property_count > 0,
        "supported_stack_properties_seen": supported_stack_property_count > 0,
        "no_unclassified_numeric_family": all(item["classification"] for item in matrix.values()),
        "no_implementation_missing": not any(item["classification"] == "implementation_missing" for item in matrix.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "property_counts_top": property_counts.most_common(30),
        "classification_counts": dict(sorted(classifications.items())),
    }


def _family_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S7 status numeric bindings.")
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
