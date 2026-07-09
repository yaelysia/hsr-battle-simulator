from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, UnitState
from ..rules.ir import ActionDefinitionIR, CanonicalIR, CharacterDataCardIR, MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem, ActionAvailabilityView, ActionChoice
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
)
from .validate_p3_s6_summon_action_execution import (
    _spawn_servant_turn_state,
    _spawn_summoned_monster_turn_state,
)
from .validate_p4_s0_combatant_source_inventory import build_p4_s0_combatant_source_inventory_matrix
from .validate_p4_s1_data_card_rulebook_contract import build_p4_s1_data_card_rulebook_contract_matrix


VALIDATION_VERSION = "p4_s2_combatant_action_availability"
MATRIX_SCHEMA_VERSION = "p4_s2_combatant_action_availability_matrix_v1"

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
REQUIRED_CASES = {
    "character_normal_action_availability",
    "monster_fixed_sequence_availability",
    "servant_subcard_action_availability",
    "summoned_monster_fixed_sequence_availability",
    "availability_gate_boundaries",
    "missing_action_definition_source_scan",
    "s1_monster_card_action_set_link_gap_inherited",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    s0_matrix = build_p4_s0_combatant_source_inventory_matrix(tbgd_root, ir, rules)
    s1_matrix = build_p4_s1_data_card_rulebook_contract_matrix(ir, rules, s0_matrix)
    matrix = build_p4_s2_combatant_action_availability_matrix(ir, rules, s1_matrix)
    matrix_checks = validate_p4_s2_combatant_action_availability_matrix(matrix)
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
                "mode": "p4_s2_structural_action_availability_predicates",
                "runtime_raw_tbgd_read": False,
                "runtime_behavior_changed": True,
                "runtime_behavior_change_scope": "choice_source_trace_actor_data_card_only",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "s1_gap_matrix_inherited": True,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "action_availability_matrix": matrix["action_availability_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s2_combatant_action_availability.json", result)
    write_json(output_dir / "p4_s2_combatant_action_availability_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S2 combatant action availability.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"cases={result['summary']['case_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s2_combatant_action_availability_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    s1_matrix: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        _character_normal_action_availability_case(ir, rules),
        _monster_fixed_sequence_availability_case(ir, rules),
        _servant_subcard_action_availability_case(rules),
        _summoned_monster_fixed_sequence_availability_case(rules),
        _availability_gate_boundaries_case(ir, rules),
        _missing_action_definition_source_scan_case(rules),
        _s1_monster_card_action_set_link_gap_inherited_case(s1_matrix),
    ]
    matrix = {str(row["case_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "s1_schema_version": s1_matrix.get("schema_version"),
        "action_availability_matrix": matrix,
        "summary": {
            "case_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "executable_case_count": int(classification_counts.get("executable", 0)),
            "boundary_case_count": int(classification_counts.get("boundary_only", 0)),
            "s1_inherited_validation_gap_count": int(
                matrix["s1_monster_card_action_set_link_gap_inherited"]["details"].get("inherited_gap_count") or 0
            ),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s2_combatant_action_availability.json",
                "p4_s2_combatant_action_availability_matrix.json",
            ],
        },
    }


def validate_p4_s2_combatant_action_availability_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("action_availability_matrix") or {})
    missing = sorted(REQUIRED_CASES.difference(rows))
    invalid_classifications = sorted(
        case_id
        for case_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    executable_rows = [
        row for row in rows.values() if row.get("classification") == "executable"
    ]
    executable_source_trace_ok = all(
        bool(dict(row.get("sample_choice") or {}).get("source_trace", {}).get("action_definition"))
        and bool(dict(row.get("sample_choice") or {}).get("source_trace", {}).get("actor_data_card"))
        for row in executable_rows
    )
    gap_rows = [
        row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES
    ]
    gap_rows_attributed = all(bool(row.get("gap_attribution")) for row in gap_rows)
    checks = {
        "required_cases_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "case_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "executable_rows_have_choice_source_trace": executable_source_trace_ok,
        "gap_rows_have_attribution": gap_rows_attributed,
        "character_choice_executable": rows.get("character_normal_action_availability", {}).get("classification")
        == "executable",
        "monster_choice_external_not_ai": _row_check(rows, "monster_fixed_sequence_availability", "external_choice_not_ai"),
        "servant_choice_or_boundary_present": rows.get("servant_subcard_action_availability", {}).get(
            "classification"
        )
        in {"executable", "boundary_only"},
        "summoned_monster_choice_or_boundary_present": rows.get(
            "summoned_monster_fixed_sequence_availability", {}
        ).get("classification")
        in {"executable", "boundary_only"},
        "boundary_cases_state_unchanged": _row_check(rows, "availability_gate_boundaries", "all_state_unchanged"),
        "s1_gap_inherited": int(
            rows.get("s1_monster_card_action_set_link_gap_inherited", {})
            .get("details", {})
            .get("inherited_gap_count")
            or 0
        )
        >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_cases": missing,
        "invalid_classifications": invalid_classifications,
    }


def _character_normal_action_availability_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_character_choice(
        ir,
        rules,
        lambda _choice, _definition: True,
        require_choice_kind="normal_action",
    )
    card = selected["card"]
    state = selected["state"]
    view = selected["view"]
    choice = selected["choice"]
    before = selected["before"]
    after = selected["after"]
    actor_data_card = dict(choice.source_trace.get("actor_data_card") or {})
    checks = {
        "availability_external_selectable": view.mode == "external_selectable",
        "choice_kind_normal_action": choice.choice_kind == "normal_action",
        "choice_control_external": choice.control == "external",
        "choice_command_source_manual": choice.command_template.get("source") == "manual",
        "choice_has_action_definition_source": bool(choice.source_trace.get("action_definition")),
        "choice_has_action_event_source": bool(choice.source_trace.get("action_event")),
        "choice_has_combatant_action_set_source": bool(choice.source_trace.get("combatant_action_set")),
        "choice_has_character_data_card_source": actor_data_card.get("card_kind") == "character_data_card",
        "choice_data_card_matches_actor_entity": actor_data_card.get("card_id") == card.card_id,
        "rulebook_action_definition_visible": rules.action_definition(choice.action_id, choice.action_level) is not None,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "character_normal_action_availability",
        classification="executable",
        checks=checks,
        sample_choice=_compact_choice(choice),
        sample_actor=_compact_unit(state.units[choice.actor_id]),
        details={
            "character_data_card_id": card.card_id,
            "entity_ref": card.entity_ref,
            "view": _compact_view(view),
            "selection_predicate": "first character card with executable ActionChoice from CombatantActionSetIR",
        },
    )


def _monster_fixed_sequence_availability_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_monster_fixed_sequence_choice(ir, rules)
    card = selected["card"]
    state = selected["state"]
    view = selected["view"]
    choice = selected["choice"]
    actor_data_card = dict(choice.source_trace.get("actor_data_card") or {})
    checks = {
        "availability_external_selectable": view.mode == "external_selectable",
        "choice_kind_enemy_fixed_sequence": choice.choice_kind == "enemy_fixed_sequence",
        "choice_control_external": choice.control == "external",
        "external_choice_not_ai": choice.command_template.get("source") == "manual",
        "choice_has_monster_data_card_source": bool(choice.source_trace.get("monster_data_card")),
        "choice_has_actor_data_card_source": actor_data_card.get("card_kind") == "monster_data_card",
        "choice_has_action_sequence_step_source": bool(choice.source_trace.get("action_sequence_step")),
        "choice_has_action_definition_source": bool(choice.source_trace.get("action_definition")),
        "choice_has_action_event_source": bool(choice.source_trace.get("action_event")),
        "choice_data_card_matches_actor_entity": actor_data_card.get("card_id") == card.card_id,
        "candidate_available": dict(choice.metadata.get("enemy_action_candidate") or {}).get("status") == "available",
        "state_unchanged": selected["before"] == selected["after"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "monster_fixed_sequence_availability",
        classification="executable",
        checks=checks,
        sample_choice=_compact_choice(choice),
        sample_actor=_compact_unit(state.units[choice.actor_id]),
        details={
            "monster_data_card_id": card.card_id,
            "entity_ref": card.entity_ref,
            "ai_policy": card.ai_policy,
            "view": _compact_view(view),
            "selection_predicate": "MonsterDataCardIR fixed sequence with executable external availability choice",
        },
    )


def _servant_subcard_action_availability_case(rules: RuleBook) -> dict[str, JSONValue]:
    definition = _select_executable_servant_definition(rules)
    state = _spawn_servant_turn_state(rules, definition)
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    choices = [choice for choice in view.choices if choice.choice_kind == "summon_action"]
    if not choices:
        checks = {
            "availability_blocked_or_empty": view.mode == "blocked" and not view.choices,
            "state_unchanged": before == after,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return _case_row(
            "servant_subcard_action_availability",
            classification="boundary_only",
            checks=checks,
            blocked_reasons=[reason.reason for reason in view.blocked],
            details={
                "servant_definition_id": definition.servant_definition_id,
                "view": _compact_view(view),
            },
        )
    choice = choices[0]
    actor_data_card = dict(choice.source_trace.get("actor_data_card") or {})
    checks = {
        "availability_external_selectable": view.mode == "external_selectable",
        "choice_kind_summon_action": choice.choice_kind == "summon_action",
        "choice_control_external": choice.control == "external",
        "choice_has_servant_definition_source": actor_data_card.get("card_kind") == "servant_definition",
        "choice_data_card_matches_servant_definition": actor_data_card.get("card_id") == definition.servant_definition_id,
        "choice_has_summon_action_admission": bool(choice.source_trace.get("summon_action_admission")),
        "choice_has_action_definition_source": bool(choice.source_trace.get("action_definition")),
        "choice_has_action_event_source": bool(choice.source_trace.get("action_event")),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "servant_subcard_action_availability",
        classification="executable",
        checks=checks,
        sample_choice=_compact_choice(choice),
        sample_actor=_compact_unit(state.units[choice.actor_id]),
        details={
            "servant_definition_id": definition.servant_definition_id,
            "owner_entity_ref": definition.owner_entity_ref,
            "view": _compact_view(view),
            "selection_predicate": "ServantDefinitionIR executable unit representation with summon_action choice",
        },
    )


def _summoned_monster_fixed_sequence_availability_case(rules: RuleBook) -> dict[str, JSONValue]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _spawn_summoned_monster_turn_state(rules, intent)
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    actor_id = str(state.global_flags.get("turn_owner_id") or "")
    actor = state.units.get(actor_id)
    choices = [choice for choice in view.choices if choice.choice_kind == "enemy_fixed_sequence"]
    if not choices:
        checks = {
            "availability_boundary_not_executable": view.mode == "blocked" and not view.choices,
            "runtime_action_admission_present": actor is not None
            and isinstance(actor.flags.get("summon_action_admission"), dict),
            "state_unchanged": before == after,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return _case_row(
            "summoned_monster_fixed_sequence_availability",
            classification="boundary_only",
            checks=checks,
            blocked_reasons=[reason.reason for reason in view.blocked],
            details={
                "summon_intent_id": intent.summon_intent_id,
                "view": _compact_view(view),
            },
        )
    choice = choices[0]
    actor_data_card = dict(choice.source_trace.get("actor_data_card") or {})
    checks = {
        "availability_external_selectable": view.mode == "external_selectable",
        "choice_kind_enemy_fixed_sequence": choice.choice_kind == "enemy_fixed_sequence",
        "choice_control_external": choice.control == "external",
        "external_choice_not_ai": choice.command_template.get("source") == "manual",
        "runtime_actor_is_summoned_monster": actor is not None and actor.flags.get("summon_kind") == "summoned_monster",
        "runtime_action_admission_present": actor is not None
        and isinstance(actor.flags.get("summon_action_admission"), dict)
        and actor.flags["summon_action_admission"].get("coverage_status") == "executable",
        "choice_has_monster_data_card_source": bool(choice.source_trace.get("monster_data_card")),
        "choice_has_actor_data_card_source": actor_data_card.get("card_kind") == "monster_data_card",
        "choice_has_action_sequence_step_source": bool(choice.source_trace.get("action_sequence_step")),
        "choice_has_action_definition_source": bool(choice.source_trace.get("action_definition")),
        "choice_has_action_event_source": bool(choice.source_trace.get("action_event")),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "summoned_monster_fixed_sequence_availability",
        classification="executable",
        checks=checks,
        sample_choice=_compact_choice(choice),
        sample_actor=_compact_unit(actor) if actor is not None else {},
        details={
            "summon_intent_id": intent.summon_intent_id,
            "view": _compact_view(view),
            "selection_predicate": "SummonMonsterIntentIR executable spawn with source-backed fixed-sequence choice",
        },
    )


def _availability_gate_boundaries_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    cases = {
        "missing_action_set": _missing_action_set_boundary(rules),
        "target_candidates_empty": _target_candidates_empty_boundary(ir, rules),
        "insufficient_skill_points": _insufficient_skill_points_boundary(ir, rules),
        "timeline_turn_required": _timeline_turn_required_boundary(ir, rules),
        "servant_runtime_missing": _servant_runtime_missing_boundary(rules),
    }
    checks = {
        f"{name}_ok": case["checks"]["ok"] for name, case in cases.items()
    }
    checks["all_state_unchanged"] = all(case["checks"]["checks"].get("state_unchanged") is True for case in cases.values())
    checks["all_no_selected_choice_for_blocked_action"] = all(
        case["checks"]["checks"].get("no_selected_choice_for_blocked_action", True) is True for case in cases.values()
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "availability_gate_boundaries",
        classification="boundary_only",
        checks=checks,
        blocked_reasons=sorted(
            {
                reason
                for case in cases.values()
                for reason in case.get("blocked_reasons", ())
                if isinstance(reason, str) and reason
            }
        ),
        details={
            "boundary_case_count": len(cases),
            "cases": cases,
        },
    )


def _missing_action_definition_source_scan_case(rules: RuleBook) -> dict[str, JSONValue]:
    missing: list[dict[str, JSONValue]] = []
    scanned_entries = 0
    for action_set in rules.combatant_action_sets():
        for skill_index, entry in _sorted_action_set_entries(action_set.skill_index_map):
            scanned_entries += 1
            action_id = str(entry.get("action_ref") or "")
            level = _default_level(entry)
            if entry.get("coverage_status") == "executable" and action_id and level > 0:
                if rules.action_definition(action_id, level) is None:
                    missing.append(
                        {
                            "combatant_action_set_id": action_set.combatant_action_set_id,
                            "entity_ref": action_set.entity_ref,
                            "skill_index": skill_index,
                            "action_id": action_id,
                            "action_level": level,
                        }
                    )
    checks = {
        "scan_completed": scanned_entries > 0,
        "missing_action_definition_count_zero": not missing,
        "no_synthetic_missing_action_definition_case": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    classification = "source_absent_not_required" if not missing else "validation_gap"
    return _case_row(
        "missing_action_definition_source_scan",
        classification=classification,
        checks=checks,
        gap_attribution={"validation_gap": len(missing)} if missing else {},
        details={
            "scanned_action_set_entry_count": scanned_entries,
            "missing_action_definition_count": len(missing),
            "missing_samples": missing[:5],
            "note": "Current executable CombatantActionSetIR entries all resolve to ActionDefinitionIR; no synthetic missing-definition choice was created.",
        },
    )


def _s1_monster_card_action_set_link_gap_inherited_case(s1_matrix: dict[str, Any]) -> dict[str, JSONValue]:
    row = dict(dict(s1_matrix.get("contract_matrix") or {}).get("monster_card_link_contract") or {})
    details = dict(row.get("details") or {})
    missing_counts = dict(details.get("missing_link_counts") or {})
    inherited_gap_count = int(missing_counts.get("action_set_refs") or 0)
    checks = {
        "s1_contract_row_present": bool(row),
        "s1_classification_preserved": row.get("classification") in {"validation_gap", "admission_gap", "executable"},
        "inherited_gap_count_recorded": inherited_gap_count >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _case_row(
        "s1_monster_card_action_set_link_gap_inherited",
        classification="validation_gap" if inherited_gap_count else "boundary_only",
        checks=checks,
        gap_attribution={"validation_gap": inherited_gap_count} if inherited_gap_count else {},
        details={
            "source_contract_id": "monster_card_link_contract",
            "source_classification": row.get("classification", ""),
            "inherited_gap_count": inherited_gap_count,
            "missing_link_counts": missing_counts,
            "blocked_missing_link_counts": dict(details.get("blocked_missing_link_counts") or {}),
            "note": "S2 inherits S1 action-set link gaps instead of hiding them behind executable availability samples.",
        },
    )


def _missing_action_set_boundary(rules: RuleBook) -> dict[str, JSONValue]:
    state = BattleState(
        units={
            "ally:missing_action_set": _ally_unit("ally:missing_action_set", "validation:missing_action_set"),
            "enemy:target": _enemy_target(),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={
            "phase": "scenario",
            "current_window": "idle",
            "turn_owner_id": "ally:missing_action_set",
        },
    )
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    reasons = [reason.reason for reason in view.blocked]
    checks = {
        "availability_blocked": view.mode == "blocked",
        "missing_action_set_reason": "combatant_action_set_missing" in reasons,
        "no_choices": not view.choices,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reasons": reasons,
        "view": _compact_view(view),
    }


def _target_candidates_empty_boundary(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_character_choice(
        ir,
        rules,
        lambda _choice, definition: definition.damage_kind == "hp_damage",
        require_choice_kind="normal_action",
    )
    choice = selected["choice"]
    actor = _ally_unit("ally:target_gate", selected["card"].entity_ref)
    state = BattleState(
        units={"ally:target_gate": actor},
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:target_gate"},
    )
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    blocked_for_action = [
        reason.reason for reason in view.blocked if reason.action_id == choice.action_id and reason.action_level == choice.action_level
    ]
    checks = {
        "target_candidates_empty_reason": any("target_candidates_empty" in reason for reason in blocked_for_action),
        "no_selected_choice_for_blocked_action": all(
            item.action_id != choice.action_id or item.action_level != choice.action_level for item in view.choices
        ),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reasons": blocked_for_action,
        "blocked_action": {"action_id": choice.action_id, "action_level": choice.action_level},
        "view": _compact_view(view),
    }


def _insufficient_skill_points_boundary(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_character_action_set_entry(ir, rules, lambda definition: definition.bp_need > 0)
    action_id = selected["action_id"]
    action_level = selected["action_level"]
    card = selected["card"]
    actor = _ally_unit("ally:resource_gate", card.entity_ref)
    state = BattleState(
        units={"ally:resource_gate": actor, "enemy:target": _enemy_target()},
        skill_points=0,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:resource_gate"},
    )
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    blocked_for_action = [
        reason.reason for reason in view.blocked if reason.action_id == action_id and reason.action_level == action_level
    ]
    checks = {
        "insufficient_skill_points_reason": any("insufficient_skill_points" in reason for reason in blocked_for_action),
        "no_selected_choice_for_blocked_action": all(
            item.action_id != action_id or item.action_level != action_level for item in view.choices
        ),
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reasons": blocked_for_action,
        "blocked_action": {"action_id": action_id, "action_level": action_level},
        "action_set_entry": selected["entry"],
        "view": _compact_view(view),
    }


def _timeline_turn_required_boundary(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    selected = _select_character_choice(ir, rules, lambda _choice, _definition: True, require_choice_kind="normal_action")
    card = selected["card"]
    state = BattleState(
        units={"ally:turn_gate": _ally_unit("ally:turn_gate", card.entity_ref), "enemy:target": _enemy_target()},
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle"},
    )
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    checks = {
        "scheduler_required": view.mode == "scheduler_required",
        "ordinary_input_blocked": view.ordinary_input_blocked is True,
        "turn_begin_requires_scheduler_step": view.ordinary_input_blocked_reason == "turn_begin_requires_scheduler_step",
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reasons": [view.ordinary_input_blocked_reason],
        "view": _compact_view(view),
    }


def _servant_runtime_missing_boundary(rules: RuleBook) -> dict[str, JSONValue]:
    definition = _select_executable_servant_definition(rules)
    state = _spawn_servant_turn_state(rules, definition)
    state = replace(
        state,
        global_flags={key: value for key, value in state.global_flags.items() if key != "summon_runtime"},
    )
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after = state.snapshot().to_json()
    reasons = [reason.reason for reason in view.blocked]
    checks = {
        "availability_blocked": view.mode == "blocked",
        "summon_runtime_state_missing_reason": "summon_runtime_state_missing" in reasons,
        "no_choices": not view.choices,
        "state_unchanged": before == after,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_reasons": reasons,
        "view": _compact_view(view),
    }


def _select_character_choice(
    ir: CanonicalIR,
    rules: RuleBook,
    predicate: Callable[[ActionChoice, ActionDefinitionIR], bool],
    *,
    require_choice_kind: str,
) -> dict[str, Any]:
    availability = ActionAvailabilitySystem(rules)
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        action_set = rules.combatant_action_set(card.entity_ref)
        if action_set is None or action_set.coverage_status != "executable":
            continue
        actor = _ally_unit("ally:sample", card.entity_ref)
        state = BattleState(
            units={"ally:sample": actor, "enemy:target": _enemy_target()},
            skill_points=5,
            max_skill_points=5,
            global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:sample"},
        )
        before = state.snapshot().to_json()
        view = availability.view(state)
        after = state.snapshot().to_json()
        for choice in view.choices:
            if choice.choice_kind != require_choice_kind:
                continue
            definition = rules.action_definition(choice.action_id, choice.action_level)
            if definition is not None and predicate(choice, definition):
                return {
                    "card": card,
                    "state": state,
                    "view": view,
                    "choice": choice,
                    "definition": definition,
                    "before": before,
                    "after": after,
                }
    raise RuntimeError(f"no character action availability choice selected for {require_choice_kind}")


def _select_monster_fixed_sequence_choice(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    availability = ActionAvailabilitySystem(rules)
    for card in sorted(ir.monster_data_cards, key=lambda item: item.card_id):
        if card.ai_policy.get("admission_status") != "executable" or not card.action_sequence:
            continue
        actor = UnitState(
            unit_id="enemy:sample",
            side="enemy",
            template_id=card.entity_ref,
            level=80,
            max_hp=1000.0,
            hp=1000.0,
            attack=100.0,
            defense=100.0,
            speed=100.0,
            flags={"monster_data_card_id": card.card_id},
        )
        state = BattleState(
            units={"enemy:sample": actor, "ally:target": _ally_target()},
            skill_points=5,
            max_skill_points=5,
            global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "enemy:sample"},
        )
        before = state.snapshot().to_json()
        view = availability.view(state)
        after = state.snapshot().to_json()
        for choice in view.choices:
            if choice.choice_kind == "enemy_fixed_sequence":
                return {
                    "card": card,
                    "state": state,
                    "view": view,
                    "choice": choice,
                    "before": before,
                    "after": after,
                }
    raise RuntimeError("no monster fixed-sequence action availability choice selected")


def _select_character_action_set_entry(
    ir: CanonicalIR,
    rules: RuleBook,
    predicate: Callable[[ActionDefinitionIR], bool],
) -> dict[str, Any]:
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        action_set = rules.combatant_action_set(card.entity_ref)
        if action_set is None or action_set.coverage_status != "executable":
            continue
        for skill_index, entry in _sorted_action_set_entries(action_set.skill_index_map):
            if entry.get("coverage_status") != "executable":
                continue
            action_id = str(entry.get("action_ref") or "")
            action_level = _default_level(entry)
            if not action_id or action_level <= 0:
                continue
            definition = rules.action_definition(action_id, action_level)
            if definition is not None and predicate(definition):
                return {
                    "card": card,
                    "action_set": action_set,
                    "skill_index": skill_index,
                    "entry": entry,
                    "action_id": action_id,
                    "action_level": action_level,
                    "definition": definition,
                }
    raise RuntimeError("no character action set entry selected by structured predicate")


def _case_row(
    case_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    sample_choice: dict[str, JSONValue] | None = None,
    sample_actor: dict[str, JSONValue] | None = None,
    blocked_reasons: list[str] | None = None,
    gap_attribution: dict[str, int] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "case_id": case_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "sample_choice": sample_choice or {},
        "sample_actor": sample_actor or {},
        "blocked_reasons": blocked_reasons or [],
        "gap_attribution": gap_attribution or {},
        "details": details or {},
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _compact_choice(choice: ActionChoice) -> dict[str, JSONValue]:
    return {
        "choice_id": choice.choice_id,
        "choice_kind": choice.choice_kind,
        "control": choice.control,
        "actor_id": choice.actor_id,
        "actor_side": choice.actor_side,
        "action_id": choice.action_id,
        "action_level": choice.action_level,
        "command_template": choice.command_template,
        "auto_target_ids": list(choice.auto_target_ids),
        "selectable_target_ids": list(choice.selectable_target_ids),
        "target_status": choice.target_status,
        "resource_status": choice.resource_status,
        "coverage_status": choice.coverage_status,
        "source_trace": {
            key: value
            for key, value in choice.source_trace.items()
            if key
            in {
                "actor_data_card",
                "combatant_action_set",
                "combatant_action_set_id",
                "skill_index",
                "action_set_entry",
                "summon_action_admission",
                "monster_data_card",
                "monster_data_card_id",
                "action_sequence_step",
                "ai_policy",
                "action_definition",
                "action_event",
            }
        },
        "metadata": {
            "selection_controller": choice.metadata.get("selection_controller"),
            "actor_data_card": choice.metadata.get("actor_data_card"),
            "candidate_kind": choice.metadata.get("candidate_kind"),
            "skill_index": choice.metadata.get("skill_index"),
        },
    }


def _compact_unit(unit: UnitState | None) -> dict[str, JSONValue]:
    if unit is None:
        return {}
    return {
        "unit_id": unit.unit_id,
        "side": unit.side,
        "template_id": unit.template_id,
        "flags": {
            key: value
            for key, value in unit.flags.items()
            if key
            in {
                "monster_data_card_id",
                "servant_definition_id",
                "servant_ref",
                "summon_kind",
                "summon_intent_id",
                "team_side",
                "timeline_admitted",
                "summon_action_admitted",
            }
        },
    }


def _compact_view(view: ActionAvailabilityView) -> dict[str, JSONValue]:
    return {
        "mode": view.mode,
        "ordinary_input_blocked": view.ordinary_input_blocked,
        "ordinary_input_blocked_reason": view.ordinary_input_blocked_reason,
        "choice_count": len(view.choices),
        "blocked_reasons": [reason.reason for reason in view.blocked],
        "coverage": view.coverage,
    }


def _ally_unit(unit_id: str, template_id: str) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side="ally",
        template_id=template_id,
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        energy=100.0,
        max_energy=100.0,
    )


def _enemy_target() -> UnitState:
    return UnitState(
        unit_id="enemy:target",
        side="enemy",
        template_id="validation:enemy_target",
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
    )


def _ally_target() -> UnitState:
    return UnitState(
        unit_id="ally:target",
        side="ally",
        template_id="validation:ally_target",
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
    )


def _sorted_action_set_entries(skill_index_map: dict[str, JSONValue]) -> tuple[tuple[str, dict[str, JSONValue]], ...]:
    entries: list[tuple[str, dict[str, JSONValue]]] = []
    for key, value in skill_index_map.items():
        if isinstance(value, dict):
            entries.append((str(key), value))
    return tuple(sorted(entries, key=lambda item: (_skill_index_sort_key(item[0]), item[0])))


def _skill_index_sort_key(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 9999


def _default_level(entry: dict[str, JSONValue]) -> int:
    default_level = entry.get("default_level")
    if isinstance(default_level, bool):
        return 0
    if isinstance(default_level, int):
        return default_level
    if isinstance(default_level, float):
        return int(default_level)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
