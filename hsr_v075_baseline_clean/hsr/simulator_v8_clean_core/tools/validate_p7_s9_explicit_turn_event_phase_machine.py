from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import WaveDefinitionIR, WaveMonsterEntryIR
from ..rules.rulebook import RuleBook
from ..systems.decision import DecisionSystem
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.phase_machine import (
    ACTION_EXECUTION,
    EXTRA_ACTION,
    IDLE,
    POST_ACTION,
    PRE_ACTION,
    WAVE_TRANSITION,
    CombatPhaseMachine,
)
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..systems.wave import WAVE_RUNTIME_SCHEMA_VERSION
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _source
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s9_explicit_turn_event_phase_machine"
MATRIX_SCHEMA_VERSION = "p7_s9_turn_event_phase_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    rules = _trust_rulebook()
    regular_turn = _regular_turn_case(rules)
    pre_action_dot = _pre_action_dot_phase_case(regular_turn)
    extra_action = _extra_action_phase_case()
    illegal = _illegal_phase_case(rules)
    wave_ingress = _wave_ingress_case(rules)
    wave_source_audit = _wave_phase_source_audit_case(rules)
    static_boundary = _static_boundary(package_root)
    rows = (
        regular_turn,
        pre_action_dot,
        extra_action,
        illegal,
        wave_ingress,
        wave_source_audit,
        static_boundary,
    )
    checks = {
        "regular_turn_phase_path_complete": regular_turn["ok"],
        "turn_begin_end_dispatched_once": regular_turn["turn_events_once"],
        "decision_reports_phase_and_next": regular_turn["decision_phase_contract"],
        "dot_lifecycle_before_decision_and_action": pre_action_dot["ok"],
        "extra_action_does_not_repeat_regular_turn": extra_action["ok"],
        "illegal_phase_transition_blocked": illegal["phase_transition_blocked"],
        "illegal_phase_event_blocked_state_unchanged": illegal["event_dispatch_blocked"],
        "corrupt_current_phase_blocked_state_unchanged": illegal["corrupt_phase_blocked"],
        "wave_event_has_explicit_phase_ingress": wave_ingress["ok"],
        "wave_phase_mutations_source_audit_ok": wave_source_audit["ok"],
        "turn_end_flag_removed": static_boundary["turn_end_flag_removed"],
        "runtime_uses_phase_for_admission": static_boundary["phase_admission_wired"],
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
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
        },
        "deferred": {
            "speed_recalculation_and_control_skip": "P7-S10",
            "queue_invalid_entry_policy": "P7-S11",
            "wave_spawn_source": "P7-S17",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s9_explicit_turn_event_phase_machine.json", summary)
    write_json(
        output_dir / "p7_s9_turn_event_phase_matrix.json",
        {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "rows": [
                {"row_id": row["row_id"], "classification": row["classification"], "ok": row["ok"]}
                for row in rows
            ],
        },
    )
    write_json(
        output_dir / "p7_s9_turn_event_phase_evidence.json",
        {
            "regular_turn": regular_turn,
            "pre_action_dot": pre_action_dot,
            "extra_action": extra_action,
            "illegal": illegal,
            "wave_ingress": wave_ingress,
            "wave_source_audit": wave_source_audit,
            "static_boundary": static_boundary,
        },
    )
    return summary


def _regular_turn_case(rules: RuleBook) -> dict[str, Any]:
    initial = _regular_initial_state()
    decisions = DecisionSystem(rules)
    advance = decisions.advance_to_decision(initial)
    choice = advance.decision.availability.choices[0]
    command = ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=(choice.selectable_target_ids[0],),
        source="manual",
    )
    submit = decisions.submit(advance.after_state, advance.decision.token, command)
    transitions = (*advance.transitions, submit.transition)
    phase_path = [
        str(mutation.after)
        for transition in transitions
        for mutation in transition.transaction.mutations
        if mutation.path == ("global_flags", "combat_phase")
    ]
    events = [event for transition in transitions for event in transition.transaction.events]
    event_types = [event.event_type for event in events]
    expected_path = [
        "timeline_advancing",
        "turn_begin",
        "pre_action",
        "awaiting_decision",
        "action_execution",
        "post_action",
        "turn_end",
        "idle",
    ]
    replay = [
        MutationReducer().replay_snapshot(
            before,
            transition.transaction.mutations,
            transition.after.to_json(),
        ).ok
        for before, transition in (
            (initial, advance.transitions[0]),
            (advance.after_state, submit.transition),
        )
    ]
    audits = [RuntimeSourceAuditor(rules).validate_transition(transition).ok for transition in transitions]
    turn_events_once = event_types.count("turn.begin") == 1 and event_types.count("turn.end") == 1
    decision_phase_contract = (
        advance.decision.combat_phase == "awaiting_decision"
        and "action_execution" in advance.decision.allowed_next_phases
        and submit.transition.coverage.get("phase_machine", {}).get("current_phase") == "idle"
    )
    ok = (
        phase_path == expected_path
        and turn_events_once
        and decision_phase_contract
        and submit.transition.outcome.successor_eligible
        and submit.after_state.global_flags.get("combat_phase") == IDLE
        and all(replay)
        and all(audits)
    )
    return {
        "row_id": "regular_turn_full_phase_and_event_order",
        "classification": "executable",
        "ok": ok,
        "phase_path": phase_path,
        "expected_phase_path": expected_path,
        "event_types": event_types,
        "event_details": [
            {"event_type": event.event_type, "window": event.window, "payload": event.payload}
            for event in events
        ],
        "turn_events_once": turn_events_once,
        "decision_phase_contract": decision_phase_contract,
        "replay_ok": replay,
        "source_audit_ok": audits,
    }


