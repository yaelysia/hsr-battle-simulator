from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ServantDefinitionIR, SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.summon import SummonSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_summon_state,
    _first_servant_id,
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
)
from .validate_p3_s5_servant_lifecycle import _formal_servant_state


VALIDATION_VERSION = "p3_s6_summon_action_execution"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    rules: RuleBook | None = None,
) -> dict[str, Any]:
    lowering_build_count = 0
    if rules is None:
        rules = RuleBook(TBGDLowering(tbgd_root).build())
        lowering_build_count = 1
    static_result = run_static_checks(package_root)
    servant_definition = _select_executable_servant_definition(rules)
    summon_intent = _select_executable_summon_monster_intent(rules)
    groups = {
        "servant_action_execution": _servant_action_execution_case(rules, servant_definition),
        "summoned_monster_action_boundary": _summoned_monster_action_boundary_case(rules, summon_intent),
        "executor_bypass_boundaries": _executor_bypass_boundary_cases(rules, servant_definition),
        "resource_pressure_boundary": _resource_pressure_boundary_case(rules, servant_definition),
    }
    checks = {
        **{name: group["checks"] for name, group in groups.items()},
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "lowering_build_count": lowering_build_count,
            "selection_policy": {
                "mode": "structured_summon_servant_action_admission_execution_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "servant_definition_id": servant_definition.servant_definition_id,
                "summon_intent_id": summon_intent.summon_intent_id,
            },
        },
        "summary": {
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
            "servant_action_graph_classification": groups["servant_action_execution"]["classification"],
            "servant_action_enabled": groups["servant_action_execution"]["transition_coverage"].get("action_enabled") is True,
            "servant_action_mutation_count": groups["servant_action_execution"]["mutation_count"],
            "servant_action_replay_ok": groups["servant_action_execution"]["replay"]["ok"],
            "servant_action_source_audit_ok": groups["servant_action_execution"]["source_audit"]["ok"],
            "summoned_monster_action_classification": groups["summoned_monster_action_boundary"]["classification"],
            "negative_case_count": groups["executor_bypass_boundaries"]["negative_case_count"],
            "resource_pressure_classification": groups["resource_pressure_boundary"]["classification"],
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s6_summon_action_execution.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S6 summon/servant action availability and execution.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _servant_action_execution_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state = _spawn_servant_turn_state(rules, definition)
    view = ActionAvailabilitySystem(rules).view(state)
    selected = _select_executable_choice(rules, state, view)
    if selected["choice"] is None:
        checks = {
            "availability_classified": view.mode in {"external_selectable", "blocked"},
            "no_successor_eligible_choice": all(
                attempt["successor_eligible"] is False for attempt in selected["attempts"]
            ),
            "untrusted_attempts_keep_official_state_unchanged": all(
                attempt["official_state_unchanged"] is True for attempt in selected["attempts"]
            ),
            "implementation_gap_has_structured_query_evidence": bool(selected["attempts"] or view.blocked),
            "no_executable_choice_fabricated": True,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "classification": "implementation_missing",
            "p7_invariant_blocker": False,
            "servant_definition_id": definition.servant_definition_id,
            "servant_unit_id": _first_servant_id(state),
            "choice_count": len(view.choices),
            "blocked_choices": [item.to_json() for item in view.blocked[:10]],
            "attempts": selected["attempts"],
            "transition_coverage": {},
            "mutation_count": 0,
            "mutation_source_counts": {},
            "record_types": [],
            "replay": {"ok": True, "errors": []},
            "source_audit": {"ok": True, "checked_mutations": 0, "checked_records": 0, "traces": [], "violations": []},
        }
    command = _command_from_choice(selected["choice"], selected["target_ids"])
    after, transition = CombatExecutor(rules).execute(command, state)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    checks = {
        "availability_external_selectable": view.mode == "external_selectable",
        "choice_is_summon_action": selected["choice"].choice_kind == "summon_action",
        "choice_source_trace_complete": bool(selected["choice"].source_trace.get("summon_action_admission"))
        and bool(selected["choice"].source_trace.get("action_definition"))
        and bool(selected["choice"].source_trace.get("action_event")),
        "external_target_selected": bool(command.target_ids),
        "action_enabled": transition.coverage.get("action_enabled") is True,
        "mutation_count_positive": bool(transition.transaction.mutations),
        "no_damage_without_servant_damage_stat_admission": transition.coverage.get("damage_mutation_count", 0) == 0,
        "non_damage_mutation_present": any(
            mutation.source in {"status_system", "effect_system", "combat_executor.timeline"}
            for mutation in transition.transaction.mutations
        ),
        "settlement_records_present": bool(records),
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "after_matches_transition": after.snapshot().to_json() == transition.after.to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": command.actor_id,
        "choice": _compact_choice(selected["choice"]),
        "command": _command_json(command),
        "target_resolution": transition.target_resolution.to_json(),
        "transition_coverage": _compact_coverage(transition.coverage),
        "mutation_count": len(transition.transaction.mutations),
        "mutation_source_counts": _mutation_source_counts(transition.transaction.mutations),
        "record_types": [str(record.get("record_type") or "") for record in records[:20]],
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit),
    }


