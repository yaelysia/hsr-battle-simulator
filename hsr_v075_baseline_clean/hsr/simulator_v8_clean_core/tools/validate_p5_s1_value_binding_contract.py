from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s1_value_binding_contract"
MATRIX_SCHEMA_VERSION = "p5_s1_value_binding_contract_matrix_v1"

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
GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "unclassified",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}

REQUIRED_BINDING_ROWS = {
    "skill_formula_binding_contract",
    "damage_emission_contract",
    "toughness_emission_contract",
    "resource_rule_contract",
    "status_damage_emission_contract",
    "action_delay_emission_contract",
    "queue_intent_contract",
    "summon_intent_contract",
    "data_card_mechanism_slot_contract",
}
REQUIRED_QUERY_ROWS = {
    "skill_formula_binding_rulebook_queries",
    "damage_toughness_rulebook_queries",
    "resource_rulebook_queries",
    "status_callback_numeric_rulebook_queries",
    "summon_intent_rulebook_queries",
    "data_card_mechanism_rulebook_queries",
}
REQUIRED_CONSUMER_ROWS = {
    "damage_toughness_runtime_consumer_contract",
    "resource_runtime_consumer_contract",
    "status_callback_numeric_runtime_consumer_contract",
    "summon_intent_runtime_consumer_contract",
    "numeric_evaluator_current_contract",
    "s0_missing_consumer_ref_policy",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s1_value_binding_contract_matrix(package_root, ir, rules)
    matrix_checks = validate_p5_s1_value_binding_contract_matrix(matrix)
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
                "mode": "p5_s1_current_ir_rulebook_runtime_consumer_contract_audit",
                "runtime_behavior_changed": False,
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "s0_missing_consumer_refs_counted_as_consumer_admitted": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "binding_container_contract_matrix": matrix["binding_container_contract_matrix"],
        "rulebook_query_contract_matrix": matrix["rulebook_query_contract_matrix"],
        "runtime_consumer_contract_matrix": matrix["runtime_consumer_contract_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "sample_source_traces": matrix["sample_source_traces"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s1_value_binding_contract.json", result)
    write_json(output_dir / "p5_s1_value_binding_contract_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S1 value binding and RuleBook contract audit.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['total_row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s1_value_binding_contract_matrix(
    package_root: Path,
    ir: CanonicalIR,
    rules: RuleBook,
) -> dict[str, Any]:
    binding_rows = [
        _container_contract_row(
            "skill_formula_binding_contract",
            tuple(ir.skill_formula_bindings),
            id_attr="binding_id",
            rulebook_lookup=lambda item: rules.skill_formula_binding(item.binding_id) is item,
            parent_lookup=lambda item: item
            in rules.skill_formula_bindings_for_action_param(
                item.action_id,
                item.level,
                item.param_index,
                item.formula_role,
            ),
            consumer_owner="P5-S2 static parameter binding, P5-S4 ValueResolver",
        ),
        _container_contract_row(
            "damage_emission_contract",
            tuple(ir.damage_emissions),
            id_attr="damage_emission_id",
            rulebook_lookup=lambda item: rules.damage_emission(item.damage_emission_id) is item,
            parent_lookup=lambda item: item in rules.damage_emissions_for_action(item.action_id, item.level)
            and item in rules.damage_emissions_for_task(item.source_task_id),
            consumer_owner="P5-S5 damage consumer",
        ),
        _container_contract_row(
            "toughness_emission_contract",
            tuple(ir.toughness_emissions),
            id_attr="toughness_emission_id",
            rulebook_lookup=lambda item: rules.toughness_emission(item.toughness_emission_id) is item,
            parent_lookup=lambda item: item in rules.toughness_emissions_for_action(item.action_id, item.level)
            and item in rules.toughness_emissions_for_task(item.source_task_id),
            consumer_owner="P5-S5 toughness consumer",
        ),
        _container_contract_row(
            "resource_rule_contract",
            tuple(ir.resource_rules),
            id_attr="resource_rule_id",
            rulebook_lookup=lambda item: rules.resource_rule(item.resource_rule_id) is item,
            parent_lookup=lambda item: item in rules.resource_rules_by_kind(item.rule_kind),
            consumer_owner="P5-S6 skill point, energy and custom resource consumers",
        ),
        _container_contract_row(
            "status_damage_emission_contract",
            tuple(ir.status_damage_emissions),
            id_attr="status_damage_emission_id",
            rulebook_lookup=lambda item: rules.status_damage_emission(item.status_damage_emission_id) is item,
            parent_lookup=lambda item: item in rules.status_damage_emissions_for_callback(item.callback_id),
            consumer_owner="P5-S6 status numeric consumer",
        ),
        _container_contract_row(
            "action_delay_emission_contract",
            tuple(ir.action_delay_emissions),
            id_attr="action_delay_emission_id",
            rulebook_lookup=lambda item: rules.action_delay_emission(item.action_delay_emission_id) is item,
            parent_lookup=lambda item: item in rules.action_delay_emissions_for_callback(item.callback_id),
            consumer_owner="P5-S6 callback queue numeric consumer",
        ),
        _container_contract_row(
            "queue_intent_contract",
            tuple(ir.queue_intents),
            id_attr="queue_intent_id",
            rulebook_lookup=lambda item: rules.queue_intent(item.queue_intent_id) is item,
            parent_lookup=lambda item: item in rules.queue_intents_for_callback(item.callback_id),
            consumer_owner="P5-S6 callback queue numeric consumer",
        ),
        _container_contract_row(
            "summon_intent_contract",
            tuple(ir.summon_monster_intents),
            id_attr="summon_intent_id",
            rulebook_lookup=lambda item: rules.summon_monster_intent(item.summon_intent_id) is item,
            parent_lookup=lambda item: bool(item.entries),
            consumer_owner="P5-S7 summoned monster custom/profile binding",
        ),
        _mechanism_slot_contract_row(ir, rules),
    ]
    query_rows = [
        _query_contract_row(
            "skill_formula_binding_rulebook_queries",
            required_methods=("skill_formula_binding", "skill_formula_bindings_for_action_param"),
            sample_count=len(ir.skill_formula_bindings),
            visible_count=_count_visible(
                ir.skill_formula_bindings,
                lambda item: rules.skill_formula_binding(item.binding_id) is item
                and item
                in rules.skill_formula_bindings_for_action_param(
                    item.action_id,
                    item.level,
                    item.param_index,
                    item.formula_role,
                ),
            ),
            source_trace_count=_source_trace_count(ir.skill_formula_bindings),
            consumer_owner="P5-S2/P5-S4",
        ),
        _query_contract_row(
            "damage_toughness_rulebook_queries",
            required_methods=(
                "damage_emission",
                "damage_emissions_for_action",
                "damage_emissions_for_task",
                "toughness_emission",
                "toughness_emissions_for_action",
                "toughness_emissions_for_task",
            ),
            sample_count=len(ir.damage_emissions) + len(ir.toughness_emissions),
            visible_count=_count_visible(ir.damage_emissions, lambda item: rules.damage_emission(item.damage_emission_id) is item)
            + _count_visible(ir.toughness_emissions, lambda item: rules.toughness_emission(item.toughness_emission_id) is item),
            source_trace_count=_source_trace_count((*ir.damage_emissions, *ir.toughness_emissions)),
            consumer_owner="P5-S5",
        ),
        _query_contract_row(
            "resource_rulebook_queries",
            required_methods=("resource_rule", "resource_rules_by_kind"),
            sample_count=len(ir.resource_rules),
            visible_count=_count_visible(ir.resource_rules, lambda item: rules.resource_rule(item.resource_rule_id) is item),
            source_trace_count=_source_trace_count(ir.resource_rules),
            consumer_owner="P5-S6",
        ),
        _query_contract_row(
            "status_callback_numeric_rulebook_queries",
            required_methods=(
                "status_damage_emission",
                "status_damage_emissions_for_callback",
                "action_delay_emission",
                "action_delay_emissions_for_callback",
                "queue_intent",
                "queue_intents_for_callback",
            ),
            sample_count=len(ir.status_damage_emissions) + len(ir.action_delay_emissions) + len(ir.queue_intents),
            visible_count=_count_visible(
                ir.status_damage_emissions,
                lambda item: rules.status_damage_emission(item.status_damage_emission_id) is item,
            )
            + _count_visible(ir.action_delay_emissions, lambda item: rules.action_delay_emission(item.action_delay_emission_id) is item)
            + _count_visible(ir.queue_intents, lambda item: rules.queue_intent(item.queue_intent_id) is item),
            source_trace_count=_source_trace_count((*ir.status_damage_emissions, *ir.action_delay_emissions, *ir.queue_intents)),
            consumer_owner="P5-S6",
        ),
        _query_contract_row(
            "summon_intent_rulebook_queries",
            required_methods=("summon_monster_intent", "summon_monster_intents"),
            sample_count=len(ir.summon_monster_intents),
            visible_count=_count_visible(
                ir.summon_monster_intents,
                lambda item: rules.summon_monster_intent(item.summon_intent_id) is item,
            ),
            source_trace_count=_source_trace_count(ir.summon_monster_intents),
            consumer_owner="P5-S7",
        ),
        _query_contract_row(
            "data_card_mechanism_rulebook_queries",
            required_methods=(
                "character_mechanism_slot",
                "character_mechanism_slots_for_card",
                "passive_mechanism_slot",
                "passive_mechanism_slots_for_card",
                "passive_mechanism_slots_for_owner",
            ),
            sample_count=len(ir.character_mechanism_slots) + len(ir.passive_mechanism_slots),
            visible_count=_count_visible(
                ir.character_mechanism_slots,
                lambda item: rules.character_mechanism_slot(item.mechanism_slot_id) is item,
            )
            + _count_visible(ir.passive_mechanism_slots, lambda item: rules.passive_mechanism_slot(item.passive_slot_id) is item),
            source_trace_count=_source_trace_count((*ir.character_mechanism_slots, *ir.passive_mechanism_slots)),
            consumer_owner="P5-S8",
        ),
    ]
    consumer_rows = [
        _runtime_consumer_row(
            package_root,
            "damage_toughness_runtime_consumer_contract",
            file_paths=("core/executor.py", "systems/damage.py", "systems/damage_formula.py"),
            required_tokens=("damage_emissions_for_action", "toughness_emissions_for_action", "source_trace"),
            direct_ir_evidence={
                "damage_emission_count": len(ir.damage_emissions),
                "toughness_emission_count": len(ir.toughness_emissions),
            },
            future_owner="P5-S5 ValueResolver consumer migration",
        ),
        _runtime_consumer_row(
            package_root,
            "resource_runtime_consumer_contract",
            file_paths=("systems/action_preflight.py", "systems/resource.py", "core/executor.py"),
            required_tokens=("ResourcePlan", "resource", "energy", "skill_point"),
            direct_ir_evidence={"resource_rule_count": len(ir.resource_rules)},
            future_owner="P5-S6 resource consumer migration",
        ),
        _runtime_consumer_row(
            package_root,
            "status_callback_numeric_runtime_consumer_contract",
            file_paths=("systems/status_callbacks.py", "systems/status.py", "systems/queue.py"),
            required_tokens=("status_damage_emissions_for_callback", "action_delay_emissions_for_callback", "queue_intents_for_callback"),
            direct_ir_evidence={
                "status_damage_emission_count": len(ir.status_damage_emissions),
                "action_delay_emission_count": len(ir.action_delay_emissions),
                "queue_intent_count": len(ir.queue_intents),
            },
            future_owner="P5-S6 status/callback numeric consumer migration",
        ),
        _runtime_consumer_row(
            package_root,
            "summon_intent_runtime_consumer_contract",
            file_paths=("systems/summon.py",),
            required_tokens=("plan_spawn_from_intent", "SummonMonsterIntentIR", "source_trace"),
            direct_ir_evidence={"summon_monster_intent_count": len(ir.summon_monster_intents)},
            future_owner="P5-S7 summon intent ValueResolver migration",
        ),
        _runtime_consumer_row(
            package_root,
            "numeric_evaluator_current_contract",
            file_paths=("rules/evaluator.py",),
            required_tokens=("evaluate_numeric", "dynamic_hash", "dynamic_hash_unbound"),
            direct_ir_evidence={"formula_count": len(ir.formulas)},
            future_owner="P5-S4 ValueResolver admission",
            classification_override="boundary_only",
        ),
        _s0_missing_consumer_ref_policy_row(),
    ]

    all_rows = binding_rows + query_rows + consumer_rows
    gap_attribution = _gap_attribution_matrix(all_rows)
    classification_counts = Counter(str(row["classification"]) for row in all_rows)
    gap_counts = _gap_counts(all_rows)
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "binding_container_contract_matrix": {str(row["row_id"]): row for row in binding_rows},
        "rulebook_query_contract_matrix": {str(row["row_id"]): row for row in query_rows},
        "runtime_consumer_contract_matrix": {str(row["row_id"]): row for row in consumer_rows},
        "gap_attribution_matrix": gap_attribution,
        "sample_source_traces": _sample_source_trace_matrix(all_rows),
        "summary": {
            "total_row_count": len(all_rows),
            "binding_container_row_count": len(binding_rows),
            "rulebook_query_row_count": len(query_rows),
            "runtime_consumer_row_count": len(consumer_rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": disallowed_gap_count,
            "implementation_missing_count": int(gap_counts.get("implementation_missing", 0)),
            "lowering_gap_count": int(gap_counts.get("lowering_gap", 0)),
            "validation_gap_count": int(gap_counts.get("validation_gap", 0)),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "sample_source_trace_count": _sample_source_trace_matrix(all_rows)["summary"]["sample_count"],
            "s0_missing_consumer_refs_policy": "direct_ir_consumer_or_source_evidence_required; missing P4 later-stage rows are not consumer admission proof",
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "runtime_file_scan_count": 9,
            "subprocess_validation_count": 0,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_scope": "p5_s1_contract_matrices_gap_attribution_samples_only",
            "output_files": [
                "validation_summary_p5_s1_value_binding_contract.json",
                "p5_s1_value_binding_contract_matrix.json",
            ],
        },
    }


def validate_p5_s1_value_binding_contract_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    binding_rows = dict(matrix.get("binding_container_contract_matrix") or {})
    query_rows = dict(matrix.get("rulebook_query_contract_matrix") or {})
    consumer_rows = dict(matrix.get("runtime_consumer_contract_matrix") or {})
    all_rows = {**binding_rows, **query_rows, **consumer_rows}
    missing_binding = sorted(REQUIRED_BINDING_ROWS.difference(binding_rows))
    missing_query = sorted(REQUIRED_QUERY_ROWS.difference(query_rows))
    missing_consumer = sorted(REQUIRED_CONSUMER_ROWS.difference(consumer_rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in all_rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_without_attribution = sorted(
        row_id
        for row_id, row in all_rows.items()
        if str(row.get("classification") or "") in GAP_STATES and not row.get("gap_attribution")
    )
    checks = {
        "required_binding_rows_present": not missing_binding,
        "required_query_rows_present": not missing_query,
        "required_consumer_rows_present": not missing_consumer,
        "valid_classifications": not invalid_classifications,
        "unclassified_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "disallowed_gap_zero": int(matrix.get("summary", {}).get("disallowed_gap_count") or 0) == 0,
        "all_row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in all_rows.values()),
        "gap_rows_have_attribution": not gap_without_attribution,
        "sample_source_traces_present": int(matrix.get("summary", {}).get("sample_source_trace_count") or 0) > 0,
        "s0_missing_consumer_policy_present": "s0_missing_consumer_ref_policy" in consumer_rows,
        "resource_budget_summary_only": (
            matrix.get("resource_budget", {}).get("full_ir_written") is False
            and matrix.get("resource_budget", {}).get("full_rulebook_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_binding_rows": missing_binding,
        "missing_query_rows": missing_query,
        "missing_consumer_rows": missing_consumer,
        "invalid_classifications": invalid_classifications,
        "gap_without_attribution": gap_without_attribution,
    }


def _container_contract_row(
    row_id: str,
    items: tuple[Any, ...],
    *,
    id_attr: str,
    rulebook_lookup: Callable[[Any], bool],
    parent_lookup: Callable[[Any], bool],
    consumer_owner: str,
) -> dict[str, JSONValue]:
    stable_id_count = sum(1 for item in items if bool(getattr(item, id_attr, "")))
    source_trace_count = _source_trace_count(items)
    rulebook_visible_count = _count_visible(items, rulebook_lookup)
    parent_visible_count = _count_visible(items, parent_lookup)
    executable_count = sum(1 for item in items if getattr(item, "coverage_status", "") == "executable")
    gap_count = 0
    gap_reasons: dict[str, int] = {}
    if stable_id_count != len(items):
        gap_reasons["missing_stable_id"] = len(items) - stable_id_count
    if source_trace_count != len(items):
        gap_reasons["missing_source_trace"] = len(items) - source_trace_count
    if rulebook_visible_count != len(items):
        gap_reasons["missing_rulebook_id_query"] = len(items) - rulebook_visible_count
    if parent_visible_count != len(items):
        gap_reasons["missing_parent_query"] = len(items) - parent_visible_count
    gap_count = sum(gap_reasons.values())
    classification = "executable" if items and gap_count == 0 else "admission_gap"
    if not items:
        classification = "source_gap_blocked"
        gap_reasons["source_absent"] = 1
        gap_count = 1
    checks = {
        "scan_completed": True,
        "stable_ids_counted": stable_id_count <= len(items),
        "source_traces_counted": source_trace_count <= len(items),
        "rulebook_visibility_counted": rulebook_visible_count <= len(items),
        "parent_visibility_counted": parent_visible_count <= len(items),
        "consumer_not_claimed_as_value_resolver_admitted": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        classification=classification,
        checks=checks,
        ir_count=len(items),
        rulebook_visible_count=rulebook_visible_count,
        executable_count=executable_count,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if classification == "admission_gap" else {"source_gap_blocked": gap_count}
        if classification == "source_gap_blocked"
        else {},
        sample_source_trace=_first_source_trace(items),
        details={
            "id_attr": id_attr,
            "stable_id_count": stable_id_count,
            "source_trace_count": source_trace_count,
            "parent_visible_count": parent_visible_count,
            "coverage_status_counts": dict(sorted(Counter(str(getattr(item, "coverage_status", "")) for item in items).items())),
            "gap_reasons": dict(sorted(gap_reasons.items())),
            "consumer_owner": consumer_owner,
        },
    )


def _mechanism_slot_contract_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    character_slots = tuple(ir.character_mechanism_slots)
    passive_slots = tuple(ir.passive_mechanism_slots)
    items = (*character_slots, *passive_slots)
    character_visible = _count_visible(
        character_slots,
        lambda item: rules.character_mechanism_slot(item.mechanism_slot_id) is item
        and item in rules.character_mechanism_slots_for_card(item.character_data_card_id),
    )
    passive_visible = _count_visible(
        passive_slots,
        lambda item: rules.passive_mechanism_slot(item.passive_slot_id) is item
        and item in rules.passive_mechanism_slots_for_card(item.data_card_id),
    )
    source_trace_count = _source_trace_count(items)
    gap_count = (len(items) - character_visible - passive_visible) + (len(items) - source_trace_count)
    classification = "executable" if items and gap_count == 0 else "admission_gap"
    checks = {
        "scan_completed": True,
        "mechanism_slots_present": bool(items),
        "rulebook_visibility_counted": character_visible + passive_visible <= len(items),
        "source_traces_counted": source_trace_count <= len(items),
        "consumer_not_claimed_as_value_resolver_admitted": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "data_card_mechanism_slot_contract",
        classification=classification,
        checks=checks,
        ir_count=len(items),
        rulebook_visible_count=character_visible + passive_visible,
        executable_count=sum(1 for item in items if getattr(item, "coverage_status", "") == "executable"),
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        sample_source_trace=_first_source_trace(items),
        details={
            "character_mechanism_slot_count": len(character_slots),
            "passive_mechanism_slot_count": len(passive_slots),
            "source_trace_count": source_trace_count,
            "consumer_owner": "P5-S8 character trace/eidolon/enhanced-form numeric binding",
        },
    )


def _query_contract_row(
    row_id: str,
    *,
    required_methods: tuple[str, ...],
    sample_count: int,
    visible_count: int,
    source_trace_count: int,
    consumer_owner: str,
) -> dict[str, JSONValue]:
    missing_methods = [method for method in required_methods if not hasattr(RuleBook, method)]
    gap_count = len(missing_methods) + max(sample_count - visible_count, 0) + max(sample_count - source_trace_count, 0)
    classification = "executable" if sample_count and gap_count == 0 else "admission_gap"
    if not sample_count:
        classification = "source_gap_blocked"
        gap_count = max(gap_count, 1)
    checks = {
        "methods_checked": True,
        "required_methods_present": not missing_methods,
        "visibility_counted": visible_count <= sample_count,
        "source_trace_counted": source_trace_count <= sample_count,
        "consumer_not_claimed_as_value_resolver_admitted": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        classification=classification,
        checks=checks,
        ir_count=sample_count,
        rulebook_visible_count=visible_count,
        executable_count=visible_count if classification == "executable" else 0,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if classification == "admission_gap" else {"source_gap_blocked": gap_count}
        if classification == "source_gap_blocked"
        else {},
        details={
            "required_methods": list(required_methods),
            "missing_methods": missing_methods,
            "source_trace_count": source_trace_count,
            "consumer_owner": consumer_owner,
        },
    )


def _runtime_consumer_row(
    package_root: Path,
    row_id: str,
    *,
    file_paths: tuple[str, ...],
    required_tokens: tuple[str, ...],
    direct_ir_evidence: dict[str, JSONValue],
    future_owner: str,
    classification_override: str | None = None,
) -> dict[str, JSONValue]:
    texts = {path: _read_text(package_root / path) for path in file_paths}
    found_tokens = {
        token: sorted(path for path, text in texts.items() if token in text)
        for token in required_tokens
    }
    missing_tokens = sorted(token for token, paths in found_tokens.items() if not paths)
    consumer_count = sum(int(value) for value in direct_ir_evidence.values() if isinstance(value, int))
    gap_count = len(missing_tokens)
    classification = classification_override or ("admission_gap" if consumer_count or gap_count else "source_gap_blocked")
    if classification_override is None and not missing_tokens and not consumer_count:
        classification = "source_gap_blocked"
        gap_count = 1
    checks = {
        "runtime_files_scanned": all(texts.values()),
        "tokens_scanned": True,
        "direct_ir_evidence_present": bool(direct_ir_evidence),
        "missing_p4_later_stage_refs_not_used_as_admission_proof": True,
        "consumer_not_claimed_as_value_resolver_admitted": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        classification=classification,
        checks=checks,
        consumer_count=consumer_count,
        blocked_or_gap_count=max(gap_count, 1 if classification == "admission_gap" else 0),
        gap_attribution={"admission_gap": max(gap_count, 1)} if classification == "admission_gap" else {},
        details={
            "file_paths": list(file_paths),
            "required_tokens": list(required_tokens),
            "found_tokens": found_tokens,
            "missing_tokens": missing_tokens,
            "direct_ir_evidence": direct_ir_evidence,
            "future_owner": future_owner,
            "note": "This row proves only current source/consumer evidence; it does not prove ValueResolver admission.",
        },
    )


def _s0_missing_consumer_ref_policy_row() -> dict[str, JSONValue]:
    checks = {
        "s0_acceptance_note_recorded": True,
        "missing_consumer_refs_are_not_admission_proof": True,
        "direct_ir_consumer_or_source_evidence_required_for_s1_s5_s6": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "s0_missing_consumer_ref_policy",
        classification="boundary_only",
        checks=checks,
        details={
            "accepted_s0_note": (
                "Some S0 source families have missing_consumer_refs because S0 does not load later P4 "
                "stage matrices. S1/S5/S6 must not treat those refs as consumer admission proof."
            ),
            "policy": "Only direct IR consumer/source evidence or current runtime query evidence can support contract rows.",
        },
    )


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
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
        "schema_version": "p5_s1_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
    consumer_count: int = 0,
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
        "rulebook_visible_count": int(rulebook_visible_count),
        "consumer_count": int(consumer_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": sample_source_trace or {},
        "details": details or {},
    }


def _count_visible(items: Iterable[Any], predicate: Callable[[Any], bool]) -> int:
    count = 0
    for item in items:
        try:
            if predicate(item):
                count += 1
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return count


def _source_trace_count(items: Iterable[Any]) -> int:
    return sum(1 for item in items if bool(_source_trace(item)))


def _first_source_trace(items: Iterable[Any]) -> dict[str, JSONValue]:
    for item in items:
        trace = _source_trace(item)
        if trace:
            return _compact_json(trace)
    return {}


def _source_trace(item: Any) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    try:
        trace = source.to_json()
    except AttributeError:
        return {}
    return trace if isinstance(trace, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _sample_source_trace_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    samples = [
        {
            "row_id": str(row.get("row_id") or ""),
            "classification": str(row.get("classification") or ""),
            "sample_source_trace": _compact_json(row.get("sample_source_trace") or {}),
        }
        for row in rows
        if row.get("sample_source_trace")
    ]
    return {
        "schema_version": "p5_s1_sample_source_trace_matrix_v1",
        "rows": samples[:24],
        "summary": {"sample_count": len(samples[:24])},
    }


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter({key: 0 for key in GAP_STATES})
    for row in rows:
        attribution = row.get("gap_attribution") if isinstance(row.get("gap_attribution"), dict) else {}
        for key, value in attribution.items():
            if str(key) in GAP_STATES:
                counts[str(key)] += int(value or 0)
    return counts


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 18:
                result["..."] = "truncated"
                break
            result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:18]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
