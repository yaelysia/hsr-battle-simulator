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
    GameEvent,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, QueueIntentIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..systems.status_callbacks import StatusCallbackSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_254"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    kill_chain = _kill_to_extra_turn_case(ir, rules)
    checks = {
        "kill_to_extra_turn": kill_chain["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "extra_turn_source": (
                    "Selected by executable TurnInsertAction + PrepareAbilityName, mainline Avatar source, "
                    "QueueWindowIR(window_family=extra_turn), QueueResolutionIR(extra_turn_action_choice); "
                    "no character name/action id/file hash selector."
                ),
                "extra_turn_action": (
                    "Selected from the same ability file as the queue source, executable ActionDefinitionIR, "
                    "non-ultimate action. Damage mutation is only expected when the selected action has admitted DamageEmissionIR."
                ),
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "kill_to_extra_turn_case": kill_chain,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_254.json", result)
    write_json(output_dir / "extra_turn_kill_chain_case_v0_254.json", kill_chain)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_254 kill-listener to true extra-turn action chain.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _kill_to_extra_turn_case(ir, rules: RuleBook) -> dict[str, Any]:
    intent = _select_extra_turn_prepare_action_intent(ir, rules)
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected queue intent has no status callback")
    death_callback = _matching_death_callback(rules, callback)
    action = _select_non_ultimate_action_for_callback_source(ir, rules, callback)
    initial_state = _state_with_extra_turn_listener(rules, callback, death_callback)
    callback_system = StatusCallbackSystem(rules, effect_registry=EffectRegistry(StatusSystem(rules)))

    death_result = callback_system.execute(
        initial_state,
        unit_id="ally:actor",
        modifier_name=callback.modifier_name,
        event=death_callback.event,
        trigger_event=GameEvent(
            "unit.defeated",
            source_id="ally:actor",
            target_id="enemy:defeated",
            window=death_callback.event,
            process_only=True,
            payload={
                "target_id": "enemy:defeated",
                "primary_target_id": "enemy:defeated",
                "is_current_skill_active": True,
                "is_insert_action": False,
            },
        ),
    )
    death_transition = _system_transition(
        before_state=initial_state,
        after_state=death_result.after_state,
        records=death_result.records,
        mutations=death_result.mutations,
        events=death_result.events,
        action_id="status_callback:on_trigger_death",
        metadata={
            "callback_id": death_callback.callback_id,
            "modifier_name": callback.modifier_name,
            "selected_queue_intent_id": intent.queue_intent_id,
        },
    )
    after_skill_result = callback_system.execute(
        death_result.after_state,
        unit_id="ally:actor",
        modifier_name=callback.modifier_name,
        event=callback.event,
        trigger_event=GameEvent(
            "action.after_skill_use",
            source_id="ally:actor",
            target_id="enemy:defeated",
            window=callback.event,
            process_only=True,
            payload={
                "target_id": "enemy:defeated",
                "primary_target_id": "enemy:defeated",
                "is_current_skill_active": False,
                "is_insert_action": False,
            },
        ),
    )
    after_skill_transition = _system_transition(
        before_state=death_result.after_state,
        after_state=after_skill_result.after_state,
        records=after_skill_result.records,
        mutations=after_skill_result.mutations,
        events=after_skill_result.events,
        action_id="status_callback:on_after_skill_use",
        metadata={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "selected_queue_intent_id": intent.queue_intent_id,
        },
    )
    route_command = ActionCommand(
        actor_id="ally:actor",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:alive",),
        source="manual",
        metadata={
            "crit_mode": "noncrit",
            "route_source": "validation_extra_turn_action_choice",
        },
    )
    scheduler_result = CombatScheduler(rules).step(after_skill_result.after_state, command=route_command)
    child = scheduler_result.child_transitions[0] if scheduler_result.child_transitions else None

    death_audit = RuntimeSourceAuditor(rules).validate_transition(death_transition)
    after_skill_audit = RuntimeSourceAuditor(rules).validate_transition(after_skill_transition)
    scheduler_audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
    child_audit = RuntimeSourceAuditor(rules).validate_transition(child) if child is not None else None
    initial_duration = _duration_guard_value(initial_state)
    final_duration = _duration_guard_value(scheduler_result.after_state)
    scheduler_events = [event.event_type for event in scheduler_result.transition.transaction.events]
    child_events = [event.event_type for event in child.transaction.events] if child is not None else []
    queue_entries_after_skill = _queue_entries(after_skill_result.after_state, intent.queue_kind)
    queue_entries_after_scheduler = _queue_entries(scheduler_result.after_state, intent.queue_kind)
    child_queue_parent = child.transaction.command.metadata.get("queue_parent", {}) if child is not None else {}
    child_window_plan = child_queue_parent.get("queue_window_plan", {}) if isinstance(child_queue_parent, dict) else {}
    checks = {
        **{f"death_{key}": value for key, value in _transition_checks(death_transition, initial_state).items()},
        **{f"after_skill_{key}": value for key, value in _transition_checks(after_skill_transition, death_result.after_state).items()},
        **{f"scheduler_{key}": value for key, value in _transition_checks(scheduler_result.transition, after_skill_result.after_state).items()},
        "death_source_audit": death_audit.ok,
        "after_skill_source_audit": after_skill_audit.ok,
        "scheduler_source_audit": scheduler_audit.ok,
        "child_source_audit": bool(child_audit and child_audit.ok),
        "death_listener_wrote_insert_action_flag": _dynamic_value_present(death_result.after_state, "InsertAction", 1.0),
        "after_skill_enqueued_extra_turn": bool(queue_entries_after_skill),
        "after_skill_queue_entry_window_extra_turn": any(entry.get("window_family") == "extra_turn" for entry in queue_entries_after_skill),
        "scheduler_drained_queue_first": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "queue_removed_after_drain": len(queue_entries_after_scheduler) < len(queue_entries_after_skill),
        "child_transition_present": child is not None,
        "child_source_queue": bool(child and child.transaction.command.source == "queue"),
        "child_action_is_route_selected_non_ultimate": bool(
            child
            and child.transaction.command.action_id == action.action_id
            and child.transaction.command.action_level == action.level
            and not _is_ultimate_action(action)
        ),
        "child_window_family_extra_turn": child_window_plan.get("window_family") == "extra_turn",
        "extra_turn_begin_and_end_events": "extra_turn.begin" in scheduler_events and "extra_turn.end" in scheduler_events,
        "ordinary_turn_begin_end_not_emitted": "turn.begin" not in scheduler_events and "turn.end" not in scheduler_events,
        "ordinary_duration_not_consumed": initial_duration == final_duration == 2,
        "child_action_did_not_emit_turn_lifecycle": "turn.begin" not in child_events and "turn.end" not in child_events,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_queue_intent": intent.to_json(),
        "selected_status_callback": callback.to_json(),
        "selected_death_callback": death_callback.to_json(),
        "selected_extra_turn_action": action.to_json(),
        "observed_blocked_subtasks": {
            "death": list(death_result.errors),
            "after_skill_use": list(after_skill_result.errors),
        },
        "unexpected_effect_check": {
            "normal_turn_events_absent": checks["ordinary_turn_begin_end_not_emitted"],
            "duration_guard_before": initial_duration,
            "duration_guard_after": final_duration,
            "queue_count_after_skill": len(queue_entries_after_skill),
            "queue_count_after_scheduler": len(queue_entries_after_scheduler),
        },
        "source_audits": {
            "death": death_audit.to_json(),
            "after_skill": after_skill_audit.to_json(),
            "scheduler": scheduler_audit.to_json(),
            "child": child_audit.to_json() if child_audit is not None else {},
        },
        "transitions": {
            "death_listener": death_transition.to_json(),
            "after_skill_listener": after_skill_transition.to_json(),
            "scheduler": scheduler_result.transition.to_json(),
            "child_action": child.to_json() if child is not None else {},
        },
    }


def _select_extra_turn_prepare_action_intent(ir, rules: RuleBook) -> QueueIntentIR:
    for intent in sorted(ir.queue_intents, key=lambda item: item.queue_intent_id):
        if intent.opcode != "TurnInsertAction" or intent.coverage_status != "executable":
            continue
        if intent.skill_index_expr.get("source_field") != "PrepareAbilityName":
            continue
        if not intent.source.source_path.startswith("Config/ConfigAbility/Avatar/"):
            continue
        if _blocked_source_path(intent.source.source_path):
            continue
        window = rules.queue_window_for_intent(intent.queue_intent_id)
        resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
        if window is None or resolution is None:
            continue
        if window.window_family != "extra_turn" or window.coverage_status != "executable":
            continue
        if resolution.resolved_kind != "extra_turn_action_choice" or resolution.coverage_status != "executable":
            continue
        callback = rules.status_callback(intent.callback_id)
        if callback is None or callback.event != "OnAfterSkillUse" or callback.coverage_status != "executable":
            continue
        try:
            _matching_death_callback(rules, callback)
            _select_non_ultimate_action_for_callback_source(ir, rules, callback)
        except RuntimeError:
            continue
        return intent
    raise RuntimeError("no executable mainline Avatar TurnInsertAction PrepareAbilityName extra-turn intent found")


def _matching_death_callback(rules: RuleBook, callback: StatusCallbackIR) -> StatusCallbackIR:
    for event in ("OnTriggerDeath", "OnTriggerDeathrattle"):
        for candidate in rules.status_callbacks_for_modifier_event(callback.modifier_name, event):
            if candidate.source.source_path != callback.source.source_path:
                continue
            if candidate.coverage_status == "executable":
                return candidate
    raise RuntimeError("selected extra-turn listener has no executable same-source death callback")


def _select_non_ultimate_action_for_callback_source(ir, rules: RuleBook, callback: StatusCallbackIR) -> ActionDefinitionIR:
    selected: ActionDefinitionIR | None = None
    for action in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.coverage_status != "executable" or _is_ultimate_action(action):
            continue
        if action.target_mode not in {"single", "blast", "aoe"}:
            continue
        binding = rules.action_ability_binding(action.action_id, action.level)
        if binding is None or binding.coverage_status != "executable":
            continue
        ability_file = ""
        evidence = binding.source.evidence if isinstance(binding.source.evidence, dict) else {}
        raw_ability = evidence.get("ability_file")
        if isinstance(raw_ability, str):
            ability_file = raw_ability
        if ability_file != callback.source.source_path:
            continue
        if rules.action_event(action.action_id, action.level) is None:
            continue
        if action.level == 10:
            return action
        selected = selected or action
    if selected is None:
        raise RuntimeError("no executable non-ultimate action found for selected extra-turn source")
    return selected


def _state_with_extra_turn_listener(rules: RuleBook, callback: StatusCallbackIR, death_callback: StatusCallbackIR) -> BattleState:
    action_dynamic_keys = _dynamic_values_written_by_callback(rules, death_callback)
    status_dynamic_values = _initial_status_dynamic_values(rules, callback, exclude_keys=action_dynamic_keys)
    actor = UnitState(
        unit_id="ally:actor",
        side="ally",
        template_id=_template_id_from_callback(callback),
        level=80,
        max_hp=5000.0,
        hp=5000.0,
        attack=1000.0,
        defense=100.0,
        speed=100.0,
        energy=0.0,
        max_energy=120.0,
        resources={"critical_chance": 0.0, "critical_damage": 0.5},
    )
    status_id = f"modifier:{callback.modifier_name}"
    listener_detail = {
        "instance_id": f"validation:{callback.callback_id}",
        "status_id": status_id,
        "modifier_name": callback.modifier_name,
        "owner_id": "ally:actor",
        "caster_id": "ally:actor",
        "source_id": callback.callback_id,
        "source_trace": {"status_callback": callback.source.to_json()},
        "trigger_ids_by_event": {
            callback.event: [callback.callback_id],
            death_callback.event: [death_callback.callback_id],
        },
        "dynamic_values": status_dynamic_values,
    }
    duration_guard = {
        "instance_id": "validation:duration_guard",
        "status_id": "modifier:validation_duration_guard",
        "modifier_name": "validation_duration_guard",
        "owner_id": "ally:actor",
        "caster_id": "ally:actor",
        "source_trace": {"validation": "extra_turn_should_not_tick_normal_duration"},
        "remaining_duration": 2,
        "life_step_moment": "ActionPhaseEnd",
    }
    actor = replace(
        actor,
        statuses=(status_id, "modifier:validation_duration_guard"),
        flags={"status_details": (listener_detail, duration_guard)},
    )
    defeated = UnitState(
        unit_id="enemy:defeated",
        side="enemy",
        template_id="monster:validation_defeated",
        level=80,
        max_hp=1000.0,
        hp=0.0,
        defense=100.0,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Quantum", "Physical")},
    )
    alive = UnitState(
        unit_id="enemy:alive",
        side="enemy",
        template_id="monster:validation_alive",
        level=80,
        max_hp=20000.0,
        hp=20000.0,
        defense=100.0,
        speed=100.0,
        flags={"position": 1, "weaknesses": ("Quantum", "Physical")},
    )
    return BattleState(
        units={"ally:actor": actor, "enemy:defeated": defeated, "enemy:alive": alive},
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "validation"},
    )


