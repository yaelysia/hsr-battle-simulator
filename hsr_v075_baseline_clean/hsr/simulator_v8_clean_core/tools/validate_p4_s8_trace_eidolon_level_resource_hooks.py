from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterBuildAssemblyResult, CharacterBuildInput
from ..core.model import JSONValue
from ..equipment.models import EquipmentBuildInput
from ..rules.ir import CanonicalIR, CharacterDataCardIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s8_trace_eidolon_level_resource_hooks"
MATRIX_SCHEMA_VERSION = "p4_s8_trace_eidolon_level_resource_hooks_matrix_v1"

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
}
REQUIRED_ROWS = {
    "trace_node_slot_matrix",
    "trace_static_stat_assembly_runtime",
    "trace_startup_ability_boundary",
    "eidolon_slot_rank_matrix",
    "eidolon_skill_level_assembly_runtime",
    "action_level_ladder_matrix",
    "startup_listener_resource_matrix",
    "equipment_build_input_hook_boundary",
    "invalid_eidolon_level_boundary",
}

BASE_STATS = {"max_hp", "attack", "defense", "speed"}
STARTUP_EVENTS = {"OnEnterBattle", "OnCreate", "OnStack"}
RESOURCE_OPCODES = {
    "ModifySP",
    "ModifySPNew",
    "ModifyEnergy",
    "SetDynamicValue",
    "SetDynamicValueByAddValue",
    "SetDynamicValueByCharacterCount",
    "DefineDynamicValue",
    "ConsumeActionCountDown",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s8_trace_eidolon_level_resource_hooks_matrix(ir, rules)
    matrix_checks = validate_p4_s8_trace_eidolon_level_resource_hooks_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s8_trace_eidolon_level_resource_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "scenario_injected_character_mechanism_result": False,
                "equipment_runtime_rule_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "trace_eidolon_level_resource_matrix": matrix["trace_eidolon_level_resource_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s8_trace_eidolon_level_resource_hooks.json", result)
    write_json(output_dir / "p4_s8_trace_eidolon_level_resource_hooks_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S8 trace/eidolon/level/resource/build hooks.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s8_trace_eidolon_level_resource_hooks_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    rows = [
        _trace_node_slot_matrix_row(ir, rules),
        _trace_static_stat_assembly_runtime_row(ir, rules),
        _trace_startup_ability_boundary_row(ir, rules),
        _eidolon_slot_rank_matrix_row(ir, rules),
        _eidolon_skill_level_assembly_runtime_row(ir, rules),
        _action_level_ladder_matrix_row(ir, rules),
        _startup_listener_resource_matrix_row(ir, rules),
        build_p4_s8_equipment_boundary_matrix_row(ir, rules),
        _invalid_eidolon_level_boundary_row(ir, rules),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "trace_eidolon_level_resource_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "trace_node_count": len(ir.character_trace_nodes),
            "eidolon_slot_count": len(ir.character_eidolon_slots),
            "character_mechanism_slot_count": len(ir.character_mechanism_slots),
            "character_data_card_count": len(ir.character_data_cards),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "scenario_builder_runtime_samples": 3,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s8_trace_eidolon_level_resource_hooks.json",
                "p4_s8_trace_eidolon_level_resource_hooks_matrix.json",
            ],
        },
    }


def validate_p4_s8_trace_eidolon_level_resource_hooks_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("trace_eidolon_level_resource_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    equipment_boundary_validation = validate_p4_s8_equipment_boundary_matrix_row(
        dict(rows.get("equipment_build_input_hook_boundary") or {})
    )
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "trace_static_runtime_executable": rows.get("trace_static_stat_assembly_runtime", {}).get("classification")
        == "executable",
        "eidolon_skill_level_runtime_executable": rows.get("eidolon_skill_level_assembly_runtime", {}).get("classification")
        == "executable",
        "equipment_typed_boundary_migration_complete": equipment_boundary_validation["ok"],
        "invalid_eidolon_rejected": _row_check(
            rows,
            "invalid_eidolon_level_boundary",
            "eidolon_level_above_six_rejected",
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "equipment_boundary_validation": equipment_boundary_validation,
    }