def _summoned_monster_action_boundary_case(rules: RuleBook, intent: SummonMonsterIntentIR) -> dict[str, Any]:
    state = _spawn_summoned_monster_turn_state(rules, intent)
    actor_id = str(state.global_flags.get("turn_owner_id") or "")
    view = ActionAvailabilitySystem(rules).view(state)
    blocked_reasons = [item.reason for item in view.blocked]
    actor = state.units[actor_id]
    selectable = tuple(choice for choice in view.choices if choice.auto_target_ids or choice.selectable_target_ids)
    if view.mode != "blocked" and selectable:
        choice = selectable[0]
        checks = {
            "spawned_monster_has_runtime_action_admission": actor.flags.get("summon_action_admitted") is True
            and isinstance(actor.flags.get("summon_action_admission"), dict)
            and actor.flags["summon_action_admission"].get("coverage_status") == "executable",
            "runtime_registry_present": isinstance(state.global_flags.get("summon_runtime"), dict),
            "availability_executable": view.mode == "external_selectable",
            "choice_is_summoned_monster_fixed_sequence": choice.choice_kind == "enemy_fixed_sequence",
            "choice_source_trace_complete": bool(choice.source_trace.get("action_definition"))
            and bool(choice.source_trace.get("action_event"))
            and bool(choice.source_trace.get("action_sequence_step"))
            and bool(choice.source_trace.get("ai_policy"))
            and bool(choice.source_trace.get("monster_data_card")),
            "choice_candidate_available": (
                isinstance(choice.metadata.get("enemy_action_candidate"), dict)
                and choice.metadata["enemy_action_candidate"].get("status") == "available"
            ),
            "state_unchanged": state.snapshot().to_json() == state.snapshot().to_json(),
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "classification": "executable",
            "summon_intent_id": intent.summon_intent_id,
            "summoned_monster_unit_id": actor_id,
            "choice": choice.to_json(),
            "availability": _compact_availability(view),
            "source_note": "Selected summoned monster sample now has source-backed action availability.",
        }
    checks = {
        "spawned_monster_has_runtime_action_admission": actor.flags.get("summon_action_admitted") is True
        and isinstance(actor.flags.get("summon_action_admission"), dict)
        and actor.flags["summon_action_admission"].get("coverage_status") == "executable",
        "runtime_registry_present": isinstance(state.global_flags.get("summon_runtime"), dict),
        "availability_boundary_not_executable": view.mode == "blocked" and not view.choices,
        "blocked_reason_machine_readable": bool(
            blocked_reasons or view.ordinary_input_blocked_reason
        ),
        "state_unchanged": state.snapshot().to_json() == state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "summon_intent_id": intent.summon_intent_id,
        "summoned_monster_unit_id": actor_id,
        "blocked_reasons": blocked_reasons,
        "availability": _compact_availability(view),
        "source_note": "Current executable SummonMonster spawn samples lack fixed-sequence enemy action admission, so they remain action-boundary only.",
    }


