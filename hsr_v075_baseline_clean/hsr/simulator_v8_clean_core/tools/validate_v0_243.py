from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.rulebook import RuleBook
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
from .validate_v0_235 import _execute_break_setup, _select_break_family_case, _transition_checks
from .validate_v0_237 import _event_for_callback, _state_with_callback_status
from .validate_v0_242 import _candidate_queue_intents, _require_callback


VALIDATION_VERSION = "v0_243"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    timeline_case = _timeline_advance_case(rules)
    initialize_case = _initialize_override_case(rules)
    enemy_case = _enemy_ai_blocked_case(rules)
    unsupported_case = _unsupported_hooks_case(rules)
    break_setup = _execute_break_setup(rules, _select_break_family_case(ir, rules))
    queue_case = _queue_scheduler_bridge_case(rules, break_setup["initial_state"])

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), ir),
        "timeline_advance": timeline_case["checks"],
        "timeline_initialize": initialize_case["checks"],
        "enemy_ai_blocked": enemy_case["checks"],
        "unsupported_hooks": unsupported_case["checks"],
        "queue_scheduler_bridge": queue_case["checks"],
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
            "selected_queue_intent": queue_case.get("queue_intent", {}),
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "timeline_advance": timeline_case["source_audit"],
            "timeline_end": timeline_case["end_source_audit"],
            "timeline_initialize": initialize_case["source_audit"],
            "queue_scheduler_bridge": queue_case["source_audit"],
            "enemy_ai_blocked": enemy_case["source_audit"],
            "unsupported_hooks": unsupported_case["source_audits"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_243.json", result)
    write_json(output_dir / "sample_timeline_advance_transition_v0_243.json", timeline_case["transition"])
    write_json(output_dir / "sample_timeline_end_transition_v0_243.json", timeline_case["end_transition"])
    write_json(output_dir / "sample_queue_scheduler_bridge_transition_v0_243.json", queue_case["transition"])
    write_json(output_dir / "coverage_summary_v0_243.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_243 timeline scheduler and turn advance.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _timeline_advance_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(
        ally_a_av=50.0,
        ally_b_av=20.0,
        enemy_av=80.0,
        enemy_ai=False,
    )
    scheduler = CombatScheduler(rules)
    result = scheduler.advance_to_next_turn(state)
    end_result = scheduler.end_current_turn(result.after_state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    end_audit = RuntimeSourceAuditor(rules).validate_transition(end_result.transition)
    checks = _transition_checks(result.transition, state)
    end_checks = _transition_checks(end_result.transition, result.after_state)
    actor = result.after_state.units["ally:fast"]
    ended_actor = end_result.after_state.units["ally:fast"]
    checks.update(
        {
            "source_audit": source_audit.ok,
            "selected_fast_actor": result.transition.transaction.command.actor_id == "ally:fast",
            "global_av_advanced": result.after_state.global_flags.get("global_av") == 20.0,
            "slow_actor_av_reduced": result.after_state.units["ally:slow"].action_value == 30.0,
            "active_turn_set": result.after_state.global_flags.get("active_turn", {}).get("actor_id") == "ally:fast",
            "actor_av_zero_at_turn_begin": actor.action_value == 0.0,
            "turn_end_contract": end_checks["transition_contract"],
            "turn_end_traceability": end_checks["settlement_traceability"],
            "turn_end_replay": end_checks["replay"],
            "turn_end_source_audit": end_audit.ok,
            "turn_end_reset_av": ended_actor.action_value == 100.0,
            "turn_end_clears_active_turn": "active_turn" not in end_result.after_state.global_flags,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "transition": result.transition.to_json(),
        "end_transition": end_result.transition.to_json(),
        "source_audit": source_audit.to_json(),
        "end_source_audit": end_audit.to_json(),
    }


def _initialize_override_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(ally_a_av=0.0, ally_b_av=12.0, enemy_av=0.0, enemy_ai=False)
    result = CombatScheduler(rules).initialize_timeline(state, explicit_overrides=("ally:fast",))
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "explicit_override_preserved": result.after_state.units["ally:fast"].action_value == 12.0,
            "non_override_initialized": result.after_state.units["ally:slow"].action_value == 100.0,
            "enemy_initialized": result.after_state.units["enemy:ai"].action_value == 100.0,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": result.transition.to_json(), "source_audit": source_audit.to_json()}


def _enemy_ai_blocked_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(ally_a_av=50.0, ally_b_av=70.0, enemy_av=0.0, enemy_ai=False)
    result = CombatScheduler(rules).advance_to_next_turn(state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, state)
    blocked_reason = str(result.transition.coverage.get("blocked_reason") or "")
    checks.update(
        {
            "source_audit": source_audit.ok,
            "enemy_ai_blocked": blocked_reason
            in {"enemy_ai_missing", "enemy_monster_data_card_id_missing"},
            "after_snapshot_unchanged": result.after_state.snapshot().to_json() == state.snapshot().to_json(),
            "no_mutations": not result.transition.transaction.mutations,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": result.transition.to_json(), "source_audit": source_audit.to_json()}


def _unsupported_hooks_case(rules: RuleBook) -> dict[str, Any]:
    state = _timeline_state(ally_a_av=0.0, ally_b_av=20.0, enemy_av=40.0, enemy_ai=False)
    scheduler = CombatScheduler(rules)
    duration = scheduler._blocked(
        state,
        "timeline:duration_tick",
        "duration_tick_dependency_missing",
        {"blocking_dependency": "StatusLifecycle source admission for decrement/expire"},
    )
    speed = scheduler._blocked(
        state,
        "timeline:speed_recompute",
        "speed_recompute_dependency_missing",
        {"blocking_dependency": "admitted speed modifier source and AV rescale rule"},
    )
    duration_audit = RuntimeSourceAuditor(rules).validate_transition(duration.transition)
    speed_audit = RuntimeSourceAuditor(rules).validate_transition(speed.transition)
    duration_checks = _transition_checks(duration.transition, state)
    speed_checks = _transition_checks(speed.transition, state)
    checks = {
        "duration_contract": duration_checks["transition_contract"],
        "duration_traceability": duration_checks["settlement_traceability"],
        "duration_replay": duration_checks["replay"],
        "duration_source_audit": duration_audit.ok,
        "duration_after_unchanged": duration.after_state.snapshot().to_json() == state.snapshot().to_json(),
        "speed_contract": speed_checks["transition_contract"],
        "speed_traceability": speed_checks["settlement_traceability"],
        "speed_replay": speed_checks["replay"],
        "speed_source_audit": speed_audit.ok,
        "speed_after_unchanged": speed.after_state.snapshot().to_json() == state.snapshot().to_json(),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "source_audits": {"duration": duration_audit.to_json(), "speed": speed_audit.to_json()},
        "transitions": {"duration": duration.transition.to_json(), "speed": speed.transition.to_json()},
    }


def _queue_scheduler_bridge_case(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
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
        result = CombatScheduler(rules).advance_to_next_turn(enqueue_result.after_state)
        source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
        checks = _transition_checks(result.transition, enqueue_result.after_state)
        checks.update(
            {
                "source_audit": source_audit.ok,
                "queue_dequeue_present": any(mutation.source == "queue_system" for mutation in result.transition.transaction.mutations),
                "standalone_effect_present": any(
                    mutation.source in {"effect_system", "status_system", "status_callback_system", "damage_system"}
                    for mutation in result.transition.transaction.mutations
                ),
                "queue_entry_removed": len(result.after_state.queues.get(intent.queue_kind, ()))
                < len(enqueue_result.after_state.queues.get(intent.queue_kind, ())),
                "scheduler_used_queue_before_av": result.transition.transaction.command.action_id == "queue:drain_admitted",
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
    raise RuntimeError(f"no scheduler queue bridge case found; failures={failures[:5]}")


def _timeline_state(*, ally_a_av: float, ally_b_av: float, enemy_av: float, enemy_ai: bool) -> BattleState:
    return BattleState(
        units={
            "ally:slow": UnitState(
                unit_id="ally:slow",
                side="ally",
                template_id="avatar:timeline_slow",
                max_hp=1000.0,
                hp=1000.0,
                speed=100.0,
                action_value=ally_a_av,
            ),
            "ally:fast": UnitState(
                unit_id="ally:fast",
                side="ally",
                template_id="avatar:timeline_fast",
                max_hp=1000.0,
                hp=1000.0,
                speed=100.0,
                action_value=ally_b_av,
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
        global_flags={"phase": "timeline_validation", "current_window": "idle"},
    )


def _unit_id_for_callback(callback) -> str:
    if "Monster" in callback.source.source_path:
        return "enemy:profile_target"
    return "ally:actor"


def _coverage_checks(coverage_json: dict[str, Any], ir) -> dict[str, object]:
    checks = {
        "canonical_ir_has_timeline_rule": len(ir.timeline_rules) >= 1,
        "timeline_rule_executable": any(rule.coverage_status == "executable" for rule in ir.timeline_rules),
        "coverage_counts_timeline_rules": coverage_json.get("ir_summary", {}).get("timeline_rules", 0) >= 1,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "timeline_av_advance": {
            "semantic_status": "trusted_for_current_scope" if checks["timeline_advance"]["ok"] else "blocked",
            "scope": "natural AV advance by admitted TimelineRuleIR engine convention 10000 / speed",
        },
        "turn_begin_end": {
            "semantic_status": "trusted_for_current_scope" if checks["timeline_advance"]["ok"] else "blocked",
            "scope": "turn begin/end flags and regular turn action_value reset",
        },
        "queue_scheduler_bridge": {
            "semantic_status": "trusted_for_current_scope" if checks["queue_scheduler_bridge"]["ok"] else "blocked",
            "scope": "v0_242 admitted queue drain before natural AV advance",
        },
        "enemy_ai_action": {
            "semantic_status": "blocked",
            "blocking_dependency": "enemy AI action and target selection admission",
        },
        "full_status_duration_tick": {
            "semantic_status": "blocked",
            "blocking_dependency": "status lifecycle source admission for decrement and expire",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