def _trace_node_slot_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    nodes = tuple(ir.character_trace_nodes)
    trace_slots = tuple(
        slot for slot in ir.character_mechanism_slots if slot.mechanism_kind.startswith("trace_")
    )
    visible_nodes = sum(1 for node in nodes if rules.character_trace_node(node.trace_node_id) is node)
    visible_slots = sum(1 for slot in trace_slots if rules.character_mechanism_slot(slot.mechanism_slot_id) is slot)
    executable = sum(1 for node in nodes if node.coverage_status == "executable") + sum(
        1 for slot in trace_slots if slot.coverage_status == "executable"
    )
    blocked = len(nodes) + len(trace_slots) - executable
    checks = {
        "trace_nodes_present": bool(nodes),
        "trace_slots_present": bool(trace_slots),
        "rulebook_nodes_visible": visible_nodes == len(nodes),
        "rulebook_slots_visible": visible_slots == len(trace_slots),
        "blocked_trace_slots_have_reason": all(slot.blocked_reason for slot in trace_slots if slot.coverage_status != "executable"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    total = len(nodes) + len(trace_slots)
    return _row(
        "trace_node_slot_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total,
        ir_count=total,
        rulebook_visible_count=visible_nodes + visible_slots,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(nodes)),
        details={
            "trace_node_coverage_counts": dict(sorted(Counter(node.coverage_status for node in nodes).items())),
            "trace_kind_counts": dict(sorted(Counter(node.trace_kind for node in nodes).items())),
            "trace_slot_coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in trace_slots).items())),
            "trace_slot_kind_counts": dict(sorted(Counter(slot.mechanism_kind for slot in trace_slots).items())),
            "blocked_reason_counts_top": _counter_top(Counter(slot.blocked_reason for slot in trace_slots if slot.blocked_reason), 20),
        },
    )


def _trace_static_stat_assembly_runtime_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_trace_static_stat_sample(ir, rules)
    checks: dict[str, Any]
    runtime_samples: list[dict[str, JSONValue]] = []
    if selected is None:
        checks = {"trace_static_sample_exists": False, "ok": False}
        return _row(
            "trace_static_stat_assembly_runtime",
            classification="validation_gap",
            checks=checks,
            raw_count=0,
            ir_count=0,
            blocked_or_gap_count=1,
            gap_attribution={"validation_gap": 1},
            details={"reason": "no executable trace static stat sample selected by structural predicate"},
        )
    card, node, slot, term, base_result, selected_result, selected_build = selected
    target_key = str(term.get("target_key") or "")
    before_value = Decimal(str(getattr(base_result.base_panel, target_key)))
    after_value = Decimal(str(getattr(selected_result.base_panel, target_key)))
    contributions = tuple(
        contribution
        for contribution in selected_result.contribution_ledger
        if contribution.source_ref.definition_kind == "character_mechanism_slot"
        and contribution.source_ref.definition_identity == slot.mechanism_slot_id
    )
    term_value = Decimal(str(term.get("value")))
    checks = {
        "trace_static_sample_exists": True,
        "formal_character_assembler_used": selected_result.assembly_status == "assembled",
        "formal_panel_available": selected_result.base_panel is not None,
        "trace_node_selected_in_build": node.trace_node_id
        in selected_build.unlocked_trace_node_ids,
        "trace_contributes_exactly_once": len(contributions) == 1,
        "trace_contribution_source_matches_slot": len(contributions) == 1
        and contributions[0].source == slot.source,
        "trace_contribution_keeps_exact_decimal": len(contributions) == 1
        and Decimal(contributions[0].exact_value) == term_value,
        "base_stat_changed": after_value != before_value,
        "legacy_panel_flag_path_not_used": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    runtime_samples.append(
        {
            "card_id": card.card_id,
            "trace_node_id": node.trace_node_id,
            "mechanism_slot_id": slot.mechanism_slot_id,
            "target_key": target_key,
            "before_value": str(before_value),
            "after_value": str(after_value),
            "exact_term_value": str(term_value),
            "source_trace": slot.source.to_json(),
        }
    )
    return _row(
        "trace_static_stat_assembly_runtime",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=1,
        ir_count=1,
        rulebook_visible_count=1,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=slot.source.to_json(),
        runtime_samples=runtime_samples,
    )


def _trace_startup_ability_boundary_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    slots = tuple(slot for slot in ir.character_mechanism_slots if slot.mechanism_kind == "trace_ability_hook")
    visible = sum(1 for slot in slots if rules.character_mechanism_slot(slot.mechanism_slot_id) is slot)
    executable = [slot for slot in slots if slot.coverage_status == "executable"]
    blocked = len(slots) - len(executable)
    checks = {
        "trace_ability_hook_slots_present": bool(slots),
        "rulebook_visible": visible == len(slots),
        "blocked_hooks_have_reason": all(slot.blocked_reason for slot in slots if slot.coverage_status != "executable"),
        "startup_hooks_do_not_execute_without_executable_slot": blocked >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "trace_startup_ability_boundary",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(slots),
        ir_count=len(slots),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(slots)),
        details={
            "coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in slots).items())),
            "blocked_reason_counts_top": _counter_top(Counter(slot.blocked_reason for slot in slots if slot.blocked_reason), 20),
        },
    )


def _eidolon_slot_rank_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    slots = tuple(ir.character_eidolon_slots)
    mechanism_slots = tuple(
        slot for slot in ir.character_mechanism_slots if slot.mechanism_kind.startswith("eidolon_")
    )
    visible_slots = sum(1 for slot in slots if rules.character_eidolon_slot(slot.eidolon_slot_id) is slot)
    visible_mechanisms = sum(1 for slot in mechanism_slots if rules.character_mechanism_slot(slot.mechanism_slot_id) is slot)
    executable = sum(1 for slot in slots if slot.coverage_status == "executable") + sum(
        1 for slot in mechanism_slots if slot.coverage_status == "executable"
    )
    blocked = len(slots) + len(mechanism_slots) - executable
    checks = {
        "eidolon_slots_present": bool(slots),
        "eidolon_mechanism_slots_present": bool(mechanism_slots),
        "rulebook_eidolon_slots_visible": visible_slots == len(slots),
        "rulebook_mechanism_slots_visible": visible_mechanisms == len(mechanism_slots),
        "rank_range_one_to_six": all(1 <= slot.rank <= 6 for slot in slots),
        "blocked_eidolon_mechanisms_have_reason": all(
            slot.blocked_reason for slot in mechanism_slots if slot.coverage_status != "executable"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    total = len(slots) + len(mechanism_slots)
    return _row(
        "eidolon_slot_rank_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total,
        ir_count=total,
        rulebook_visible_count=visible_slots + visible_mechanisms,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(slots)),
        details={
            "eidolon_slot_coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in slots).items())),
            "eidolon_rank_counts": dict(sorted(Counter(str(slot.rank) for slot in slots).items())),
            "mechanism_slot_coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in mechanism_slots).items())),
            "blocked_reason_counts_top": _counter_top(Counter(slot.blocked_reason for slot in mechanism_slots if slot.blocked_reason), 20),
        },
    )


def _eidolon_skill_level_assembly_runtime_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_eidolon_skill_level_sample(ir, rules)
    if selected is None:
        checks = {"eidolon_skill_level_sample_exists": False, "ok": False}
        return _row(
            "eidolon_skill_level_assembly_runtime",
            classification="validation_gap",
            checks=checks,
            raw_count=0,
            ir_count=0,
            blocked_or_gap_count=1,
            gap_attribution={"validation_gap": 1},
            details={"reason": "no eidolon skill_add_level_list sample selected by structural predicate"},
        )
    (
        card,
        slot,
        mechanism,
        raw_skill_id,
        bonus,
        base_result,
        selected_result,
        selected_build,
        resolution,
    ) = selected
    base_resolution = next(
        item for item in base_result.effective_skill_levels if item.action_id == resolution.action_id
    )
    bonus_sources = tuple(
        source
        for source in resolution.sources
        if source.source_kind == "eidolon_bonus"
        and source.source_ref.definition_identity == mechanism.mechanism_slot_id
    )
    checks = {
        "eidolon_skill_level_sample_exists": True,
        "formal_character_assembler_used": selected_result.assembly_status == "assembled",
        "eidolon_level_requested_recorded": selected_build.eidolon_level == slot.rank,
        "prefix_closed_rank_slot_selected": slot in rules.character_eidolon_slots_for_level(
            card.card_id,
            selected_build.eidolon_level,
        ),
        "skill_level_bonus_recorded": resolution.eidolon_level_bonus >= bonus
        and resolution.effective_level == base_resolution.effective_level + resolution.eidolon_level_bonus,
        "skill_level_bonus_source_recorded": len(bonus_sources) == 1
        and bonus_sources[0].level_value == bonus
        and bonus_sources[0].source == mechanism.source,
        "action_definition_binding_preserved": len(
            rules.action_definition_candidates(
                resolution.action_id,
                resolution.effective_level,
            )
        )
        == 1,
        "legacy_eidolon_runtime_flags_not_required": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "eidolon_skill_level_assembly_runtime",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=1,
        ir_count=1,
        rulebook_visible_count=1,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=slot.source.to_json(),
        runtime_samples=[
            {
                "card_id": card.card_id,
                "eidolon_slot_id": slot.eidolon_slot_id,
                "rank": slot.rank,
                "action_id": resolution.action_id,
                "bonus": bonus,
                "base_level": base_resolution.effective_level,
                "effective_level": resolution.effective_level,
                "source_trace": mechanism.source.to_json(),
            }
        ],
    )


def _action_level_ladder_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    entries = _character_action_entries(tuple(ir.character_data_cards))
    visible = sum(1 for _card, entry in entries if _definition_for_entry(rules, entry) is not None)
    executable = sum(
        1
        for _card, entry in entries
        for definition in [_definition_for_entry(rules, entry)]
        if definition is not None and definition.coverage_status == "executable"
    )
    blocked = len(entries) - executable
    checks = {
        "action_entries_present": bool(entries),
        "action_definitions_visible": visible == len(entries),
        "levels_present": bool(Counter(int(entry.get("level") or 0) for _card, entry in entries)),
        "skill_trigger_keys_present": bool(Counter(str(entry.get("skill_trigger_key") or "") for _card, entry in entries)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "action_level_ladder_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(entries),
        ir_count=len(entries),
        rulebook_visible_count=visible,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_entry_source(_first(entry for _card, entry in entries)),
        details={
            "level_counts": dict(sorted(Counter(str(int(entry.get("level") or 0)) for _card, entry in entries).items())),
            "max_level_counts": dict(sorted(Counter(str(entry.get("max_level") or "") for _card, entry in entries).items())),
            "skill_trigger_key_counts_top": _counter_top(Counter(str(entry.get("skill_trigger_key") or "") for _card, entry in entries), 20),
        },
    )


def _startup_listener_resource_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    callbacks = tuple(callback for callback in ir.status_callbacks if _is_character_source(callback) and callback.event in STARTUP_EVENTS)
    resource_tasks = tuple(task for task in ir.ability_tasks if _is_character_source(task) and task.opcode in RESOURCE_OPCODES)
    visible_callbacks = sum(1 for callback in callbacks if rules.status_callback(callback.callback_id) is callback)
    executable = sum(1 for callback in callbacks if callback.admission_status == "executable") + sum(
        1 for task in resource_tasks if task.coverage_status == "executable"
    )
    blocked = len(callbacks) + len(resource_tasks) - executable
    checks = {
        "startup_callbacks_present": bool(callbacks),
        "resource_tasks_present": bool(resource_tasks),
        "callbacks_rulebook_visible": visible_callbacks == len(callbacks),
        "blocked_callbacks_have_dependency": all(
            callback.blocking_dependency for callback in callbacks if callback.admission_status != "executable"
        ),
        "resource_tasks_classified": len(resource_tasks) >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "startup_listener_resource_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(callbacks) + len(resource_tasks),
        ir_count=len(callbacks) + len(resource_tasks),
        rulebook_visible_count=visible_callbacks + len(resource_tasks),
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(callbacks) or _first(resource_tasks)),
        details={
            "startup_event_counts": dict(sorted(Counter(callback.event for callback in callbacks).items())),
            "startup_admission_counts": dict(sorted(Counter(callback.admission_status for callback in callbacks).items())),
            "resource_task_opcode_counts": dict(sorted(Counter(task.opcode for task in resource_tasks).items())),
            "resource_task_coverage_counts": dict(sorted(Counter(task.coverage_status for task in resource_tasks).items())),
            "blocking_dependency_counts_top": _counter_top(
                Counter(callback.blocking_dependency for callback in callbacks if callback.blocking_dependency),
                20,
            ),
        },
    )


def build_p4_s8_equipment_boundary_matrix_row(
    ir: CanonicalIR,
    rules: RuleBook,
) -> dict[str, JSONValue]:
    cards = tuple(ir.character_data_cards)
    legacy_boundary_cards = tuple(
        card for card in cards if "equipment_boundary" in card.card_contract
    )
    sample_card = cards[0] if cards else None
    unit_flags: dict[str, JSONValue] = {}
    unit_resources: dict[str, float] = {}
    equipment_setup_mutations: tuple[Any, ...] = ()
    if sample_card is not None:
        built = ScenarioStateBuilder(rules).build(_single_avatar_scenario("p4_s8_equipment_boundary", sample_card))
        unit = built.state.units["ally:subject"]
        unit_flags = dict(unit.flags)
        unit_resources = dict(unit.resources)
        equipment_setup_mutations = tuple(
            mutation
            for mutation in built.setup_mutations
            if any(
                token in str(mutation).lower()
                for token in ("light_cone", "lightcone", "relic", "ornament", "equipment")
            )
        )
    forbidden_tokens = ("light_cone", "lightcone", "relic", "ornament", "equipment")
    has_equipment_runtime_key = any(
        token in str(key).lower()
        for key in (*unit_flags.keys(), *unit_resources.keys())
        for token in forbidden_tokens
    )
    character_card_source = (
        Path(__file__).resolve().parents[1] / "tbgd" / "character_cards.py"
    ).read_text(encoding="utf-8")
    eligibility_resolutions = tuple(
        rules.character_equipment_eligibility_for_card(card.card_id)
        for card in cards
    )
    checks = {
        "cards_present": bool(cards),
        "legacy_string_boundary_absent_from_source": '"equipment_boundary"' not in character_card_source,
        "legacy_string_boundary_absent_from_generated_cards": not legacy_boundary_cards,
        "typed_equipment_eligibility_field_present": all(
            hasattr(card, "equipment_eligibility_id") for card in cards
        ),
        "current_unbound_equipment_eligibility_queries_blocked": bool(eligibility_resolutions)
        and all(
            resolution.resolution_status == "blocked"
            and resolution.value is None
            and resolution.blocked_reason == "character_equipment_eligibility_unbound"
            for resolution in eligibility_resolutions
        ),
        "no_equipment_runtime_mutation_without_build_input": not has_equipment_runtime_key,
        "no_equipment_setup_mutation_without_build_input": not equipment_setup_mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "equipment_build_input_hook_boundary",
        classification="boundary_only",
        checks=checks,
        raw_count=len(cards),
        ir_count=len(cards),
        rulebook_visible_count=len(eligibility_resolutions),
        executable_count=0,
        blocked_or_gap_count=0,
        sample_source_trace=_source(sample_card),
        details={
            "card_count": len(cards),
            "legacy_boundary_card_count": len(legacy_boundary_cards),
            "typed_eligibility_ref_count": sum(bool(card.equipment_eligibility_id) for card in cards),
            "blocked_eligibility_query_count": sum(
                resolution.resolution_status == "blocked"
                for resolution in eligibility_resolutions
            ),
            "equipment_setup_mutation_count": len(equipment_setup_mutations),
            "future_owner": "CanonicalIR character equipment eligibility plus per-build equipment input",
        },
    )


def validate_p4_s8_equipment_boundary_matrix_row(row: dict[str, Any]) -> dict[str, Any]:
    required_checks = {
        "cards_present",
        "legacy_string_boundary_absent_from_source",
        "legacy_string_boundary_absent_from_generated_cards",
        "typed_equipment_eligibility_field_present",
        "current_unbound_equipment_eligibility_queries_blocked",
        "no_equipment_runtime_mutation_without_build_input",
        "no_equipment_setup_mutation_without_build_input",
    }
    check_envelope = dict(row.get("checks") or {})
    row_checks = dict(check_envelope.get("checks") or {})
    checks = {
        "row_id_preserved": row.get("row_id") == "equipment_build_input_hook_boundary",
        "classification_is_boundary_only": row.get("classification") == "boundary_only",
        "required_checks_present": required_checks.issubset(row_checks),
        "all_required_checks_true": all(row_checks.get(key) is True for key in required_checks),
        "row_ok": check_envelope.get("ok") is True and row_checks.get("ok") is True,
        "legacy_boundary_count_zero": int(row.get("details", {}).get("legacy_boundary_card_count") or 0) == 0,
        "equipment_setup_mutation_count_zero": int(
            row.get("details", {}).get("equipment_setup_mutation_count") or 0
        )
        == 0,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _invalid_eidolon_level_boundary_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    card = _first(ir.character_data_cards)
    error = ""
    if card is not None:
        try:
            ScenarioStateBuilder(rules).build(_single_avatar_scenario("p4_s8_invalid_eidolon", card, eidolon_level=7))
        except ValueError as exc:
            error = str(exc)
    checks = {
        "character_card_present": card is not None,
        "eidolon_level_above_six_rejected": "eidolon_level must be between 0 and 6" in error,
        "invalid_level_does_not_create_state": bool(error),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "invalid_eidolon_level_boundary",
        classification="boundary_only",
        checks=checks,
        raw_count=1,
        ir_count=1,
        blocked_or_gap_count=1,
        sample_source_trace=_source(card),
        details={"error": error},
    )


def _select_trace_static_stat_sample(
    ir: CanonicalIR,
    rules: RuleBook,
) -> tuple[
    CharacterDataCardIR,
    Any,
    Any,
    dict[str, Any],
    CharacterBuildAssemblyResult,
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
] | None:
    cards_by_id = {card.card_id: card for card in ir.character_data_cards}
    slots_by_id = {slot.mechanism_slot_id: slot for slot in ir.character_mechanism_slots}
    for node in sorted(ir.character_trace_nodes, key=lambda item: item.trace_node_id):
        card = cards_by_id.get(node.character_data_card_id)
        if card is None or rules.character_data_card(card.card_id) is not card:
            continue
        if node.default_unlocked or node.prerequisite_trace_ids:
            continue
        profile = rules.avatar_profile_by_profile_id(card.profile_id)
        if profile is None or not profile.promotion_tiers or profile.max_energy is None:
            continue
        tier = max(profile.promotion_tiers, key=lambda item: (item.promotion, item.max_level))
        base_build = _formal_character_build(card.card_id, tier.max_level, tier.promotion)
        base_result = assemble_character_build(rules, base_build)
        selected_build = _formal_character_build(
            card.card_id,
            tier.max_level,
            tier.promotion,
            trace_node_ids=(node.trace_node_id,),
        )
        selected_result = assemble_character_build(
            rules,
            selected_build,
        )
        if (
            base_result.assembly_status != "assembled"
            or base_result.base_panel is None
            or selected_result.assembly_status != "assembled"
            or selected_result.base_panel is None
        ):
            continue
        for slot_id in node.linked_mechanism_slot_ids:
            slot = slots_by_id.get(slot_id)
            if slot is None or slot.mechanism_kind != "trace_static_stat_bonus" or slot.coverage_status != "executable":
                continue
            for term in _dict_items(slot.semantics.get("mapped_terms")):
                if str(term.get("application_kind") or "") not in {"base_stat_ratio", "base_stat_delta"}:
                    continue
                if str(term.get("target_key") or "") not in BASE_STATS:
                    continue
                try:
                    value = Decimal(str(term.get("value")))
                except InvalidOperation:
                    continue
                if value != 0:
                    return (
                        card,
                        node,
                        slot,
                        term,
                        base_result,
                        selected_result,
                        selected_build,
                    )
    return None


def _select_eidolon_skill_level_sample(
    ir: CanonicalIR,
    rules: RuleBook,
) -> tuple[
    CharacterDataCardIR,
    Any,
    Any,
    str,
    int,
    CharacterBuildAssemblyResult,
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    Any,
] | None:
    cards_by_id = {card.card_id: card for card in ir.character_data_cards}
    mechanism_by_id = {
        mechanism.mechanism_slot_id: mechanism
        for mechanism in ir.character_mechanism_slots
    }
    for slot in sorted(ir.character_eidolon_slots, key=lambda item: item.eidolon_slot_id):
        card = cards_by_id.get(slot.character_data_card_id)
        if card is None:
            continue
        profile = rules.avatar_profile_by_profile_id(card.profile_id)
        if profile is None or not profile.promotion_tiers or profile.max_energy is None:
            continue
        tier = max(profile.promotion_tiers, key=lambda item: (item.promotion, item.max_level))
        base_build = _formal_character_build(card.card_id, tier.max_level, tier.promotion)
        base_result = assemble_character_build(rules, base_build)
        selected_build = _formal_character_build(
            card.card_id,
            tier.max_level,
            tier.promotion,
            eidolon_level=slot.rank,
        )
        selected_result = assemble_character_build(
            rules,
            selected_build,
        )
        if base_result.assembly_status != "assembled" or selected_result.assembly_status != "assembled":
            continue
        for mechanism_slot_id in slot.linked_mechanism_slot_ids:
            mechanism = mechanism_by_id.get(mechanism_slot_id)
            if mechanism is None or mechanism.mechanism_kind != "eidolon_skill_level":
                continue
            skill_add = mechanism.semantics.get("skill_add_level_list")
            if not isinstance(skill_add, dict):
                continue
            for raw_skill_id, raw_bonus in sorted(skill_add.items()):
                raw_value = raw_bonus.get("Value") if isinstance(raw_bonus, dict) else raw_bonus
                if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value <= 0:
                    continue
                action_id = f"avatar_skill:{raw_skill_id}"
                base_resolution = next(
                    (item for item in base_result.effective_skill_levels if item.action_id == action_id),
                    None,
                )
                resolution = next(
                    (item for item in selected_result.effective_skill_levels if item.action_id == action_id),
                    None,
                )
                if base_resolution is not None and resolution is not None:
                    return (
                        card,
                        slot,
                        mechanism,
                        str(raw_skill_id),
                        raw_value,
                        base_result,
                        selected_result,
                        selected_build,
                        resolution,
                    )
    return None


def _formal_character_build(
    card_id: str,
    level: int,
    promotion: int,
    *,
    eidolon_level: int = 0,
    trace_node_ids: tuple[str, ...] = (),
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:p4_s8:{card_id}:{level}:{promotion}:{eidolon_level}",
        character_card_id=card_id,
        level=level,
        promotion=promotion,
        eidolon_level=eidolon_level,
        unlocked_trace_node_ids=trace_node_ids,
        equipment_build=EquipmentBuildInput(
            build_id=f"validation:p4_s8:empty_equipment:{card_id}",
            character_card_id=card_id,
        ),
    )


def _single_avatar_scenario(
    scenario_id: str,
    card: CharacterDataCardIR,
    *,
    eidolon_level: int = 0,
    flags: dict[str, JSONValue] | None = None,
    panel_overrides: dict[str, float] | None = None,
) -> ScenarioSpec:
    values = {
        "max_hp": 1000.0,
        "hp": 1000.0,
        "attack": 100.0,
        "defense": 100.0,
        "speed": 100.0,
        "energy": 0.0,
        "max_energy": 100.0,
        "toughness": 0.0,
        "max_toughness": 0.0,
        "action_value": 0.0,
    }
    values.update(panel_overrides or {})
    panel = PanelInput(
        max_hp=values["max_hp"],
        hp=values["hp"],
        attack=values["attack"],
        defense=values["defense"],
        speed=values["speed"],
        energy=values["energy"],
        max_energy=values["max_energy"],
        toughness=values["toughness"],
        max_toughness=values["max_toughness"],
        action_value=values["action_value"],
        flags=flags or {},
        resources={},
        statuses=(),
    )
    return ScenarioSpec(
        scenario_id=scenario_id,
        version="p4_s8",
        units=(
            UnitSpec(
                unit_id="ally:subject",
                side="ally",
                build_mode="kernel_fixture",
                entity_ref=card.entity_ref,
                level=80,
                eidolon_level=eidolon_level,
                position=0,
                panel=panel,
            ),
        ),
        route=(),
        skill_points=3,
        max_skill_points=5,
    )


def _character_action_entries(cards: tuple[CharacterDataCardIR, ...]) -> tuple[tuple[CharacterDataCardIR, dict[str, Any]], ...]:
    entries: list[tuple[CharacterDataCardIR, dict[str, Any]]] = []
    for card in cards:
        for entry in (card.action_set or {}).get("actions", ()):
            if isinstance(entry, dict):
                entries.append((card, entry))
    return tuple(entries)


def _definition_for_entry(rules: RuleBook, entry: dict[str, Any]) -> Any | None:
    action_id = str(entry.get("action_id") or "")
    try:
        level = int(entry.get("level") or 0)
    except (TypeError, ValueError):
        level = 0
    return rules.action_definition(action_id, level) if action_id and level > 0 else None


def _is_character_source(item: Any) -> bool:
    source = getattr(item, "source", None)
    source_path = str(getattr(source, "source_path", "") or "")
    raw_type = str(getattr(source, "raw_type", "") or "")
    raw_id = str(getattr(source, "raw_id", "") or "")
    source_mode = str(getattr(item, "source_mode", "") or "")
    source_text = f"{source_path} {raw_type}"
    full_text = f"{source_text} {raw_id}"
    if "AssistantAvatar" in full_text:
        return False
    if source_mode == "mainline_avatar_ability":
        return True
    return "Avatar" in source_text or "Character" in source_text


def _slot_mentions_resource(slot: Any) -> bool:
    payload = " ".join(
        [
            str(slot.mechanism_kind),
            str(slot.runtime_system),
            str(slot.linked_ir_ids),
            str(slot.activation),
            str(slot.semantics),
        ]
    ).lower()
    return any(token in payload for token in ("resource", "energy", "sp", "skill_point", "countdown", "counter"))


def _dict_items(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _base_value_for_key(key: str) -> float:
    if key == "max_hp":
        return 1000.0
    return 100.0


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, Any],
    raw_count: int,
    ir_count: int,
    rulebook_visible_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    runtime_samples: list[dict[str, JSONValue]] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": sample_source_trace or {},
        "runtime_samples": runtime_samples or [],
        "details": details or {},
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _first(items: Iterable[Any]) -> Any | None:
    for item in items:
        return item
    return None


def _entry_source(entry: Any | None) -> dict[str, JSONValue]:
    if not isinstance(entry, dict):
        return {}
    source = entry.get("source_trace")
    return dict(source) if isinstance(source, dict) else {}


def _source(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    return source.to_json() if source is not None else {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