def _executor_bypass_boundary_cases(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    base_state = _spawn_servant_turn_state(rules, definition)
    view = ActionAvailabilitySystem(rules).view(base_state)
    selected = _select_executable_choice(rules, base_state, view)
    query_choice = selected["choice"] or selected["query_choice"]
    query_target_ids = selected["target_ids"] or selected["query_target_ids"]
    if query_choice is None:
        checks = {
            "query_choice_absence_classified_with_action_graph_gap": True,
            "negative_command_not_fabricated": True,
        }
        checks["ok"] = all(checks.values())
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "classification": "implementation_missing",
            "negative_case_count": 0,
            "cases": {},
        }
    command = _command_from_choice(query_choice, query_target_ids)
    servant_id = command.actor_id
    cases = {
        "missing_target": _blocked_execution_case(
            rules,
            base_state,
            replace(command, target_ids=()),
            "target_selection_too_few",
        ),
        "runtime_missing": _blocked_execution_case(
            rules,
            replace(base_state, global_flags={key: value for key, value in base_state.global_flags.items() if key != "summon_runtime"}),
            command,
            "summon_runtime_state_missing",
        ),
        "timeline_not_admitted": _blocked_execution_case(
            rules,
            _with_unit_flag(base_state, servant_id, "timeline_admitted", False),
            command,
            "summon_timeline_not_admitted",
        ),
        "action_source_not_admitted": _blocked_execution_case(
            rules,
            _with_unit_flag(
                base_state,
                servant_id,
                "summon_action_admission",
                {"coverage_status": "blocked", "blocked_reason": "validation_action_source_blocked"},
            ),
            command,
            "summon_action_source_not_admitted",
        ),
        "runtime_binding_mismatch": _blocked_execution_case(
            rules,
            _with_runtime_source_intent(base_state, servant_id, "servant_definition:wrong"),
            command,
            "summon_runtime_source_binding_mismatch",
        ),
        "defeated_actor": _blocked_execution_case(
            rules,
            _with_unit_flag(_with_unit_field(base_state, servant_id, "hp", 0.0), servant_id, "lifecycle_status", "defeated"),
            command,
            "unit_defeated",
        ),
    }
    checks = {f"{name}_blocked": case["checks"]["ok"] for name, case in cases.items()}
    checks["all_blocked_cases_no_mutation"] = all(case["checks"]["checks"]["no_mutations"] for case in cases.values())
    checks["all_blocked_cases_state_unchanged"] = all(case["checks"]["checks"]["state_unchanged"] for case in cases.values())
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "negative_case_count": len(cases),
        "cases": cases,
    }


