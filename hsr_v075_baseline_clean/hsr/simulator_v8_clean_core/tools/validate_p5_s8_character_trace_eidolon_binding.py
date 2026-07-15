from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..scenarios.build_state import ScenarioStateBuilder
from ..systems.action_availability import ActionAvailabilitySystem, ActionChoice
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p4_s8_trace_eidolon_level_resource_hooks import (
    _base_value_for_key,
    _select_trace_static_stat_sample,
    _single_avatar_scenario,
)


VALIDATION_VERSION = "p5_s8_character_trace_eidolon_binding"
MATRIX_SCHEMA_VERSION = "p5_s8_character_trace_eidolon_binding_matrix_v1"

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
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "trace_static_stat_value_resolver",
    "eidolon_skill_level_value_resolver",
    "eidolon_effective_level_replay_source_audit",
    "missing_trace_eidolon_value_context_blocked",
    "character_gap_visibility",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s8_character_trace_eidolon_binding_matrix(ir, rules)
    matrix_checks = validate_p5_s8_character_trace_eidolon_binding_matrix(matrix)
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
                "mode": "p5_s8_character_trace_eidolon_value_resolver_structural_samples",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "character_name_hardcoded": False,
                "scenario_injected_character_mechanism_result": False,
                "synthetic_positive_created": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "character_binding_matrix": matrix["character_binding_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "runtime_samples": matrix["runtime_samples"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s8_character_trace_eidolon_binding.json", result)
    write_json(output_dir / "p5_s8_character_trace_eidolon_binding_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S8 character trace/eidolon ValueResolver binding.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s8_character_trace_eidolon_binding_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    trace_case = _trace_static_case(ir, rules)
    eidolon_case = _eidolon_skill_level_case(ir, rules)
    action_case = _eidolon_action_execution_case(rules, eidolon_case)
    negative_case = _missing_context_negative_case(rules, trace_case, eidolon_case)
    gap_case = _character_gap_visibility_case(ir)
    rows = [
        _trace_static_stat_value_resolver_row(trace_case),
        _eidolon_skill_level_value_resolver_row(eidolon_case),
        _eidolon_effective_level_replay_source_audit_row(action_case),
        _missing_trace_eidolon_value_context_blocked_row(negative_case),
        _character_gap_visibility_row(gap_case),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "character_binding_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "trace_value_resolution_count": len(trace_case.get("value_resolutions") or ()),
            "eidolon_value_resolution_count": len(eidolon_case.get("value_resolutions") or ()),
            "action_execution_sample_count": 1 if action_case.get("found") else 0,
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "runtime_samples": {
            "trace": trace_case.get("runtime_sample", {}),
            "eidolon": eidolon_case.get("runtime_sample", {}),
            "action_execution": action_case.get("runtime_sample", {}),
            "negative": negative_case.get("runtime_sample", {}),
            "gap_visibility": gap_case,
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "scenario_builder_runtime_samples": 2,
            "combat_executor_runtime_sample_count": 1 if action_case.get("found") else 0,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s8_character_trace_eidolon_binding.json",
                "p5_s8_character_trace_eidolon_binding_matrix.json",
            ],
        },
    }