def _dynamic_values_written_by_callback(rules: RuleBook, callback: StatusCallbackIR) -> set[str]:
    names: set[str] = set()
    for task in rules.status_callback_tasks_for_callback(callback.callback_id):
        if not task.effect_id:
            continue
        effect = rules.effect(task.effect_id)
        if effect is None:
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if isinstance(standard, dict) and standard.get("kind") == "dynamic_value_store":
            value_name = standard.get("value_name")
            if isinstance(value_name, str) and value_name:
                names.add(value_name)
    return names


def _initial_status_dynamic_values(rules: RuleBook, callback: StatusCallbackIR, *, exclude_keys: set[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for task in rules.status_callback_tasks_for_callback(callback.callback_id):
        if not task.condition_id:
            continue
        condition = rules.condition(task.condition_id)
        if condition is None:
            continue
        _collect_equal_zero_dynamic_conditions(condition.payload, values, exclude_keys=exclude_keys)
    return values


def _collect_equal_zero_dynamic_conditions(payload: Any, values: dict[str, float], *, exclude_keys: set[str]) -> None:
    if not isinstance(payload, dict):
        return
    opcode = str(payload.get("$type") or "")
    if opcode.endswith("ByCompareDynamicValue") or ("DynamicKey" in payload and "CompareValue" in payload):
        key = _value_field(payload.get("DynamicKey"))
        compare_type = payload.get("CompareType")
        compare_value = _fixed_numeric_value(payload.get("CompareValue"))
        if isinstance(key, str) and key not in exclude_keys and compare_type == "Equal" and compare_value == 0.0:
            values[key] = 0.0
    for child in payload.get("PredicateList", ()) if isinstance(payload.get("PredicateList"), list) else ():
        _collect_equal_zero_dynamic_conditions(child, values, exclude_keys=exclude_keys)
    child = payload.get("Predicate")
    if isinstance(child, dict):
        _collect_equal_zero_dynamic_conditions(child, values, exclude_keys=exclude_keys)


def _template_id_from_callback(callback: StatusCallbackIR) -> str:
    path = callback.source.source_path
    stem = path.rsplit("/", 1)[-1].replace("_Ability.json", "")
    return f"avatar:{stem}"


def _dynamic_value_present(state: BattleState, name: str, value: float) -> bool:
    store = state.global_flags.get("dynamic_value_store")
    if not isinstance(store, dict):
        return False
    by_name = store.get("by_name")
    entries = store.get("entries")
    if not isinstance(by_name, dict) or not isinstance(entries, dict):
        return False
    ids = by_name.get(name)
    if not isinstance(ids, list):
        return False
    for entry_id in ids:
        entry = entries.get(entry_id)
        if isinstance(entry, dict) and float(entry.get("value") or 0.0) == value:
            return True
    return False


def _duration_guard_value(state: BattleState) -> int | None:
    actor = state.units.get("ally:actor")
    if actor is None:
        return None
    for detail in actor.flags.get("status_details", ()):
        if isinstance(detail, dict) and detail.get("modifier_name") == "validation_duration_guard":
            value = detail.get("remaining_duration")
            return int(value) if isinstance(value, int) else None
    return None


def _queue_entries(state: BattleState, queue_name: str) -> tuple[dict[str, Any], ...]:
    return tuple(item for item in state.queues.get(queue_name, ()) if isinstance(item, dict))


def _system_transition(
    *,
    before_state: BattleState,
    after_state: BattleState,
    records: tuple[dict[str, Any], ...],
    mutations: tuple[Any, ...],
    events: tuple[GameEvent, ...],
    action_id: str,
    metadata: dict[str, Any],
) -> BattleTransition:
    command = ActionCommand(
        actor_id="ally:actor",
        action_id=action_id,
        action_level=0,
        target_ids=("enemy:alive",),
        source="manual",
        metadata=metadata,
    )
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=command.target_ids,
        records=tuple(records),
    )
    transaction = ActionTransaction(
        command=command,
        before=before_state.snapshot(),
        events=tuple(events),
        mutations=tuple(mutations),
        settlement=settlement,
    )
    return BattleTransition(
        transaction=transaction,
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=("enemy:alive",),
            legal=("enemy:alive",),
            selected=("enemy:alive",),
            reason=action_id,
            source="validation_system_transition",
        ),
        coverage={"validation_action": action_id, "mutation_count": len(tuple(mutations))},
    )


def _transition_checks(transition: BattleTransition, before_state: BattleState) -> dict[str, bool]:
    traceability = SettlementTraceabilityValidator().validate(transition.transaction.settlement, transition.transaction.mutations)
    contract = TransitionContractValidator().validate(transition)
    snapshot = SnapshotCompletenessValidator().validate(before_state.snapshot())
    replay = MutationReducer().replay_snapshot(before_state, transition.transaction.mutations, transition.after.to_json())
    return {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "snapshot_completeness": snapshot.ok,
        "replay": replay.ok,
    }


def _is_ultimate_action(action: ActionDefinitionIR) -> bool:
    return str(action.attack_type).lower() == "ultra" or str(action.skill_effect).lower() == "ultra"


def _blocked_source_path(path: str) -> bool:
    return any(marker in path for marker in ("Rogue", "Activity", "GridFight", "ElationBattle", "Fate", "Story", "Level/", "SubLevelGraph", "Chess"))


def _fixed_numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, dict):
        return None
    if "Value" in value:
        return _fixed_numeric_value(value.get("Value"))
    fixed = value.get("FixedValue")
    if isinstance(fixed, dict):
        return _fixed_numeric_value(fixed)
    return None


def _value_field(value: Any) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return value.get("Value")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
