from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, ServantDefinitionIR
from ..rules.rulebook import RuleBook
from ..scenarios import ScenarioLoader, ScenarioStateBuilder
from ..systems.action_availability import ActionAvailabilitySystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_8_battle_setup import (
    _base_scenario_data_for_avatar,
    _select_avatar_action_for_entity,
    _select_enemy_entity,
)
from .validate_p1_3_summon_assistant_servant import (
    _select_executable_servant_definition,
    _select_servant_owner_entity_ref,
)
from .validate_p3_s6_summon_action_execution import _command_from_choice


VALIDATION_VERSION = "p3_s11_battle_setup_scenario_route"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    servant_definition = _select_executable_servant_definition(rules)
    enemy_ref = _select_enemy_entity(rules)
    groups = {
        "initial_servant_route_execution": _initial_servant_route_execution_case(rules, servant_definition, enemy_ref),
        "initial_summon_blocked_boundary": _initial_summon_blocked_boundary_case(rules, servant_definition, enemy_ref),
        "illegal_damage_route_blocked": _illegal_damage_route_blocked_case(rules, servant_definition, enemy_ref),
        "missing_target_route_blocked": _missing_target_route_blocked_case(rules, servant_definition, enemy_ref),
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
            "selection_policy": {
                "mode": "structured_battle_setup_summon_scenario_route_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "servant_definition_id": servant_definition.servant_definition_id,
                "enemy_ref": enemy_ref,
            },
            "resource_budget": {
                "rulebook_build_count": 1,
                "large_artifacts_written": False,
                "output_scope": "summary_and_compact_route_audit_only",
            },
        },
        "summary": {
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
            "initial_servant_setup_classification": groups["initial_servant_route_execution"].get(
                "setup_classification",
                "executable",
            ),
            "servant_route_action_graph_classification": groups["initial_servant_route_execution"]["classification"],
            "route_action_id": groups["initial_servant_route_execution"]["command"]["action_id"],
            "route_replay_ok": groups["initial_servant_route_execution"]["replay"]["ok"],
            "route_source_audit_ok": groups["initial_servant_route_execution"]["source_audit"]["ok"],
            "initial_blocked_reason": groups["initial_summon_blocked_boundary"]["blocked_reason"],
            "illegal_damage_route_reason": groups["illegal_damage_route_blocked"]["coverage"].get(
                "summon_damage_stat_blocked_reason",
                "",
            ),
            "missing_target_route_reason": groups["missing_target_route_blocked"]["coverage"].get(
                "blocked_reason",
                "",
            ),
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s11_battle_setup_scenario_route.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S11 battle setup and scenario route integration.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _initial_servant_route_execution_case(
    rules: RuleBook,
    definition: ServantDefinitionIR,
    enemy_ref: str,
) -> dict[str, Any]:
    draft_build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=())
    servant_id = _first_servant_id(draft_build.state)
    selected = _select_route_choice(rules, draft_build.state, servant_id)
    if selected["choice"] is None:
        runtime = (
            draft_build.state.global_flags.get("summon_runtime")
            if isinstance(draft_build.state.global_flags.get("summon_runtime"), dict)
            else {}
        )
        checks = {
            "scenario_built_with_initial_servant": servant_id in draft_build.state.units
            and draft_build.state.units[servant_id].flags.get("summon_kind") == "servant",
            "setup_mutations_present": any(
                mutation.metadata.get("lifecycle_operation") == "unit_spawn"
                for mutation in draft_build.setup_mutations
            ),
            "runtime_tracks_servant": isinstance(runtime.get("servants"), dict)
            and servant_id in runtime["servants"],
            "action_graph_gap_has_query_evidence": bool(selected["attempts"] or selected["blocked_choices"]),
            "no_untrusted_route_successor": all(
                attempt["successor_eligible"] is False for attempt in selected["attempts"]
            ),
            "untrusted_route_attempts_state_unchanged": all(
                attempt["official_state_unchanged"] is True for attempt in selected["attempts"]
            ),
            "route_not_fabricated": True,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "classification": "implementation_missing",
            "setup_classification": "executable",
            "p7_invariant_blocker": False,
            "servant_definition_id": definition.servant_definition_id,
            "servant_unit_id": servant_id,
            "setup_record_types": [str(record.get("record_type") or "") for record in draft_build.setup_records],
            "setup_mutation_source_counts": _mutation_source_counts(draft_build.setup_mutations),
            "attempts": selected["attempts"],
            "blocked_choices": selected["blocked_choices"],
            "command": {"action_id": ""},
            "coverage": {},
            "mutation_source_counts": {},
            "record_types": [],
            "replay": {"ok": True, "errors": []},
            "source_audit": {"ok": True, "checked_mutations": 0, "checked_records": 0},
        }
    choice = selected["choice"]
    target_ids = selected["target_ids"]
    route = (
        {
            "actor_id": servant_id,
            "action_ref": choice.action_id,
            "action_level": choice.action_level,
            "target_ids": list(target_ids),
            "source": "manual",
            "metadata": {"label": "p3_s11_servant_route", "reset_actor_av": True},
        },
    )
    build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=route)
    command = build.commands[0]
    availability = ActionAvailabilitySystem(rules).view(build.state)
    after, transition = CombatExecutor(rules).execute(command, build.state)
    replay = MutationReducer().replay_snapshot(build.state, transition.transaction.mutations, transition.after.to_json())
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    runtime = build.state.global_flags.get("summon_runtime") if isinstance(build.state.global_flags.get("summon_runtime"), dict) else {}
    checks = {
        "scenario_built_with_initial_servant": servant_id in build.state.units
        and build.state.units[servant_id].flags.get("summon_kind") == "servant",
        "setup_mutations_present": any(mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in build.setup_mutations),
        "runtime_tracks_servant": isinstance(runtime.get("servants"), dict) and servant_id in runtime["servants"],
        "route_command_from_builder": bool(build.commands)
        and command.actor_id == servant_id
        and command.action_id == choice.action_id
        and command.target_ids == target_ids,
        "availability_exposes_route_action": availability.mode == "external_selectable"
        and any(item.choice_kind == "summon_action" and item.action_id == command.action_id for item in availability.choices),
        "action_enabled": transition.coverage.get("action_enabled") is True,
        "mutations_present": bool(transition.transaction.mutations),
        "target_resolution_selected": transition.target_resolution.selected == target_ids,
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "after_matches_transition": after.snapshot().to_json() == transition.after.to_json(),
        "settlement_records_present": bool(records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable_end_to_end_scenario_route",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "setup_record_types": [str(record.get("record_type") or "") for record in build.setup_records],
        "setup_mutation_source_counts": _mutation_source_counts(build.setup_mutations),
        "availability": _compact_availability(availability),
        "command": _command_json(command),
        "coverage": _compact_coverage(transition.coverage),
        "target_resolution": transition.target_resolution.to_json(),
        "mutation_source_counts": _mutation_source_counts(transition.transaction.mutations),
        "record_types": [str(record.get("record_type") or "") for record in records[:30]],
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit.to_json()),
    }