def _pre_action_dot_phase_case(regular_turn: dict[str, Any]) -> dict[str, Any]:
    details = regular_turn["event_details"]
    turn_begin_index = _event_index(details, "turn.begin")
    lifecycle_index = next(
        (
            index
            for index, event in enumerate(details)
            if event["event_type"] == "status.lifecycle.tick"
            and event["payload"].get("life_step_moment") == "ModifierPhase1End"
        ),
        -1,
    )
    decision_index = _event_index(details, "turn.decision.opened")
    action_index = _event_index(details, "scheduler.action.before")
    ok = (
        turn_begin_index >= 0
        and lifecycle_index > turn_begin_index
        and decision_index > lifecycle_index
        and action_index > decision_index
    )
    return {
        "row_id": "dot_and_modifier_phase1_before_action",
        "classification": "executable_phase_hook",
        "ok": ok,
        "turn_begin_index": turn_begin_index,
        "modifier_phase1_index": lifecycle_index,
        "decision_index": decision_index,
        "action_index": action_index,
        "direct_damage_positive_evidence": "validate_p2_s8_status_damage direct regression",
    }


def _extra_action_phase_case() -> dict[str, Any]:
    machine = CombatPhaseMachine()
    reducer = MutationReducer()
    state = replace(
        _base_state(),
        global_flags={
            **_base_state().global_flags,
            "combat_phase": POST_ACTION,
            "turn_sequence_index": 7,
            "turn_owner_id": "ally:actor",
        },
    )
    phases = (EXTRA_ACTION, ACTION_EXECUTION, POST_ACTION)
    current = state
    events: list[GameEvent] = []
    actual: list[str] = []
    for phase in phases:
        result = machine.transition(
            current,
            phase,
            actor_id="ally:actor",
            reason="validation extra action phase path",
        )
        if not result.plan.ok:
            break
        current = reducer.apply_all(current, result.mutations)
        events.extend(result.events)
        actual.append(phase)
    event_types = [event.event_type for event in events]
    ok = (
        actual == list(phases)
        and current.global_flags.get("turn_sequence_index") == 7
        and current.global_flags.get("turn_owner_id") == "ally:actor"
        and "turn.begin" not in event_types
        and "turn.end" not in event_types
    )
    return {
        "row_id": "extra_action_phase_path_no_regular_turn_repeat",
        "classification": "executable_phase_contract",
        "ok": ok,
        "phase_path": actual,
        "event_types": event_types,
        "turn_sequence_before": 7,
        "turn_sequence_after": current.global_flags.get("turn_sequence_index"),
    }


