from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import BattleState, GameEvent
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CanonicalIR, IRSource, WaveDefinitionIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.phase_machine import WAVE_TRANSITION
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..systems.timeline import TimelineSystem
from ..systems.wave import WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p1_2_wave_system import (
    _current_wave_unit_ids,
    _initial_setup_case,
    _select_action_definition,
    _with_units_defeated,
)


VALIDATION_VERSION = "p7_s17_wave_lifecycle_events"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    return run_validation_with_rules(ir, rules, output_dir)


def run_validation_with_rules(
    ir: CanonicalIR,
    rules: RuleBook,
    output_dir: Path,
) -> dict[str, Any]:
    definition = _select_two_wave_definition(rules)
    action_ref, action_level = _select_action_definition(rules)
    setup = _initial_setup_case(rules, definition, action_ref, action_level)
    initial = setup["state"]

    start = CombatScheduler(rules).step(initial)
    started = start.after_state
    first_cleared = _with_units_defeated(started, _current_wave_unit_ids(started))
    advance = CombatScheduler(rules).step(first_cleared)
    second = advance.after_state
    final_cleared = _with_units_defeated(second, _current_wave_unit_ids(second))
    completed = CombatScheduler(rules).step(final_cleared)

    rows = {
        "initial_wave_start": _initial_start_row(rules, initial, start),
        "real_two_wave_advance": _advance_row(rules, first_cleared, advance),
        "battle_complete": _complete_row(rules, final_cleared, completed),
        "event_payload_negative": _event_payload_negative_row(rules, started),
        "source_and_residual_negative": _source_negative_row(ir, rules, definition, started),
    }
    result = {
        "schema_version": "p7_s17_wave_lifecycle_validation_v1",
        "ok": all(row["ok"] for row in rows.values()),
        "ready_for_review": all(row["ok"] for row in rows.values()),
        "selection": {
            "mode": "structured_exact_two_wave_definition",
            "fixed_stage_or_monster_id": False,
            "wave_definition_id": definition.wave_definition_id,
            "stage_id": definition.stage_id,
            "wave_count": definition.wave_count,
            "source_path": definition.source.source_path,
        },
        "rows": rows,
        "resource_budget": {
            "tbgd_build_count": 1,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s17_wave_lifecycle_events.json", result)
    write_json(output_dir / "p7_s17_wave_lifecycle_matrix.json", {"rows": rows})
    write_json(
        output_dir / "p7_s17_wave_lifecycle_evidence.json",
        {
            "selection": result["selection"],
            "start": _transition_evidence(start),
            "advance": _transition_evidence(advance),
            "complete": _transition_evidence(completed),
        },
    )
    return _json_safe(result)


def _initial_start_row(rules: RuleBook, initial: BattleState, result) -> dict[str, Any]:
    runtime = result.after_state.global_flags.get("wave_runtime")
    event_types = _event_types(result)
    dispatch_types = _dispatch_event_types(result)
    replay = MutationReducer().replay_snapshot(
        initial,
        result.transition.transaction.mutations,
        result.after_state.snapshot().to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = {
        "pending_start_source_state": isinstance(initial.global_flags.get("wave_runtime"), dict)
        and initial.global_flags["wave_runtime"].get("status") == "pending_start",
        "committed": result.transition.outcome.successor_eligible,
        "runtime_active": isinstance(runtime, dict) and runtime.get("status") == "active",
        "wave_started_dispatched": "wave.started" in event_types and "wave.started" in dispatch_types,
        "monster_enter_dispatched": "wave.monster" in event_types and "wave.monster" in dispatch_types,
        "no_duplicate_birth": not any(
            mutation.metadata.get("lifecycle_operation") == "unit_spawn"
            for mutation in result.transition.transaction.mutations
        ),
        "phase_restored": result.after_state.global_flags.get("combat_phase") == "idle",
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
    }
    return {"ok": all(checks.values()), **checks}


def _advance_row(rules: RuleBook, before: BattleState, result) -> dict[str, Any]:
    transition = result.transition
    runtime = result.after_state.global_flags.get("wave_runtime")
    next_ids = _current_wave_unit_ids(result.after_state)
    event_types = _event_types(result)
    dispatch_types = _dispatch_event_types(result)
    replay = MutationReducer().replay_snapshot(
        before,
        transition.transaction.mutations,
        result.after_state.snapshot().to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    timeline = TimelineSystem().plan_next_actor(result.after_state, rules.default_timeline_rule())
    skipped = {str(item.get("unit_id")) for item in timeline.skipped_units}
    old_ids = _current_wave_unit_ids(before)
    mutation_ids = {mutation.stable_id() for mutation in transition.transaction.mutations}
    settlement_ids = {
        str(record.get("mutation_id") or "")
        for record in (transition.transaction.settlement.records if transition.transaction.settlement else ())
        if record.get("process_only") is False
    }
    checks = {
        "committed": transition.outcome.successor_eligible,
        "wave_index_advanced": result.after_state.wave_index == before.wave_index + 1,
        "runtime_active": isinstance(runtime, dict) and runtime.get("status") == "active",
        "old_wave_removed": bool(old_ids)
        and all(result.after_state.units[unit_id].flags.get("lifecycle_status") == "removed" for unit_id in old_ids),
        "next_wave_spawned_once": bool(next_ids)
        and len(next_ids) == len(set(next_ids))
        and all(unit_id in result.after_state.units for unit_id in next_ids),
        "wave_events_dispatched": {"wave.cleared", "wave.started", "wave.monster"}.issubset(set(dispatch_types)),
        "timeline_restored": result.after_state.global_flags.get("combat_phase") == "idle"
        and all(unit_id not in skipped for unit_id in next_ids),
        "no_duplicate_turn_begin": "turn.begin" not in event_types,
        "no_pending_queue": not any(result.after_state.queues.values()),
        "settlement_covers_mutations": mutation_ids.issubset(settlement_ids),
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
    }
    return {"ok": all(checks.values()), **checks}


def _complete_row(rules: RuleBook, before: BattleState, result) -> dict[str, Any]:
    transition = result.transition
    event_types = _event_types(result)
    dispatch_types = _dispatch_event_types(result)
    replay = MutationReducer().replay_snapshot(
        before,
        transition.transaction.mutations,
        result.after_state.snapshot().to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    checks = {
        "committed": transition.outcome.successor_eligible,
        "victory_recorded": result.after_state.global_flags.get("battle_outcome") == "victory",
        "combat_phase_ended": result.after_state.global_flags.get("combat_phase") == "ended",
        "battle_phase_ended": result.after_state.global_flags.get("phase") == "ended",
        "battle_completed_dispatched": "battle.completed" in event_types and "battle.completed" in dispatch_types,
        "wave_cleared_dispatched": "wave.cleared" in dispatch_types,
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
    }
    return {"ok": all(checks.values()), **checks}


def _event_payload_negative_row(rules: RuleBook, state: BattleState) -> dict[str, Any]:
    dispatch_state = replace(state, global_flags={**state.global_flags, "combat_phase": WAVE_TRANSITION})
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    missing_start = dispatcher.dispatch_event(
        dispatch_state,
        event=GameEvent("wave.started", source_id="wave_system", payload={"wave_index": state.wave_index}),
    )
    missing_monster = dispatcher.dispatch_event(
        dispatch_state,
        event=GameEvent("wave.monster", source_id="wave_system", target_id="enemy:missing", payload={}),
    )
    checks = {
        "missing_start_payload_blocked": bool(missing_start.errors)
        and any("payload_incomplete" in item for item in missing_start.errors),
        "missing_start_state_unchanged": missing_start.after_state == dispatch_state and not missing_start.mutations,
        "missing_monster_payload_blocked": bool(missing_monster.errors),
        "missing_monster_state_unchanged": missing_monster.after_state == dispatch_state and not missing_monster.mutations,
    }
    return {"ok": all(checks.values()), **checks}


def _source_negative_row(
    ir: CanonicalIR,
    rules: RuleBook,
    definition: WaveDefinitionIR,
    state: BattleState,
) -> dict[str, Any]:
    cleared = _with_units_defeated(state, _current_wave_unit_ids(state))
    missing_runtime = dict(cleared.global_flags.get("wave_runtime", {}))
    missing_runtime["wave_definition_id"] = "wave_definition:missing"
    missing_state = replace(cleared, global_flags={**cleared.global_flags, "wave_runtime": missing_runtime})
    missing_step = CombatScheduler(rules).step(missing_state)

    no_stage_definition = replace(definition, stage_id="")
    no_stage_rules = RuleBook(_replace_wave_definition(ir, no_stage_definition))
    no_stage_plan = WaveSystem(no_stage_rules).plan_transition(cleared)

    next_index = state.wave_index + 1
    no_birth_entries = tuple(
        replace(entry, birth_template_id="")
        if entry.wave_index == next_index
        else entry
        for entry in definition.entries
    )
    no_birth_definition = replace(definition, entries=no_birth_entries)
    no_birth_rules = RuleBook(_replace_wave_definition(ir, no_birth_definition))
    no_birth_plan = WaveSystem(no_birth_rules).plan_transition(cleared)

    queued = replace(cleared, queues={"validation": ({"entry_id": "pending"},)})
    queued_plan = WaveSystem(rules).plan_transition(queued)
    audit_runtime = dict(cleared.global_flags.get("wave_runtime", {}))
    audit_runtime["source_trace"] = {
        "source_path": "validation/audit_expanded_only.json",
        "evidence": {"detail": "does_not_change_wave_behavior"},
    }
    audit_units = {
        unit_id: replace(
            unit,
            flags={
                **unit.flags,
                "wave_entry_source_trace": {"source_path": "validation/unit_audit_only.json"},
            },
        )
        if unit_id in _current_wave_unit_ids(cleared)
        else unit
        for unit_id, unit in cleared.units.items()
    }
    audit_variant = replace(
        cleared,
        units=audit_units,
        global_flags={**cleared.global_flags, "wave_runtime": audit_runtime},
    )
    base_plan = WaveSystem(rules).plan_transition(cleared)
    audit_plan = WaveSystem(rules).plan_transition(audit_variant)
    audit_behavior_equal = (
        base_plan.ok,
        base_plan.status,
        base_plan.wave_definition_id,
        base_plan.current_wave_index,
        base_plan.next_wave_index,
        base_plan.blocked_reason,
        base_plan.remove_unit_ids,
        tuple(request.unit_id for request in base_plan.spawn_requests),
    ) == (
        audit_plan.ok,
        audit_plan.status,
        audit_plan.wave_definition_id,
        audit_plan.current_wave_index,
        audit_plan.next_wave_index,
        audit_plan.blocked_reason,
        audit_plan.remove_unit_ids,
        tuple(request.unit_id for request in audit_plan.spawn_requests),
    )
    empty_source = IRSource(source_path="", raw_type="", raw_id="", evidence={})
    audit_trimmed_definition = replace(
        definition,
        source=empty_source,
        entries=tuple(replace(entry, source=empty_source) for entry in definition.entries),
    )
    audit_trimmed_rules = RuleBook(_replace_wave_definition(ir, audit_trimmed_definition))
    audit_trimmed_plan = WaveSystem(audit_trimmed_rules).plan_transition(cleared)
    definition_audit_trim_behavior_equal = (
        base_plan.ok,
        base_plan.status,
        base_plan.wave_definition_id,
        base_plan.current_wave_index,
        base_plan.next_wave_index,
        base_plan.blocked_reason,
        base_plan.remove_unit_ids,
        tuple(request.unit_id for request in base_plan.spawn_requests),
    ) == (
        audit_trimmed_plan.ok,
        audit_trimmed_plan.status,
        audit_trimmed_plan.wave_definition_id,
        audit_trimmed_plan.current_wave_index,
        audit_trimmed_plan.next_wave_index,
        audit_trimmed_plan.blocked_reason,
        audit_trimmed_plan.remove_unit_ids,
        tuple(request.unit_id for request in audit_trimmed_plan.spawn_requests),
    )
    checks = {
        "missing_definition_blocked": not missing_step.transition.outcome.successor_eligible
        and missing_step.after_state == missing_state,
        "missing_stage_blocked": no_stage_plan.status == "blocked"
        and no_stage_plan.blocked_reason == "wave_stage_id_missing",
        "missing_birth_blocked": no_birth_plan.status == "blocked"
        and no_birth_plan.blocked_reason == "wave_entry_birth_template_missing",
        "pending_queue_blocks_transition": queued_plan.status == "blocked"
        and queued_plan.blocked_reason == "pending_queue_before_wave_transition",
        "audit_trace_expansion_does_not_change_wave_plan": audit_behavior_equal,
        "definition_and_entry_audit_clear_does_not_change_wave_plan": definition_audit_trim_behavior_equal,
    }
    return {"ok": all(checks.values()), **checks}


def _replace_wave_definition(ir: CanonicalIR, replacement: WaveDefinitionIR) -> CanonicalIR:
    return replace(
        ir,
        wave_definitions=tuple(
            replacement if item.wave_definition_id == replacement.wave_definition_id else item
            for item in ir.wave_definitions
        ),
    )


def _select_two_wave_definition(rules: RuleBook) -> WaveDefinitionIR:
    for definition in rules.wave_definitions():
        if definition.coverage_status != "executable" or definition.wave_count != 2:
            continue
        entries0 = rules.wave_entries_for_wave(definition.wave_definition_id, 0)
        entries1 = rules.wave_entries_for_wave(definition.wave_definition_id, 1)
        if entries0 and entries1 and all(entry.coverage_status == "executable" for entry in (*entries0, *entries1)):
            return definition
    raise AssertionError("no executable exact-two-wave WaveDefinitionIR found")


def _dispatch_event_types(result) -> tuple[str, ...]:
    records = result.transition.transaction.settlement.records if result.transition.transaction.settlement else ()
    values: list[str] = []
    for record in records:
        if record.get("record_type") != "event_dispatch":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        event_payload = payload.get("event")
        event_type = event_payload.get("event_type") if isinstance(event_payload, dict) else None
        if isinstance(event_type, str):
            values.append(event_type)
    return tuple(values)


def _event_types(result) -> tuple[str, ...]:
    return tuple(event.event_type for event in result.transition.transaction.events)


def _transition_evidence(result) -> dict[str, Any]:
    transition = result.transition
    return {
        "outcome": transition.outcome.to_json(),
        "event_types": list(_event_types(result)),
        "dispatched_event_types": list(_dispatch_event_types(result)),
        "mutation_count": len(transition.transaction.mutations),
        "wave_lifecycle": transition.coverage.get("wave_lifecycle", {}),
        "atomic_commit": transition.coverage.get("atomic_commit", {}),
    }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S17 explicit wave lifecycle and event dispatch.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root or find_tbgd_root(package_root.parent)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={len(result['rows'])} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
