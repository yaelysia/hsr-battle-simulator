from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    TargetResolution,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.rulebook import RuleBook
from ..scenarios import IdentityResolver, ScenarioLoader, ScenarioStateBuilder
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.break_system import BreakSystem
from ..systems.effect import EffectRegistry
from ..systems.status import StatusSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.toughness import ToughnessPacket
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_1_unit_lifecycle import _damage_defeat_case
from .validate_p1_4_status_system import (
    _LifecycleResultAdapter,
    _base_state as _status_base_state,
    _chance_cases,
    _control_gate_case,
    _dispel_case,
    _dot_lifecycle_case,
    _duration_owner_case,
    _expire_remove_case,
    _has_random_dispel_source,
    _random_dispel_replay_case,
    _refresh_case,
    _stack_cap_case,
    _stack_only_refresh_case,
    _stack_reduce_case,
    _stack_refresh_source_counts,
    _status_transition,
)
from .validate_p1_5_queue_window_system import (
    _actor_target_lifecycle_case,
    _conditional_queue_case,
    _counter_case,
    _current_queue_scope,
    _extra_turn_case,
    _insert_ability_case,
    _mandatory_insert_action_case,
    _queue_family_source_gaps,
    _queue_source_contract_case,
    _queue_source_matrix,
    _selectable_ultimate_case,
    _unknown_family_blocked_case,
)
from .validate_p1_6_target_system import _fetch_cases, _sort_cases
from .validate_p1_7_rng_branch_system import _rng_helper_cases, _surface_matrix, _target_random_cases
from .validate_p1_8_battle_setup import (
    _base_scenario_data,
    _base_scenario_data_for_avatar,
    _select_avatar_action,
    _select_avatar_action_for_entity,
    _select_enemy_entity,
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
    _select_servant_owner_entity_ref,
    _select_initial_status_case,
    _select_two_wave_definition,
)
from .validate_v0_232 import _break_status_checks, _break_transition_checks, _select_break_case


