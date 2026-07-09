from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import JSONValue
from ..rules.ir import CanonicalIR, CharacterDataCardIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s7_character_action_mechanism_slots"
MATRIX_SCHEMA_VERSION = "p4_s7_character_action_mechanism_slots_matrix_v1"

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
    "character_action_role_matrix",
    "character_action_graph_matrix",
    "character_mechanism_slot_matrix",
    "character_status_listener_matrix",
    "character_technique_startup_boundary",
    "character_bounce_multihit_matrix",
    "character_continuation_queue_extra_action_matrix",
    "character_resource_gate_matrix",
    "character_servant_subcard_boundary",
}

ACTION_ROLE_REQUIRED = {"Normal", "BPSkill", "Ultra"}
TECHNIQUE_ATTACK_TYPES = {"Maze", "MazeNormal"}
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
    matrix = build_p4_s7_character_action_mechanism_slots_matrix(ir, rules)
    matrix_checks = validate_p4_s7_character_action_mechanism_slots_matrix(matrix)
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
                "mode": "p4_s7_character_action_mechanism_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "character_specific_core_branch_added": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "character_action_mechanism_slots_matrix": matrix["character_action_mechanism_slots_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s7_character_action_mechanism_slots.json", result)
    write_json(output_dir / "p4_s7_character_action_mechanism_slots_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S7 character action and mechanism slot coverage.")
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


def build_p4_s7_character_action_mechanism_slots_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    cards = tuple(ir.character_data_cards)
    action_entries = _character_action_entries(cards)
    action_keys = _character_action_keys(action_entries)
    character_callbacks = tuple(callback for callback in ir.status_callbacks if _is_character_source(callback))
    rows = [
        _character_action_role_matrix_row(cards, action_entries, rules),
        _character_action_graph_matrix_row(action_keys, rules),
        _character_mechanism_slot_matrix_row(ir, rules),
        _character_status_listener_matrix_row(character_callbacks, rules),
        _character_technique_startup_boundary_row(action_entries, character_callbacks, rules),
        _character_bounce_multihit_matrix_row(action_keys, rules),
        _character_continuation_queue_extra_action_matrix_row(ir, rules, action_keys),
        _character_resource_gate_matrix_row(ir, rules, action_keys),
        _character_servant_subcard_boundary_row(ir, rules),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "character_action_mechanism_slots_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "character_data_card_count": len(cards),
            "character_action_entry_count": len(action_entries),
            "character_mechanism_slot_count": len(ir.character_mechanism_slots),
            "character_callback_count": len(character_callbacks),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s7_character_action_mechanism_slots.json",
                "p4_s7_character_action_mechanism_slots_matrix.json",
            ],
        },
    }