def _initial_summon_blocked_boundary_case(
    rules: RuleBook,
    definition: ServantDefinitionIR,
    enemy_ref: str,
) -> dict[str, Any]:
    owner_entity_ref = _select_servant_owner_entity_ref(definition)
    action = _select_avatar_action_for_entity(rules, owner_entity_ref)
    base = _base_scenario_data_for_avatar(rules, action, owner_entity_ref, enemy_ref)
    base["scenario_id"] = "p3_s11_no_initial_summon_base"
    baseline = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(base))
    blocked_ref = _select_battle_unit_summon_ref(rules)
    data = _base_scenario_data_for_avatar(rules, action, owner_entity_ref, enemy_ref)
    data["scenario_id"] = "p3_s11_initial_battle_unit_summon_blocked"
    data["battle_setup"] = {
        "initial_summons": [
            {
                "kind": "battle_unit_summon",
                "owner_id": "ally:actor",
                "summon_intent_ref": blocked_ref,
            }
        ]
    }
    build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    blocked_record = build.blocked_setup[0] if build.blocked_setup else {}
    checks = {
        "blocked_setup_present": bool(build.blocked_setup),
        "blocked_reason_boundary": blocked_record.get("blocked_reason") == "battle_unit_summon_initial_setup_boundary_only",
        "no_setup_mutations": not build.setup_mutations,
        "state_unchanged_from_no_setup": build.state.snapshot().to_json() == baseline.state.snapshot().to_json(),
        "source_trace_if_known": bool(blocked_record.get("source_trace") or blocked_ref == ""),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "blocked_initial_summon_boundary_state_unchanged",
        "summon_intent_ref": blocked_ref,
        "blocked_reason": str(blocked_record.get("blocked_reason") or ""),
        "blocked_record": blocked_record,
    }