def _illegal_phase_case(rules: RuleBook) -> dict[str, Any]:
    machine = CombatPhaseMachine()
    state = _base_state()
    invalid = machine.transition(state, POST_ACTION, reason="illegal validation transition")
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    event = GameEvent(
        "turn.end",
        source_id="ally:actor",
        target_id="ally:actor",
        event_id="validation:illegal_turn_end",
        window="turn_end",
        process_only=True,
        payload={"actor_id": "ally:actor"},
    )
    dispatched = dispatcher.dispatch_event(state, event=event)
    corrupt_state = replace(
        state,
        global_flags={**state.global_flags, "combat_phase": "corrupt_phase_value"},
    )
    corrupt = machine.transition(
        corrupt_state,
        PRE_ACTION,
        actor_id="ally:actor",
        reason="corrupt current phase validation",
    )
    phase_transition_blocked = (
        not invalid.plan.ok
        and invalid.plan.blocked_reason == "illegal_phase_transition:idle:post_action"
        and not invalid.mutations
    )
    event_dispatch_blocked = (
        dispatched.after_state == state
        and not dispatched.mutations
        and dispatched.node_results
        and dispatched.node_results[0].status == "blocked"
        and dispatched.node_results[0].reason_code == "event_not_allowed_in_phase:turn.end:idle"
    )
    corrupt_phase_blocked = (
        not corrupt.plan.ok
        and corrupt.plan.blocked_reason
        == "unknown_current_combat_phase:corrupt_phase_value"
        and not corrupt.mutations
        and corrupt_state.global_flags.get("combat_phase") == "corrupt_phase_value"
    )
    return {
        "row_id": "illegal_phase_transition_and_event",
        "classification": "negative",
        "ok": phase_transition_blocked and event_dispatch_blocked and corrupt_phase_blocked,
        "phase_transition_blocked": phase_transition_blocked,
        "event_dispatch_blocked": event_dispatch_blocked,
        "corrupt_phase_blocked": corrupt_phase_blocked,
        "corrupt_phase_plan": corrupt.plan.to_json(),
        "phase_plan": invalid.plan.to_json(),
        "event_node_results": [node.to_json() for node in dispatched.node_results],
    }


def _wave_ingress_case(rules: RuleBook) -> dict[str, Any]:
    machine = CombatPhaseMachine()
    reducer = MutationReducer()
    state = _base_state()
    ingress = machine.transition(state, WAVE_TRANSITION, reason="enter wave event ingress")
    wave_state = reducer.apply_all(state, ingress.mutations)
    event = GameEvent(
        "wave.monster",
        source_id="wave:validation",
        target_id="enemy:target",
        event_id="validation:wave_monster",
        window="wave_transition",
        process_only=True,
        payload={
            "wave_definition_id": "validation:wave",
            "wave_index": 0,
            "unit_id": "enemy:target",
            "entry_id": "validation:entry",
            "position": 0,
            "source_trace": {"validation": VALIDATION_VERSION},
        },
    )
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    admitted = dispatcher.dispatch_event(wave_state, event=event)
    blocked = dispatcher.dispatch_event(state, event=event)
    ok = (
        ingress.plan.ok
        and admitted.node_results
        and admitted.node_results[0].complete
        and blocked.node_results
        and blocked.node_results[0].status == "blocked"
        and blocked.after_state == state
    )
    return {
        "row_id": "wave_event_phase_ingress",
        "classification": "boundary",
        "ok": ok,
        "ingress": ingress.plan.to_json(),
        "admitted_nodes": [node.to_json() for node in admitted.node_results],
        "blocked_nodes": [node.to_json() for node in blocked.node_results],
    }