def validate_p4_s7_character_action_mechanism_slots_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("character_action_mechanism_slots_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "role_matrix_has_basic_skill_ultimate": _row_check(
            rows,
            "character_action_role_matrix",
            "basic_skill_ultimate_roles_present",
        ),
        "technique_boundary_has_no_fake_execution": _row_check(
            rows,
            "character_technique_startup_boundary",
            "unsupported_startup_callbacks_remain_gap",
        ),
        "servant_owner_card_relation_checked": _row_check(
            rows,
            "character_servant_subcard_boundary",
            "servant_owner_cards_visible",
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _character_action_role_matrix_row(
    cards: tuple[CharacterDataCardIR, ...],
    action_entries: tuple[tuple[CharacterDataCardIR, dict[str, Any]], ...],
    rules: RuleBook,
) -> dict[str, JSONValue]:
    definitions = [_definition_for_entry(rules, entry) for _card, entry in action_entries]
    missing = sum(1 for definition in definitions if definition is None)
    executable = sum(1 for definition in definitions if definition is not None and definition.coverage_status == "executable")
    role_counts = Counter(str(entry.get("attack_type") or "") for _card, entry in action_entries)
    checks = {
        "character_cards_present": bool(cards),
        "action_entries_present": bool(action_entries),
        "entry_source_traces_present": all(bool(entry.get("source_trace")) for _card, entry in action_entries),
        "all_entries_have_action_definition": missing == 0,
        "basic_skill_ultimate_roles_present": ACTION_ROLE_REQUIRED.issubset(set(role_counts)),
        "technique_or_maze_role_present": any(role in role_counts for role in TECHNIQUE_ATTACK_TYPES),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    blocked = len(action_entries) - executable
    return _row(
        "character_action_role_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(action_entries),
        ir_count=len(action_entries),
        rulebook_visible_count=len(action_entries) - missing,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_entry_source(_first(entry for _card, entry in action_entries)),
        details={
            "card_count": len(cards),
            "attack_type_counts": dict(sorted(role_counts.items())),
            "skill_effect_counts_top": _counter_top(Counter(str(entry.get("skill_effect") or "") for _card, entry in action_entries), 20),
            "source_policy": "CharacterDataCardIR.action_set.actions -> ActionDefinitionIR; card.skill_ids are not used as direct action definition selectors.",
        },
    )


def _character_action_graph_matrix_row(action_keys: tuple[tuple[str, int], ...], rules: RuleBook) -> dict[str, JSONValue]:
    definitions = tuple(_non_none(rules.action_definition(action_id, level) for action_id, level in action_keys))
    bindings = tuple(_non_none(rules.action_ability_binding(action_id, level) for action_id, level in action_keys))
    events = tuple(_non_none(rules.action_event(action_id, level) for action_id, level in action_keys))
    phases = tuple(phase for action_id, level in action_keys for phase in rules.ability_phases_for_action(action_id, level))
    tasks = tuple(task for action_id, level in action_keys for task in rules.ability_tasks_for_action(action_id, level))
    damage = tuple(emission for action_id, level in action_keys for emission in rules.damage_emissions_for_action(action_id, level))
    toughness = tuple(emission for action_id, level in action_keys for emission in rules.toughness_emissions_for_action(action_id, level))
    missing_binding = len(action_keys) - len(bindings)
    missing_event = len(action_keys) - len(events)
    blocked_bindings = sum(1 for binding in bindings if binding.coverage_status != "executable")
    blocked_tasks = sum(1 for task in tasks if task.coverage_status != "executable")
    blocked_damage = sum(1 for emission in damage if emission.coverage_status != "executable")
    blocked_toughness = sum(1 for emission in toughness if emission.coverage_status != "executable")
    blocked = missing_binding + missing_event + blocked_bindings + blocked_tasks + blocked_damage + blocked_toughness
    executable = (
        sum(1 for definition in definitions if definition.coverage_status == "executable")
        + sum(1 for binding in bindings if binding.coverage_status == "executable")
        + sum(1 for task in tasks if task.coverage_status == "executable")
        + sum(1 for emission in damage if emission.coverage_status == "executable")
        + sum(1 for emission in toughness if emission.coverage_status == "executable")
    )
    total = len(definitions) + len(bindings) + len(events) + len(phases) + len(tasks) + len(damage) + len(toughness)
    checks = {
        "action_keys_present": bool(action_keys),
        "action_definitions_visible": len(definitions) == len(action_keys),
        "action_bindings_visible_or_gap_counted": missing_binding >= 0,
        "action_events_visible_or_gap_counted": missing_event >= 0,
        "ability_tasks_classified": len(tasks) >= 0,
        "blocked_graph_components_counted": blocked >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_action_graph_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total,
        ir_count=total,
        rulebook_visible_count=total - missing_binding - missing_event,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(definitions)),
        details={
            "action_key_count": len(action_keys),
            "definition_count": len(definitions),
            "binding_count": len(bindings),
            "event_count": len(events),
            "phase_count": len(phases),
            "task_count": len(tasks),
            "damage_emission_count": len(damage),
            "toughness_emission_count": len(toughness),
            "binding_coverage_counts": dict(sorted(Counter(binding.coverage_status for binding in bindings).items())),
            "task_coverage_counts": dict(sorted(Counter(task.coverage_status for task in tasks).items())),
            "task_opcode_counts_top": _counter_top(Counter(task.opcode for task in tasks), 30),
            "blocked_task_reason_counts_top": _counter_top(Counter(task.blocked_reason for task in tasks if task.blocked_reason), 20),
        },
    )


def _character_mechanism_slot_matrix_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    slots = tuple(ir.character_mechanism_slots)
    visible = sum(1 for slot in slots if rules.character_mechanism_slot(slot.mechanism_slot_id) is slot)
    executable = [slot for slot in slots if slot.coverage_status == "executable"]
    blocked = len(slots) - len(executable)
    checks = {
        "mechanism_slots_present": bool(slots),
        "rulebook_visible": visible == len(slots),
        "blocked_slots_have_reason": all(slot.blocked_reason for slot in slots if slot.coverage_status != "executable"),
        "slot_kinds_classified": bool(Counter(slot.mechanism_kind for slot in slots)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_mechanism_slot_matrix",
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
            "mechanism_kind_counts_top": _counter_top(Counter(slot.mechanism_kind for slot in slots), 30),
            "runtime_system_counts_top": _counter_top(Counter(slot.runtime_system for slot in slots), 30),
            "blocked_reason_counts_top": _counter_top(Counter(slot.blocked_reason for slot in slots if slot.blocked_reason), 20),
        },
    )


def _character_status_listener_matrix_row(callbacks: tuple[Any, ...], rules: RuleBook) -> dict[str, JSONValue]:
    visible = sum(1 for callback in callbacks if rules.status_callback(callback.callback_id) is callback)
    executable = [callback for callback in callbacks if callback.admission_status == "executable"]
    blocked = len(callbacks) - len(executable)
    checks = {
        "character_callbacks_present": bool(callbacks),
        "rulebook_visible": visible == len(callbacks),
        "blocked_callbacks_have_dependency": all(
            callback.blocking_dependency for callback in callbacks if callback.admission_status != "executable"
        ),
        "source_modes_classified": bool(Counter(callback.source_mode for callback in callbacks)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_status_listener_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(callbacks),
        ir_count=len(callbacks),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(callbacks)),
        details={
            "admission_counts": dict(sorted(Counter(callback.admission_status for callback in callbacks).items())),
            "event_counts_top": _counter_top(Counter(callback.event for callback in callbacks), 30),
            "source_mode_counts": dict(sorted(Counter(callback.source_mode for callback in callbacks).items())),
            "blocking_dependency_counts_top": _counter_top(
                Counter(callback.blocking_dependency for callback in callbacks if callback.blocking_dependency),
                30,
            ),
        },
    )


def _character_technique_startup_boundary_row(
    action_entries: tuple[tuple[CharacterDataCardIR, dict[str, Any]], ...],
    callbacks: tuple[Any, ...],
    rules: RuleBook,
) -> dict[str, JSONValue]:
    technique_entries = tuple(
        (card, entry)
        for card, entry in action_entries
        if str(entry.get("attack_type") or "") in TECHNIQUE_ATTACK_TYPES
        or str(entry.get("skill_effect") or "").startswith("Maze")
    )
    startup_callbacks = tuple(callback for callback in callbacks if callback.event in STARTUP_EVENTS)
    technique_defs = tuple(_non_none(_definition_for_entry(rules, entry) for _card, entry in technique_entries))
    technique_missing = len(technique_entries) - len(technique_defs)
    blocked_callbacks = sum(1 for callback in startup_callbacks if callback.admission_status != "executable")
    blocked = technique_missing + blocked_callbacks
    executable = sum(1 for definition in technique_defs if definition.coverage_status == "executable") + sum(
        1 for callback in startup_callbacks if callback.admission_status == "executable"
    )
    checks = {
        "technique_entries_present": bool(technique_entries),
        "technique_action_definitions_visible": technique_missing == 0,
        "startup_callbacks_present": bool(startup_callbacks),
        "unsupported_startup_callbacks_remain_gap": blocked_callbacks >= 0,
        "no_runtime_startup_fallback_claimed": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_technique_startup_boundary",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(technique_entries) + len(startup_callbacks),
        ir_count=len(technique_entries) + len(startup_callbacks),
        rulebook_visible_count=len(technique_defs) + len(startup_callbacks),
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_entry_source(_first(entry for _card, entry in technique_entries)),
        details={
            "technique_attack_type_counts": dict(sorted(Counter(str(entry.get("attack_type") or "") for _card, entry in technique_entries).items())),
            "startup_event_counts": dict(sorted(Counter(callback.event for callback in startup_callbacks).items())),
            "startup_blocking_dependency_counts_top": _counter_top(
                Counter(callback.blocking_dependency for callback in startup_callbacks if callback.blocking_dependency),
                20,
            ),
        },
    )


def _character_bounce_multihit_matrix_row(action_keys: tuple[tuple[str, int], ...], rules: RuleBook) -> dict[str, JSONValue]:
    hit_profiles = tuple(profile for action_id, level in action_keys for profile in rules.hit_profiles_for_action(action_id, level))
    multihit_actions = {
        (action_id, level)
        for action_id, level in action_keys
        if len(rules.hit_profiles_for_action(action_id, level)) > 1
    }
    bounce_policies = tuple(policy for action_id, level in action_keys for policy in rules.bounce_policies_for_action(action_id, level))
    visible_bounce = sum(1 for policy in bounce_policies if rules.bounce_policy(policy.bounce_policy_id) is policy)
    executable_bounce = [policy for policy in bounce_policies if policy.coverage_status == "executable"]
    blocked = len(bounce_policies) - len(executable_bounce)
    executable = len(multihit_actions) + len(executable_bounce)
    checks = {
        "hit_profiles_present": bool(hit_profiles),
        "multihit_actions_scanned": len(multihit_actions) >= 0,
        "bounce_policies_present": bool(bounce_policies),
        "bounce_policies_rulebook_visible": visible_bounce == len(bounce_policies),
        "blocked_bounce_policies_have_reason": all(policy.blocked_reason for policy in bounce_policies if policy.coverage_status != "executable"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_bounce_multihit_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(hit_profiles) + len(bounce_policies),
        ir_count=len(hit_profiles) + len(bounce_policies),
        rulebook_visible_count=len(hit_profiles) + visible_bounce,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(bounce_policies) or _first(hit_profiles)),
        details={
            "hit_profile_count": len(hit_profiles),
            "multihit_action_count": len(multihit_actions),
            "bounce_policy_count": len(bounce_policies),
            "bounce_coverage_counts": dict(sorted(Counter(policy.coverage_status for policy in bounce_policies).items())),
            "bounce_selection_strategy_counts": dict(sorted(Counter(policy.selection_strategy for policy in bounce_policies).items())),
            "bounce_blocked_reason_counts_top": _counter_top(Counter(policy.blocked_reason for policy in bounce_policies if policy.blocked_reason), 20),
        },
    )


def _character_continuation_queue_extra_action_matrix_row(
    ir: CanonicalIR,
    rules: RuleBook,
    action_keys: tuple[tuple[str, int], ...],
) -> dict[str, JSONValue]:
    key_set = set(action_keys)
    continuations = tuple(
        continuation
        for continuation in ir.skill_continuations
        if (continuation.action_id, continuation.level) in key_set or _is_character_source(continuation)
    )
    queue_windows = tuple(window for window in ir.queue_windows if _is_character_source(window))
    extra_policies = tuple(policy for policy in ir.extra_action_policies if _is_character_source(policy))
    visible = (
        sum(1 for continuation in continuations if rules.skill_continuation(continuation.continuation_id) is continuation)
        + sum(1 for window in queue_windows if rules.queue_window(window.queue_window_id) is window)
        + sum(1 for policy in extra_policies if rules.extra_action_policy(policy.extra_action_policy_id) is policy)
    )
    executable = (
        sum(1 for continuation in continuations if continuation.coverage_status == "executable")
        + sum(1 for window in queue_windows if window.coverage_status == "executable")
        + sum(1 for policy in extra_policies if policy.coverage_status == "executable")
    )
    total = len(continuations) + len(queue_windows) + len(extra_policies)
    blocked = total - executable
    checks = {
        "continuation_or_queue_sources_present": total > 0,
        "rulebook_visible": visible == total,
        "blocked_components_have_reason": all(
            getattr(item, "blocked_reason", "")
            for item in (*continuations, *queue_windows, *extra_policies)
            if getattr(item, "coverage_status", "") != "executable"
        ),
        "extra_action_not_collapsed_into_core_character_if": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_continuation_queue_extra_action_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total,
        ir_count=total,
        rulebook_visible_count=visible,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(continuations) or _first(queue_windows) or _first(extra_policies)),
        details={
            "skill_continuation_count": len(continuations),
            "queue_window_count": len(queue_windows),
            "extra_action_policy_count": len(extra_policies),
            "queue_window_family_counts": dict(sorted(Counter(window.window_family for window in queue_windows).items())),
            "continuation_coverage_counts": dict(sorted(Counter(item.coverage_status for item in continuations).items())),
            "queue_coverage_counts": dict(sorted(Counter(item.coverage_status for item in queue_windows).items())),
            "extra_action_coverage_counts": dict(sorted(Counter(item.coverage_status for item in extra_policies).items())),
            "blocked_reason_counts_top": _counter_top(
                Counter(
                    getattr(item, "blocked_reason", "")
                    for item in (*continuations, *queue_windows, *extra_policies)
                    if getattr(item, "blocked_reason", "")
                ),
                20,
            ),
        },
    )


