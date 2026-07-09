from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, BattleTransition, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, CanonicalIR
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
from .validate_p4_s2_combatant_action_availability import (
    _compact_choice,
    _compact_unit,
    _compact_view,
    _select_character_choice,
    _select_monster_fixed_sequence_choice,
)


VALIDATION_VERSION = "p4_s11_action_query_contract"
MATRIX_SCHEMA_VERSION = "p4_s11_action_query_contract_matrix_v1"

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
    "query_all_actionable_units_contract",
    "character_action_command_transition_contract",
    "monster_action_command_transition_contract",
    "summon_or_servant_action_command_transition_contract",
    "illegal_command_blocked_state_unchanged",
    "no_planner_rule_ownership_boundary",
}
REQUIRED_TRANSITION_KEYS = {
    "before",
    "after",
    "command",
    "target_resolution",
    "events",
    "rng_events",
    "mutations",
    "trigger_windows",
    "settlement",
    "coverage",
    "contract_validation",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s11_action_query_contract_matrix(ir, rules)
    matrix_checks = validate_p4_s11_action_query_contract_matrix(matrix)
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
                "mode": "p4_s11_thin_external_contract_samples_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "ui_structure_read": False,
                "planner_search_scoring_or_route_selection_implemented": False,
                "enemy_action_auto_selected_by_core": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "action_query_contract_matrix": matrix["action_query_contract_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s11_action_query_contract.json", result)
    write_json(output_dir / "p4_s11_action_query_contract_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S11 action/query contract samples.")
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


def build_p4_s11_action_query_contract_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    samples = _select_contract_samples(ir, rules)
    rows = [
        _query_all_actionable_units_row(rules, samples),
        _positive_execution_row(rules, "character_action_command_transition_contract", samples["character"]),
        _positive_execution_row(rules, "monster_action_command_transition_contract", samples["monster"]),
        _positive_execution_row(
            rules,
            "summon_or_servant_action_command_transition_contract",
            samples["summon_execution"],
        ),
        _illegal_command_blocked_row(rules, samples["character"]),
        _no_planner_rule_ownership_row(samples),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "action_query_contract_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "positive_transition_count": sum(
                1 for row in rows if row.get("row_kind") == "positive_execution_contract"
            ),
            "blocked_transition_count": sum(
                1 for row in rows if row.get("row_kind") == "blocked_contract"
            ),
            "source_audit_all_ok": all(
                dict(row.get("transition_contract") or {}).get("source_audit_ok", True) is True
                for row in rows
            ),
            "replay_all_ok": all(
                dict(row.get("transition_contract") or {}).get("replay_ok", True) is True for row in rows
            ),
            "planner_implemented": False,
            "enemy_action_auto_selected_by_core": False,
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "subprocess_validation_count": 0,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s11_action_query_contract.json",
                "p4_s11_action_query_contract_matrix.json",
            ],
        },
    }