VALIDATION_VERSION = "p1_9_phase1_aggregate"
SOURCE_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "audit_only",
    "discovered_only",
    "not_touched",
}
VALIDATION_STATES = {"passed", "expected_blocked", "failed", "skipped_by_scope"}
SUMMARY_FILES = (
    "validation_summary_p1_9_phase1_aggregate.json",
    "phase1_system_matrix_p1_9.json",
    "phase1_transition_audit_samples_p1_9.json",
    "phase1_source_gap_matrix_p1_9.json",
    "phase1_static_boundary_p1_9.json",
    "phase1_resource_budget_p1_9.json",
    "phase1_validation_inventory_p1_9.json",
)


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    write_large_artifacts: bool = False,
    include_direct_regression_summaries: bool = False,
    rules: RuleBook | None = None,
) -> dict[str, Any]:
    if rules is None:
        rules = RuleBook(TBGDLowering(tbgd_root).build())
    ir = rules.ir

    action = _select_avatar_action(rules)
    enemy_ref = _select_enemy_entity(rules)
    status_effect, selected_status_case = _select_initial_status_case(rules, action, enemy_ref)
    summon_intent = _select_executable_summon_monster_intent(rules)
    wave_definition = _select_two_wave_definition(rules)

    scenario_data = _aggregate_scenario_data(rules, action, enemy_ref, status_effect.effect_id, summon_intent.summon_intent_id, wave_definition.wave_definition_id)
    scenario = ScenarioLoader().load_dict(scenario_data)
    identity = IdentityResolver(rules).validate(scenario)
    build = ScenarioStateBuilder(rules).build(scenario)

    command = build.commands[0]
    after_state, transition = CombatExecutor(rules).execute(command, build.state)
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(
        build.state,
        transition.transaction.mutations,
        after_state.snapshot().to_json(),
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    settlement_traceability = SettlementTraceabilityValidator().validate(
        transition.transaction.settlement,
        transition.transaction.mutations,
    )
    status_transition_case = _direct_status_transition_case(rules, action, enemy_ref, status_effect)

    direct_cases = _direct_cases(package_root.parent, rules)
    servant_case = _servant_initial_summon_case(rules, enemy_ref)
    battle_unit_summon_blocked = _blocked_initial_summon_case(rules, action, enemy_ref, "battle_unit_summon")
    blocked_status_case = _blocked_status_case(rules, action, enemy_ref)
    target_case = _aggregate_target_case(build.state, transition)
    action_boundary = _aggregate_action_boundary_case(rules, build.state, build.commands)
    wave_case = _aggregate_wave_case(rules, build.state, wave_definition.wave_definition_id)
    setup_case = _aggregate_setup_case(build, selected_status_case, status_effect.effect_id, summon_intent.summon_intent_id)
    static_boundary = _static_boundary_case(package_root, output_dir, write_large_artifacts)
    source_gap_matrix = _source_gap_matrix(
        rules,
        direct_cases=direct_cases,
        servant_case=servant_case,
        battle_unit_summon_blocked=battle_unit_summon_blocked,
    )
    transition_samples = _transition_samples(
        build=build,
        transition=transition,
        contract=contract.to_json(),
        replay={"ok": replay.ok, "errors": list(replay.errors)},
        source_audit=source_audit.to_json(),
        settlement_traceability=settlement_traceability.to_json(),
        servant_case=servant_case,
        blocked_status=blocked_status_case,
        target_case=target_case,
        direct_cases=direct_cases,
        status_transition_case=status_transition_case,
    )

    matrix = [
        _item(
            "p1_0.action_boundary",
            "P1-0",
            "executable",
            "passed" if action_boundary["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=0,
            mutation_count=0,
            source_trace_count=len(build.source_traces),
            replay_ok=True,
            source_audit_ok=True,
            notes=action_boundary["notes"],
        ),
        _item(
            "p1_1.lifecycle",
            "P1-1",
            "executable",
            "passed" if direct_cases["lifecycle"]["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=1,
            mutation_count=len(direct_cases["lifecycle"].get("mutations", ())),
            replay_ok=direct_cases["lifecycle"].get("replay", {}).get("ok") is True,
            source_audit_ok=True,
            notes=["direct_contract_case"],
        ),
        _item(
            "p1_2.wave",
            "P1-2",
            "executable",
            "passed" if wave_case["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=0,
            mutation_count=0,
            source_trace_count=1 if wave_case.get("source_trace") else 0,
            replay_ok=True,
            source_audit_ok=True,
            notes=[],
        ),
        _item(
            "p1_3.summon",
            "P1-3",
            "executable",
            "passed" if setup_case["summon"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=0,
            mutation_count=setup_case["summon"]["mutation_count"],
            source_trace_count=setup_case["summon"]["source_trace_count"],
            replay_ok=True,
            source_audit_ok=setup_case["summon"]["source_trace_count"] > 0,
            notes=[],
        ),
        _item(
            "p1_3.servant_runtime",
            "P1-3",
            "executable",
            "passed" if servant_case["setup_checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=1,
            mutation_count=servant_case["setup_mutation_count"],
            blocked_count=0,
            source_trace_count=servant_case["source_trace_count"],
            replay_ok=True,
            source_audit_ok=servant_case["source_trace_count"] > 0,
            notes=[
                "servant definition is admitted from AvatarServantConfig/AvatarServantSkillConfig",
                "spawn and target registry are executable; incomplete servant action graphs are inherited separately as an implementation gap",
            ],
        ),
        _item(
            "p1_4.status",
            "P1-4",
            "executable",
            "passed" if setup_case["status"]["ok"] and direct_cases["status_regression"]["checks"]["ok"] else "failed",
            positive_case_count=9,
            negative_case_count=4,
            mutation_count=setup_case["status"]["mutation_count"],
            blocked_count=1 if blocked_status_case["checks"]["ok"] else 0,
            source_trace_count=setup_case["status"]["source_trace_count"],
            replay_ok=status_transition_case["replay"]["ok"],
            source_audit_ok=status_transition_case["source_audit"]["ok"],
            notes=[
                "setup source trace counted from nested status lifecycle/status_instance; audit uses direct status transition",
                "direct P1-4 regression covers refresh, stack, chance/resist/immunity, duration, expire, DoT, deterministic dispel, real break status mutation, and blocked boundaries",
            ],
        ),
        _item(
            "p1_4.status_boundary",
            "P1-4",
            "boundary_only",
            "expected_blocked" if _source_gap_rows_ok(source_gap_matrix, "P1-4") else "failed",
            positive_case_count=0,
            negative_case_count=2,
            mutation_count=0,
            blocked_count=sum(1 for row in source_gap_matrix if row["phase_item"] == "P1-4" and row["source_state"] in {"boundary_only", "source_absent_not_required"}),
            replay_ok=True,
            source_audit_ok=True,
            notes=["conditional/no-current-source status rows stay process-only and are not executable claims"],
        ),
        _item(
            "p1_5.queue_window",
            "P1-5",
            "executable",
            "passed"
            if direct_cases["queue_scope"]["checks"]["ok"]
            and direct_cases["queue_source"]["checks"]["ok"]
            and direct_cases["queue_regression"]["checks"]["ok"]
            else "failed",
            positive_case_count=3,
            negative_case_count=4,
            mutation_count=0,
            source_trace_count=0,
            replay_ok=True,
            source_audit_ok=True,
            notes=[
                "route-level direct P1-5 regression covers mandatory insert action, insert ability, selectable ultimate, and actor/target lifecycle guards",
                "follow-up/counter/assistant family rows are classified separately and not implied complete by this item",
            ],
        ),
        _item(
            "p1_6.target",
            "P1-6",
            "executable",
            "passed" if target_case["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=1,
            mutation_count=0,
            source_trace_count=1 if _target_resolution_ok(transition.target_resolution) else 0,
            replay_ok=True,
            source_audit_ok=True,
            notes=[],
        ),
        _item(
            "p1_7.rng",
            "P1-7",
            "executable",
            "passed" if direct_cases["rng_helper"]["checks"]["ok"] and direct_cases["target_random"]["checks"]["ok"] else "failed",
            positive_case_count=2,
            negative_case_count=2,
            mutation_count=0,
            replay_ok=True,
            source_audit_ok=True,
            notes=["direct_contract_case"],
        ),
        _item(
            "p1_8.battle_setup",
            "P1-8",
            "executable",
            "passed" if setup_case["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=2,
            mutation_count=len(build.setup_mutations),
            blocked_count=len(build.blocked_setup),
            source_trace_count=len(build.source_traces),
            replay_ok=True,
            source_audit_ok=True,
            notes=[
                "battle setup executable scope covers roster/resources/wave/status/summoned_monster/timeline/rng/objective",
                "servant and battle_unit_summon setup are classified separately and are not completed by this row",
            ],
        ),
        _item(
            "core.snapshot_replay",
            "Core",
            "executable",
            "passed" if status_transition_case["replay"]["ok"] else "failed",
            positive_case_count=1,
            mutation_count=status_transition_case["mutation_count"],
            replay_ok=status_transition_case["replay"]["ok"],
            source_audit_ok=status_transition_case["source_audit"]["ok"],
            notes=["core mutation replay positive is direct_status_transition; route transition is contract-only when no mutation"],
        ),
        _item(
            "core.source_audit",
            "Core",
            "executable",
            "passed"
            if status_transition_case["source_audit"]["ok"] and status_transition_case["settlement_traceability"]["ok"]
            else "failed",
            positive_case_count=1,
            mutation_count=status_transition_case["mutation_count"],
            source_trace_count=status_transition_case["source_audit"]["checked_mutations"],
            replay_ok=status_transition_case["replay"]["ok"],
            source_audit_ok=status_transition_case["source_audit"]["ok"],
            notes=["core source audit positive is direct_status_transition; route transition is contract-only when no mutation"],
        ),
        _item(
            "core.static_boundary",
            "Core",
            "executable",
            "passed" if static_boundary["checks"]["ok"] else "failed",
            positive_case_count=1,
            negative_case_count=0,
            mutation_count=0,
            replay_ok=True,
            source_audit_ok=True,
            notes=[],
        ),
    ]
    counts = _matrix_counts(matrix)
    source_gap_counts = _matrix_counts(source_gap_matrix)
    checks = {
        "aggregate_scenario": {"ok": identity.ok and bool(build.state.units) and bool(build.commands), "identity": identity.to_json()},
        "transition_contract": contract.to_json(),
        "route_transition_contract": contract.to_json(),
        "route_transition_replay": {"ok": replay.ok, "errors": list(replay.errors), "mutation_count": len(transition.transaction.mutations)},
        "snapshot_replay": status_transition_case["replay"],
        "source_audit": status_transition_case["source_audit"],
        "settlement_traceability": status_transition_case["settlement_traceability"],
        "static_boundary": static_boundary["checks"],
        "blocked_no_mutation": _blocked_no_mutation_check(servant_case, battle_unit_summon_blocked, blocked_status_case, direct_cases),
    }
    minimum_slice_blockers = [
        row["item_id"]
        for row in source_gap_matrix
        if row["phase1_minimum_battle_slice_blocker"] is True
    ]
    implementation_missing_items = [
        item["item_id"]
        for item in matrix
        if item["source_state"] == "implementation_missing"
    ]
    minimum_slice_blockers.extend(item_id for item_id in implementation_missing_items if item_id not in minimum_slice_blockers)
    full_acceptance_blockers = [
        row["item_id"]
        for row in source_gap_matrix
        if row["phase1_full_acceptance_blocker"] is True
    ]
    full_acceptance_blockers.extend(
        item_id for item_id in implementation_missing_items if item_id not in full_acceptance_blockers
    )
    ok = (
        all(item["validation_state"] in {"passed", "expected_blocked", "skipped_by_scope"} for item in matrix)
        and all(_matrix_item_audit_ok(item) for item in matrix)
        and all(_check_ok(value) for value in checks.values())
    )
    phase1_minimum_battle_slice = ok and not minimum_slice_blockers
    phase1_full_acceptance = ok and not full_acceptance_blockers
    summary = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "p1_9_done_eligible": phase1_minimum_battle_slice,
        "phase1_repair_substrate_accepted": ok,
        "phase1_minimum_battle_slice": phase1_minimum_battle_slice,
        "phase1_minimum_battle_slice_blocked_by": minimum_slice_blockers,
        "phase1_full_acceptance": phase1_full_acceptance,
        "phase1_full_acceptance_blocked_by": full_acceptance_blockers,
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_ir_predicates",
                "fixed_character_or_monster_name_used_for_main_samples": False,
                "fixed_action_id_stage_id_or_file_hash_used_for_main_samples": False,
                "avatar_action_id": action.action_id,
                "avatar_action_level": action.level,
                "enemy_ref": enemy_ref,
                "status_effect_id": status_effect.effect_id,
                "summon_intent_id": summon_intent.summon_intent_id,
                "wave_definition_id": wave_definition.wave_definition_id,
            },
            "counts": {
                "entities": len(ir.entities),
                "action_definitions": len(ir.action_definitions),
                "effects": len(ir.effects),
                "wave_definitions": len(ir.wave_definitions),
                "summon_monster_intents": len(ir.summon_monster_intents),
                "target_expressions": len(ir.target_expressions),
            },
        },
        "matrix_counts": counts,
        "source_gap_matrix_counts": source_gap_counts,
        "repair_acceptance_taxonomy": {
            "executable": "real IR source exists and runtime mutation/settlement/replay/source audit pass",
            "boundary_only": "guarded blocked/process-only path is validated, but this is not a completed executable mechanism",
            "source_absent_not_required": "current database has no required executable source for this submechanism; no synthetic positive case is allowed",
            "implementation_missing": "the phase objective still lacks lowering/admission/runtime support and blocks the P1 minimum battle slice",
        },
        "checks": checks,
        "direct_regression_checks": {
            "lifecycle": direct_cases["lifecycle"]["checks"],
            "servant_setup": servant_case["setup_checks"],
            "servant_action": servant_case["action_checks"],
            "status": direct_cases["status_regression"]["checks"],
            "status_cases": {
                key: value.get("checks", {})
                for key, value in direct_cases["status_regression"].get("cases", {}).items()
                if key in {"chance", "control", "stack_reduce", "break_status"} and isinstance(value, dict)
            },
            "break_status_evidence": direct_cases["status_regression"]
            .get("cases", {})
            .get("break_status", {}),
            "queue": direct_cases["queue_regression"]["checks"],
            "queue_cases": {
                key: value.get("checks", {})
                for key, value in direct_cases["queue_regression"].get("cases", {}).items()
                if key in {"mandatory_insert_action", "insert_ability", "selectable_ultimate", "actor_target_lifecycle"}
                and isinstance(value, dict)
            },
            "queue_case_evidence": {
                "actor_target_lifecycle": {
                    key: direct_cases["queue_regression"]
                    .get("cases", {})
                    .get("actor_target_lifecycle", {})
                    .get(key, "")
                    for key in ("actor_terminal_reason", "target_terminal_reason")
                }
            },
            "target": target_case["checks"],
        },
        "resource_policy": {
            "single_tbgd_lowering": True,
            "default_high_io_scripts_run": False,
            "large_artifacts_written": False,
            "write_large_artifacts_requested": write_large_artifacts,
            "include_direct_regression_summaries": include_direct_regression_summaries,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = _validation_inventory(package_root)
    write_json(output_dir / "phase1_system_matrix_p1_9.json", {"items": matrix, "counts": counts})
    write_json(output_dir / "phase1_transition_audit_samples_p1_9.json", transition_samples)
    write_json(output_dir / "phase1_source_gap_matrix_p1_9.json", {"items": source_gap_matrix, "counts": source_gap_counts})
    write_json(output_dir / "phase1_static_boundary_p1_9.json", static_boundary)
    write_json(output_dir / "phase1_validation_inventory_p1_9.json", inventory)
    write_json(output_dir / "validation_summary_p1_9_phase1_aggregate.json", summary)
    resource_budget = _rewrite_resource_budget(output_dir, summary, write_large_artifacts=write_large_artifacts)
    summary["resource_budget"] = resource_budget
    write_json(output_dir / "validation_summary_p1_9_phase1_aggregate.json", summary)
    return summary


def _aggregate_scenario_data(
    rules: RuleBook,
    action: Any,
    enemy_ref: str,
    status_effect_id: str,
    summon_intent_id: str,
    wave_definition_id: str,
) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["scenario_id"] = "p1_9_phase1_aggregate_validation"
    data["version"] = VALIDATION_VERSION
    data["skill_points"] = 2
    data["max_skill_points"] = 5
    data["rng_state"] = "seed:p1_9"
    data["units"][0]["panel"]["hp_ratio"] = 0.75
    data["units"][0]["panel"].pop("hp", None)
    data["units"][0]["panel"]["energy_ratio"] = 1.0
    data["units"][0]["panel"].pop("energy", None)
    data["route"][0]["metadata"] = {
        "label": "p1_9_aggregate_route",
        "reset_actor_av": True,
        "rng_choices": {"p1_9:route_choice": "right"},
    }
    data["battle_setup"] = {
        "resources": {"skill_points": 2, "max_skill_points": 5},
        "wave": {"kind": "wave_definition", "wave_definition_ref": wave_definition_id, "wave_index": 0},
        "initial_statuses": [
            {
                "target_id": "enemy:target",
                "source_id": "ally:actor",
                "caster_id": "ally:actor",
                "owner_id": "ally:actor",
                "param_entity_id": "ally:actor",
                "current_action_target_id": "enemy:target",
                "effect_ref": status_effect_id,
            }
        ],
        "initial_summons": [
            {"kind": "summoned_monster", "owner_id": "ally:actor", "summon_intent_ref": summon_intent_id}
        ],
        "timeline": {
            "mode": "explicit_action_values",
            "global_av": 9.0,
            "turn_owner_id": "ally:actor",
            "action_values": {"ally:actor": 0.0},
            "explicit_overrides": ["ally:actor"],
        },
        "rng": {
            "rng_state": "seed:p1_9",
            "rng_mode": "explicit_ledger",
            "rng_choices": {"p1_9:setup_choice": "right"},
        },
        "objective": {
            "objective_id": "p1_9_keep_actor_alive",
            "kind": "survive",
            "payload": {"unit_id": "ally:actor"},
        },
        "metadata": {"validation": VALIDATION_VERSION},
    }
    return data


def _direct_cases(hsr_root: Path, rules: RuleBook) -> dict[str, Any]:
    return {
        "lifecycle": _json_safe(_damage_defeat_case()),
        "status_regression": _status_regression_cases(rules),
        "queue_regression": _queue_regression_cases(hsr_root, rules),
        "queue_scope": _json_safe(_current_queue_scope(rules.ir)),
        "queue_source": _json_safe(_queue_source_matrix(rules.ir, rules)),
        "rng_helper": _json_safe(_rng_helper_cases()),
        "target_random": _json_safe(_target_random_cases()),
        "rng_surface": _json_safe(_surface_matrix()),
        "target_sort": _json_safe(_sort_cases(rules)),
        "target_fetch": _json_safe(_fetch_cases(rules)),
    }


def _status_regression_cases(rules: RuleBook) -> dict[str, Any]:
    stack_case = _stack_cap_case(rules)
    dispel_case = _dispel_case(rules)
    cases = {
        "stack_cap": _compact_case(stack_case),
        "refresh": _compact_case(_refresh_case(rules)),
        "stack_only_refresh": _compact_case(_stack_only_refresh_case(rules)),
        "chance": _compact_case(_chance_cases(rules)),
        "control": _compact_case(_control_gate_case(rules, stack_case["status_detail"])),
        "duration_owner": _compact_case(_duration_owner_case(rules)),
        "expire_remove": _compact_case(_expire_remove_case(rules)),
        "dot_lifecycle": _compact_case(_dot_lifecycle_case(rules.ir, rules)),
        "dispel": _compact_case(dispel_case),
        "random_dispel": _compact_case(_random_dispel_replay_case(rules, dispel_case)),
        "stack_reduce": _compact_case(_stack_reduce_case(rules)),
        "break_status": _compact_case(_break_status_runtime_case(rules)),
    }
    checks = {key: _case_ok(value) for key, value in cases.items()}
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "cases": cases,
    }


def _break_status_runtime_case(rules: RuleBook) -> dict[str, Any]:
    case = _select_break_case(rules.ir, rules)
    emission = case["emission"]
    state = _status_base_state()
    target = state.units["enemy:target"]
    target = replace(target, toughness=0.0, max_toughness=max(target.max_toughness, 100.0))
    state = replace(state, units={**state.units, target.unit_id: target})
    packet = ToughnessPacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        toughness_emission_id=emission.toughness_emission_id,
        source_task_id=emission.source_task_id,
        hit_profile_id=emission.hit_profile_id,
        element_type=emission.element_type,
        amount=None,
        amount_expr=emission.toughness_amount_expr,
        target_group=emission.target_group,
        coverage_status="executable",
        source_trace=emission.source.to_json(),
        metadata={"primary_action_target_id": "enemy:target"},
    )
    result = BreakSystem(rules, EffectRegistry(StatusSystem(rules))).enter_break(state, packet)
    transition = _status_transition(
        state,
        _LifecycleResultAdapter(result),
        f"validation:real_break:{case['action'].action_id}",
    )
    transition_json = transition.to_json()
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(state, result.mutations, result.after_state.snapshot().to_json())
    traceability = SettlementTraceabilityValidator().validate(
        transition.transaction.settlement,
        transition.transaction.mutations,
    )
    transition_checks = _break_transition_checks(transition_json)
    status_checks = _break_status_checks(case["break_status_emissions"], transition_json)
    typed_targets: list[dict[str, Any]] = []
    for emission in case["break_status_emissions"]:
        if emission.coverage_status != "executable":
            continue
        effect = rules.effect(emission.effect_id)
        standard = effect.payload.get("standard", {}) if effect is not None else {}
        expression_id = standard.get("target_expression_id") if isinstance(standard, dict) else None
        expression = rules.target_expression(expression_id) if isinstance(expression_id, str) else None
        typed_targets.append(
            {
                "break_status_emission_id": emission.break_status_emission_id,
                "effect_id": emission.effect_id,
                "target_expression_id": expression_id or "",
                "target_alias": expression.alias if expression is not None else "",
                "coverage_status": expression.coverage_status if expression is not None else "missing",
                "typed_node_present": expression is not None and expression.node is not None,
            }
        )
    checks = {
        "real_break_execution_ok": result.ok,
        "real_break_after_state_matches_mutations": transition.after.to_json() == result.after_state.snapshot().to_json(),
        "real_break_source_audit_ok": source_audit.ok,
        "real_break_replay_ok": replay.ok,
        "real_break_settlement_traceability_ok": traceability.ok,
        "real_break_transition_ok": transition_checks.get("ok") is True,
        "real_break_status_mutation_ok": status_checks.get("ok") is True,
        "executable_break_targets_present": bool(typed_targets),
        "executable_break_targets_typed": bool(typed_targets)
        and all(
            item["target_expression_id"]
            and item["coverage_status"] == "executable"
            and item["typed_node_present"] is True
            for item in typed_targets
        ),
        "param_entity_target_preserved": any(item["target_alias"] == "ParamEntity" for item in typed_targets),
    }
    return {
        "checks": {"ok": all(checks.values()), "checks": checks},
        "execution_checks": {
            "result_ok": result.ok,
            "errors": list(result.errors),
            "mutation_count": len(result.mutations),
            "record_count": len(result.records),
            "source_audit": source_audit.to_json(),
            "replay": replay.to_json(),
            "settlement_traceability": traceability.to_json(),
        },
        "transition_checks": transition_checks,
        "status_checks": status_checks,
        "typed_targets": typed_targets,
        "selected_action": {
            "action_id": case["action"].action_id,
            "action_level": case["action"].level,
            "element_type": case["emission"].element_type,
        },
    }


def _queue_regression_cases(hsr_root: Path, rules: RuleBook) -> dict[str, Any]:
    counter_case = _counter_case(hsr_root, rules)
    cases = {
        "mandatory_insert_action": _compact_case(_mandatory_insert_action_case(rules)),
        "insert_ability": _compact_case(_insert_ability_case(rules)),
        "selectable_ultimate": _compact_case(_selectable_ultimate_case(rules)),
        "extra_turn": _compact_case(_extra_turn_case(rules.ir, rules)),
        "counter_route": _compact_case(counter_case),
        "family_gaps": _compact_case(
            _queue_family_source_gaps(
                rules.ir,
                counter_executable=counter_case.get("runtime_executable") is True,
            )
        ),
        "actor_target_lifecycle": _compact_case(_actor_target_lifecycle_case(rules)),
        "conditional_queue": _compact_case(_conditional_queue_case(rules.ir, rules)),
        "source_contract": _compact_case(_queue_source_contract_case(rules.ir)),
        "unknown_family_blocked": _compact_case(_unknown_family_blocked_case(rules.ir)),
    }
    required = (
        "mandatory_insert_action",
        "insert_ability",
        "selectable_ultimate",
        "counter_route",
        "actor_target_lifecycle",
        "conditional_queue",
        "source_contract",
        "unknown_family_blocked",
    )
    checks = {key: _case_ok(cases[key]) for key in required}
    checks["extra_turn_classified"] = _case_ok(cases["extra_turn"])
    checks["family_gaps_classified"] = _case_ok(cases["family_gaps"])
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "cases": cases,
    }


def _direct_status_transition_case(rules: RuleBook, action: Any, enemy_ref: str, effect: Any) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["scenario_id"] = "p1_9_direct_status_transition"
    data["version"] = VALIDATION_VERSION
    build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    state = build.state
    target_resolution = TargetResolution(
        requested=("enemy:target",),
        legal=("enemy:target",),
        selected=("enemy:target",),
        reason="p1_9_direct_status_transition",
        source="status_system",
        metadata={"effect_id": effect.effect_id},
    )
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="p1_9:direct_status_transition",
        owner_id="ally:actor",
        param_entity_id="ally:actor",
        current_action_target_id="enemy:target",
        target_resolution=target_resolution,
        event_payload={
            "rng_mode": "explicit_ledger",
            "rng_choices": {"p1_9:direct_status_choice": "success"},
        },
    )
    after_state = MutationReducer().apply_all(state, result.mutations)
    command = ActionCommand(
        actor_id="ally:actor",
        action_id="p1_9:direct_status_transition",
        action_level=1,
        target_ids=("enemy:target",),
        source="manual",
        metadata={
            "validation": VALIDATION_VERSION,
            "case": "direct_status_transition",
            "effect_id": effect.effect_id,
        },
    )
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(
                action_id=command.action_id,
                actor_id=command.actor_id,
                target_ids=command.target_ids,
                records=tuple(result.records),
            ),
        ),
        after=after_state.snapshot(),
        target_resolution=target_resolution,
        rng_events=result.rng_events,
        coverage={
            "case_kind": "direct_status_transition",
            "effect_id": effect.effect_id,
            "status_ok": result.ok,
            "unsupported": list(result.unsupported),
        },
    )
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after_state.snapshot().to_json())
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    settlement_traceability = SettlementTraceabilityValidator().validate(
        transition.transaction.settlement,
        transition.transaction.mutations,
    )
    checks = {
        "status_application_ok": result.ok,
        "mutation_positive": bool(result.mutations),
        "settlement_record_positive": bool(result.records),
        "contract_ok": contract.ok,
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "settlement_traceability_ok": settlement_traceability.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "transition": transition,
        "transition_summary": _transition_summary(
            transition,
            replay={"ok": replay.ok, "errors": list(replay.errors)},
            source_audit=source_audit.to_json(),
            settlement_traceability=settlement_traceability.to_json(),
            audit_scope="direct_status_transition",
        ),
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": source_audit.to_json(),
        "settlement_traceability": settlement_traceability.to_json(),
        "contract": contract.to_json(),
    }