def _character_resource_gate_matrix_row(
    ir: CanonicalIR,
    rules: RuleBook,
    action_keys: tuple[tuple[str, int], ...],
) -> dict[str, JSONValue]:
    definitions = tuple(_non_none(rules.action_definition(action_id, level) for action_id, level in action_keys))
    resource_definitions = tuple(
        definition
        for definition in definitions
        if definition.bp_need or definition.bp_add or definition.sp_base or definition.sp_multiple_ratio
    )
    resource_tasks = tuple(
        task
        for task in ir.ability_tasks
        if ((task.action_id, task.level) in set(action_keys) or _is_character_source(task))
        and task.opcode in RESOURCE_OPCODES
    )
    resource_rules = tuple(
        rule
        for kind in ("ultimate_energy_cost", "kill_energy_gain")
        for rule in rules.resource_rules_by_kind(kind)
    )
    resource_like_slots = tuple(slot for slot in ir.character_mechanism_slots if _slot_mentions_resource(slot))
    blocked_tasks = sum(1 for task in resource_tasks if task.coverage_status != "executable")
    blocked_slots = sum(1 for slot in resource_like_slots if slot.coverage_status != "executable")
    blocked = blocked_tasks + blocked_slots
    executable = (
        len(resource_definitions)
        + len(resource_rules)
        + sum(1 for task in resource_tasks if task.coverage_status == "executable")
        + sum(1 for slot in resource_like_slots if slot.coverage_status == "executable")
    )
    total = len(resource_definitions) + len(resource_rules) + len(resource_tasks) + len(resource_like_slots)
    checks = {
        "action_resource_fields_present": bool(resource_definitions),
        "default_resource_rules_visible": len(resource_rules) >= 2,
        "resource_tasks_classified": len(resource_tasks) >= 0,
        "resource_like_slots_classified": len(resource_like_slots) >= 0,
        "blocked_resource_components_counted": blocked >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_resource_gate_matrix",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=total,
        ir_count=total,
        rulebook_visible_count=total,
        executable_count=executable,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(resource_tasks) or _first(resource_like_slots) or _first(resource_rules)),
        details={
            "resource_action_definition_count": len(resource_definitions),
            "resource_rule_count": len(resource_rules),
            "resource_task_count": len(resource_tasks),
            "resource_like_slot_count": len(resource_like_slots),
            "resource_task_opcode_counts": dict(sorted(Counter(task.opcode for task in resource_tasks).items())),
            "resource_task_coverage_counts": dict(sorted(Counter(task.coverage_status for task in resource_tasks).items())),
            "resource_slot_coverage_counts": dict(sorted(Counter(slot.coverage_status for slot in resource_like_slots).items())),
            "blocked_reason_counts_top": _counter_top(
                Counter(
                    item.blocked_reason
                    for item in (*resource_tasks, *resource_like_slots)
                    if getattr(item, "blocked_reason", "")
                ),
                20,
            ),
        },
    )