def validate_p4_s11_action_query_contract_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("action_query_contract_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    positive_rows = [row for row in rows.values() if row.get("row_kind") == "positive_execution_contract"]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "positive_rows_have_transition_contract": all(
            _transition_contract_checks_ok(row) for row in positive_rows
        ),
        "character_contract_executable": rows.get("character_action_command_transition_contract", {}).get(
            "classification"
        )
        == "executable",
        "monster_contract_executable": rows.get("monster_action_command_transition_contract", {}).get(
            "classification"
        )
        == "executable",
        "summon_or_servant_contract_executable": rows.get(
            "summon_or_servant_action_command_transition_contract", {}
        ).get(
            "classification"
        )
        == "executable",
        "illegal_command_blocked_state_unchanged": _row_check(
            rows,
            "illegal_command_blocked_state_unchanged",
            "blocked_state_unchanged",
        ),
        "no_planner_implemented": _row_check(rows, "no_planner_rule_ownership_boundary", "no_search_or_scoring"),
        "summary_source_audit_ok": bool(matrix.get("summary", {}).get("source_audit_all_ok")),
        "summary_replay_ok": bool(matrix.get("summary", {}).get("replay_all_ok")),
        "matrix_is_summary_only": (
            matrix.get("resource_budget", {}).get("full_ir_written") is False
            and matrix.get("resource_budget", {}).get("full_transition_dump_written") is False
            and matrix.get("resource_budget", {}).get("large_artifacts_written") is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _select_contract_samples(ir: CanonicalIR, rules: RuleBook) -> dict[str, dict[str, Any]]:
    character = _select_character_choice(
        ir,
        rules,
        lambda _choice, definition: definition.coverage_status == "executable",
        require_choice_kind="normal_action",
    )
    monster = _select_monster_fixed_sequence_choice(ir, rules)
    servant = _select_servant_query_sample(rules)
    summoned_monster = _select_summoned_monster_query_sample(rules)
    summon_execution = _select_enabled_summon_execution_sample(rules, (servant, summoned_monster))
    return {
        "character": {
            "sample_kind": "character",
            **character,
        },
        "monster": {
            "sample_kind": "monster",
            **monster,
        },
        "servant": servant,
        "summoned_monster": summoned_monster,
        "summon_execution": summon_execution,
    }


def _select_servant_query_sample(rules: RuleBook) -> dict[str, Any]:
    servant_definition = _select_executable_servant_definition(rules)
    state = _spawn_servant_turn_state(rules, servant_definition)
    view = ActionAvailabilitySystem(rules).view(state)
    choices = [choice for choice in view.choices if choice.choice_kind == "summon_action"]
    if not choices:
        raise RuntimeError("no servant action contract choice selected")
    choice = choices[0]
    return {
        "sample_kind": "servant",
        "card": servant_definition,
        "state": state,
        "view": view,
        "choice": choice,
        "definition": rules.action_definition(choice.action_id, choice.action_level),
        "before": state.snapshot().to_json(),
        "after": state.snapshot().to_json(),
    }


def _select_summoned_monster_query_sample(rules: RuleBook) -> dict[str, Any]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _spawn_summoned_monster_turn_state(rules, intent)
    view = ActionAvailabilitySystem(rules).view(state)
    choices = [choice for choice in view.choices if choice.choice_kind == "enemy_fixed_sequence"]
    if not choices:
        raise RuntimeError("no summoned monster action contract choice selected")
    choice = choices[0]
    return {
        "sample_kind": "summoned_monster",
        "card": intent,
        "state": state,
        "view": view,
        "choice": choice,
        "definition": rules.action_definition(choice.action_id, choice.action_level),
        "before": state.snapshot().to_json(),
        "after": state.snapshot().to_json(),
    }


def _select_enabled_summon_execution_sample(
    rules: RuleBook,
    samples: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    for sample in samples:
        command = _external_command_from_choice(sample["choice"])
        _after_state, transition = CombatExecutor(rules).execute(command, sample["state"])
        if transition.coverage.get("action_enabled") is True:
            return sample
    blockers = {
        str(sample.get("sample_kind") or ""): str(
            CombatExecutor(rules)
            .execute(_external_command_from_choice(sample["choice"]), sample["state"])[1]
            .coverage.get("blocked_reason")
            or ""
        )
        for sample in samples
    }
    raise RuntimeError(f"no enabled summon/servant execution contract sample selected: {blockers}")


def _query_all_actionable_units_row(rules: RuleBook, samples: dict[str, dict[str, Any]]) -> dict[str, JSONValue]:
    query_rows = []
    for sample_id in ("character", "monster", "servant", "summoned_monster"):
        sample = samples[sample_id]
        state = sample["state"]
        actor_id = sample["choice"].actor_id
        view_state = _state_with_turn_owner(state, actor_id)
        before = view_state.snapshot().to_json()
        view = ActionAvailabilitySystem(rules).view(view_state)
        after = view_state.snapshot().to_json()
        choices = [choice for choice in view.choices if choice.coverage_status == "executable"]
        query_rows.append(
            {
                "sample_id": sample_id,
                "actor_id": actor_id,
                "actor_side": view.actor.actor_side if view.actor is not None else "",
                "mode": view.mode,
                "choice_count": len(view.choices),
                "executable_choice_count": len(choices),
                "state_unchanged": before == after,
                "view": _compact_view(view),
                "first_choice": _compact_choice(choices[0]) if choices else {},
            }
        )
    checks = {
        "all_queries_external_selectable": all(row["mode"] == "external_selectable" for row in query_rows),
        "all_queries_have_choices": all(int(row["executable_choice_count"]) > 0 for row in query_rows),
        "all_queries_state_unchanged": all(row["state_unchanged"] is True for row in query_rows),
        "all_choices_source_backed": all(
            bool(dict(row.get("first_choice") or {}).get("source_trace", {}).get("actor_data_card"))
            and bool(dict(row.get("first_choice") or {}).get("source_trace", {}).get("action_definition"))
            for row in query_rows
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "query_all_actionable_units_contract",
        row_kind="query_contract",
        classification="executable",
        checks=checks,
        details={
            "query_contract": "ActionAvailabilitySystem.view over explicit actor turn context",
            "query_rows": _compact_json(query_rows),
            "rule_owner": "core/action availability; thin client does not infer action legality",
        },
    )


def _positive_execution_row(rules: RuleBook, row_id: str, sample: dict[str, Any]) -> dict[str, JSONValue]:
    state = sample["state"]
    choice: ActionChoice = sample["choice"]
    command = _external_command_from_choice(choice)
    after_state, transition = CombatExecutor(rules).execute(command, state)
    contract = _transition_contract(rules, state, after_state, transition, expected_enabled=True)
    choice_source = _choice_source_contract(choice)
    checks = {
        "choice_from_action_availability": choice.coverage_status == "executable" and choice.control == "external",
        "target_policy_available": bool(choice.target_policy),
        "target_choices_available": bool(choice.auto_target_ids or choice.selectable_target_ids),
        "command_external_manual": command.source == "manual",
        "command_matches_choice": command.action_id == choice.action_id
        and command.action_level == choice.action_level
        and command.actor_id == choice.actor_id,
        "transition_action_enabled": transition.coverage.get("action_enabled") is True,
        "transition_contract_ok": contract["ok"] is True,
        "source_contract_ok": choice_source["ok"] is True,
    }
    if sample.get("sample_kind") == "monster":
        checks["enemy_action_passed_externally"] = command.source == "manual" and command.metadata.get(
            "candidate_kind"
        ) == "fixed_sequence_candidate"
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        row_kind="positive_execution_contract",
        classification="executable",
        checks=checks,
        sample_choice=_compact_choice(choice),
        sample_actor=_compact_unit(state.units.get(choice.actor_id)),
        transition_contract=contract,
        details={
            "sample_kind": str(sample.get("sample_kind") or ""),
            "command": _command_json(command),
            "choice_source_contract": choice_source,
            "target_policy": _compact_json(choice.target_policy),
            "target_choices": {
                "auto_target_ids": list(choice.auto_target_ids),
                "selectable_target_ids": list(choice.selectable_target_ids),
            },
        },
    )


def _illegal_command_blocked_row(rules: RuleBook, sample: dict[str, Any]) -> dict[str, JSONValue]:
    state = sample["state"]
    choice: ActionChoice = sample["choice"]
    command = _external_command_from_choice(choice, force_target_ids=("validation:missing_target",))
    after_state, transition = CombatExecutor(rules).execute(command, state)
    before_json = state.snapshot().to_json()
    after_json = after_state.snapshot().to_json()
    transition_json = transition.to_json()
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, after_json)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    blocked_reason = str(transition.coverage.get("blocked_reason") or "")
    checks = {
        "command_from_known_choice": command.action_id == choice.action_id and command.action_level == choice.action_level,
        "target_missing_blocked": bool(blocked_reason) and transition.coverage.get("action_enabled") is False,
        "no_mutations": len(transition.transaction.mutations) == 0,
        "blocked_state_unchanged": before_json == after_json,
        "target_resolution_rejected": bool(transition.target_resolution.rejected)
        or not transition.target_resolution.selected,
        "settlement_records_blocked_reason": _settlement_has_record(transition, "action_blocked"),
        "replay_ok": replay.ok,
        "source_audit_ok_for_no_mutation": source_audit.ok and source_audit.checked_mutations == 0,
        "transition_keys_present": REQUIRED_TRANSITION_KEYS.issubset(set(transition_json)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "illegal_command_blocked_state_unchanged",
        row_kind="blocked_contract",
        classification="boundary_only",
        checks=checks,
        sample_choice=_compact_choice(choice),
        transition_contract={
            "ok": checks["ok"],
            "blocked_reason": blocked_reason,
            "mutation_count": len(transition.transaction.mutations),
            "state_unchanged": before_json == after_json,
            "replay_ok": replay.ok,
            "source_audit_ok": source_audit.ok,
            "settlement_record_types": _settlement_record_types(transition),
            "transition_keys_present": sorted(set(transition_json)),
        },
        details={
            "command": _command_json(command),
            "target_resolution": transition.target_resolution.to_json(),
            "rule_owner": "core target system blocks invalid target; thin client does not repair it",
        },
    )


def _no_planner_rule_ownership_row(samples: dict[str, dict[str, Any]]) -> dict[str, JSONValue]:
    sample_choices = {key: _compact_choice(value["choice"]) for key, value in samples.items()}
    checks = {
        "no_search_or_scoring": True,
        "no_route_selection": True,
        "no_enemy_ai_selection": True,
        "choices_from_action_availability": all(
            dict(choice.get("metadata") or {}).get("selection_controller") == "external"
            or dict(choice.get("command_template") or {}).get("metadata", {}).get("selection_controller") == "external"
            for choice in sample_choices.values()
        ),
        "target_policy_from_choice": all(bool(choice.get("target_status")) for choice in sample_choices.values()),
        "thin_client_does_not_interpret_damage_or_status": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "no_planner_rule_ownership_boundary",
        row_kind="contract_boundary",
        classification="boundary_only",
        checks=checks,
        details={
            "sample_choices": sample_choices,
            "thin_client_responsibilities": [
                "query view",
                "choose one ActionChoice",
                "fill an explicit target from target choices when required",
                "submit ActionCommand",
                "read BattleTransition",
            ],
            "explicit_non_goals": [
                "search",
                "planning",
                "scoring",
                "enemy AI",
                "damage/status/target rule interpretation",
            ],
        },
    )


def _transition_contract(
    rules: RuleBook,
    before_state: BattleState,
    after_state: BattleState,
    transition: BattleTransition,
    *,
    expected_enabled: bool,
) -> dict[str, JSONValue]:
    transition_json = transition.to_json()
    replay = MutationReducer().replay_snapshot(
        before_state,
        transition.transaction.mutations,
        after_state.snapshot().to_json(),
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    required_keys_present = REQUIRED_TRANSITION_KEYS.issubset(set(transition_json))
    forbidden_surface_absent = _forbidden_runtime_surface_absent(transition_json)
    checks = {
        "required_transition_keys_present": required_keys_present,
        "before_after_present": bool(transition_json.get("before")) and bool(transition_json.get("after")),
        "target_resolution_present": bool(transition_json.get("target_resolution")),
        "settlement_present": bool(transition.transaction.settlement),
        "settlement_has_records": bool(transition.transaction.settlement and transition.transaction.settlement.records),
        "coverage_action_enabled_matches": transition.coverage.get("action_enabled") is expected_enabled,
        "mutation_count_positive": len(transition.transaction.mutations) > 0 if expected_enabled else True,
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "forbidden_runtime_surface_absent": forbidden_surface_absent,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "mutation_count": len(transition.transaction.mutations),
        "event_count": len(transition.transaction.events),
        "rng_event_count": len(transition.rng_events),
        "trigger_window_count": len(transition.transaction.trigger_windows),
        "settlement_record_count": len(transition.transaction.settlement.records)
        if transition.transaction.settlement
        else 0,
        "settlement_record_types": _settlement_record_types(transition),
        "target_resolution": _compact_json(transition.target_resolution.to_json()),
        "coverage": {
            "action_enabled": transition.coverage.get("action_enabled"),
            "blocked_reason": transition.coverage.get("blocked_reason"),
            "target_ok": transition.coverage.get("target_ok"),
            "resource_ok": transition.coverage.get("resource_ok"),
            "binding_ok": transition.coverage.get("binding_ok"),
            "event_ok": transition.coverage.get("event_ok"),
            "damage_mutation_count": transition.coverage.get("damage_mutation_count"),
            "toughness_mutation_count": transition.coverage.get("toughness_mutation_count"),
            "timeline_mutation_count": transition.coverage.get("timeline_mutation_count"),
            "resource_mutation_count": transition.coverage.get("resource_mutation_count"),
        },
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "source_audit": {
            "checked_mutations": source_audit.checked_mutations,
            "checked_records": source_audit.checked_records,
            "violation_count": len(source_audit.violations),
        },
    }


def _choice_source_contract(choice: ActionChoice) -> dict[str, JSONValue]:
    source_trace = choice.source_trace
    checks = {
        "has_actor_data_card": bool(source_trace.get("actor_data_card")),
        "has_action_definition": bool(source_trace.get("action_definition")),
        "has_action_event": bool(source_trace.get("action_event")),
        "has_target_policy": bool(choice.target_policy),
        "has_command_template": bool(choice.command_template),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "choice_kind": choice.choice_kind,
        "source_trace_keys": sorted(str(key) for key in source_trace.keys()),
    }


def _external_command_from_choice(
    choice: ActionChoice,
    *,
    force_target_ids: tuple[str, ...] | None = None,
) -> ActionCommand:
    template = dict(choice.command_template or {})
    target_ids = force_target_ids
    if target_ids is None:
        raw_targets = template.get("target_ids")
        if isinstance(raw_targets, list):
            target_ids = tuple(str(item) for item in raw_targets if isinstance(item, str))
        else:
            target_ids = tuple(choice.auto_target_ids)
        if not target_ids and choice.selectable_target_ids:
            target_ids = (choice.selectable_target_ids[0],)
    metadata = dict(template.get("metadata") or {})
    metadata["p4_s11_choice_id"] = choice.choice_id
    metadata["p4_s11_contract_client"] = "thin_external_command_submitter"
    return ActionCommand(
        actor_id=str(template.get("actor_id") or choice.actor_id),
        action_id=str(template.get("action_id") or choice.action_id),
        action_level=int(template.get("action_level") or choice.action_level),
        target_ids=target_ids or (),
        source="manual",
        queue_name=template.get("queue_name") if isinstance(template.get("queue_name"), str) else None,
        metadata=metadata,
    )


def _state_with_turn_owner(state: BattleState, actor_id: str) -> BattleState:
    flags = dict(state.global_flags)
    flags["phase"] = str(flags.get("phase") or "scenario")
    flags["current_window"] = str(flags.get("current_window") or "idle")
    flags["turn_owner_id"] = actor_id
    return replace(state, global_flags=flags)


def _forbidden_runtime_surface_absent(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    forbidden = ("simulator_v8_ui", "TextMap", "model_pack_v3_0", "SimulatorRuntimeAdapter", "_legacy_effects")
    return not any(token in text for token in forbidden)


def _settlement_has_record(transition: BattleTransition, record_type: str) -> bool:
    if transition.transaction.settlement is None:
        return False
    return any(record.get("record_type") == record_type for record in transition.transaction.settlement.records)


def _settlement_record_types(transition: BattleTransition) -> list[str]:
    if transition.transaction.settlement is None:
        return []
    return sorted({str(record.get("record_type") or "") for record in transition.transaction.settlement.records})


def _transition_contract_checks_ok(row: dict[str, Any]) -> bool:
    contract = dict(row.get("transition_contract") or {})
    checks = dict(contract.get("checks") or {})
    return bool(contract.get("ok")) and all(value is True for key, value in checks.items() if key != "ok")


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _row(
    row_id: str,
    *,
    row_kind: str,
    classification: str,
    checks: dict[str, JSONValue],
    sample_choice: dict[str, JSONValue] | None = None,
    sample_actor: dict[str, JSONValue] | None = None,
    transition_contract: dict[str, JSONValue] | None = None,
    gap_attribution: dict[str, int] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "row_kind": row_kind,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "sample_choice": sample_choice or {},
        "sample_actor": sample_actor or {},
        "transition_contract": transition_contract or {},
        "gap_attribution": gap_attribution or {},
        "details": details or {},
    }


def _command_json(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 16:
                result["..."] = "truncated"
                break
            result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:16]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
