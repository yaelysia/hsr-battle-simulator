from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _scenario_dict
from .validate_v0_235 import (
    _select_break_family_case,
    _state_with_toughness_binding,
    _transition_checks,
)
from .validate_v0_237 import _event_for_callback, _state_with_callback_status
from .validate_v0_242 import _candidate_queue_intents, _require_callback


VALIDATION_VERSION = "v0_244"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    action_case = _manual_action_step_case(ir, rules)
    mismatch_case = _manual_actor_mismatch_case(rules, action_case["state"], action_case["command"])
    enemy_case = _enemy_ai_step_case(rules)
    unsupported_case = _unsupported_lifecycle_hooks_case(rules)
    queue_case = _queue_priority_step_case(rules, action_case["state"])

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), rules),
        "manual_action_step": action_case["checks"],
        "manual_actor_mismatch": mismatch_case["checks"],
        "enemy_ai_blocked": enemy_case["checks"],
        "unsupported_hooks": unsupported_case["checks"],
        "queue_priority_step": queue_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "timeline_rule": rules.default_timeline_rule().to_json(),
            "selected_action": action_case["selection"],
            "selected_queue_intent": queue_case.get("queue_intent", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "manual_action_step": action_case["source_audit"],
            "manual_actor_mismatch": mismatch_case["source_audit"],
            "enemy_ai_blocked": enemy_case["source_audit"],
            "unsupported_hooks": unsupported_case["source_audits"],
            "queue_priority_step": queue_case["source_audit"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_244.json", result)
    write_json(output_dir / "sample_scheduler_step_transition_v0_244.json", action_case["transition"])
    write_json(output_dir / "sample_scheduler_queue_step_transition_v0_244.json", queue_case["transition"])
    write_json(output_dir / "coverage_summary_v0_244.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_244 scheduler loop and turn lifecycle.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _manual_action_step_case(ir, rules: RuleBook) -> dict[str, Any]:
    case = _select_break_family_case(ir, rules)
    build_state, command = _state_and_command_from_case(rules, case)
    state = _make_actor_next(build_state)
    result = CombatScheduler(rules).step(state, command)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, state)
    action_child = result.child_transitions[1] if len(result.child_transitions) >= 2 else None
    checks.update(
        {
            "source_audit": source_audit.ok,
            "child_transition_count": len(result.child_transitions) == 3,
            "scheduler_step_action": result.transition.transaction.command.action_id == "scheduler:step",
            "manual_action_executed": action_child is not None
            and action_child.transaction.command.action_id == command.action_id,
            "child_has_parent_metadata": action_child is not None
            and isinstance(action_child.transaction.command.metadata.get("scheduler_parent"), dict),
            "turn_end_reset_actor_av": result.after_state.units["ally:actor"].action_value > 0,
            "active_turn_cleared": "active_turn" not in result.after_state.global_flags,
            "turn_begin_event": any(event.event_type == "turn.begin" for event in result.transition.transaction.events),
            "turn_end_event": any(event.event_type == "turn.end" for event in result.transition.transaction.events),
            "scheduler_before_after_events": {
                "scheduler.action.before",
                "scheduler.action.after",
            }.issubset({event.event_type for event in result.transition.transaction.events}),
            "unsupported_hooks_recorded": set(result.transition.coverage.get("unsupported_hooks", {}))
            >= {"duration_tick", "extra_turn", "ultimate", "interrupt"},
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "state": state,
        "command": command,
        "selection": {
            "action_id": command.action_id,
            "action_level": command.action_level,
            "selection_mode": "structured_break_family_action_for_scheduler_step",
        },
        "transition": result.transition.to_json(),
        "child_transitions": [transition.to_json() for transition in result.child_transitions],
        "source_audit": source_audit.to_json(),
    }


def _manual_actor_mismatch_case(rules: RuleBook, state: BattleState, command: ActionCommand) -> dict[str, Any]:
    mismatch = replace(command, actor_id="ally:wrong_actor")
    result = CombatScheduler(rules).step(state, mismatch)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "blocked_reason": result.transition.coverage.get("blocked_reason") == "manual_command_actor_mismatch",
            "after_snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
            "no_mutations": not result.transition.transaction.mutations,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": result.transition.to_json(), "source_audit": source_audit.to_json()}


def _enemy_ai_step_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(ally_av=80.0, enemy_av=0.0, enemy_ai=False)
    result = CombatScheduler(rules).step(state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "enemy_ai_blocked": result.transition.coverage.get("blocked_reason") == "enemy_ai_missing",
            "after_snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
            "no_mutations": not result.transition.transaction.mutations,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": result.transition.to_json(), "source_audit": source_audit.to_json()}


def _unsupported_lifecycle_hooks_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(ally_av=0.0, enemy_av=50.0, enemy_ai=False)
    scheduler = CombatScheduler(rules)
    cases = {
        "duration_tick": scheduler._blocked(
            state,
            "timeline:duration_tick",
            "duration_tick_dependency_missing",
            {"blocking_dependency": "StatusLifecycle source admission for decrement/expire"},
        ),
        "extra_turn": scheduler._blocked(
            state,
            "timeline:extra_turn",
            "extra_turn_dependency_missing",
            {"blocking_dependency": "extra-turn queue/window admission"},
        ),
        "ultimate": scheduler._blocked(
            state,
            "timeline:ultimate",
            "ultimate_dependency_missing",
            {"blocking_dependency": "ultimate interrupt queue priority admission"},
        ),
        "interrupt": scheduler._blocked(
            state,
            "timeline:interrupt",
            "interrupt_dependency_missing",
            {"blocking_dependency": "interrupt window admission"},
        ),
    }
    source_audits = {name: RuntimeSourceAuditor(rules).validate_transition(item.transition) for name, item in cases.items()}
    checks = {}
    transitions = {}
    for name, item in cases.items():
        transition_checks = _transition_checks(item.transition, state)
        checks[f"{name}_contract"] = transition_checks["transition_contract"]
        checks[f"{name}_traceability"] = transition_checks["settlement_traceability"]
        checks[f"{name}_replay"] = transition_checks["replay"]
        checks[f"{name}_source_audit"] = source_audits[name].ok
        checks[f"{name}_after_unchanged"] = item.after_state.snapshot().to_json() == state.snapshot().to_json()
        checks[f"{name}_no_mutations"] = not item.transition.transaction.mutations
        transitions[name] = item.transition.to_json()
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "transitions": transitions,
        "source_audits": {name: audit.to_json() for name, audit in source_audits.items()},
    }


def _queue_priority_step_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for intent in _candidate_queue_intents(rules):
        callback = _require_callback(rules, intent)
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if resolution is None or resolution.coverage_status != "executable":
            continue
        if resolution.resolved_kind != "standalone_ability_graph":
            continue
        state = _state_with_callback_status(base_state, callback)
        enqueue_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(
            state,
            event=_event_for_callback(callback),
            unit_id=_unit_id_for_callback(callback),
            modifier_name=callback.modifier_name,
        )
        if not enqueue_result.mutations:
            failures.append({"queue_intent_id": intent.queue_intent_id, "reason": "enqueue_missing_mutation"})
            continue
        result = CombatScheduler(rules).step(enqueue_result.after_state)
        source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
        checks = _transition_checks(result.transition, enqueue_result.after_state)
        checks.update(
            {
                "source_audit": source_audit.ok,
                "queue_dequeue_present": any(
                    mutation.source == "queue_system" for mutation in result.transition.transaction.mutations
                ),
                "standalone_effect_present": any(
                    mutation.source in {"effect_system", "status_system", "status_callback_system", "damage_system"}
                    for mutation in result.transition.transaction.mutations
                ),
                "queue_entry_removed": len(result.after_state.queues.get(intent.queue_kind, ()))
                < len(enqueue_result.after_state.queues.get(intent.queue_kind, ())),
                "scheduler_used_queue_before_av": result.transition.transaction.command.action_id == "queue:drain_admitted",
                "scheduler_queue_record": any(
                    record.get("record_type") == "scheduler_queue_step"
                    for record in (result.transition.transaction.settlement.records if result.transition.transaction.settlement else ())
                ),
            }
        )
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "checks": checks,
            "queue_intent": intent.to_json(),
            "queue_resolution": resolution.to_json(),
            "transition": result.transition.to_json(),
            "source_audit": source_audit.to_json(),
            "selection_failures": failures[:10],
        }
    raise RuntimeError(f"no scheduler queue step case found; failures={failures[:5]}")


def _state_and_command_from_case(rules: RuleBook, case: dict[str, Any]) -> tuple[BattleState, ActionCommand]:
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(
            case["profile"],
            case["action"],
            case["avatar"],
            enemy_panel={"max_hp": 100000.0, "hp": 100000.0},
        )
    )
    identity_result = IdentityResolver(rules).validate(scenario)
    if not identity_result.ok:
        raise RuntimeError(f"structured scheduler scenario identity failed: {identity_result.errors}")
    build_result = ScenarioStateBuilder(rules).build(scenario)
    enemy = build_result.state.units["enemy:profile_target"]
    state = _state_with_toughness_binding(build_result.state, case["toughness_emission"], enemy.toughness)
    return state, build_result.commands[0]


def _make_actor_next(state: BattleState) -> BattleState:
    units = {}
    for unit_id, unit in state.units.items():
        if unit_id == "ally:actor":
            units[unit_id] = replace(unit, action_value=0.0)
        elif unit.side == "enemy":
            units[unit_id] = replace(unit, action_value=40.0, flags={**unit.flags, "ai_policy_admitted": False})
        else:
            units[unit_id] = replace(unit, action_value=80.0)
    return replace(state, units=units, skill_points=max(5, state.skill_points), global_flags={**state.global_flags, "current_window": "idle"})


def _timeline_state(*, ally_av: float, enemy_av: float, enemy_ai: bool) -> BattleState:
    from ..core.model import UnitState

    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:timeline_actor",
                max_hp=1000.0,
                hp=1000.0,
                speed=100.0,
                action_value=ally_av,
            ),
            "enemy:ai": UnitState(
                unit_id="enemy:ai",
                side="enemy",
                template_id="monster:timeline_enemy",
                max_hp=1000.0,
                hp=1000.0,
                speed=100.0,
                action_value=enemy_av,
                flags={"ai_policy_admitted": True} if enemy_ai else {},
            ),
        },
        global_flags={"phase": "scheduler_validation", "current_window": "idle"},
    )