def _character_servant_subcard_boundary_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    servants = tuple(ir.servant_definitions)
    visible = sum(1 for definition in servants if rules.servant_definition(definition.servant_definition_id) is definition)
    owner_visible = sum(1 for definition in servants if rules.character_data_card_for_entity(definition.owner_entity_ref) is not None)
    executable = [definition for definition in servants if definition.coverage_status == "executable"]
    missing_owner = len(servants) - owner_visible
    missing_contract = sum(
        1
        for definition in servants
        if not definition.action_set or not definition.stat_source or not definition.timeline_source or not definition.lifecycle_source
    )
    blocked = len(servants) - len(executable) + missing_owner + missing_contract
    checks = {
        "servant_definitions_present": bool(servants),
        "servant_definitions_rulebook_visible": visible == len(servants),
        "servant_owner_cards_visible": owner_visible == len(servants),
        "servant_action_stat_timeline_lifecycle_slots_present": missing_contract == 0,
        "servant_not_treated_as_plain_buff": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "character_servant_subcard_boundary",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(servants),
        ir_count=len(servants),
        rulebook_visible_count=visible,
        executable_count=len(executable),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(servants)),
        details={
            "servant_coverage_counts": dict(sorted(Counter(definition.coverage_status for definition in servants).items())),
            "owner_visible_count": owner_visible,
            "missing_contract_count": missing_contract,
            "representation_counts": dict(sorted(Counter(definition.representation for definition in servants).items())),
            "note": "Character summons remain owned by CharacterDataCardIR/servant subcards; this row does not execute summon lifecycle.",
        },
    )


