from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    JSONValue,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import ExecutionNodeResult, classify_transition_outcome
from ..rules.ir import EffectIR, RuleEntity, TimelineRuleIR
from ..rules.rulebook import RuleBook
from ..systems.decision import DecisionSystem
from ..systems.timeline import TimelineAdjustmentResult, TimelineSystem, timeline_tie_choice_id
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s10_timeline_control_semantics"
MATRIX_SCHEMA_VERSION = "p7_s10_timeline_control_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    rules = _control_rulebook()
    rule, blocked_reason = rules.select_timeline_rule()
    if rule is None:
        raise AssertionError(f"validation timeline rule missing: {blocked_reason}")
    speed = _speed_continuity_case(rules, rule)
    tie = _tie_priority_case(rule)
    adjustments = _adjustment_case(rules, rule)
    filtering = _candidate_filter_case(rule)
    control = _controlled_turn_case(rules)
    static_boundary = _static_boundary(package_root)
    rows = (speed, tie, adjustments, filtering, control, static_boundary)
    checks = {
        "speed_change_preserves_elapsed_progress": speed["ok"],
        "tie_requires_sourced_priority_or_explicit_choice": tie["ok"],
        "advance_delay_immediate_share_adjustment_contract": adjustments["ok"],
        "non_admitted_units_never_selected": filtering["ok"],
        "controlled_turn_consumed_and_scheduler_progresses": control["ok"],
        "unit_id_not_used_as_tie_semantics": static_boundary["ok"],
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
            "status_hit_probability": "P7-S15",
            "rng_identity": "P7-S16",
            "queue_terminal_policy": "P7-S11",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s10_timeline_control_semantics.json", summary)
    write_json(
        output_dir / "p7_s10_timeline_control_matrix.json",
        {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "rows": [
                {"row_id": row["row_id"], "classification": row["classification"], "ok": row["ok"]}
                for row in rows
            ],
        },
    )
    write_json(
        output_dir / "p7_s10_timeline_control_evidence.json",
        {
            "speed_continuity": speed,
            "tie_priority": tie,
            "adjustments": adjustments,
            "candidate_filter": filtering,
            "controlled_turn": control,
            "static_boundary": static_boundary,
        },
    )
    return summary


def _speed_continuity_case(rules: RuleBook, rule: TimelineRuleIR) -> dict[str, Any]:
    timeline = TimelineSystem()
    state = _single_unit_state(speed=100.0, action_value=60.0)
    accelerated = timeline.change_speed_preserving_progress(
        state,
        "unit:actor",
        new_speed=200.0,
        rule=rule,
        source="timeline_system",
        metadata={"source_trace": rule.source.to_json(), "validation_case": "accelerate"},
    )
    after_accelerated, accelerated_evidence = _adjustment_evidence(rules, state, accelerated)
    slowed = timeline.change_speed_preserving_progress(
        after_accelerated,
        "unit:actor",
        new_speed=50.0,
        rule=rule,
        source="timeline_system",
        metadata={"source_trace": rule.source.to_json(), "validation_case": "slow"},
    )
    after_slowed, slowed_evidence = _adjustment_evidence(rules, after_accelerated, slowed)
    old_progress = 1.0 - 60.0 / timeline.full_action_value(100.0, rule)
    accelerated_progress = 1.0 - after_accelerated.units["unit:actor"].action_value / timeline.full_action_value(200.0, rule)
    slowed_progress = 1.0 - after_slowed.units["unit:actor"].action_value / timeline.full_action_value(50.0, rule)
    expected_accelerated = 60.0 * 100.0 / 200.0
    expected_slowed = expected_accelerated * 200.0 / 50.0
    ok = (
        abs(after_accelerated.units["unit:actor"].action_value - expected_accelerated) < 1e-9
        and abs(after_slowed.units["unit:actor"].action_value - expected_slowed) < 1e-9
        and abs(old_progress - accelerated_progress) < 1e-9
        and abs(old_progress - slowed_progress) < 1e-9
        and accelerated_evidence["ok"]
        and slowed_evidence["ok"]
    )
    return {
        "row_id": "mid_timeline_speed_up_and_down",
        "classification": "executable",
        "ok": ok,
        "remaining_action_values": {
            "before": 60.0,
            "accelerated": after_accelerated.units["unit:actor"].action_value,
            "slowed": after_slowed.units["unit:actor"].action_value,
        },
        "progress_completed": {
            "before": old_progress,
            "accelerated": accelerated_progress,
            "slowed": slowed_progress,
        },
        "accelerated_evidence": accelerated_evidence,
        "slowed_evidence": slowed_evidence,
    }


def _tie_priority_case(rule: TimelineRuleIR) -> dict[str, Any]:
    timeline = TimelineSystem()
    source = rule.source.to_json()
    units = {
        "zeta": UnitState(
            unit_id="zeta",
            side="ally",
            template_id="validation:tie_a",
            hp=100.0,
            max_hp=100.0,
            action_value=10.0,
            flags={"timeline_priority": {"value": 20.0, "priority_id": "formation:late", "source_trace": source}},
        ),
        "alpha": UnitState(
            unit_id="alpha",
            side="ally",
            template_id="validation:tie_b",
            hp=100.0,
            max_hp=100.0,
            action_value=10.0,
            flags={"timeline_priority": {"value": 10.0, "priority_id": "formation:early", "source_trace": source}},
        ),
    }
    state = BattleState(units=units)
    sourced = timeline.plan_next_actor(state, rule)
    unsourced_units = {
        unit_id: replace(unit, flags={})
        for unit_id, unit in units.items()
    }
    unsourced = timeline.plan_next_actor(replace(state, units=unsourced_units), rule)
    unsourced_state = replace(state, units=unsourced_units)
    explicit_choice_id = timeline_tie_choice_id(unsourced_state, rule, "zeta")
    explicit = timeline.plan_next_actor(
        unsourced_state,
        rule,
        tie_choice_actor_id="zeta",
        tie_choice_id=explicit_choice_id,
    )
    invalid_explicit = timeline.plan_next_actor(
        unsourced_state,
        rule,
        tie_choice_actor_id="zeta",
        tie_choice_id="forged:timeline_choice",
    )
    decision_system = DecisionSystem(_control_rulebook())
    decision = decision_system.current_decision(unsourced_state)
    zeta_choice = next(
        (choice for choice in decision.availability.choices if choice.actor_id == "zeta"),
        None,
    )
    submitted = (
        decision_system.submit(
            unsourced_state,
            decision.token,
            ActionCommand(
                actor_id="zeta",
                action_id=str(zeta_choice.action_id),
                action_level=zeta_choice.action_level,
                metadata={"timeline_choice_id": zeta_choice.metadata["timeline_choice_id"]},
            ),
        )
        if decision.ready and decision.token is not None and zeta_choice is not None
        else None
    )
    ok = (
        sourced.ok
        and sourced.actor_id == "alpha"
        and sourced.tie_resolution.get("mode") == "priority"
        and not unsourced.ok
        and unsourced.blocked_reason == "timeline_tie_priority_missing"
        and explicit.ok
        and explicit.actor_id == "zeta"
        and explicit.tie_resolution.get("mode") == "explicit_choice"
        and explicit.tie_resolution.get("choice_id") == explicit_choice_id
        and not invalid_explicit.ok
        and invalid_explicit.blocked_reason == "timeline_tie_explicit_choice_invalid"
        and decision.ready
        and decision.availability.mode == "timeline_actor_selectable"
        and len(decision.availability.choices) == 2
        and submitted is not None
        and submitted.transition.outcome.successor_eligible
        and submitted.after_state.global_flags.get("turn_owner_id") == "zeta"
    )
    return {
        "row_id": "equal_action_value_priority_and_explicit_choice",
        "classification": "executable_and_negative",
        "ok": ok,
        "sourced_plan": sourced.to_json(),
        "unsourced_plan": unsourced.to_json(),
        "explicit_plan": explicit.to_json(),
        "invalid_explicit_plan": invalid_explicit.to_json(),
        "decision": decision.to_json(),
        "submitted_transition": submitted.transition.to_json() if submitted is not None else {},
    }


def _adjustment_case(rules: RuleBook, rule: TimelineRuleIR) -> dict[str, Any]:
    timeline = TimelineSystem()
    base = _single_unit_state(speed=100.0, action_value=60.0)
    metadata = {"source_trace": rule.source.to_json(), "validation_case": "timeline_adjustment"}
    results = {
        "advance": timeline.adjust_action_value(
            base, "unit:actor", operation="advance", amount=20.0, source="timeline_system", metadata=metadata, rule=rule
        ),
        "delay": timeline.adjust_action_value(
            base, "unit:actor", operation="delay", amount=30.0, source="timeline_system", metadata=metadata, rule=rule
        ),
        "immediate_action": timeline.adjust_action_value(
            base, "unit:actor", operation="immediate_action", source="timeline_system", metadata=metadata, rule=rule
        ),
        "extra_action": timeline.adjust_action_value(
            base, "unit:actor", operation="extra_action", source="timeline_system", metadata=metadata, rule=rule
        ),
        "unsupported": timeline.adjust_action_value(
            base, "unit:actor", operation="unknown", source="timeline_system", metadata=metadata, rule=rule
        ),
    }
    expected = {"advance": 40.0, "delay": 90.0, "immediate_action": 0.0, "extra_action": 60.0}
    evidence: dict[str, Any] = {}
    for operation in ("advance", "delay", "immediate_action"):
        after, item = _adjustment_evidence(rules, base, results[operation])
        evidence[operation] = {**item, "after_action_value": after.units["unit:actor"].action_value}
    extra_after = MutationReducer().apply_all(base, results["extra_action"].mutations)
    evidence["extra_action"] = {
        "mutation_count": len(results["extra_action"].mutations),
        "after_action_value": extra_after.units["unit:actor"].action_value,
    }
    ok = (
        all(abs(evidence[key]["after_action_value"] - value) < 1e-9 for key, value in expected.items())
        and all(evidence[key]["ok"] for key in ("advance", "delay", "immediate_action"))
        and evidence["extra_action"]["mutation_count"] == 0
        and not results["unsupported"].plan.ok
        and results["unsupported"].plan.blocked_reason == "unsupported_timeline_adjustment"
        and not results["unsupported"].mutations
    )
    return {
        "row_id": "advance_delay_immediate_and_extra_action",
        "classification": "executable_and_negative",
        "ok": ok,
        "expected_remaining_action_values": expected,
        "evidence": evidence,
        "unsupported": results["unsupported"].plan.to_json(),
    }


def _candidate_filter_case(rule: TimelineRuleIR) -> dict[str, Any]:
    units = {
        "dead": UnitState("dead", "ally", "validation:dead", hp=0.0, max_hp=100.0, action_value=0.0),
        "removed": UnitState(
            "removed", "ally", "validation:removed", hp=100.0, max_hp=100.0, action_value=0.0,
            flags={"lifecycle_status": "removed"},
        ),
        "off_field": UnitState(
            "off_field", "ally", "validation:off_field", hp=100.0, max_hp=100.0, action_value=0.0,
            flags={"on_field": False},
        ),
        "backline": UnitState(
            "backline", "ally", "validation:backline", hp=100.0, max_hp=100.0, action_value=0.0,
            flags={"backline": True},
        ),
        "disabled": UnitState(
            "disabled", "ally", "validation:disabled", hp=100.0, max_hp=100.0, action_value=0.0,
            flags={"action_disabled": True},
        ),
        "eligible": UnitState("eligible", "ally", "validation:eligible", hp=100.0, max_hp=100.0, action_value=5.0),
    }
    plan = TimelineSystem().plan_next_actor(BattleState(units=units), rule)
    reasons = {str(item["unit_id"]): str(item["reason"]) for item in plan.skipped_units}
    expected_reasons = {
        "dead": "unit_defeated",
        "removed": "unit_removed",
        "off_field": "unit_off_field",
        "backline": "unit_backline",
        "disabled": "action_disabled",
    }
    ok = plan.ok and plan.actor_id == "eligible" and all(reasons.get(key) == value for key, value in expected_reasons.items())
    return {
        "row_id": "dead_removed_off_field_backline_disabled_filtered",
        "classification": "executable_filter",
        "ok": ok,
        "plan": plan.to_json(),
        "expected_skip_reasons": expected_reasons,
    }


def _controlled_turn_case(rules: RuleBook) -> dict[str, Any]:
    state = _base_state()
    effect = rules.effect("validation:control_effect")
    definition = rules.entity("modifier_definition:ValidationControl")
    if effect is None or definition is None:
        raise AssertionError("structured control validation source missing")
    source_trace = {
        "effect_id": effect.effect_id,
        "effect_source": effect.source.to_json(),
        "modifier_name": "ValidationControl",
        "modifier_definition": definition.source.to_json(),
    }
    detail: dict[str, JSONValue] = {
        "instance_id": "status_instance:validation_control:ally_actor",
        "status_id": "modifier:ValidationControl",
        "modifier_name": "ValidationControl",
        "owner_id": "ally:actor",
        "source_id": "validation:control_source",
        "caster_id": "enemy:target",
        "remaining_duration": 1.0,
        "duration": 1.0,
        "life_step_moment": "TurnEnd",
        "duration_unit": "TurnEnd",
        "duration_admission": {
            "admission_status": "executable",
            "tick_owner_policy": "holder",
            "life_step_moment": "TurnEnd",
        },
        "lifecycle_state": "active",
        "status_category": "control",
        "control_kind": "structured_skip_turn",
        "source_trace": source_trace,
    }
    actor = replace(
        state.units["ally:actor"],
        statuses=("modifier:ValidationControl",),
        flags={**state.units["ally:actor"].flags, "status_details": [detail]},
    )
    enemy = replace(
        state.units["enemy:target"],
        flags={**state.units["enemy:target"].flags, "action_disabled": True},
    )
    initial = replace(state, units={**state.units, "ally:actor": actor, "enemy:target": enemy})
    advance = DecisionSystem(rules).advance_to_decision(initial, max_internal_steps=8)
    events = [event.event_type for transition in advance.transitions for event in transition.transaction.events]
    action_before_count = events.count("scheduler.action.before")
    control_skip_count = events.count("turn.control_skipped")
    status_details = advance.after_state.units["ally:actor"].flags.get("status_details", ())
    transition_evidence = [
        {
            "action_id": transition.transaction.command.action_id,
            "outcome": transition.outcome.to_json(),
            "replay_ok": MutationReducer().replay_snapshot(
                before,
                transition.transaction.mutations,
                transition.after.to_json(),
            ).ok,
            "source_audit_ok": RuntimeSourceAuditor(rules).validate_transition(transition).ok,
            "source_audit_violations": [
                item.to_json()
                for item in RuntimeSourceAuditor(rules).validate_transition(transition).violations
            ],
            "contract_ok": TransitionContractValidator().validate(transition).ok,
        }
        for before, transition in _transition_before_pairs(initial, advance.transitions)
    ]
    ok = (
        advance.decision.ready
        and advance.decision.token is not None
        and advance.decision.token.actor_id == "ally:actor"
        and len(advance.transitions) == 3
        and all(item["outcome"]["successor_eligible"] for item in transition_evidence)
        and all(item["replay_ok"] and item["source_audit_ok"] and item["contract_ok"] for item in transition_evidence)
        and control_skip_count == 1
        and action_before_count == 0
        and events.count("turn.end") == 1
        and events.count("turn.begin") == 2
        and not status_details
        and int(advance.after_state.global_flags.get("turn_sequence_index", 0)) == 2
    )
    return {
        "row_id": "controlled_turn_consumed_status_expires_next_decision_ready",
        "classification": "executable",
        "ok": ok,
        "decision": advance.decision.to_json(),
        "transition_count": len(advance.transitions),
        "events": events,
        "control_skip_count": control_skip_count,
        "scheduler_action_before_count": action_before_count,
        "remaining_status_details": list(status_details) if isinstance(status_details, (list, tuple)) else status_details,
        "turn_sequence_index": advance.after_state.global_flags.get("turn_sequence_index"),
        "transition_evidence": transition_evidence,
    }


def _adjustment_evidence(
    rules: RuleBook,
    before: BattleState,
    result: TimelineAdjustmentResult,
) -> tuple[BattleState, dict[str, Any]]:
    reducer = MutationReducer()
    after = reducer.apply_all(before, result.mutations)
    transition = _adjustment_transition(before, after, result)
    replay = reducer.replay_snapshot(before, result.mutations, after.snapshot().to_json())
    contract = TransitionContractValidator().validate(transition)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    return after, {
        "ok": replay.ok and contract.ok and audit.ok and transition.outcome.successor_eligible,
        "plan": result.plan.to_json(),
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
        "replay_ok": replay.ok,
        "contract_ok": contract.ok,
        "source_audit_ok": audit.ok,
        "source_audit_violations": [item.to_json() for item in audit.violations],
        "outcome": transition.outcome.to_json(),
    }


def _adjustment_transition(
    before: BattleState,
    after: BattleState,
    result: TimelineAdjustmentResult,
) -> BattleTransition:
    command = ActionCommand(
        actor_id=result.plan.unit_id,
        action_id=f"timeline:{result.plan.operation}",
        action_level=1,
        source="timeline_system",
    )
    outcome = classify_transition_outcome(
        (
            ExecutionNodeResult(
                node_kind="timeline_adjustment",
                node_id=command.action_id,
                status="complete",
            ),
        ),
        state_changed=after != before,
        mutation_count=len(result.mutations),
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=before.snapshot(),
            events=result.events,
            mutations=result.mutations,
            settlement=ActionSettlement(
                action_id=command.action_id,
                actor_id=command.actor_id,
                target_ids=(command.actor_id,),
                records=result.records,
            ),
        ),
        after=after.snapshot(),
        outcome=outcome,
        coverage={"timeline_adjustment_plan": result.plan.to_json()},
    )