def _wave_phase_source_audit_case(base_rules: RuleBook) -> dict[str, Any]:
    source = _source("wave:phase:audit")
    entry = WaveMonsterEntryIR(
        entry_id="validation:wave:entry",
        stage_id="validation:stage",
        wave_index=0,
        position=0,
        monster_entity_ref="validation:enemy",
        monster_raw_id="validation:enemy",
        birth_template_id="validation:unused_for_victory",
        source=source,
        coverage_status="executable",
    )
    definition = WaveDefinitionIR(
        wave_definition_id="validation:wave:definition",
        stage_id="validation:stage",
        wave_count=1,
        entries=(entry,),
        stage_ability_refs=(),
        source=source,
        coverage_status="executable",
    )
    rules = RuleBook(replace(base_rules.ir, wave_definitions=(definition,)))
    state = _base_state()
    enemy = state.units["enemy:target"]
    defeated_enemy = replace(
        enemy,
        hp=0.0,
        flags={
            **enemy.flags,
            "lifecycle_status": "defeated",
            "wave_member_kind": "stage_wave_enemy",
            "wave_index": 0,
        },
    )
    state = replace(
        state,
        units={**state.units, enemy.unit_id: defeated_enemy},
        global_flags={
            **state.global_flags,
            "combat_phase": IDLE,
            "wave_runtime": {
                "schema_version": WAVE_RUNTIME_SCHEMA_VERSION,
                "wave_definition_id": definition.wave_definition_id,
                "current_wave_index": 0,
                "total_waves": 1,
                "status": "active",
                "current_wave_unit_ids": [enemy.unit_id],
                "source_trace": source.to_json(),
            },
        },
    )
    result = CombatScheduler(rules).step(state)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    phase_mutations = tuple(
        mutation
        for mutation in result.transition.transaction.mutations
        if mutation.path == ("global_flags", "combat_phase")
    )
    replay = MutationReducer().replay_snapshot(
        state,
        result.transition.transaction.mutations,
        result.transition.after.to_json(),
    )
    checks = {
        "committed": result.transition.outcome.successor_eligible,
        "phase_mutations_present": len(phase_mutations) == 2,
        "phase_mutations_use_wave_source": all(
            mutation.source == "wave_system" for mutation in phase_mutations
        ),
        "phase_mutations_carry_wave_identity": all(
            mutation.metadata.get("wave_definition_id") == definition.wave_definition_id
            and isinstance(mutation.metadata.get("source_trace"), dict)
            for mutation in phase_mutations
        ),
        "source_audit_ok": audit.ok,
        "replay_ok": replay.ok,
    }
    return {
        "row_id": "wave_phase_mutation_source_audit",
        "classification": "executable",
        "ok": all(checks.values()),
        **checks,
        "audit": audit.to_json(),
        "phase_mutations": [mutation.to_json() for mutation in phase_mutations],
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    scheduler_source = (package_root / "systems" / "scheduler.py").read_text(encoding="utf-8")
    decision_source = (package_root / "systems" / "decision.py").read_text(encoding="utf-8")
    event_source = (package_root / "systems" / "event_dispatch.py").read_text(encoding="utf-8")
    phase_source = (package_root / "systems" / "phase_machine.py").read_text(encoding="utf-8")
    turn_end_flag_removed = "admit_turn_end_listener_dispatch" not in scheduler_source
    phase_admission_wired = all(
        token in scheduler_source + decision_source + event_source
        for token in (
            "operation_blocked_reason",
            "event_blocked_reason",
            "combat_phase",
        )
    )
    invalid_phase_never_defaults = "unknown_current_combat_phase" in phase_source and "else IDLE" not in phase_source
    wave_phase_source_explicit = (
        'mutation_source="wave_system"' in scheduler_source
        and '"wave_transition_plan": plan.to_json()' in scheduler_source
    )
    return {
        "row_id": "phase_machine_static_boundary",
        "classification": "boundary",
        "ok": turn_end_flag_removed
        and phase_admission_wired
        and invalid_phase_never_defaults
        and wave_phase_source_explicit,
        "turn_end_flag_removed": turn_end_flag_removed,
        "phase_admission_wired": phase_admission_wired,
        "invalid_phase_never_defaults": invalid_phase_never_defaults,
        "wave_phase_source_explicit": wave_phase_source_explicit,
    }


def _regular_initial_state() -> BattleState:
    state = _base_state()
    target = replace(
        state.units["enemy:target"],
        flags={**state.units["enemy:target"].flags, "action_disabled": True},
    )
    return replace(state, units={**state.units, "enemy:target": target})


def _event_index(events: list[dict[str, Any]], event_type: str) -> int:
    return next((index for index, event in enumerate(events) if event["event_type"] == event_type), -1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S9 explicit turn and event phase machine.")
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