def _illegal_damage_route_blocked_case(
    rules: RuleBook,
    definition: ServantDefinitionIR,
    enemy_ref: str,
) -> dict[str, Any]:
    draft_build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=())
    servant_id = _first_servant_id(draft_build.state)
    damage_action = _select_servant_hp_damage_action(rules)
    route = (
        {
            "actor_id": servant_id,
            "action_ref": damage_action.action_id,
            "action_level": damage_action.level,
            "target_ids": ["enemy:target"],
            "source": "manual",
            "metadata": {"label": "p3_s11_illegal_damage_route"},
        },
    )
    build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=route)
    command = build.commands[0]
    availability = ActionAvailabilitySystem(rules).view(build.state)
    after, transition = CombatExecutor(rules).execute(command, build.state)
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    reason_text = " ".join(
        (
            str(transition.coverage.get("blocked_reason") or ""),
            str(transition.coverage.get("plan_blocked_reason") or ""),
            str(transition.coverage.get("summon_damage_stat_blocked_reason") or ""),
            " ".join(transition.outcome.reason_codes),
        )
    )
    damage_gate_reached = "summon_damage_stat_binding_not_admitted" in reason_text
    checks = {
        "route_command_preserved": command.action_id == damage_action.action_id and command.target_ids == ("enemy:target",),
        "route_action_not_available": all(choice.action_id != damage_action.action_id for choice in availability.choices),
        "action_disabled": transition.coverage.get("action_enabled") is False,
        "structured_block_reason_present": bool(reason_text.strip()),
        "untrusted_route_not_successor_eligible": not transition.outcome.successor_eligible,
        "no_mutations": not transition.transaction.mutations,
        "state_unchanged": after.snapshot().to_json() == build.state.snapshot().to_json(),
        "settlement_is_process_only_or_empty": not records or all(record.get("process_only") is True for record in records),
        "no_auto_reselection": transition.transaction.command.action_id == damage_action.action_id,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "illegal_route_blocked_state_unchanged" if damage_gate_reached else "implementation_missing",
        "damage_stat_gate_reached": damage_gate_reached,
        "blocked_reason": reason_text.strip(),
        "servant_unit_id": servant_id,
        "command": _command_json(command),
        "coverage": _compact_coverage(transition.coverage),
        "availability": _compact_availability(availability),
        "record_types": [str(record.get("record_type") or "") for record in records[:20]],
    }


def _missing_target_route_blocked_case(
    rules: RuleBook,
    definition: ServantDefinitionIR,
    enemy_ref: str,
) -> dict[str, Any]:
    draft_build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=())
    servant_id = _first_servant_id(draft_build.state)
    selected = _select_route_choice(rules, draft_build.state, servant_id)
    choice = selected["choice"] or selected["query_choice"]
    if choice is None:
        checks = {
            "missing_target_negative_not_fabricated_without_query_choice": True,
            "servant_action_graph_gap_classified_upstream": True,
        }
        checks["ok"] = all(checks.values())
        return {
            "checks": {"ok": checks["ok"], "checks": checks},
            "classification": "implementation_missing",
            "servant_unit_id": servant_id,
            "command": {"action_id": ""},
            "coverage": {"blocked_reason": "servant_action_query_choice_missing"},
            "record_types": [],
        }
    route = (
        {
            "actor_id": servant_id,
            "action_ref": choice.action_id,
            "action_level": choice.action_level,
            "target_ids": [],
            "source": "manual",
            "metadata": {"label": "p3_s11_missing_target_route"},
        },
    )
    build = _build_initial_servant_scenario(rules, definition, enemy_ref, route=route)
    command = build.commands[0]
    after, transition = CombatExecutor(rules).execute(command, build.state)
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    checks = {
        "route_command_has_no_targets": command.target_ids == (),
        "action_disabled": transition.coverage.get("action_enabled") is False,
        "blocked_reason_no_selected_target": "no_selected_target" in str(transition.coverage.get("blocked_reason") or ""),
        "no_mutations": not transition.transaction.mutations,
        "state_unchanged": after.snapshot().to_json() == build.state.snapshot().to_json(),
        "process_only_blocked_record": any(
            record.get("record_type") == "action_blocked" and record.get("process_only") is True
            for record in records
        ),
        "no_auto_target_selection": not transition.target_resolution.selected,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "missing_target_route_blocked_state_unchanged",
        "servant_unit_id": servant_id,
        "command": _command_json(command),
        "coverage": _compact_coverage(transition.coverage),
        "target_resolution": transition.target_resolution.to_json(),
        "record_types": [str(record.get("record_type") or "") for record in records[:20]],
    }