def _aggregate_setup_case(build: Any, selected_status_case: dict[str, Any], status_effect_id: str, summon_intent_id: str) -> dict[str, Any]:
    status_mutations = [
        mutation
        for mutation in build.setup_mutations
        if mutation.source == "status_system" or mutation.metadata.get("effect_id") == status_effect_id
    ]
    summon_mutations = [
        mutation
        for mutation in build.setup_mutations
        if mutation.metadata.get("lifecycle_operation") == "unit_spawn"
    ]
    setup_records = list(build.setup_records)
    status_checks = {
        "source_backed_status_mutation": bool(status_mutations),
        "selected_status_has_source_trace": bool(selected_status_case.get("status_detail", {}).get("source_trace")),
        "status_mutations_have_source_trace": bool(status_mutations)
        and all(_mutation_has_source_trace(mutation) for mutation in status_mutations),
        "setup_record_present": any(
            record.get("record_type") == "setup_initial_status" and record.get("effect_ref") == status_effect_id
            for record in setup_records
        ),
    }
    status_checks["ok"] = all(value for key, value in status_checks.items() if key != "ok")
    summon_checks = {
        "source_backed_summon_spawn": bool(summon_mutations),
        "summon_record_present": any(
            record.get("record_type") == "setup_initial_summon"
            and record.get("summon_intent_ref") == summon_intent_id
            and record.get("status") == "applied"
            for record in setup_records
        ),
        "spawned_unit_present": any(unit.flags.get("summon_kind") == "summoned_monster" for unit in build.state.units.values()),
        "spawn_source_trace_present": all(
            bool(mutation.metadata.get("source_trace")) for mutation in summon_mutations
        ),
    }
    summon_checks["ok"] = all(value for key, value in summon_checks.items() if key != "ok")
    checks = {
        "state_units_present": bool(build.state.units),
        "route_commands_present": bool(build.commands),
        "setup_records_present": bool(build.setup_records),
        "resources_applied": build.state.skill_points == 2 and build.state.max_skill_points == 5,
        "timeline_applied": build.state.global_flags.get("global_av") == 9.0,
        "rng_setup_recorded": build.state.rng_state == "seed:p1_9",
        "objective_metadata_present": isinstance(build.state.global_flags.get("objective"), dict),
        "status_ok": status_checks["ok"],
        "summon_ok": summon_checks["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "status": {
            "ok": status_checks["ok"],
            "mutation_count": len(status_mutations),
            "source_trace_count": _mutation_source_trace_count(status_mutations),
        },
        "summon": {
            "ok": summon_checks["ok"],
            "mutation_count": len(summon_mutations),
            "source_trace_count": _mutation_source_trace_count(summon_mutations),
        },
        "setup_record_count": len(build.setup_records),
        "blocked_setup_count": len(build.blocked_setup),
    }