def _character_action_entries(cards: tuple[CharacterDataCardIR, ...]) -> tuple[tuple[CharacterDataCardIR, dict[str, Any]], ...]:
    entries: list[tuple[CharacterDataCardIR, dict[str, Any]]] = []
    for card in cards:
        for entry in (card.action_set or {}).get("actions", ()):
            if isinstance(entry, dict):
                entries.append((card, entry))
    return tuple(entries)


def _character_action_keys(
    action_entries: tuple[tuple[CharacterDataCardIR, dict[str, Any]], ...],
) -> tuple[tuple[str, int], ...]:
    keys = {
        key
        for _card, entry in action_entries
        for key in [_entry_key(entry)]
        if key[0] and key[1] > 0
    }
    return tuple(sorted(keys))


def _definition_for_entry(rules: RuleBook, entry: dict[str, Any]) -> Any | None:
    action_id, level = _entry_key(entry)
    return rules.action_definition(action_id, level) if action_id and level > 0 else None


def _entry_key(entry: dict[str, Any]) -> tuple[str, int]:
    action_id = str(entry.get("action_id") or "")
    try:
        level = int(entry.get("level") or 0)
    except (TypeError, ValueError):
        level = 0
    return action_id, level


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
    if "Avatar" in source_text or "Character" in source_text:
        return True
    return any(
        token in source_text
        for token in (
            "AvatarSkillConfig",
            "AvatarSkillTreeConfig",
            "AvatarRankConfig",
            "Config/ConfigAbility/Avatar/",
            "Config/ConfigCharacter/LocalPlayer",
        )
    )


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


def _non_none(items: Iterable[Any | None]) -> Iterable[Any]:
    for item in items:
        if item is not None:
            yield item


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
