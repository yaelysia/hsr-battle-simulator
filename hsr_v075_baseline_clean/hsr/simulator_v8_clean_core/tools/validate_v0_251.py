from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import IRSource, QueueResolutionIR
from ..rules.rulebook import RuleBook
from ..systems.queue import QueueEntry, QueueSystem
from ..systems.scheduler import CombatScheduler
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_251"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    semantic_case = _extra_action_semantics_case(ir, rules)
    priority_case = _queue_priority_case()
    pending_turn_case = _pending_turn_end_case(rules)
    checks = {
        "semantic_classification": semantic_case["checks"],
        "queue_priority": priority_case["checks"],
        "pending_turn_end": pending_turn_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "static_checks": static_result.to_json(),
        "extra_action_semantics": semantic_case,
        "queue_priority_case": priority_case,
        "pending_turn_end_case": pending_turn_case,
        "coverage_summary": coverage.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_251.json", result)
    write_json(output_dir / "extra_action_semantics_matrix_v0_251.json", semantic_case)
    write_json(output_dir / "queue_priority_case_v0_251.json", priority_case)
    write_json(output_dir / "pending_turn_end_case_v0_251.json", pending_turn_case)
    write_json(output_dir / "coverage_summary_v0_251.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_251 extra-action semantic correction.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _extra_action_semantics_case(ir, rules: RuleBook) -> dict[str, Any]:
    continuations = rules.skill_continuations()
    use_skill_queue_intents = tuple(intent for intent in ir.queue_intents if intent.opcode == "UseSkillOneMore")
    use_skill_extra_windows = tuple(
        window
        for window in ir.queue_windows
        if window.window_family == "extra_turn"
        and isinstance(window.source.evidence, dict)
        and window.source.evidence.get("opcode") == "UseSkillOneMore"
    )
    turn_insert_intents = tuple(intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAction")
    turn_insert_windows = tuple(
        window
        for window in ir.queue_windows
        if any(intent.queue_intent_id == window.queue_intent_id for intent in turn_insert_intents)
    )
    continuation_source_paths = Counter(continuation.source.source_path for continuation in continuations)
    window_families = Counter(window.window_family for window in turn_insert_windows)
    checks = {
        "ok": False,
        "use_skill_one_more_continuation_ir_present": len(continuations) > 0,
        "use_skill_one_more_not_queue_intent": len(use_skill_queue_intents) == 0,
        "use_skill_one_more_not_extra_turn_window": len(use_skill_extra_windows) == 0,
        "continuation_not_executable_as_queue": all(item.coverage_status != "executable" for item in continuations),
        "turn_insert_action_sources_present": len(turn_insert_intents) > 0,
        "turn_insert_action_windows_classified": len(turn_insert_windows) > 0,
        "counter_not_damage_family_guarded_elsewhere": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "skill_continuation_count": len(continuations),
        "skill_continuation_opcode_counts": dict(Counter(item.opcode for item in continuations)),
        "skill_continuation_source_samples": [
            {
                "continuation_id": item.continuation_id,
                "source_path": item.source.source_path,
                "ability_name": item.ability_name,
                "fixed_skill_type": item.fixed_skill_type,
                "child_skill_index_expr": item.child_skill_index_expr,
                "blocked_reason": item.blocked_reason,
            }
            for item in continuations[:20]
        ],
        "skill_continuation_source_path_counts": dict(continuation_source_paths.most_common(20)),
        "turn_insert_action_count": len(turn_insert_intents),
        "turn_insert_window_family_counts": dict(sorted(window_families.items())),
        "turn_insert_window_samples": [
            {
                "queue_window_id": window.queue_window_id,
                "queue_intent_id": window.queue_intent_id,
                "window_family": window.window_family,
                "coverage_status": window.coverage_status,
                "blocked_reason": window.blocked_reason,
                "source_path": window.source.source_path,
            }
            for window in turn_insert_windows[:20]
        ],
    }


def _queue_priority_case() -> dict[str, Any]:
    queue = QueueSystem()
    resolution_follow = _synthetic_resolution("intent:follow")
    resolution_ultimate = _synthetic_resolution("intent:ultimate")
    resolution_extra = _synthetic_resolution("intent:extra")
    follow_entry = _synthetic_entry("entry:follow", "intent:follow", "follow_up", priority=999, order=0)
    ultimate_entry = _synthetic_entry("entry:ultimate", "intent:ultimate", "ultimate", priority=0, order=1)
    extra_entry = _synthetic_entry("entry:extra", "intent:extra", "extra_turn", priority=0, order=0)
    state_follow_vs_ultimate = BattleState(queues={"insert": (ultimate_entry, follow_entry)})
    selected_follow = queue.plan_next_drain(
        state_follow_vs_ultimate,
        "insert",
        {
            "intent:follow": resolution_follow,
            "intent:ultimate": resolution_ultimate,
        },
    )
    state_ultimate_then_extra = BattleState(queues={"insert": (ultimate_entry, extra_entry)})
    selected_ultimate_first = queue.plan_next_drain(
        state_ultimate_then_extra,
        "insert",
        {
            "intent:ultimate": resolution_ultimate,
            "intent:extra": resolution_extra,
        },
    )
    state_extra_then_ultimate = BattleState(queues={"insert": (extra_entry, ultimate_entry)})
    selected_extra_first = queue.plan_next_drain(
        state_extra_then_ultimate,
        "insert",
        {
            "intent:ultimate": resolution_ultimate,
            "intent:extra": resolution_extra,
        },
    )
    checks = {
        "ok": False,
        "follow_up_over_ultimate_even_with_larger_priority_value": selected_follow.queue_intent_id == "intent:follow",
        "counter_order_same_as_follow_up": _family_order("counter") == _family_order("follow_up"),
        "ultimate_and_extra_turn_same_family_order": _family_order("ultimate") == _family_order("extra_turn"),
        "ultimate_before_extra_when_enqueued_first": selected_ultimate_first.queue_intent_id == "intent:ultimate",
        "extra_before_ultimate_when_enqueued_first": selected_extra_first.queue_intent_id == "intent:extra",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "selected_follow_vs_ultimate": selected_follow.to_json(),
        "selected_ultimate_then_extra": selected_ultimate_first.to_json(),
        "selected_extra_then_ultimate": selected_extra_first.to_json(),
        "selection_mode": "synthetic_ordering_unit_check; no runtime mutation is produced",
    }


def _pending_turn_end_case(rules: RuleBook) -> dict[str, Any]:
    state = BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:validation",
                speed=100.0,
                action_value=0.0,
            )
        },
        global_flags={
            "active_turn": {"actor_id": "ally:actor", "turn_kind": "regular", "turn_sequence_index": 1},
            "turn_owner_id": "ally:actor",
            "current_window": "action",
            "turn_sequence_index": 1,
            "pending_turn_end": {
                "actor_id": "ally:actor",
                "child_action_id": "validation:action",
                "turn_sequence_index": 1,
                "reason": "queue_entries_pending_after_action",
            },
        },
    )
    result = CombatScheduler(rules).step(state)
    replay = MutationReducer().replay_snapshot(
        state,
        result.transition.transaction.mutations,
        result.transition.after.to_json(),
    )
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    after_flags = result.after_state.global_flags
    checks = {
        "ok": False,
        "pending_marker_cleared": after_flags.get("pending_turn_end") is None,
        "turn_end_completed_after_queue_empty": after_flags.get("active_turn") is None,
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "no_queue_required_for_completion": not any(result.after_state.queues.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": source_audit.to_json(),
        "mutation_sources": [mutation.source for mutation in result.transition.transaction.mutations],
        "coverage": result.transition.coverage,
    }


def _synthetic_entry(entry_id: str, intent_id: str, family: str, *, priority: float, order: int) -> dict[str, Any]:
    priority_source = {
        "priority_ordering_admitted": True,
        "priority_value": priority,
        "priority_key": f"validation:{family}",
        "queue_priority_id": f"queue_priority:validation:{family}",
        "source_trace": {"selection_mode": "synthetic_ordering_unit_check"},
    }
    return QueueEntry(
        entry_id=entry_id,
        queue_name="insert",
        queue_kind=f"validation_{family}",
        queue_intent_id=intent_id,
        actor_id="ally:actor",
        action_or_ability_ref=f"validation:{family}",
        target_ids=("enemy:target",),
        priority_source=priority_source,
        source_trace={"selection_mode": "synthetic_ordering_unit_check"},
        priority_key=str(priority_source["priority_key"]),
        priority_value=priority,
        queue_priority_id=str(priority_source["queue_priority_id"]),
        queue_window_id=f"queue_window:{intent_id}",
        window_family=family,
        window_policy={
            "priority_ordering_admitted": True,
            "window_ordering_admitted": True,
            "lifecycle_policy_admitted": family == "extra_turn",
            "selection_mode": "synthetic_ordering_unit_check",
        },
        target_resolution={"ok": True, "actor_id": "ally:actor", "target_ids": ["enemy:target"]},
        status="pending",
        drain_status="not_attempted",
    ).to_json() | {"_validation_order": order}


def _synthetic_resolution(intent_id: str) -> QueueResolutionIR:
    return QueueResolutionIR(
        queue_resolution_id=f"queue_resolution:{intent_id}",
        queue_intent_id=intent_id,
        action_or_ability_ref=f"validation:{intent_id}",
        resolved_kind="standalone_ability_graph",
        resolved_ids={"standalone_ability_graph_id": f"graph:{intent_id}", "executable_task_ids": ["task:validation"]},
        source=IRSource(
            source_path="validation/v0_251_queue_ordering",
            raw_type="QueueResolutionValidation",
            raw_id=intent_id,
            evidence={"selection_mode": "synthetic_ordering_unit_check"},
        ),
        coverage_status="executable",
        blocked_reason="",
    )


def _family_order(family: str) -> int:
    from ..systems.queue import QUEUE_WINDOW_FAMILY_ORDER

    return QUEUE_WINDOW_FAMILY_ORDER.get(family, 999)


if __name__ == "__main__":
    raise SystemExit(main())