def _aggregate_action_boundary_case(rules: RuleBook, state: BattleState, commands: tuple[Any, ...]) -> dict[str, Any]:
    before = _snapshot_hash(state)
    view = ActionAvailabilitySystem(rules).view(state)
    after = _snapshot_hash(state)
    command = commands[0] if commands else None
    notes = []
    if view.mode != "external_selectable":
        notes.append(f"availability_mode={view.mode}")
    checks = {
        "route_command_available": command is not None and command.source == "manual",
        "availability_query_state_unchanged": before == after,
        "enemy_ai_not_selected_by_core": all(choice.command_template.get("source") != "ai" for choice in view.choices),
        "ordinary_and_queue_not_mixed": view.queue is None or view.ordinary_input_blocked is True,
        "view_json_serializable": _json_roundtrips(view.to_json()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "view": view.to_json(), "notes": notes}


def _aggregate_wave_case(rules: RuleBook, state: BattleState, wave_definition_id: str) -> dict[str, Any]:
    runtime = state.global_flags.get("wave_runtime")
    definition = rules.wave_definition(wave_definition_id)
    current_ids = tuple(runtime.get("current_wave_unit_ids", ()) if isinstance(runtime, dict) else ())
    next_ids = {
        _wave_unit_id(definition.stage_id if definition is not None else "", entry)
        for entry in rules.wave_entries_for_wave(wave_definition_id, 1)
        if entry.coverage_status == "executable"
    }
    checks = {
        "runtime_present": isinstance(runtime, dict),
        "current_wave_spawned": bool(current_ids) and all(unit_id in state.units for unit_id in current_ids),
        "next_wave_absent": bool(next_ids) and all(unit_id not in state.units for unit_id in next_ids),
        "source_trace_present": isinstance(runtime, dict) and isinstance(runtime.get("source_trace"), dict),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "runtime": runtime if isinstance(runtime, dict) else {},
        "source_trace": runtime.get("source_trace") if isinstance(runtime, dict) else {},
    }


def _aggregate_target_case(state: BattleState, transition: BattleTransition) -> dict[str, Any]:
    system = TargetSystem()
    policy = TargetPolicy(target_relation="enemy")
    explicit = system.resolve_explicit_targets(state, "ally:actor", ("enemy:target",), policy=policy)
    invalid = system.resolve_explicit_targets(state, "ally:actor", ("enemy:missing",), policy=policy)
    checks = {
        "explicit_target_ok": explicit.ok and explicit.resolution.selected == ("enemy:target",),
        "invalid_target_blocked": not invalid.ok,
        "invalid_target_no_rng": not invalid.rng_events,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "transition_target_resolution": transition.target_resolution.to_json(),
        "explicit": _targeting_result_json(explicit),
        "invalid": _targeting_result_json(invalid),
    }


def _servant_initial_summon_case(rules: RuleBook, enemy_ref: str) -> dict[str, Any]:
    definition = _select_executable_servant_definition(rules)
    owner_entity_ref = _select_servant_owner_entity_ref(definition)
    action = _select_avatar_action_for_entity(rules, owner_entity_ref)
    data = _base_scenario_data_for_avatar(rules, action, owner_entity_ref, enemy_ref)
    data["scenario_id"] = "p1_9_servant_initial_setup"
    data["battle_setup"] = {
        "initial_summons": [
            {
                "kind": "servant",
                "owner_id": "ally:actor",
                "summon_intent_ref": definition.servant_definition_id,
            }
        ]
    }
    build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    servant_units = tuple(
        unit_id for unit_id, unit in build.state.units.items() if unit.flags.get("summon_kind") == "servant"
    )
    runtime = build.state.global_flags.get("summon_runtime")
    availability = None
    if servant_units:
        availability = ActionAvailabilitySystem(rules).view(
            replace(
                build.state,
                global_flags={
                    **build.state.global_flags,
                    "turn_owner_id": servant_units[0],
                    "phase": "scenario",
                    "current_window": "idle",
                },
            )
        )
    caster_servant_expression = _select_global_target_expression(rules, "CasterServant")
    caster_servant_result = (
        TargetSystem().resolve_target_expression(build.state, caster_servant_expression, caster_id="ally:actor")
        if caster_servant_expression is not None
        else None
    )
    checks = {
        "definition_executable": definition.coverage_status == "executable",
        "setup_not_blocked": not build.blocked_setup,
        "servant_spawned": bool(servant_units),
        "setup_mutation_present": any(
            mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in build.setup_mutations
        ),
        "runtime_tracks_servant": isinstance(runtime, dict)
        and any(unit_id in runtime.get("servants", {}) for unit_id in servant_units),
        "action_availability_ok": availability is not None
        and availability.mode == "external_selectable"
        and any(choice.choice_kind == "summon_action" for choice in availability.choices),
        "caster_servant_target_expression_present": caster_servant_expression is not None,
        "caster_servant_target_resolves": caster_servant_result is not None
        and caster_servant_result.ok
        and any(unit_id in caster_servant_result.target_ids for unit_id in servant_units),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    setup_check_names = {
        "definition_executable",
        "setup_not_blocked",
        "servant_spawned",
        "setup_mutation_present",
        "runtime_tracks_servant",
        "caster_servant_target_expression_present",
        "caster_servant_target_resolves",
    }
    setup_checks = {key: value for key, value in checks.items() if key in setup_check_names}
    setup_checks["ok"] = all(setup_checks.values())
    action_checks = {"action_availability_ok": checks["action_availability_ok"]}
    action_checks["ok"] = all(action_checks.values())
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "setup_checks": {"ok": setup_checks["ok"], "checks": setup_checks},
        "action_checks": {"ok": action_checks["ok"], "checks": action_checks},
        "servant_definition_id": definition.servant_definition_id,
        "servant_ref": definition.servant_ref,
        "servant_unit_ids": list(servant_units),
        "setup_mutation_count": len(build.setup_mutations),
        "source_trace_count": len(build.source_traces),
        "blocked_setup": list(build.blocked_setup),
        "setup_records": list(build.setup_records),
        "availability": availability.to_json() if availability is not None else {},
        "caster_servant_expression": caster_servant_expression.to_json() if caster_servant_expression is not None else {},
        "caster_servant_result": caster_servant_result.to_json() if caster_servant_result is not None else {},
    }


def _select_global_target_expression(rules: RuleBook, alias: str):
    for expression in sorted(rules.target_expressions(), key=lambda item: item.target_expression_id):
        if expression.coverage_status != "executable":
            continue
        payload = expression.payload if isinstance(expression.payload, dict) else {}
        field_name = str(payload.get("field_name") or "")
        if expression.alias == alias or field_name == f"AliasDict.{alias}":
            return expression
    return None


def _blocked_initial_summon_case(rules: RuleBook, action: Any, enemy_ref: str, kind: str) -> dict[str, Any]:
    data = _base_scenario_data(rules, action, enemy_ref)
    data["scenario_id"] = f"p1_9_blocked_{kind}"
    data["version"] = VALIDATION_VERSION
    data["battle_setup"] = {"initial_summons": [{"kind": kind, "owner_id": "ally:actor"}]}
    build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    expected_reason = {
        "battle_unit_summon": "battle_unit_summon_initial_setup_boundary_only",
    }.get(kind, f"{kind}_initial_setup_blocked")
    checks = {
        "blocked_record_present": any(record.get("blocked_reason") == expected_reason for record in build.blocked_setup),
        "no_setup_mutation": not build.setup_mutations,
        "state_unit_count_unchanged": len(build.state.units) == 2,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "kind": kind,
        "blocked_setup": list(build.blocked_setup),
        "setup_mutation_count": len(build.setup_mutations),
    }


def _blocked_status_case(rules: RuleBook, action: Any, enemy_ref: str) -> dict[str, Any]:
    blocked_add = next(
        (
            item
            for item in rules.ir.effects
            if item.opcode == "AddModifier" and EffectRegistry(StatusSystem(rules)).coverage(item) != "executable"
        ),
        None,
    )
    if blocked_add is None:
        return {
            "checks": {"ok": True, "checks": {"blocked_add_modifier_source_gap_recorded": True}},
            "effect_id": "",
            "blocked_setup": [],
            "setup_mutation_count": 0,
        }
    data = _base_scenario_data(rules, action, enemy_ref)
    data["scenario_id"] = "p1_9_blocked_initial_status"
    data["version"] = VALIDATION_VERSION
    data["battle_setup"] = {
        "initial_statuses": [
            {
                "target_id": "enemy:target",
                "source_id": "ally:actor",
                "caster_id": "ally:actor",
                "owner_id": "ally:actor",
                "param_entity_id": "ally:actor",
                "current_action_target_id": "enemy:target",
                "effect_ref": blocked_add.effect_id,
            }
        ]
    }
    build = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    checks = {
        "blocked_record_present": any(record.get("status") == "blocked" for record in build.blocked_setup),
        "no_setup_mutations": not build.setup_mutations,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_id": blocked_add.effect_id,
        "blocked_setup": list(build.blocked_setup),
        "setup_mutation_count": len(build.setup_mutations),
    }


def _source_gap_matrix(
    rules: RuleBook,
    *,
    direct_cases: dict[str, Any],
    servant_case: dict[str, Any],
    battle_unit_summon_blocked: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stack_counts = _stack_refresh_source_counts(rules)
    rows.append(
        _gap_row(
            "p1_4.stack_duration_refresh",
            "P1-4",
            "stack + duration refresh same AddModifier source",
            source_state="executable"
            if stack_counts.get("stackable_refresh_prefilter", 0) > 0
            else "source_absent_not_required",
            gap_classification="executable"
            if stack_counts.get("stackable_refresh_prefilter", 0) > 0
            else "no_current_structured_source_for_combined_stack_duration_refresh",
            evidence_mode="structured_scan",
            reason=f"stack_refresh_source_counts={stack_counts}",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
        )
    )
    random_dispel_present = _has_random_dispel_source(rules)
    rows.append(
        _gap_row(
            "p1_4.random_dispel_order_random",
            "P1-4",
            "DispelStatus(Order=Random)",
            source_state="executable" if random_dispel_present else "source_absent_not_required",
            gap_classification="executable" if random_dispel_present else "current_database_has_no_random_dispel_source",
            evidence_mode="structured_scan",
            reason="Order=Random DispelStatus source present"
            if random_dispel_present
            else "no Order=Random DispelStatus source found; deterministic dispel is the current executable P1 requirement",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
        )
    )
    queue_family_rows = direct_cases["queue_regression"].get("cases", {}).get("family_gaps", {}).get("rows", [])
    for family in ("follow_up", "counter", "assistant"):
        row = next((item for item in queue_family_rows if item.get("window_family") == family), {})
        total_count = int(row.get("total_count") or 0) if isinstance(row, dict) else 0
        executable_count = int(row.get("executable_count") or 0) if isinstance(row, dict) else 0
        semantic_e2e_executable_count = (
            int(row.get("semantic_e2e_executable_count") or 0) if isinstance(row, dict) else 0
        )
        family_classification = str(row.get("classification") or "") if isinstance(row, dict) else ""
        if executable_count or semantic_e2e_executable_count or family_classification == "executable":
            source_state = "executable"
            classification = "executable"
        elif family_classification in {"lowering_gap", "admission_gap", "validation_gap"}:
            source_state = family_classification
            classification = f"{family}_queue_{family_classification}"
        elif total_count:
            source_state = "boundary_only"
            classification = f"{family}_queue_sources_not_executable_current_scope"
        else:
            source_state = "source_absent_not_required"
            classification = f"no_current_{family}_queue_window_source"
        rows.append(
            _gap_row(
                f"p1_5.{family}",
                "P1-5",
                f"{family} queue family",
                source_state=source_state,
                gap_classification=classification,
                evidence_mode="queue_family_source_matrix",
                reason=json.dumps(row, ensure_ascii=False, sort_keys=True) if row else "no current queue window sources",
                runtime_guarded_path=True,
                blocked_no_mutation=True,
                minimum_slice_blocker=False,
            )
        )
    sort_cases = direct_cases["target_sort"].get("cases", {})
    fetch_cases = direct_cases["target_fetch"].get("cases", {})
    for key, item_id, name in (
        ("formation_sort", "p1_6.formation_sort", "formation sort"),
        ("toughness_sort", "p1_6.toughness_sort", "toughness sort"),
    ):
        case = sort_cases.get(key, {})
        source_state = "executable"
        gap_classification = "executable"
        if _is_source_gap(case):
            source_state = "lowering_gap"
            gap_classification = "global_target_config_lowering_or_selection_gap"
        rows.append(
            _gap_row(
                item_id,
                "P1-6",
                name,
                source_state=source_state,
                gap_classification=gap_classification,
                evidence_mode="structured_scan",
                reason=str(case.get("reason") or "executable target expression found"),
                runtime_guarded_path=True,
                blocked_no_mutation=True,
            )
        )
    owner_case = fetch_cases.get("owner", {})
    owner_is_gap = _is_source_gap(owner_case)
    rows.append(
        _gap_row(
            "p1_3.servant_action_graph",
            "P1-3",
            "servant action selected graph",
            source_state="executable" if servant_case["action_checks"]["ok"] else "implementation_missing",
            gap_classification="executable"
            if servant_case["action_checks"]["ok"]
            else "servant_selected_action_graph_incomplete",
            evidence_mode="servant_action_availability",
            reason="servant action is externally selectable"
            if servant_case["action_checks"]["ok"]
            else "servant is spawned and targetable, but its selected action graph contains unimplemented semantic nodes",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
            minimum_slice_blocker=False,
        )
    )
    rows.append(
        _gap_row(
            "p1_6.owner_fetch",
            "P1-6",
            "TargetFetchModifierOwner/TargetFetchOwner",
            source_state="lowering_gap" if owner_is_gap else "executable",
            gap_classification="global_target_config_lowering_or_selection_gap" if owner_is_gap else "executable",
            evidence_mode="structured_scan",
            reason=str(owner_case.get("reason") or "executable owner fetch source found"),
            runtime_guarded_path=True,
            blocked_no_mutation=True,
        )
    )
    rows.append(
        _gap_row(
            "p1_6.servant_target",
            "P1-6",
            "servant target registry",
            source_state="executable" if servant_case["checks"]["checks"].get("caster_servant_target_resolves") else "implementation_missing",
            gap_classification="executable"
            if servant_case["checks"]["checks"].get("caster_servant_target_resolves")
            else "servant_target_runtime_registry_admission_gap",
            evidence_mode="servant_runtime_positive_case",
            reason="CasterServant target expression resolved through summon_runtime.servants"
            if servant_case["checks"]["checks"].get("caster_servant_target_resolves")
            else "servant target runtime registry did not resolve executable CasterServant expression",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
        )
    )
    rng_surface_rows = direct_cases["rng_surface"].get("rows", [])
    random_source_gaps = [
        row for row in rng_surface_rows if isinstance(row, dict) and "source_gap_blocked" in str(row.get("status") or "")
    ]
    rows.append(
        _gap_row(
            "p1_7.random_source_paths",
            "P1-7",
            "RNG surfaces without current real source admission",
            source_state="source_absent_not_required" if random_source_gaps else "executable",
            gap_classification="current_database_random_surface_not_required" if random_source_gaps else "executable",
            evidence_mode="structured_validation_matrix",
            reason=f"source_gap_surface_count={len(random_source_gaps)}; P1-7 keeps no-synthetic-random boundary and does not require random dispel as current executable source",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
        )
    )
    rows.append(
        _gap_row(
            "p1_8.servant_initial_setup",
            "P1-8",
            "servant initial setup",
            source_state="executable" if servant_case["setup_checks"]["ok"] else "implementation_missing",
            gap_classification="executable" if servant_case["setup_checks"]["ok"] else "servant_definition_runtime_setup_admission_gap",
            evidence_mode="servant_runtime_positive_case",
            reason="servant setup spawned a unit from executable ServantDefinitionIR"
            if servant_case["setup_checks"]["ok"]
            else "servant setup positive case failed",
            runtime_guarded_path=True,
            blocked_no_mutation=True,
            blocked_records=servant_case["blocked_setup"],
        )
    )
    rows.append(
        _gap_row(
            "p1_8.battle_unit_summon_initial_setup",
            "P1-8",
            "battle_unit_summon initial setup",
            source_state="boundary_only",
            gap_classification="summon_unit_battle_admission_gap",
            evidence_mode="runtime_blocked_case",
            reason="SummonUnitData is a catalog/definition source, not an automatic battle spawn trigger; current setup boundary blocks it without mutation",
            runtime_guarded_path=True,
            blocked_no_mutation=battle_unit_summon_blocked["checks"]["ok"],
            blocked_records=battle_unit_summon_blocked["blocked_setup"],
        )
    )
    return rows


def _gap_row(
    item_id: str,
    phase_item: str,
    name: str,
    *,
    source_state: str,
    gap_classification: str,
    evidence_mode: str,
    reason: str,
    runtime_guarded_path: bool,
    blocked_no_mutation: bool,
    blocked_records: list[dict[str, Any]] | None = None,
    minimum_slice_blocker: bool | None = None,
) -> dict[str, Any]:
    if source_state not in SOURCE_STATES:
        raise ValueError(f"invalid source_state: {source_state}")
    return {
        "item_id": item_id,
        "phase_item": phase_item,
        "name": name,
        "source_state": source_state,
        "gap_classification": gap_classification,
        "validation_state": "passed"
        if source_state in {"executable", "source_absent_not_required"}
        else "expected_blocked",
        "evidence_mode": evidence_mode,
        "reason": reason,
        "runtime_guarded_path": runtime_guarded_path,
        "blocked_no_mutation": blocked_no_mutation,
        "phase1_minimum_battle_slice_blocker": (
            source_state in {"lowering_gap", "admission_gap", "validation_gap", "implementation_missing"}
            if minimum_slice_blocker is None
            else minimum_slice_blocker
        ),
        "phase1_full_acceptance_blocker": source_state
        in {"lowering_gap", "admission_gap", "validation_gap", "implementation_missing"},
        "blocked_records": blocked_records or [],
    }


def _transition_samples(
    *,
    build: Any,
    transition: BattleTransition,
    contract: dict[str, Any],
    replay: dict[str, Any],
    source_audit: dict[str, Any],
    settlement_traceability: dict[str, Any],
    servant_case: dict[str, Any],
    blocked_status: dict[str, Any],
    target_case: dict[str, Any],
    direct_cases: dict[str, Any],
    status_transition_case: dict[str, Any],
) -> dict[str, Any]:
    mutation_ids = [mutation.stable_id() for mutation in transition.transaction.mutations[:8]]
    settlement = transition.transaction.settlement
    records = list(settlement.records) if settlement is not None else []
    setup_mutations = [mutation.to_json() for mutation in build.setup_mutations[:8]]
    route_audit_scope = "route_mutation_transition" if transition.transaction.mutations else "route_contract_only_no_mutation"
    route_summary = _transition_summary(
        transition,
        replay=replay,
        source_audit=source_audit,
        settlement_traceability=settlement_traceability,
        audit_scope=route_audit_scope,
    )
    status_transition = status_transition_case["transition"]
    return {
        "setup_mutation_sample": {
            "mutation_count": len(build.setup_mutations),
            "sample_mutations": setup_mutations,
            "setup_record_count": len(build.setup_records),
            "blocked_setup_count": len(build.blocked_setup),
        },
        "route_action_transition_sample": {
            **route_summary,
            "transition_id": _transition_id(transition),
            "mutation_count": len(transition.transaction.mutations),
            "event_count": len(transition.transaction.events),
            "rng_event_count": len(transition.rng_events),
            "settlement_record_count": len(records),
            "blocked_record_count": sum(1 for record in records if record.get("process_only") is True),
            "replay_ok": replay["ok"],
            "source_audit_ok": source_audit["ok"],
            "contract_ok": contract["ok"],
            "settlement_traceability_ok": settlement_traceability["ok"],
            "sample_mutation_ids": mutation_ids,
            "sample_record_types": [str(record.get("record_type") or "") for record in records[:8]],
        },
        "core_mutation_audit_sample": status_transition_case["transition_summary"],
        "queue_window_sample": {
            "case_kind": "direct_regression_compact",
            "queue_scope_ok": direct_cases["queue_scope"]["checks"]["ok"],
            "queue_source_ok": direct_cases["queue_source"]["checks"]["ok"],
            "queue_regression_ok": direct_cases["queue_regression"]["checks"]["ok"],
            "queue_regression_checks": direct_cases["queue_regression"]["checks"]["checks"],
            "queue_family_rows": direct_cases["queue_regression"].get("cases", {}).get("family_gaps", {}).get("rows", []),
            "aggregate_trigger_window_count": len(transition.transaction.trigger_windows),
        },
        "status_lifecycle_sample": {
            "case_kind": "direct_regression_compact",
            "status_regression_ok": direct_cases["status_regression"]["checks"]["ok"],
            "status_regression_checks": direct_cases["status_regression"]["checks"]["checks"],
        },
        "blocked_sample": {
            "servant_initial_setup": servant_case,
            "blocked_status": blocked_status,
            "invalid_target": target_case["invalid"],
            "missing_rng_choice": direct_cases["rng_helper"]["missing"],
        },
        "replay_sample": {
            "audit_scope": "direct_status_transition",
            "before_hash": _snapshot_json_hash(status_transition.transaction.before.to_json()),
            "after_hash": _snapshot_json_hash(status_transition.after.to_json()),
            "mutation_ids": [mutation.stable_id() for mutation in status_transition.transaction.mutations[:8]],
            "replay": status_transition_case["replay"],
        },
        "source_audit_sample": {
            "audit_scope": "direct_status_transition",
            "source_audit": status_transition_case["source_audit"],
            "settlement_traceability": status_transition_case["settlement_traceability"],
            "sample_mutation_to_record": _sample_mutation_record_link(status_transition),
        },
    }


def _static_boundary_case(package_root: Path, output_dir: Path, write_large_artifacts: bool) -> dict[str, Any]:
    static = run_static_checks(package_root)
    scenario_scan = _scan_scenario_boundary(package_root)
    tool_scan = _scan_tool_artifact_policy(package_root)
    checks = {
        "runtime_static_checks": static.ok,
        "scenario_boundary": scenario_scan["ok"],
        "p1_9_large_artifacts_default_off": write_large_artifacts is False,
        "p1_9_tool_no_full_ir_write": tool_scan["ok"],
        "output_dir_outside_package_root": not _is_relative_to(output_dir.resolve(), package_root.resolve()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "runtime_static_checks": static.to_json(),
        "scenario_boundary": scenario_scan,
        "tool_artifact_policy": tool_scan,
    }


def _scan_scenario_boundary(package_root: Path) -> dict[str, Any]:
    banned = (
        "turnbasedgamedata-main",
        "TextMap",
        "model_pack_v3_0",
        "simulator_v7_7",
        "SimulatorRuntimeAdapter",
        "_legacy_effects",
        "action_ctx",
        "from ..tbgd",
    )
    violations: list[dict[str, Any]] = []
    for path in sorted((package_root / "scenarios").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token in banned:
                if token in line:
                    violations.append({"path": path.relative_to(package_root).as_posix(), "line": line_no, "token": token})
    return {"ok": not violations, "violations": violations}


def _scan_tool_artifact_policy(package_root: Path) -> dict[str, Any]:
    path = package_root / "tools" / "validate_p1_9_phase1_aggregate.py"
    text = path.read_text(encoding="utf-8")
    forbidden = ("ir.to_" + "json()", "coverage.to_" + "json()", "fidelity.to_" + "json()")
    violations = [
        {"path": path.relative_to(package_root).as_posix(), "token": token}
        for token in forbidden
        if token in text
    ]
    return {"ok": not violations, "violations": violations}


def _validation_inventory(package_root: Path) -> dict[str, Any]:
    scripts = []
    for index in range(0, 10):
        paths = sorted((package_root / "tools").glob(f"validate_p1_{index}*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            module_name = f"simulator_v8_clean_core.tools.{path.stem}"
            output_files = sorted(set(_write_json_targets(text)))
            scripts.append(
                {
                    "phase": f"P1-{index}",
                    "path": path.relative_to(package_root).as_posix(),
                    "module": module_name,
                    "has_run_validation": "def run_validation" in text,
                    "has_cli_main": "def main" in text,
                    "default_output_files": output_files,
                    "resource_risk": "high_io"
                    if any(
                        name in text
                        for name in (
                            "write_full_" + "ir",
                            "CanonicalIR.to_" + "json",
                            "coverage_" + "matrix",
                        )
                    )
                    else "lightweight",
                }
            )
    return {
        "phase1_validation_inventory": scripts,
        "p1_7_run_validation_unified": any(
            item["path"].endswith("validate_p1_7_rng_branch_system.py") and item["has_run_validation"] for item in scripts
        ),
        "default_high_io_scripts": [item for item in scripts if item["resource_risk"] == "high_io"],
    }


def _write_json_targets(text: str) -> list[str]:
    targets: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if "write_json(output_dir /" not in line and "_write_json(output_dir /" not in line:
            continue
        first = line.find('"')
        last = line.find('"', first + 1)
        if first >= 0 and last > first:
            targets.append(line[first + 1 : last])
    return targets


def _resource_budget(output_dir: Path, *, write_large_artifacts: bool) -> dict[str, Any]:
    files = []
    for path in sorted(output_dir.glob("*")):
        if path.is_file():
            files.append({"name": path.name, "bytes": path.stat().st_size})
    return {
        "ok": all(item["bytes"] < 2_000_000 for item in files),
        "large_artifacts_written": False,
        "write_large_artifacts_requested": write_large_artifacts,
        "output_file_count": len(files),
        "output_files": files,
        "default_outputs": list(SUMMARY_FILES),
        "policy": {
            "no_full_canonical_ir": True,
            "no_full_coverage_or_fidelity": True,
            "no_full_transition_dump": True,
            "single_tbgd_lowering": True,
        },
    }


def _rewrite_resource_budget(output_dir: Path, summary: dict[str, Any], *, write_large_artifacts: bool) -> dict[str, Any]:
    budget_path = output_dir / "phase1_resource_budget_p1_9.json"
    summary_path = output_dir / "validation_summary_p1_9_phase1_aggregate.json"
    budget = _resource_budget(output_dir, write_large_artifacts=write_large_artifacts)
    summary["resource_budget"] = budget
    write_json(budget_path, budget)
    write_json(summary_path, summary)
    budget = _resource_budget(output_dir, write_large_artifacts=write_large_artifacts)
    summary["resource_budget"] = budget
    write_json(budget_path, budget)
    return _resource_budget(output_dir, write_large_artifacts=write_large_artifacts)


def _blocked_no_mutation_check(
    servant_case: dict[str, Any],
    battle_unit_summon_blocked: dict[str, Any],
    blocked_status: dict[str, Any],
    direct_cases: dict[str, Any],
) -> dict[str, Any]:
    rng_missing = direct_cases["rng_helper"]["missing"]
    target_missing = direct_cases["target_random"]["missing"]
    checks = {
        "servant_initial_setup_executable_mutation_present": servant_case["setup_mutation_count"] > 0,
        "battle_unit_summon_blocked_no_mutation": battle_unit_summon_blocked["setup_mutation_count"] == 0,
        "blocked_status_no_mutation": blocked_status["setup_mutation_count"] == 0,
        "missing_rng_choice_blocked": (rng_missing.get("blocked_reason") or rng_missing.get("reason")) == "requires_rng_choice",
        "missing_target_random_choice_blocked": target_missing.get("blocked_reason") == "requires_rng_choice",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _item(
    item_id: str,
    phase_item: str,
    source_state: str,
    validation_state: str,
    *,
    positive_case_count: int = 0,
    negative_case_count: int = 0,
    mutation_count: int = 0,
    blocked_count: int = 0,
    source_trace_count: int = 0,
    replay_ok: bool = False,
    source_audit_ok: bool = False,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if source_state not in SOURCE_STATES:
        raise ValueError(f"invalid source_state: {source_state}")
    if validation_state not in VALIDATION_STATES:
        raise ValueError(f"invalid validation_state: {validation_state}")
    return {
        "item_id": item_id,
        "phase_item": phase_item,
        "source_state": source_state,
        "validation_state": validation_state,
        "positive_case_count": positive_case_count,
        "negative_case_count": negative_case_count,
        "mutation_count": mutation_count,
        "blocked_count": blocked_count,
        "source_trace_count": source_trace_count,
        "replay_ok": replay_ok,
        "source_audit_ok": source_audit_ok,
        "notes": notes or [],
    }


def _matrix_counts(matrix: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in VALIDATION_STATES}
    counts.update({state: 0 for state in SOURCE_STATES})
    for item in matrix:
        counts[str(item["validation_state"])] += 1
        counts[str(item["source_state"])] += 1
    return counts


def _matrix_item_audit_ok(item: dict[str, Any]) -> bool:
    if item["source_state"] == "executable" and item["validation_state"] == "passed":
        return item["replay_ok"] is True and item["source_audit_ok"] is True
    return True


def _source_gap_rows_ok(rows: list[dict[str, Any]], phase_item: str) -> bool:
    return all(row["blocked_no_mutation"] is True for row in rows if row["phase_item"] == phase_item)


def _case_ok(case: Any) -> bool:
    if not isinstance(case, dict):
        return False
    checks = case.get("checks")
    if isinstance(checks, dict):
        return checks.get("ok") is True
    return case.get("ok") is True


def _compact_case(case: Any) -> dict[str, Any]:
    data = case if isinstance(case, dict) else _json_safe(case)
    if not isinstance(data, dict):
        return {"checks": {"ok": False, "checks": {"case_is_dict": False}}}
    compact: dict[str, Any] = {}
    if isinstance(data.get("checks"), dict):
        compact["checks"] = _json_safe(data["checks"])
    elif "ok" in data:
        compact["checks"] = {"ok": data.get("ok") is True, "checks": {"ok": data.get("ok") is True}}
    for key in (
        "coverage_status",
        "classification",
        "reason",
        "blocked_reason",
        "matching_classification",
        "matching_blocked_reason",
        "actor_terminal_reason",
        "target_terminal_reason",
        "action_event_coverage_status",
        "unknown_count",
        "assistant_count",
        "predicate_task_count",
        "queue_child_predicate_count",
        "unsupported_predicate_queue_count",
        "same_tag_insert_precheck_intent_count",
        "executable_window_count",
        "rows",
        "selected_action",
        "rejected_candidate_count",
        "rejected_candidates",
        "execution_checks",
        "transition_checks",
        "status_checks",
        "typed_targets",
    ):
        if key in data:
            compact[key] = _json_safe(data[key])
    selected = data.get("selected")
    if isinstance(selected, dict):
        compact["selected"] = {
            key: selected.get(key)
            for key in (
                "queue_intent_id",
                "queue_resolution_id",
                "queue_window_id",
                "queue_kind",
                "window_family",
                "resolved_kind",
            )
            if key in selected
        }
    return compact


def _check_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("ok") is True


def _is_source_gap(case: Any) -> bool:
    return isinstance(case, dict) and case.get("coverage_status") == "source_gap_blocked"


def _target_resolution_ok(resolution: Any) -> bool:
    return bool(getattr(resolution, "selected", ())) and str(getattr(resolution, "reason", "")) not in {
        "not_resolved",
        "blocked",
    }


def _targeting_result_json(result: Any) -> dict[str, Any]:
    resolution = getattr(result, "resolution", None)
    return {
        "ok": bool(getattr(result, "ok", False)),
        "errors": list(getattr(result, "errors", ())),
        "rng_events": [event.to_json() for event in getattr(result, "rng_events", ())],
        "resolution": resolution.to_json() if resolution is not None else {},
    }


def _wave_unit_id(stage_id: str, entry: Any) -> str:
    return f"enemy:stage:{stage_id}:wave:{entry.wave_index}:pos:{entry.position}"


def _transition_id(transition: BattleTransition) -> str:
    payload = {
        "command": transition.transaction.command.action_id,
        "actor": transition.transaction.command.actor_id,
        "before": _snapshot_json_hash(transition.transaction.before.to_json()),
        "after": _snapshot_json_hash(transition.after.to_json()),
    }
    return "transition:p1_9:" + hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _transition_summary(
    transition: BattleTransition,
    *,
    replay: dict[str, Any],
    source_audit: dict[str, Any],
    settlement_traceability: dict[str, Any],
    audit_scope: str,
) -> dict[str, Any]:
    settlement = transition.transaction.settlement
    records = list(settlement.records) if settlement is not None else []
    mutations = list(transition.transaction.mutations)
    return {
        "audit_scope": audit_scope,
        "transition_id": _transition_id(transition),
        "mutation_count": len(mutations),
        "event_count": len(transition.transaction.events),
        "rng_event_count": len(transition.rng_events),
        "settlement_record_count": len(records),
        "source_audit_checked_mutations": source_audit.get("checked_mutations", 0),
        "source_audit_checked_records": source_audit.get("checked_records", 0),
        "replay_ok": replay.get("ok") is True,
        "source_audit_ok": source_audit.get("ok") is True,
        "settlement_traceability_ok": settlement_traceability.get("ok") is True,
        "sample_mutation_ids": [mutation.stable_id() for mutation in mutations[:8]],
        "sample_mutation_to_record": _sample_mutation_record_link(transition),
    }


def _sample_mutation_record_link(transition: BattleTransition) -> dict[str, Any]:
    settlement = transition.transaction.settlement
    records = list(settlement.records) if settlement is not None else []
    by_id = {
        str(record.get("mutation_id")): record
        for record in records
        if isinstance(record.get("mutation_id"), str)
    }
    for mutation in transition.transaction.mutations:
        record = by_id.get(mutation.stable_id())
        if record is not None:
            return {
                "mutation_id": mutation.stable_id(),
                "mutation_source": mutation.source,
                "record_type": record.get("record_type"),
                "record_source": record.get("source"),
                "trace_keys": sorted(record.get("trace", {}).keys()) if isinstance(record.get("trace"), dict) else [],
            }
    return {}


def _mutation_source_trace_count(mutations: list[Any]) -> int:
    return sum(1 for mutation in mutations if _mutation_has_source_trace(mutation))


def _mutation_has_source_trace(mutation: Any) -> bool:
    metadata = getattr(mutation, "metadata", {})
    if not isinstance(metadata, dict):
        return False
    if isinstance(metadata.get("source_trace"), dict):
        return True
    lifecycle_plan = metadata.get("lifecycle_plan")
    if isinstance(lifecycle_plan, dict) and isinstance(lifecycle_plan.get("source_trace"), dict):
        return True
    status_instance = metadata.get("status_instance")
    if isinstance(status_instance, dict) and isinstance(status_instance.get("source_trace"), dict):
        return True
    return False


def _snapshot_hash(state: BattleState) -> str:
    return _snapshot_json_hash(state.snapshot().to_json())


def _snapshot_json_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _json_roundtrips(payload: Any) -> bool:
    try:
        json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except TypeError:
        return False
    return True


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_json") and inspect.ismethod(value.to_json):
        return _json_safe(value.to_json())
    return value


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-9 phase1 aggregate acceptance.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--write-large-artifacts", action="store_true")
    parser.add_argument("--include-direct-regression-summaries", action="store_true")
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    summary = run_validation(
        package_root,
        tbgd_root,
        args.output_dir,
        write_large_artifacts=args.write_large_artifacts,
        include_direct_regression_summaries=args.include_direct_regression_summaries,
    )
    print(
        f"v8 {VALIDATION_VERSION} validation ok={summary['ok']} "
        f"phase1_repair_substrate_accepted={summary['phase1_repair_substrate_accepted']} "
        f"phase1_minimum_battle_slice={summary['phase1_minimum_battle_slice']}"
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
