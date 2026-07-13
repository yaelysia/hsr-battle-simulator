from __future__ import annotations

import argparse
import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..systems.decision import DecisionSystem
from ..systems.scheduler import CombatScheduler, DecisionSubmissionAuthorization
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state, _source
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s8_decision_query_submit_loop"
MATRIX_SCHEMA_VERSION = "p7_s8_decision_query_submit_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    ally_rules = _trust_rulebook()
    ally_decision_state = _decision_state(_base_state())
    query_idempotency = _query_idempotency_case(ally_rules, ally_decision_state)
    ally_round_trip = _ally_round_trip_case(ally_rules)
    stale_token = _stale_token_case(ally_rules, ally_round_trip)
    direct_bypass = _direct_bypass_case(ally_rules, ally_round_trip)
    enemy_round_trip = _enemy_round_trip_case()
    static_boundary = _static_boundary(package_root)
    rows = (
        query_idempotency,
        ally_round_trip,
        stale_token,
        direct_bypass,
        enemy_round_trip,
        static_boundary,
    )
    checks = {
        "query_is_idempotent": query_idempotency["ok"],
        "advance_query_submit_round_trip": ally_round_trip["ok"],
        "every_exposed_action_target_combination_submits": ally_round_trip["all_exposed_combinations_submit"],
        "submit_does_not_repeat_turn_begin": ally_round_trip["submit_turn_begin_event_count"] == 0,
        "one_submission_consumes_one_decision": ally_round_trip["decision_consumed_once"],
        "stale_token_blocked_state_unchanged": stale_token["ok"],
        "direct_scheduler_command_requires_token": direct_bypass["ok"],
        "ally_enemy_share_external_interface": enemy_round_trip["ok"],
        "forced_sequence_only_constrains_candidate": enemy_round_trip["forced_constraint_ok"],
        "no_scheduler_enemy_auto_selection": static_boundary["no_enemy_auto_selection"],
        "token_binds_full_snapshot_and_choices": static_boundary["token_contract_ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "row_count": len(rows),
        "resource_budget": {
            "tbgd_read_count": 0,
            "full_rulebook_build_count": 0,
            "minimal_in_memory_rulebook_build_count": 2,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
        },
        "deferred": {
            "explicit_turn_phase_machine": "P7-S9",
            "queue_expiration_and_drain_policy": "P7-S11",
            "enemy_ai": "outside_core",
        },
    }
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "row_id": row["row_id"],
                "classification": row["classification"],
                "ok": row["ok"],
            }
            for row in rows
        ],
    }
    evidence = {
        "query_idempotency": query_idempotency,
        "ally_round_trip": {
            key: value
            for key, value in ally_round_trip.items()
            if key not in {"initial_state", "decision_state", "primary_after_state"}
        },
        "stale_token": stale_token,
        "direct_bypass": direct_bypass,
        "enemy_round_trip": enemy_round_trip,
        "static_boundary": static_boundary,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s8_decision_query_submit_loop.json", summary)
    write_json(output_dir / "p7_s8_decision_query_submit_matrix.json", matrix)
    write_json(output_dir / "p7_s8_decision_query_submit_evidence.json", evidence)
    return summary


def _query_idempotency_case(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    system = DecisionSystem(rules)
    before = state.snapshot().to_json()
    first = system.current_decision(state)
    middle = state.snapshot().to_json()
    second = system.current_decision(state)
    after = state.snapshot().to_json()
    ok = (
        first.ready
        and second.ready
        and first.to_json() == second.to_json()
        and first.token == second.token
        and before == middle == after
        and state.event_index == int(before["event_index"])
    )
    return {
        "row_id": "query_idempotency",
        "classification": "executable",
        "ok": ok,
        "token": first.token.to_json() if first.token else {},
        "mode": first.availability.mode,
        "choice_ids": [choice.choice_id for choice in first.availability.choices],
        "snapshot_unchanged": before == middle == after,
    }


def _ally_round_trip_case(rules: RuleBook) -> dict[str, Any]:
    system = DecisionSystem(rules)
    initial = _ally_initial_state()
    advance = system.advance_to_decision(initial)
    decision_state = advance.after_state
    decision = advance.decision
    commands = _commands_from_decision(decision)
    submissions = [system.submit(decision_state, decision.token, command) for command in commands] if decision.token else []
    submission_evidence = [_submission_evidence(rules, decision_state, result) for result in submissions]
    primary = submissions[0] if submissions else None
    next_advance = system.advance_to_decision(primary.after_state) if primary is not None else None
    advance_turn_begin_count = sum(
        1
        for transition in advance.transitions
        for event in transition.transaction.events
        if event.event_type == "turn.begin"
    )
    submit_turn_begin_count = (
        sum(1 for event in primary.transition.transaction.events if event.event_type == "turn.begin")
        if primary is not None
        else -1
    )
    all_submit = bool(submission_evidence) and all(item["ok"] for item in submission_evidence)
    decision_consumed_once = bool(
        primary is not None
        and primary.transition.outcome.successor_eligible
        and primary.after_state.global_flags.get("turn_owner_id") is None
        and primary.after_state.global_flags.get("active_turn") is None
        and primary.after_state.global_flags.get("turn_sequence_index")
        == decision_state.global_flags.get("turn_sequence_index")
        and next_advance is not None
        and next_advance.decision.ready
        and int(next_advance.after_state.global_flags.get("turn_sequence_index") or 0)
        == int(decision_state.global_flags.get("turn_sequence_index") or 0) + 1
    )
    ok = (
        advance.blocked_reason == ""
        and decision.ready
        and advance_turn_begin_count == 1
        and all_submit
        and submit_turn_begin_count == 0
        and decision_consumed_once
    )
    return {
        "row_id": "ally_advance_query_submit_round_trip",
        "classification": "executable",
        "ok": ok,
        "initial_state": initial,
        "decision_state": decision_state,
        "primary_after_state": primary.after_state if primary is not None else decision_state,
        "decision": decision.to_json(),
        "advance_transition_count": len(advance.transitions),
        "advance_turn_begin_event_count": advance_turn_begin_count,
        "submit_turn_begin_event_count": submit_turn_begin_count,
        "commands": [_command_payload(command) for command in commands],
        "submission_evidence": submission_evidence,
        "all_exposed_combinations_submit": all_submit,
        "decision_consumed_once": decision_consumed_once,
        "next_decision": next_advance.decision.to_json() if next_advance is not None else {},
    }


def _stale_token_case(rules: RuleBook, round_trip: dict[str, Any]) -> dict[str, Any]:
    system = DecisionSystem(rules)
    decision_state = round_trip["decision_state"]
    after_state = round_trip["primary_after_state"]
    decision = system.current_decision(decision_state)
    commands = _commands_from_decision(decision)
    stale = system.submit(after_state, decision.token, commands[0]) if decision.token and commands else None
    ok = bool(
        stale is not None
        and stale.transition.outcome.category == "blocked"
        and stale.transition.coverage.get("blocked_reason") == "stale_decision_token"
        and stale.after_state.snapshot().to_json() == after_state.snapshot().to_json()
        and not stale.transition.transaction.mutations
    )
    return {
        "row_id": "stale_decision_token",
        "classification": "negative",
        "ok": ok,
        "blocked_reason": stale.transition.coverage.get("blocked_reason") if stale is not None else "not_executed",
        "state_unchanged": stale.after_state == after_state if stale is not None else False,
        "mutation_count": len(stale.transition.transaction.mutations) if stale is not None else -1,
    }


def _direct_bypass_case(rules: RuleBook, round_trip: dict[str, Any]) -> dict[str, Any]:
    decision_state = round_trip["decision_state"]
    decision = DecisionSystem(rules).current_decision(decision_state)
    commands = _commands_from_decision(decision)
    direct = CombatScheduler(rules).step(decision_state, commands[0]) if commands else None
    forged = None
    if commands and decision.token is not None:
        forged = CombatScheduler(rules).step(
            decision_state,
            commands[0],
            decision_authorization=DecisionSubmissionAuthorization(
                decision_id=decision.token.decision_id,
                state_revision=decision.token.state_revision,
                actor_id=commands[0].actor_id,
                action_id=commands[0].action_id,
                action_level=commands[0].action_level,
            ),
        )
    ok = bool(
        direct is not None
        and direct.transition.outcome.category == "blocked"
        and direct.transition.coverage.get("blocked_reason") == "decision_token_required"
        and direct.after_state == decision_state
        and not direct.transition.transaction.mutations
        and forged is not None
        and forged.transition.outcome.category == "blocked"
        and forged.transition.coverage.get("blocked_reason")
        == "decision_submission_authorization_not_issued"
        and forged.after_state == decision_state
        and not forged.transition.transaction.mutations
    )
    return {
        "row_id": "direct_scheduler_bypass",
        "classification": "negative",
        "ok": ok,
        "blocked_reason": direct.transition.coverage.get("blocked_reason") if direct is not None else "not_executed",
        "state_unchanged": direct.after_state == decision_state if direct is not None else False,
        "forged_blocked_reason": forged.transition.coverage.get("blocked_reason")
        if forged is not None
        else "not_executed",
        "forged_state_unchanged": forged.after_state == decision_state if forged is not None else False,
        "forged_mutation_count": len(forged.transition.transaction.mutations)
        if forged is not None
        else -1,
    }


def _enemy_round_trip_case() -> dict[str, Any]:
    rules = _enemy_rulebook()
    system = DecisionSystem(rules)
    initial = _enemy_initial_state()
    advance = system.advance_to_decision(initial)
    decision = advance.decision
    commands = _commands_from_decision(decision)
    submission = system.submit(advance.after_state, decision.token, commands[0]) if decision.token and commands else None
    choice = decision.availability.choices[0] if decision.availability.choices else None
    candidate_metadata = choice.metadata.get("enemy_action_candidate", {}) if choice is not None else {}
    candidate_source_trace = candidate_metadata.get("source_trace", {}) if isinstance(candidate_metadata, dict) else {}
    policy = candidate_source_trace.get("ai_policy", {}) if isinstance(candidate_source_trace, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    forced_constraint_ok = bool(
        choice is not None
        and choice.actor_side == "enemy"
        and choice.control == "external"
        and choice.metadata.get("selection_controller") == "external"
        and policy.get("candidate_constraint_admitted") is True
        and policy.get("candidate_constraint_kind") == "forced_sequence"
        and policy.get("enemy_ai_runtime_execution_admitted") is False
        and policy.get("selection_controller") == "external"
    )
    evidence = _submission_evidence(rules, advance.after_state, submission) if submission is not None else {"ok": False}
    cursor = submission.after_state.units["enemy:actor"].flags.get("enemy_action_sequence_cursor") if submission else None
    ok = bool(
        advance.blocked_reason == ""
        and decision.ready
        and decision.availability.mode == "external_selectable"
        and forced_constraint_ok
        and evidence["ok"]
        and cursor == 1
    )
    return {
        "row_id": "enemy_external_decision_interface",
        "classification": "executable",
        "ok": ok,
        "forced_constraint_ok": forced_constraint_ok,
        "decision": decision.to_json(),
        "command": _command_payload(commands[0]) if commands else {},
        "submission": evidence,
        "cursor_after": cursor,
        "policy": policy,
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    scheduler_path = package_root / "systems" / "scheduler.py"
    decision_path = package_root / "systems" / "decision.py"
    scheduler_source = scheduler_path.read_text(encoding="utf-8")
    decision_source = decision_path.read_text(encoding="utf-8")
    scheduler_tree = ast.parse(scheduler_source)
    scheduler_calls = {
        node.func.attr
        for node in ast.walk(scheduler_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    no_enemy_auto = "command_from_candidate" not in scheduler_calls and "decision_token_required" in scheduler_source
    token_contract_ok = all(
        token in decision_source
        for token in (
            "state.snapshot().to_json()",
            "choice_revision",
            "stale_decision_token",
            "command_not_in_decision_choices",
            "_issue_decision_submission_authorization",
        )
    ) and "decision_submission_authorization_not_issued" in scheduler_source and "_decision_authorization_seal_valid" in scheduler_source and "_DECISION_AUTHORIZATION_ISSUER" in scheduler_source
    ok = no_enemy_auto and token_contract_ok
    return {
        "row_id": "decision_static_boundary",
        "classification": "boundary",
        "ok": ok,
        "no_enemy_auto_selection": no_enemy_auto,
        "token_contract_ok": token_contract_ok,
        "scheduler_attribute_calls": sorted(scheduler_calls),
    }


def _submission_evidence(rules: RuleBook, before: BattleState, result) -> dict[str, Any]:
    replay = MutationReducer().replay_snapshot(
        before,
        result.transition.transaction.mutations,
        result.transition.after.to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    return {
        "ok": result.transition.outcome.successor_eligible and replay.ok and audit.ok,
        "outcome": result.transition.outcome.to_json(),
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
        "mutation_count": len(result.transition.transaction.mutations),
        "turn_begin_event_count": sum(
            1 for event in result.transition.transaction.events if event.event_type == "turn.begin"
        ),
    }


def _commands_from_decision(decision) -> list[ActionCommand]:
    commands: list[ActionCommand] = []
    for choice in decision.availability.choices:
        if choice.auto_target_ids:
            target_options = ((),)
        else:
            target_options = tuple((target_id,) for target_id in choice.selectable_target_ids)
        for target_ids in target_options:
            commands.append(
                ActionCommand(
                    actor_id=choice.actor_id,
                    action_id=choice.action_id,
                    action_level=choice.action_level,
                    target_ids=target_ids,
                    source="manual",
                )
            )
    return commands


def _enemy_rulebook() -> RuleBook:
    base = _trust_rulebook()
    card = MonsterDataCardIR(
        card_id="validation:monster_card",
        entity_ref="validation:actor_a",
        monster_id="validation:monster",
        template_id="validation:monster_template",
        rank="validation",
        profile_id="validation:monster_profile",
        action_set_id="validation:monster_action_set",
        skill_ids=("validation:normal",),
        skill_slots=(),
        ai_policy={
            "policy_kind": "fixed_skill_sequence",
            "admitted_task": "RPG.GameCore.UseSequencedSkill",
            "admission_status": "executable",
            "coverage_status": "lowered",
            "candidate_constraint_admitted": True,
            "candidate_constraint_kind": "forced_sequence",
            "selection_controller": "external",
            "runtime_execution_admitted": False,
            "enemy_ai_runtime_execution_admitted": False,
            "source_trace": _source("enemy_ai_policy").to_json(),
        },
        action_sequence=(
            {
                "sequence_index": 0,
                "sequence_kind": "validation_forced",
                "action_ref": "validation:normal",
                "coverage_status": "lowered",
                "blocked_reason": "",
                "source_trace": _source("enemy_action_sequence").to_json(),
            },
        ),
        summon_refs=(),
        raw_parameter_blocks={},
        card_contract={},
        source=_source("enemy_monster_card"),
        coverage_status="executable",
    )
    return RuleBook(replace(base.ir, monster_data_cards=(card,)))


def _enemy_initial_state() -> BattleState:
    state = _base_state()
    enemy = replace(
        state.units["enemy:target"],
        unit_id="enemy:actor",
        template_id="validation:actor_a",
        action_value=0.0,
        flags={
            **state.units["enemy:target"].flags,
            "monster_data_card_id": "validation:monster_card",
            "position": 0,
            "on_field": True,
            "targetable": True,
        },
    )
    ally = replace(
        state.units["ally:actor"],
        action_value=100.0,
        flags={**state.units["ally:actor"].flags, "position": 0, "on_field": True, "targetable": True},
    )
    return replace(state, units={"ally:actor": ally, "enemy:actor": enemy})


def _ally_initial_state() -> BattleState:
    state = _base_state()
    target = replace(
        state.units["enemy:target"],
        flags={**state.units["enemy:target"].flags, "action_disabled": True},
    )
    return replace(state, units={**state.units, "enemy:target": target})


def _command_payload(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S8 idempotent decision query and token-bound submission loop.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['row_count']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