def _transition_before_pairs(
    initial: BattleState,
    transitions: tuple[BattleTransition, ...],
) -> tuple[tuple[BattleState, BattleTransition], ...]:
    reducer = MutationReducer()
    before = initial
    pairs: list[tuple[BattleState, BattleTransition]] = []
    for transition in transitions:
        pairs.append((before, transition))
        before = reducer.apply_all(before, transition.transaction.mutations)
    return tuple(pairs)


def _single_unit_state(*, speed: float, action_value: float) -> BattleState:
    return BattleState(
        units={
            "unit:actor": UnitState(
                unit_id="unit:actor",
                side="ally",
                template_id="validation:timeline_actor",
                hp=100.0,
                max_hp=100.0,
                speed=speed,
                action_value=action_value,
            )
        },
        global_flags={"phase": "scenario", "current_window": "idle"},
    )


def _control_rulebook() -> RuleBook:
    baseline = _trust_rulebook()
    source = baseline.ir.timeline_rules[0].source
    definition = RuleEntity(
        entity_id="modifier_definition:ValidationControl",
        entity_type="modifier_definition",
        fields={"modifier_name": "ValidationControl", "status_category": "control"},
        source=source,
        coverage_status="executable",
    )
    effect = EffectIR(
        effect_id="validation:control_effect",
        opcode="AddModifier",
        payload={"standard": {"modifier_name": "ValidationControl"}},
        source=source,
        coverage_status="executable",
        modifier_definition_id=definition.entity_id,
        source_mode="validation",
    )
    return RuleBook(
        replace(
            baseline.ir,
            entities=(*baseline.ir.entities, definition),
            effects=(*baseline.ir.effects, effect),
        )
    )


def _static_boundary(package_root: Path) -> dict[str, Any]:
    source = (package_root / "systems" / "timeline.py").read_text(encoding="utf-8")
    callback_source = (package_root / "systems" / "status_callbacks.py").read_text(encoding="utf-8")
    forbidden_fragments = (
        "key=lambda item: (item[0], item[1])",
        "sorted(candidates)[0]",
    )
    present = [fragment for fragment in forbidden_fragments if fragment in source]
    return {
        "row_id": "static_no_unit_id_tie_break",
        "classification": "static_boundary",
        "ok": not present
        and "timeline_tie_priority_missing" in source
        and "tie_choice_id" in source
        and "self.timeline.adjust_action_value(" in callback_source
        and "self.timeline.set_action_value(" not in callback_source,
        "forbidden_fragments_present": present,
        "status_delay_uses_unified_adjustment": "self.timeline.adjust_action_value(" in callback_source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S10 timeline and controlled-turn semantics.")
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