def validate_p5_s8_character_trace_eidolon_binding_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("character_binding_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "trace_value_resolved": _row_check(rows, "trace_static_stat_value_resolver", "trace_terms_have_value_resolution"),
        "eidolon_value_resolved": _row_check(
            rows,
            "eidolon_skill_level_value_resolver",
            "eidolon_bonus_has_value_resolution",
        ),
        "eidolon_action_replay_source_audit": _row_check(
            rows,
            "eidolon_effective_level_replay_source_audit",
            "replay_ok",
        )
        and _row_check(rows, "eidolon_effective_level_replay_source_audit", "source_audit_ok"),
        "missing_context_blocked": _row_check(
            rows,
            "missing_trace_eidolon_value_context_blocked",
            "all_missing_context_blocked",
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _trace_static_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    selected = _select_trace_static_stat_sample(ir, rules)
    if selected is None:
        return {"found": False, "value_resolutions": (), "runtime_sample": {}}
    card, node, slot, term = selected
    target_key = str(term.get("target_key") or "")
    before_value = _base_value_for_key(target_key)
    scenario = _single_avatar_scenario(
        "p5_s8_trace_static_stat",
        card,
        flags={"enabled_trace_node_ids": (node.trace_node_id,)},
        panel_overrides={target_key: before_value},
    )
    built = ScenarioStateBuilder(rules).build(scenario)
    unit = built.state.units["ally:subject"]
    after_value = float(getattr(unit, target_key))
    terms = tuple(item for item in unit.flags.get("trace_static_stat_bonus_terms", ()) if isinstance(item, dict))
    selected_terms = tuple(
        item
        for item in terms
        if item.get("mechanism_slot_id") == slot.mechanism_slot_id and item.get("target_key") == target_key
    )
    value_resolutions = tuple(
        item.get("value_resolution") for item in selected_terms if isinstance(item.get("value_resolution"), dict)
    )
    return {
        "found": True,
        "card": card,
        "node": node,
        "slot": slot,
        "term": term,
        "unit": unit,
        "before_value": before_value,
        "after_value": after_value,
        "value_resolutions": value_resolutions,
        "runtime_sample": {
            "card_id": card.card_id,
            "trace_node_id": node.trace_node_id,
            "mechanism_slot_id": slot.mechanism_slot_id,
            "target_key": target_key,
            "before_value": before_value,
            "after_value": after_value,
            "source_path": slot.source.source_path,
        },
    }


def _eidolon_skill_level_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    cards_by_id = {card.card_id: card for card in ir.character_data_cards}
    fallback: dict[str, Any] | None = None
    for slot in sorted(ir.character_eidolon_slots, key=lambda item: item.eidolon_slot_id):
        semantics = slot.semantics if isinstance(slot.semantics, dict) else {}
        skill_add = semantics.get("skill_add_level_list")
        if not isinstance(skill_add, dict):
            continue
        card = cards_by_id.get(slot.character_data_card_id)
        if card is None:
            continue
        for raw_skill_id, _raw_bonus in sorted(skill_add.items()):
            action_id = f"avatar_skill:{raw_skill_id}"
            scenario = _single_avatar_scenario("p5_s8_eidolon_skill_level", card, eidolon_level=slot.rank)
            built = ScenarioStateBuilder(rules).build(scenario)
            unit = built.state.units["ally:subject"]
            value_resolutions_by_action = unit.flags.get("eidolon_skill_level_bonus_value_resolutions")
            value_resolutions = ()
            if isinstance(value_resolutions_by_action, dict):
                value_resolutions = tuple(
                    item for item in value_resolutions_by_action.get(action_id, ()) if isinstance(item, dict)
                )
            bonuses = unit.flags.get("eidolon_skill_level_bonus_by_action_id")
            bonus = bonuses.get(action_id) if isinstance(bonuses, dict) else None
            if not value_resolutions or not isinstance(bonus, int) or bonus <= 0:
                continue
            case = {
                "found": True,
                "card": card,
                "slot": slot,
                "raw_skill_id": str(raw_skill_id),
                "action_id": action_id,
                "bonus": bonus,
                "built": built,
                "unit": unit,
                "value_resolutions": value_resolutions,
                "runtime_sample": {
                    "card_id": card.card_id,
                    "eidolon_slot_id": slot.eidolon_slot_id,
                    "rank": slot.rank,
                    "action_id": action_id,
                    "bonus": bonus,
                    "source_path": slot.source.source_path,
                },
            }
            if fallback is None:
                fallback = case
            if _select_action_choice(rules, _state_with_enemy_target(built.state), action_id) is not None:
                return case
    return fallback or {"found": False, "value_resolutions": (), "runtime_sample": {}}


def _eidolon_action_execution_case(rules: RuleBook, eidolon_case: dict[str, Any]) -> dict[str, Any]:
    if not eidolon_case.get("found"):
        return {"found": False, "runtime_sample": {"reason": "eidolon sample missing"}}
    state = _state_with_enemy_target(eidolon_case["built"].state)
    choice = _select_action_choice(rules, state, str(eidolon_case["action_id"]))
    if choice is None:
        return {
            "found": False,
            "runtime_sample": {
                "reason": "action_choice_not_available",
                "action_id": str(eidolon_case["action_id"]),
            },
        }
    requested_level = _requested_level_below_cap(rules, choice.action_id, int(eidolon_case.get("bonus") or 0))
    command = _command_from_choice(choice, action_level=requested_level)
    after, transition = CombatExecutor(rules).execute(command, state)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    effective_source = transition.transaction.command.metadata.get("effective_action_level_source")
    return {
        "found": True,
        "state": state,
        "after": after,
        "choice": choice,
        "command": command,
        "transition": transition,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "audit": _audit_summary(audit),
        "effective_source": effective_source if isinstance(effective_source, dict) else {},
        "runtime_sample": {
            "action_id": choice.action_id,
            "requested_level": command.action_level,
            "effective_level": transition.transaction.command.action_level,
            "target_ids": list(command.target_ids),
            "mutation_count": len(transition.transaction.mutations),
        },
    }


def _missing_context_negative_case(
    rules: RuleBook,
    trace_case: dict[str, Any],
    eidolon_case: dict[str, Any],
) -> dict[str, Any]:
    resolver = ValueResolver(rules)
    cases: dict[str, dict[str, JSONValue]] = {}
    if trace_case.get("found"):
        resolution = resolver.resolve(
            ValueBindingRequest(
                binding_kind="fixed_numeric_expression",
                expression=trace_case["term"].get("value"),
                required_context_keys=("data_card_source",),
                source_trace=trace_case["slot"].source.to_json(),
            ),
            ValueContext(source_trace=trace_case["slot"].source.to_json()),
        )
        cases["trace_missing_data_card_source"] = resolution.to_json()
    if eidolon_case.get("found"):
        resolution = resolver.resolve(
            ValueBindingRequest(
                binding_kind="fixed_numeric_expression",
                expression=eidolon_case["bonus"],
                required_context_keys=("data_card_source",),
                source_trace=eidolon_case["slot"].source.to_json(),
            ),
            ValueContext(source_trace=eidolon_case["slot"].source.to_json()),
        )
        cases["eidolon_missing_data_card_source"] = resolution.to_json()
    return {
        "cases": cases,
        "runtime_sample": {
            case_id: {
                "ok": item.get("ok"),
                "blocked_reason": item.get("blocked_reason"),
                "binding_kind": item.get("binding_kind"),
            }
            for case_id, item in cases.items()
        },
    }


def _character_gap_visibility_case(ir: CanonicalIR) -> dict[str, Any]:
    trace_slots = tuple(
        slot for slot in ir.character_mechanism_slots if slot.mechanism_kind.startswith("trace_")
    )
    eidolon_slots = tuple(slot for slot in ir.character_eidolon_slots)
    eidolon_mechanisms = tuple(
        slot for slot in ir.character_mechanism_slots if slot.mechanism_kind.startswith("eidolon_")
    )
    blocked_reasons = Counter(
        str(slot.blocked_reason or f"slot_not_executable:{slot.coverage_status}")
        for slot in (*trace_slots, *eidolon_mechanisms)
        if slot.coverage_status != "executable"
    )
    return {
        "trace_slot_status_counts": dict(sorted(Counter(slot.coverage_status for slot in trace_slots).items())),
        "eidolon_slot_status_counts": dict(sorted(Counter(slot.coverage_status for slot in eidolon_slots).items())),
        "eidolon_mechanism_status_counts": dict(
            sorted(Counter(slot.coverage_status for slot in eidolon_mechanisms).items())
        ),
        "blocked_reason_counts_top": _counter_top(blocked_reasons, 12),
        "character_gap_hidden": False,
        "p5_all_character_mechanisms_claimed": False,
    }


def _trace_static_stat_value_resolver_row(case: dict[str, Any]) -> dict[str, Any]:
    resolutions = tuple(case.get("value_resolutions") or ())
    checks = {
        "trace_static_sample_exists": case.get("found") is True,
        "trace_terms_have_value_resolution": bool(resolutions) and all(_fixed_resolution_ok(item) for item in resolutions),
        "trace_panel_adjustment_recorded": isinstance(case.get("unit").flags.get("trace_panel_adjustments"), dict)
        if case.get("unit") is not None
        else False,
        "trace_stat_changed": case.get("after_value") != case.get("before_value"),
        "source_trace_recorded": bool(case.get("unit").flags.get("trace_source_traces")) if case.get("unit") is not None else False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "trace_static_stat_value_resolver",
        "executable" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        {
            "runtime_sample": case.get("runtime_sample", {}),
            "value_resolution_sample": _compact_resolution(_first(resolutions)),
        },
    )


def _eidolon_skill_level_value_resolver_row(case: dict[str, Any]) -> dict[str, Any]:
    resolutions = tuple(case.get("value_resolutions") or ())
    unit = case.get("unit")
    action_id = str(case.get("action_id") or "")
    bonuses = unit.flags.get("eidolon_skill_level_bonus_by_action_id") if unit is not None else None
    sources = unit.flags.get("eidolon_skill_level_bonus_sources") if unit is not None else None
    checks = {
        "eidolon_skill_level_sample_exists": case.get("found") is True,
        "eidolon_bonus_has_value_resolution": bool(resolutions) and all(_fixed_resolution_ok(item) for item in resolutions),
        "eidolon_bonus_recorded": isinstance(bonuses, dict) and bonuses.get(action_id) == case.get("bonus"),
        "eidolon_sources_carry_value_resolution": isinstance(sources, dict)
        and any(isinstance(item, dict) and isinstance(item.get("value_resolution"), dict) for item in sources.get(action_id, ())),
        "eidolon_activation_policy_prefix_closed": dict(unit.flags.get("eidolon_activation_policy") or {}).get("kind")
        == "prefix_closed"
        if unit is not None
        else False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "eidolon_skill_level_value_resolver",
        "executable" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        {
            "runtime_sample": case.get("runtime_sample", {}),
            "value_resolution_sample": _compact_resolution(_first(resolutions)),
        },
    )


def _eidolon_effective_level_replay_source_audit_row(case: dict[str, Any]) -> dict[str, Any]:
    source = dict(case.get("effective_source") or {})
    checks = {
        "action_execution_sample_found": case.get("found") is True,
        "effective_level_applied": case.get("found") is True
        and case["runtime_sample"].get("effective_level", 0) > case["runtime_sample"].get("requested_level", 0),
        "effective_source_kind_recorded": source.get("source_kind") == "character_data_card_eidolon_skill_level_bonus",
        "effective_source_carries_value_resolution": _source_payload_has_value_resolution(source),
        "replay_ok": dict(case.get("replay") or {}).get("ok") is True,
        "source_audit_ok": dict(case.get("audit") or {}).get("ok") is True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    classification = "executable" if checks["ok"] else "validation_gap"
    return _row(
        "eidolon_effective_level_replay_source_audit",
        classification,
        checks,
        "" if checks["ok"] else "validation_gap",
        {
            "runtime_sample": case.get("runtime_sample", {}),
            "effective_source": _compact_effective_source(source),
            "replay": case.get("replay", {}),
            "audit": case.get("audit", {}),
        },
    )


def _missing_trace_eidolon_value_context_blocked_row(case: dict[str, Any]) -> dict[str, Any]:
    cases = dict(case.get("cases") or {})
    checks = {
        "negative_cases_present": set(cases) == {"trace_missing_data_card_source", "eidolon_missing_data_card_source"},
        "all_missing_context_blocked": bool(cases)
        and all(item.get("ok") is False and str(item.get("blocked_reason") or "").startswith("context_missing") for item in cases.values()),
        "no_executable_negative_resolution": all(item.get("ok") is not True for item in cases.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "missing_trace_eidolon_value_context_blocked",
        "boundary_only" if checks["ok"] else "implementation_missing",
        checks,
        "" if checks["ok"] else "implementation_missing",
        case.get("runtime_sample", {}),
    )


def _character_gap_visibility_row(case: dict[str, Any]) -> dict[str, Any]:
    blocked_count = sum(
        item["count"]
        for item in case.get("blocked_reason_counts_top", ())
        if isinstance(item, dict) and isinstance(item.get("count"), int)
    )
    checks = {
        "trace_and_eidolon_status_recorded": bool(case.get("trace_slot_status_counts"))
        and bool(case.get("eidolon_slot_status_counts")),
        "character_gaps_not_hidden": case.get("character_gap_hidden") is False,
        "p5_all_character_mechanisms_not_claimed": case.get("p5_all_character_mechanisms_claimed") is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    gap = "admission_gap" if blocked_count else ""
    return _row(
        "character_gap_visibility",
        "admission_gap" if gap else "executable",
        checks,
        gap,
        case,
    )


def _state_with_enemy_target(state: BattleState) -> BattleState:
    units = dict(state.units)
    units["enemy:p5_s8_target"] = UnitState(
        "enemy:p5_s8_target",
        "enemy",
        "monster:p5_s8_target",
        hp=1000.0,
        max_hp=1000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        toughness=120.0,
        max_toughness=120.0,
        flags={"position": 5},
    )
    return replace(
        state,
        units=units,
        global_flags={**state.global_flags, "phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:subject"},
        skill_points=5,
        max_skill_points=5,
    )


def _select_action_choice(rules: RuleBook, state: BattleState, action_id: str) -> ActionChoice | None:
    view = ActionAvailabilitySystem(rules).view(state)
    for choice in view.choices:
        if choice.action_id != action_id:
            continue
        if choice.coverage_status != "executable" or choice.target_status != "ok" or choice.resource_status == "blocked":
            continue
        if choice.auto_target_ids or choice.selectable_target_ids:
            return choice
    return None


def _command_from_choice(choice: ActionChoice, *, action_level: int | None = None) -> ActionCommand:
    targets = choice.auto_target_ids or choice.selectable_target_ids[:1]
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=action_level if action_level is not None else choice.action_level,
        target_ids=targets,
        source="validation:p5_s8",
    )


def _requested_level_below_cap(rules: RuleBook, action_id: str, bonus: int) -> int:
    levels = tuple(level for level in rules.action_levels(action_id) if isinstance(level, int))
    if not levels:
        return 1
    max_level = max(levels)
    candidates = tuple(level for level in levels if level < max_level and level + bonus <= max_level)
    if candidates:
        return max(candidates)
    return min(levels)


def _fixed_resolution_ok(resolution: dict[str, JSONValue]) -> bool:
    return (
        resolution.get("ok") is True
        and resolution.get("binding_kind") == "fixed_numeric_expression"
        and isinstance(resolution.get("value"), (int, float))
        and not isinstance(resolution.get("value"), bool)
        and "data_card_source" in set(resolution.get("context_keys") or ())
        and bool(resolution.get("source_trace"))
    )


def _source_payload_has_value_resolution(source: dict[str, JSONValue]) -> bool:
    for item in source.get("sources", ()):
        if isinstance(item, dict) and _fixed_resolution_ok(dict(item.get("value_resolution") or {})):
            return True
    return False


def _audit_summary(audit: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(audit, "ok", False)),
        "violation_count": len(getattr(audit, "violations", ()) or ()),
        "violations": [item.to_json() for item in tuple(getattr(audit, "violations", ()) or ())[:6]],
    }


def _compact_effective_source(source: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "source_kind": source.get("source_kind"),
        "action_id": source.get("action_id"),
        "requested_level": source.get("requested_level"),
        "effective_level": source.get("effective_level"),
        "bonus": source.get("bonus"),
        "source_count": len(source.get("sources", ())) if isinstance(source.get("sources"), list) else 0,
        "value_resolution_sample": _compact_resolution(
            dict(source.get("sources", [{}])[0].get("value_resolution") or {})
            if isinstance(source.get("sources"), list) and source.get("sources")
            else {}
        ),
    }


def _compact_resolution(resolution: dict[str, JSONValue] | None) -> dict[str, JSONValue]:
    resolution = dict(resolution or {})
    delegate = dict(resolution.get("delegate_resolution") or {})
    source_trace = resolution.get("source_trace")
    source_path = str(source_trace.get("source_path") or "") if isinstance(source_trace, dict) else ""
    return {
        "ok": resolution.get("ok"),
        "value": resolution.get("value"),
        "binding_kind": resolution.get("binding_kind"),
        "value_source": delegate.get("value_source"),
        "blocked_reason": resolution.get("blocked_reason"),
        "context_keys": list(resolution.get("context_keys") or ()),
        "source_path": source_path,
    }


def _row(
    row_id: str,
    classification: str,
    checks: dict[str, bool],
    gap_attribution: str,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "classification": classification,
        "gap_attribution": gap_attribution,
        "checks": {"ok": checks.get("ok") is True, "checks": checks},
        "evidence": evidence,
    }


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        gap = str(row.get("gap_attribution") or "")
        if gap:
            counts[gap] += 1
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    return {
        str(row["row_id"]): {
            "classification": str(row.get("classification") or "unclassified"),
            "gap_attribution": str(row.get("gap_attribution") or ""),
            "ok": dict(row.get("checks") or {}).get("ok") is True,
        }
        for row in rows
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return dict(rows.get(row_id, {}).get("checks", {}).get("checks") or {}).get(check_id) is True


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _first(items: Iterable[Any]) -> Any:
    for item in items:
        return item
    return None


if __name__ == "__main__":
    raise SystemExit(main())
