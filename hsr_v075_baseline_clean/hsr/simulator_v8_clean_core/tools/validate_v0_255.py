from __future__ import annotations

import argparse
from dataclasses import replace
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
    GameEvent,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import (
    _blocked_source_path,
    _duration_guard_value,
    _dynamic_value_present,
    _is_ultimate_action,
    _matching_death_callback,
    _queue_entries,
    _select_extra_turn_prepare_action_intent,
    _select_non_ultimate_action_for_callback_source,
    _state_with_extra_turn_listener,
    _system_transition,
    _transition_checks,
)


VALIDATION_VERSION = "v0_255"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    automatic_chain = _automatic_kill_to_extra_turn_case(ir, rules)
    attribution = _kill_attribution_case(rules)
    checks = {
        "automatic_kill_to_extra_turn": automatic_chain["checks"],
        "kill_attribution": attribution["checks"],
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
                    "Reuses v0_254 structured selector: executable TurnInsertAction + PrepareAbilityName, "
                    "mainline Avatar source, QueueWindowIR(window_family=extra_turn), no role/action/file/hash selector."
                ),
                "damage_source": (
                    "Selected by executable ActionDefinitionIR with executable DamageEmissionIR and admitted ActionEventIR. "
                    "It is intentionally independent from the selected Seele callback source when that source has no "
                    "admitted DamageEmissionIR; the remaining same-source gap is reported instead of faked."
                ),
            },
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "automatic_kill_to_extra_turn_case": automatic_chain,
        "kill_attribution_case": attribution,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_255.json", result)
    write_json(output_dir / "automatic_kill_extra_turn_case_v0_255.json", automatic_chain)
    write_json(output_dir / "kill_attribution_case_v0_255.json", attribution)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 damage-caused kill attribution and automatic extra-turn trigger.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _automatic_kill_to_extra_turn_case(ir, rules: RuleBook) -> dict[str, Any]:
    intent = _select_extra_turn_prepare_action_intent(ir, rules)
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected queue intent has no status callback")
    death_callback = _matching_death_callback(rules, callback)
    extra_turn_action = _select_non_ultimate_action_for_callback_source(ir, rules, callback)
    damage_action = _select_executable_damage_action(ir, rules)
    same_source_damage_gap = _same_source_damage_gap(rules, extra_turn_action)

    initial_state = _state_with_extra_turn_listener(rules, callback, death_callback)
    initial_state = _with_unit_hp(initial_state, "enemy:defeated", hp=1.0, max_hp=1000.0)
    damage_command = ActionCommand(
        actor_id="ally:actor",
        action_id=damage_action.action_id,
        action_level=damage_action.level,
        target_ids=("enemy:defeated",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_automatic_kill_damage"},
    )
    after_damage_state, damage_transition = CombatExecutor(rules).execute(damage_command, initial_state)
    defeat_events = _events_of_type(damage_transition, "unit.defeated")
    defeat_event = defeat_events[0] if defeat_events else None

    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    after_skill_event = GameEvent(
        "action.after_skill_use",
        source_id="ally:actor",
        target_id="enemy:defeated",
        window="OnAfterSkillUse",
        process_only=True,
        payload={
            "target_id": "enemy:defeated",
            "primary_target_id": "enemy:defeated",
            "current_hit_target_id": "enemy:defeated",
            "is_current_skill_active": False,
            "is_insert_action": False,
        },
    )
    after_skill_result = dispatcher.dispatch_event(after_damage_state, event=after_skill_event)
    after_skill_transition = _system_transition(
        before_state=after_damage_state,
        after_state=after_skill_result.after_state,
        records=after_skill_result.records,
        mutations=after_skill_result.mutations,
        events=after_skill_result.events,
        action_id="event_dispatch:on_after_skill_use",
        metadata={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "selected_queue_intent_id": intent.queue_intent_id,
        },
    )

    route_command = ActionCommand(
        actor_id="ally:actor",
        action_id=extra_turn_action.action_id,
        action_level=extra_turn_action.level,
        target_ids=("enemy:alive",),
        source="manual",
        metadata={
            "crit_mode": "noncrit",
            "route_source": "validation_extra_turn_action_choice",
        },
    )
    scheduler_result = CombatScheduler(rules).step(after_skill_result.after_state, command=route_command)
    child = scheduler_result.child_transitions[0] if scheduler_result.child_transitions else None

    damage_audit = RuntimeSourceAuditor(rules).validate_transition(damage_transition)
    after_skill_audit = RuntimeSourceAuditor(rules).validate_transition(after_skill_transition)
    scheduler_audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
    child_audit = RuntimeSourceAuditor(rules).validate_transition(child) if child is not None else None
    queue_entries_after_skill = _queue_entries(after_skill_result.after_state, intent.queue_kind)
    queue_entries_after_scheduler = _queue_entries(scheduler_result.after_state, intent.queue_kind)
    initial_duration = _duration_guard_value(initial_state)
    final_duration = _duration_guard_value(scheduler_result.after_state)
    scheduler_events = [event.event_type for event in scheduler_result.transition.transaction.events]
    child_events = [event.event_type for event in child.transaction.events] if child is not None else []
    child_queue_parent = child.transaction.command.metadata.get("queue_parent", {}) if child is not None else {}
    child_window_plan = child_queue_parent.get("queue_window_plan", {}) if isinstance(child_queue_parent, dict) else {}
    defeat_payload = defeat_event.payload if defeat_event is not None else {}
    checks = {
        **{f"damage_{key}": value for key, value in _transition_checks(damage_transition, initial_state).items()},
        **{f"after_skill_{key}": value for key, value in _transition_checks(after_skill_transition, after_damage_state).items()},
        **{f"scheduler_{key}": value for key, value in _transition_checks(scheduler_result.transition, after_skill_result.after_state).items()},
        "damage_source_audit": damage_audit.ok,
        "after_skill_source_audit": after_skill_audit.ok,
        "scheduler_source_audit": scheduler_audit.ok,
        "child_source_audit": bool(child_audit and child_audit.ok),
        "damage_transition_emitted_unit_defeated": bool(defeat_events),
        "single_unit_defeated_event": len(defeat_events) == 1,
        "defeat_event_credits_damage_actor": defeat_payload.get("killer_id") == "ally:actor",
        "defeat_event_is_damage_caused": defeat_payload.get("caused_by_damage") is True,
        "death_listener_wrote_insert_action_flag": _dynamic_value_present(after_damage_state, "InsertAction", 1.0),
        "after_skill_enqueued_extra_turn": bool(queue_entries_after_skill),
        "after_skill_queue_entry_window_extra_turn": any(entry.get("window_family") == "extra_turn" for entry in queue_entries_after_skill),
        "scheduler_drained_queue_first": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "queue_removed_after_drain": len(queue_entries_after_scheduler) < len(queue_entries_after_skill),
        "child_transition_present": child is not None,
        "child_source_queue": bool(child and child.transaction.command.source == "queue"),
        "child_action_is_route_selected_non_ultimate": bool(
            child
            and child.transaction.command.action_id == extra_turn_action.action_id
            and child.transaction.command.action_level == extra_turn_action.level
            and not _is_ultimate_action(extra_turn_action)
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
        "selected_damage_action": damage_action.to_json(),
        "selected_extra_turn_action": extra_turn_action.to_json(),
        "same_source_damage_gap": same_source_damage_gap,
        "defeat_events": [event.to_json() for event in defeat_events],
        "source_audits": {
            "damage": damage_audit.to_json(),
            "after_skill": after_skill_audit.to_json(),
            "scheduler": scheduler_audit.to_json(),
            "child": child_audit.to_json() if child_audit is not None else {},
        },
        "unexpected_effect_check": {
            "normal_turn_events_absent": checks["ordinary_turn_begin_end_not_emitted"],
            "duration_guard_before": initial_duration,
            "duration_guard_after": final_duration,
            "queue_count_after_skill": len(queue_entries_after_skill),
            "queue_count_after_scheduler": len(queue_entries_after_scheduler),
        },
        "transitions": {
            "damage_action": damage_transition.to_json(),
            "after_skill_listener": after_skill_transition.to_json(),
            "scheduler": scheduler_result.transition.to_json(),
            "child_action": child.to_json() if child is not None else {},
        },
    }


def _kill_attribution_case(rules: RuleBook) -> dict[str, Any]:
    state = BattleState(
        units={
            "ally:first": UnitState("ally:first", "ally", "avatar:first", hp=1000.0, max_hp=1000.0),
            "ally:lethal": UnitState("ally:lethal", "ally", "avatar:lethal", hp=1000.0, max_hp=1000.0),
            "enemy:victim": UnitState("enemy:victim", "enemy", "monster:victim", hp=10.0, max_hp=10.0),
        },
        skill_points=5,
        max_skill_points=5,
    )
    reducer = MutationReducer()
    damage = DamageSystem()
    first = damage.apply_packet(state, _unit_packet("ally:first", "enemy:victim", 4.0))
    state_after_first = reducer.apply_all(state, first.mutations)
    lethal = damage.apply_packet(state_after_first, _unit_packet("ally:lethal", "enemy:victim", 6.0))
    state_after_lethal = reducer.apply_all(state_after_first, lethal.mutations)
    after_dead = damage.apply_packet(state_after_lethal, _unit_packet("ally:first", "enemy:victim", 6.0))
    defeat_events = [
        event
        for result in (first, lethal, after_dead)
        for event in result.events
        if event.event_type == "unit.defeated"
    ]

    intent = _select_extra_turn_prepare_action_intent(rules.ir, rules)
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected queue intent has no status callback")
    death_callback = _matching_death_callback(rules, callback)
    listener_state = _state_with_extra_turn_listener(rules, callback, death_callback)
    listener_state = replace(
        listener_state,
        units={
            **listener_state.units,
            "ally:other": UnitState("ally:other", "ally", "avatar:other", hp=1000.0, max_hp=1000.0),
        },
    )
    wrong_owner_event = GameEvent(
        "unit.defeated",
        source_id="ally:other",
        target_id="enemy:defeated",
        window="unit.defeated",
        process_only=True,
        payload={
            "actor_id": "ally:other",
            "attacker_id": "ally:other",
            "killer_id": "ally:other",
            "target_id": "enemy:defeated",
            "defeated_unit_id": "enemy:defeated",
            "current_hit_target_id": "enemy:defeated",
            "primary_target_id": "enemy:defeated",
            "is_current_skill_active": True,
            "is_insert_action": False,
            "caused_by_damage": True,
        },
    )
    wrong_owner_result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(listener_state, event=wrong_owner_event)
    checks = {
        "first_nonlethal_no_defeat_event": not _events_of_type_result(first, "unit.defeated"),
        "lethal_packet_has_defeat_event": len(_events_of_type_result(lethal, "unit.defeated")) == 1,
        "after_dead_packet_no_defeat_event": not _events_of_type_result(after_dead, "unit.defeated"),
        "only_one_defeat_event": len(defeat_events) == 1,
        "lethal_packet_gets_kill_credit": bool(defeat_events and defeat_events[0].payload.get("killer_id") == "ally:lethal"),
        "wrong_owner_listener_no_mutation": not wrong_owner_result.mutations,
        "wrong_owner_listener_state_unchanged": listener_state.snapshot().to_json() == wrong_owner_result.after_state.snapshot().to_json(),
        "wrong_owner_no_insert_action_flag": not _dynamic_value_present(wrong_owner_result.after_state, "InsertAction", 1.0),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "unit_damage_sequence": {
            "first_events": [event.to_json() for event in first.events],
            "lethal_events": [event.to_json() for event in lethal.events],
            "after_dead_events": [event.to_json() for event in after_dead.events],
            "defeat_events": [event.to_json() for event in defeat_events],
        },
        "wrong_owner_dispatch": {
            "event": wrong_owner_event.to_json(),
            "records": list(wrong_owner_result.records),
            "mutation_count": len(wrong_owner_result.mutations),
            "errors": list(wrong_owner_result.errors),
        },
    }


def _select_executable_damage_action(ir, rules: RuleBook) -> ActionDefinitionIR:
    candidates: list[ActionDefinitionIR] = []
    for definition in sorted(ir.action_definitions, key=lambda item: (item.target_mode != "single", item.action_id, item.level)):
        if definition.coverage_status != "executable" or definition.damage_kind != "hp_damage":
            continue
        if definition.target_mode not in {"single", "blast", "aoe"}:
            continue
        if not rules.action_ability_binding(definition.action_id, definition.level):
            continue
        event = rules.action_event(definition.action_id, definition.level)
        if event is None or event.event_source_status != "ability_phase_graph_bound":
            continue
        emissions = rules.damage_emissions_for_action(definition.action_id, definition.level)
        if not any(emission.coverage_status == "executable" for emission in emissions):
            continue
        if _blocked_source_path(definition.source.source_path):
            continue
        candidates.append(definition)
    if not candidates:
        raise RuntimeError("no executable mainline damage action with admitted DamageEmissionIR found")
    return candidates[0]


def _same_source_damage_gap(rules: RuleBook, action: ActionDefinitionIR) -> dict[str, Any]:
    emissions = rules.damage_emissions_for_action(action.action_id, action.level)
    executable = [emission for emission in emissions if emission.coverage_status == "executable"]
    return {
        "action_id": action.action_id,
        "action_level": action.level,
        "has_executable_damage_emission": bool(executable),
        "damage_emission_count": len(emissions),
        "executable_damage_emission_count": len(executable),
        "blocking_dependency": "" if executable else "same_source_extra_turn_action_damage_emission_missing",
    }


def _with_unit_hp(state: BattleState, unit_id: str, *, hp: float, max_hp: float) -> BattleState:
    unit = state.units[unit_id]
    return replace(
        state,
        units={
            **state.units,
            unit_id: replace(unit, hp=hp, max_hp=max_hp),
        },
    )


def _unit_packet(attacker_id: str, target_id: str, amount: float) -> DamagePacket:
    return DamagePacket(
        attacker_id=attacker_id,
        target_id=target_id,
        attack_type="validation_damage",
        damage_formula_family="hp_loss",
        amount=amount,
        damage_kind="hp_loss",
        source_trace={"validation": VALIDATION_VERSION, "case": "kill_attribution_unit"},
        metadata={
            "is_current_skill_active": True,
            "is_insert_action": False,
            "primary_action_target_id": target_id,
        },
    )


def _events_of_type(transition: BattleTransition, event_type: str) -> list[GameEvent]:
    return [event for event in transition.transaction.events if event.event_type == event_type]


def _events_of_type_result(result, event_type: str) -> list[GameEvent]:
    return [event for event in result.events if event.event_type == event_type]


if __name__ == "__main__":
    raise SystemExit(main())