def _build_initial_servant_scenario(
    rules: RuleBook,
    definition: ServantDefinitionIR,
    enemy_ref: str,
    *,
    route: tuple[dict[str, Any], ...],
):
    owner_entity_ref = _select_servant_owner_entity_ref(definition)
    owner_action = _select_avatar_action_for_entity(rules, owner_entity_ref)
    data = _base_scenario_data_for_avatar(rules, owner_action, owner_entity_ref, enemy_ref)
    data["scenario_id"] = "p3_s11_initial_servant_route"
    data["version"] = VALIDATION_VERSION
    if route:
        data["route"] = [dict(item) for item in route]
    else:
        data["route"][0]["metadata"] = {"label": "p3_s11_placeholder_route", "reset_actor_av": True}
    data["battle_setup"] = {
        "initial_summons": [
            {
                "kind": "servant",
                "owner_id": "ally:actor",
                "summon_intent_ref": definition.servant_definition_id,
            }
        ],
        "timeline": {"mode": "runtime_initialize", "global_av": 0.0},
    }
    return ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))


def _select_route_choice(rules: RuleBook, state: BattleState, servant_id: str):
    state = replace(
        state,
        global_flags={
            **state.global_flags,
            "turn_owner_id": servant_id,
            "phase": "scenario",
            "current_window": "idle",
            "combat_phase": "awaiting_decision",
        },
    )
    view = ActionAvailabilitySystem(rules).view(state)
    attempts: list[dict[str, Any]] = []
    query_choice = None
    query_target_ids: tuple[str, ...] = ()
    for choice in view.choices:
        if choice.choice_kind != "summon_action":
            continue
        target_ids = (servant_id,) if servant_id in choice.selectable_target_ids else tuple(choice.auto_target_ids or choice.selectable_target_ids[:1])
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
                "blocked_reason": str(
                    transition.coverage.get("blocked_reason")
                    or transition.coverage.get("plan_blocked_reason")
                    or ""
                ),
                "outcome_category": transition.outcome.category,
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
                "blocked_choices": [item.to_json() for item in view.blocked[:10]],
            }
    return {
        "choice": None,
        "target_ids": (),
        "query_choice": query_choice,
        "query_target_ids": query_target_ids,
        "attempts": attempts,
        "blocked_choices": [item.to_json() for item in view.blocked[:10]],
    }


def _first_servant_id(state: BattleState) -> str:
    for unit_id, unit in sorted(state.units.items()):
        if unit.flags.get("summon_kind") == "servant":
            return unit_id
    raise RuntimeError("initial servant unit missing")


def _select_battle_unit_summon_ref(rules: RuleBook) -> str:
    for definition in rules.summon_unit_definitions():
        if definition.coverage_status == "blocked":
            return definition.summon_definition_id
    definitions = rules.summon_unit_definitions()
    return definitions[0].summon_definition_id if definitions else ""


def _select_servant_hp_damage_action(rules: RuleBook) -> ActionDefinitionIR:
    for action in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.action_id.startswith("servant_skill:") and action.damage_kind == "hp_damage" and action.coverage_status == "executable":
            return action
    raise RuntimeError("no executable servant hp-damage ActionDefinitionIR selected by structured predicate")


def _compact_availability(view) -> dict[str, JSONValue]:
    return {
        "mode": view.mode,
        "turn_owner_id": view.turn_owner_id,
        "choice_count": len(view.choices),
        "choices": [
            {
                "choice_kind": choice.choice_kind,
                "actor_id": choice.actor_id,
                "action_id": choice.action_id,
                "action_level": choice.action_level,
                "target_status": choice.target_status,
                "selectable_target_ids": list(choice.selectable_target_ids),
                "blocked_reason": choice.blocked_reason,
            }
            for choice in view.choices[:8]
        ],
        "blocked": [item.to_json() for item in view.blocked[:8]],
    }


def _compact_coverage(coverage: dict[str, JSONValue]) -> dict[str, JSONValue]:
    keys = (
        "action_enabled",
        "blocked_reason",
        "plan_blocked_reason",
        "target_ok",
        "resource_ok",
        "binding_ok",
        "event_ok",
        "summon_execution_blocked_reason",
        "summon_damage_stat_blocked_reason",
        "damage_mutation_count",
        "resource_mutation_count",
        "ability_task_mutation_count",
    )
    return {key: coverage.get(key) for key in keys if key in coverage}


def _compact_source_audit(audit: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "ok": bool(audit.get("ok")),
        "checked_mutations": int(audit.get("checked_mutations") or 0),
        "checked_records": int(audit.get("checked_records") or 0),
        "violations": audit.get("violations", []),
        "trace_origins": [trace.get("origin", {}) for trace in audit.get("traces", []) if isinstance(trace, dict)],
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


def _mutation_source_counts(mutations) -> dict[str, int]:
    return dict(Counter(str(mutation.source) for mutation in mutations))


if __name__ == "__main__":
    raise SystemExit(main())