def _unit_id_for_callback(callback) -> str:
    if "Monster" in callback.source.source_path:
        return "enemy:profile_target"
    return "ally:actor"


def _coverage_checks(coverage_json: dict[str, Any], rules: RuleBook) -> dict[str, object]:
    checks = {
        "canonical_ir_has_timeline_rule": rules.default_timeline_rule().coverage_status == "executable",
        "coverage_counts_timeline_rules": coverage_json.get("ir_summary", {}).get("timeline_rules", 0) >= 1,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "scheduler_step": {
            "semantic_status": "trusted_for_current_scope" if checks["manual_action_step"]["ok"] else "blocked",
            "scope": "queue priority check, natural AV advance, manual action child execution, turn end/reset",
        },
        "manual_turn_action": {
            "semantic_status": "trusted_for_current_scope" if checks["manual_action_step"]["ok"] else "blocked",
            "scope": "route/manual command only when actor matches current turn owner",
        },
        "queue_scheduler_bridge": {
            "semantic_status": "trusted_for_current_scope" if checks["queue_priority_step"]["ok"] else "blocked",
            "scope": "v0_242 admitted queue drain before natural AV advance",
        },
        "enemy_ai_action": {
            "semantic_status": "blocked",
            "blocking_dependency": "enemy AI action and target selection admission",
        },
        "extra_turn": {
            "semantic_status": "blocked",
            "blocking_dependency": "extra-turn queue/window admission",
        },
        "ultimate": {
            "semantic_status": "blocked",
            "blocking_dependency": "ultimate interrupt queue priority admission",
        },
        "interrupt": {
            "semantic_status": "blocked",
            "blocking_dependency": "interrupt window admission",
        },
        "full_status_duration_tick": {
            "semantic_status": "blocked",
            "blocking_dependency": "status lifecycle source admission for decrement and expire",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