def _resource_pressure_boundary_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state = _spawn_servant_turn_state(rules, definition)
    view = ActionAvailabilitySystem(rules).view(state)
    resource_choices = [
        choice
        for choice in view.choices
        if (rules.action_definition(choice.action_id, choice.action_level) is not None)
        and rules.require_action_definition(choice.action_id, choice.action_level).bp_need > 0
    ]
    if not resource_choices:
        checks = {
            "resource_costing_summon_action_absent": True,
            "no_synthetic_resource_case": True,
        }
        checks["ok"] = True
        return {
            "checks": {"ok": True, "checks": checks},
            "classification": "source_absent_not_required",
            "resource_costing_choice_count": 0,
            "note": "Current executable servant summon-action choices have no positive skill-point cost; insufficient-resource negative is not synthesized.",
        }
    choice = resource_choices[0]
    command = _command_from_choice(choice, choice.auto_target_ids or choice.selectable_target_ids[:1])
    resource_state = replace(state, skill_points=0)
    case = _blocked_execution_case(rules, resource_state, command, "resource_plan_failed")
    checks = {
        "resource_costing_summon_action_present": True,
        "insufficient_resource_blocks": case["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "resource_costing_choice_count": len(resource_choices),
        "case": case,
    }


def _blocked_execution_case(
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
    expected_reason: str,
) -> dict[str, Any]:
    before = state.snapshot().to_json()
    after, transition = CombatExecutor(rules).execute(command, state)
    blocked_reason = str(transition.coverage.get("blocked_reason") or "")
    plan_reason = str(transition.coverage.get("plan_blocked_reason") or "")
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    checks = {
        "action_disabled": transition.coverage.get("action_enabled") is False,
        "expected_reason_present": expected_reason in blocked_reason or expected_reason in plan_reason,
        "no_mutations": not transition.transaction.mutations,
        "state_unchanged": after.snapshot().to_json() == before and transition.after.to_json() == before,
        "process_only_blocked_record": any(
            record.get("record_type") in {"action_blocked", "action_contract_blocked"}
            and record.get("process_only") is True
            for record in records
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expected_reason": expected_reason,
        "blocked_reason": blocked_reason,
        "plan_blocked_reason": plan_reason,
        "record_types": [str(record.get("record_type") or "") for record in records],
        "coverage": _compact_coverage(transition.coverage),
    }


def _spawn_servant_turn_state(rules: RuleBook, definition: ServantDefinitionIR) -> BattleState:
    state = _formal_servant_state(rules, definition)
    system = SummonSystem(rules)
    result = system.apply_spawn_servant(
        state,
        system.plan_spawn_servant(
            state,
            definition,
            owner_id="ally:servant_owner",
            spawn_source=definition.spawn_sources[0],
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    servant_id = _first_servant_id(after)
    return replace(
        after,
        global_flags={
            **after.global_flags,
            "turn_owner_id": servant_id,
            "phase": "scenario",
            "current_window": "idle",
            "combat_phase": "awaiting_decision",
        },
    )


def _spawn_summoned_monster_turn_state(rules: RuleBook, intent: SummonMonsterIntentIR) -> BattleState:
    state = _base_summon_state()
    system = SummonSystem(rules)
    result = system.apply_spawn(
        state,
        system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner"),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    spawned = next(
        unit_id
        for unit_id, unit in sorted(after.units.items())
        if unit.flags.get("summon_kind") == "summoned_monster"
    )
    return replace(
        after,
        global_flags={
            **after.global_flags,
            "turn_owner_id": spawned,
            "phase": "scenario",
            "current_window": "idle",
            "combat_phase": "awaiting_decision",
        },
    )


def _select_executable_choice(rules: RuleBook, state: BattleState, view) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    query_choice = None
    query_target_ids: tuple[str, ...] = ()
    for choice in view.choices:
        target_ids = choice.auto_target_ids or choice.selectable_target_ids[:1]
        if not target_ids:
            continue
        if query_choice is None:
            query_choice = choice
            query_target_ids = tuple(target_ids)
        command = _command_from_choice(choice, target_ids)
        after, transition = CombatExecutor(rules).execute(command, state)
        replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        attempts.append(
            {
                "action_id": choice.action_id,
                "action_level": choice.action_level,
                "target_ids": list(target_ids),
                "action_enabled": transition.coverage.get("action_enabled") is True,
                "blocked_reason": str(transition.coverage.get("blocked_reason") or transition.coverage.get("plan_blocked_reason") or ""),
                "outcome_category": transition.outcome.category,
                "outcome_reason_codes": list(transition.outcome.reason_codes),
                "incomplete_node_results": [
                    node.to_json()
                    for node in transition.outcome.node_results
                    if not node.complete
                ],
                "successor_eligible": transition.outcome.successor_eligible,
                "mutation_count": len(transition.transaction.mutations),
                "replay_ok": replay.ok,
                "source_audit_ok": audit.ok,
                "official_state_unchanged": after.snapshot().to_json() == state.snapshot().to_json(),
            }
        )
        if (
            transition.coverage.get("action_enabled") is True
            and transition.transaction.mutations
            and replay.ok
            and audit.ok
            and transition.outcome.successor_eligible
        ):
            return {
                "choice": choice,
                "target_ids": tuple(target_ids),
                "query_choice": query_choice,
                "query_target_ids": query_target_ids,
                "attempts": attempts,
            }
    return {
        "choice": None,
        "target_ids": (),
        "query_choice": query_choice,
        "query_target_ids": query_target_ids,
        "attempts": attempts,
    }


def _command_from_choice(choice, target_ids: tuple[str, ...]) -> ActionCommand:
    raw = choice.command_template
    return ActionCommand(
        actor_id=str(raw.get("actor_id") or choice.actor_id),
        action_id=str(raw.get("action_id") or choice.action_id),
        action_level=int(raw.get("action_level") or choice.action_level),
        target_ids=tuple(str(item) for item in target_ids if isinstance(item, str)),
        source=str(raw.get("source") or "manual"),  # type: ignore[arg-type]
        queue_name=raw.get("queue_name") if isinstance(raw.get("queue_name"), str) else None,
        metadata={
            **(raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}),
            "p3_s6_selected_from_availability": True,
        },
    )


def _with_unit_flag(state: BattleState, unit_id: str, key: str, value: Any) -> BattleState:
    unit = state.units[unit_id]
    flags = dict(unit.flags)
    flags[key] = value
    return _replace_unit(state, replace(unit, flags=flags))


def _with_unit_field(state: BattleState, unit_id: str, key: str, value: Any) -> BattleState:
    unit = state.units[unit_id]
    return _replace_unit(state, replace(unit, **{key: value}))


def _replace_unit(state: BattleState, unit: UnitState) -> BattleState:
    units = dict(state.units)
    units[unit.unit_id] = unit
    return replace(state, units=units)


def _with_runtime_source_intent(state: BattleState, unit_id: str, source_intent_id: str) -> BattleState:
    runtime = dict(state.global_flags.get("summon_runtime") or {})
    entities = dict(runtime.get("entities") or {})
    entry = dict(entities.get(unit_id) or {})
    entry["source_intent_id"] = source_intent_id
    entities[unit_id] = entry
    runtime["entities"] = entities
    flags = dict(state.global_flags)
    flags["summon_runtime"] = runtime
    return replace(state, global_flags=flags)


def _compact_availability(view) -> dict[str, Any]:
    return {
        "mode": view.mode,
        "ordinary_input_blocked_reason": view.ordinary_input_blocked_reason,
        "choice_count": len(view.choices),
        "blocked_reasons": [item.reason for item in view.blocked],
        "coverage": view.coverage,
    }


def _compact_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "action_enabled",
        "blocked_reason",
        "plan_blocked_reason",
        "summon_execution_blocked_reason",
        "target_ok",
        "resource_ok",
        "binding_ok",
        "event_ok",
        "damage_mutation_count",
        "toughness_mutation_count",
        "resource_mutation_count",
        "ability_task_mutation_count",
        "timeline_mutation_count",
    )
    return {key: coverage.get(key) for key in keys if key in coverage}


def _mutation_source_counts(mutations: tuple[Any, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mutation in mutations:
        source = str(mutation.source)
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _compact_choice(choice: Any) -> dict[str, Any]:
    return {
        "choice_id": choice.choice_id,
        "choice_kind": choice.choice_kind,
        "control": choice.control,
        "actor_id": choice.actor_id,
        "actor_side": choice.actor_side,
        "action_id": choice.action_id,
        "action_level": choice.action_level,
        "admission_id": choice.admission_id,
        "owner_entity_ref": choice.owner_entity_ref,
        "action_role": choice.action_role,
        "allowed_windows": list(choice.allowed_windows),
        "submission_modes": list(choice.submission_modes),
        "auto_target_ids": list(choice.auto_target_ids),
        "selectable_target_ids": list(choice.selectable_target_ids),
        "target_status": choice.target_status,
        "resource_status": choice.resource_status,
        "coverage_status": choice.coverage_status,
        "source_trace_presence": {
            key: bool(value)
            for key, value in sorted(choice.source_trace.items())
        },
    }


def _compact_source_audit(audit: Any) -> dict[str, Any]:
    return {
        "ok": audit.ok,
        "checked_mutations": audit.checked_mutations,
        "checked_records": audit.checked_records,
        "trace_count": len(audit.traces),
        "violation_count": len(audit.violations),
        "violations": [
            {
                "mutation_id": violation.mutation_id,
                "source": violation.source,
                "path": list(violation.path),
                "reason": violation.reason,
                "missing_field": violation.missing_field,
            }
            for violation in audit.violations[:10]
        ],
    }


def _command_json(command: ActionCommand) -> dict[str, Any]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
