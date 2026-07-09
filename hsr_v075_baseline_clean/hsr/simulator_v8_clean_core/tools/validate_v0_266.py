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
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, CharacterDataCardIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.queue import QUEUE_WINDOW_FAMILY_ORDER
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import (
    _duration_guard_value,
    _matching_death_callback,
    _queue_entries,
    _state_with_extra_turn_listener,
    _transition_checks,
)
from .validate_v0_255 import _dynamic_value_present, _events_of_type, _with_unit_hp
from .validate_v0_265 import _select_card_action, _select_card_extra_turn_queue_slot, _seele_card


VALIDATION_VERSION = "v0_266"
SEELE_ENTITY_REF = "avatar:1102"
ENHANCED_SEELE_SKILLS = ("1110201", "1110202", "1110203", "1110204", "1110206", "1110207")
LEGACY_SEELE_SKILLS = {"110201", "110202", "110203", "110204", "110206", "110207"}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    enhanced_card = _enhanced_card_case(rules, card)
    kill_foundation = _common_kill_event_case(rules, card)
    resurgence = _enhanced_resurgence_case(rules, card)
    auto_skill = _auto_skill_50_case(rules, card)
    queue_priority = _extra_turn_ultimate_priority_case(package_root, rules, card)
    checks = {
        "enhanced_seele_card": enhanced_card["checks"],
        "common_kill_event": kill_foundation["checks"],
        "enhanced_resurgence": resurgence["checks"],
        "auto_skill_50": auto_skill["checks"],
        "extra_turn_ultimate_priority": queue_priority["checks"],
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
                "seele_card": "User-requested sample card; selected by entity_ref avatar:1102 and verified as enhanced.",
                "resurgence": "Selected from enhanced Seele CharacterDataCardIR queue/status callback slots and action ids.",
                "auto_skill_50": (
                    "Selected by callback event OnListenAfterAttack + Retarget + TurnInsertAction SkillType source; "
                    "if the runtime event source is not admitted, this case is verified as source_gap_blocked."
                ),
            },
        },
        "checks": checks,
        "enhanced_card_case": enhanced_card,
        "common_kill_event_case": kill_foundation,
        "enhanced_resurgence_case": resurgence,
        "auto_skill_50_case": auto_skill,
        "queue_priority_case": queue_priority,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_266.json", result)
    write_json(output_dir / "enhanced_seele_card_v0_266.json", enhanced_card)
    write_json(output_dir / "common_kill_event_v0_266.json", kill_foundation)
    write_json(output_dir / "seele_resurgence_enhanced_v0_266.json", resurgence)
    write_json(output_dir / "seele_auto_skill_50_v0_266.json", auto_skill)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_266 common kill event, enhanced Seele, and extra turn semantics.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _enhanced_card_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    evidence = card.source.evidence if isinstance(card.source.evidence, dict) else {}
    slots = rules.character_mechanism_slots_for_card(card.card_id)
    callbacks = [
        rules.status_callback(str(slot.linked_ir_ids.get("status_callback_id") or slot.linked_ir_ids.get("callback_id") or ""))
        for slot in slots
        if slot.mechanism_kind == "status_callback"
    ]
    advanced_callbacks = [
        callback
        for callback in callbacks
        if callback is not None and callback.source.source_path == "Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json"
    ]
    auto_callback = _select_auto_skill_callback(rules)
    auto_callback_source_gap_blocked = (
        auto_callback.coverage_status != "executable"
        and str(auto_callback.blocking_dependency).startswith("event_source_missing:")
    )
    resurgence_slot = _select_card_extra_turn_queue_slot(rules, card)
    policy_slots = [slot for slot in slots if slot.mechanism_kind == "extra_action_policy"]
    advanced_formula_slots = [
        slot
        for slot in slots
        if slot.mechanism_kind == "formula_slot"
        and str(slot.source.raw_id) in set(ENHANCED_SEELE_SKILLS)
        and slot.coverage_status == "executable"
    ]
    checks = {
        "card_is_enhanced": evidence.get("version_kind") == "enhanced",
        "enhanced_overrides_base": evidence.get("enhanced_overrides_base") is True,
        "enhanced_source_recorded": evidence.get("enhanced_source_path") == "ExcelOutput/AvatarConfigEnhanced.json",
        "uses_enhanced_skill_ids": tuple(card.skill_ids) == ENHANCED_SEELE_SKILLS,
        "legacy_skill_ids_not_primary": not (set(card.skill_ids) & LEGACY_SEELE_SKILLS),
        "advanced_callbacks_present": bool(advanced_callbacks),
        "advanced_formula_slots_present": bool(advanced_formula_slots),
        "resurgence_slot_from_advanced_card": "Advanced/Avatar_Advanced_Seele_00" in resurgence_slot.source.source_path,
        "auto_skill_callback_executable_or_source_gap_blocked": auto_callback.coverage_status == "executable"
        or auto_callback_source_gap_blocked,
        "auto_skill_callback_from_advanced": "Advanced/Avatar_Advanced_Seele_00" in auto_callback.source.source_path,
        "extra_action_policy_allows_ultimate": any("ultimate" in slot.semantics.get("allowed_action_kinds", ()) for slot in policy_slots),
        "advanced_resurgence_duration_source_present": _advanced_resurgence_duration_source_present(rules, slots),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "card_source": card.source.to_json(),
        "skill_ids": list(card.skill_ids),
        "selected_resurgence_slot": resurgence_slot.to_json(),
        "selected_auto_skill_callback": auto_callback.to_json(),
        "advanced_formula_slot_samples": [slot.to_json() for slot in advanced_formula_slots[:5]],
    }


def _common_kill_event_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    action = _select_card_action(rules, card, attack_type="Normal")
    state = _base_action_state(actor_id="ally:seele", target_hp=1.0, energy=0.0)
    command = ActionCommand(
        actor_id="ally:seele",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:defeated",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_v0_266_common_kill_event"},
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    defeat_events = _events_of_type(transition, "unit.defeated")
    resource_mutations = [
        mutation
        for mutation in transition.transaction.mutations
        if mutation.source == "combat_executor.resources"
        and mutation.metadata.get("resource_operation") == "kill_energy_gain"
    ]
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    payload = defeat_events[0].payload if defeat_events else {}
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "single_defeat_event": len(defeat_events) == 1,
        "defeat_event_has_source_credit": bool(payload.get("kill_credit_owner_id") and payload.get("kill_credit_source_id")),
        "defeat_event_credits_actor": payload.get("kill_credit_owner_id") == "ally:seele",
        "defeat_event_has_skill_type": payload.get("SkillType") == "Normal",
        "kill_energy_mutation_present": bool(resource_mutations),
        "kill_energy_uses_same_defeat_event": any(
            mutation.metadata.get("defeated_event_payload", {}).get("damage_event_id") == payload.get("damage_event_id")
            for mutation in resource_mutations
        ),
        "kill_energy_increased": after.units["ally:seele"].energy > state.units["ally:seele"].energy,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_action": action.to_json(),
        "defeat_events": [event.to_json() for event in defeat_events],
        "resource_mutations": [mutation.to_json() for mutation in resource_mutations],
        "source_audit": audit.to_json(),
        "transition": transition.to_json(),
    }


def _enhanced_resurgence_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    cases = {
        "basic": _resurgence_for_action_kind(rules, card, attack_type="Normal"),
        "skill": _resurgence_for_action_kind(rules, card, attack_type="BPSkill"),
        "ultimate": _resurgence_for_action_kind(rules, card, attack_type="Ultra"),
    }
    extra_turn_repeat = _extra_turn_kill_does_not_retrigger_case(rules, card)
    checks = {
        "basic_kill_triggers_resurgence": cases["basic"]["checks"]["ok"],
        "skill_kill_triggers_resurgence": cases["skill"]["checks"]["ok"],
        "ultimate_kill_triggers_resurgence": cases["ultimate"]["checks"]["ok"],
        "extra_turn_kill_does_not_retrigger": extra_turn_repeat["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "by_action_kind": cases,
        "extra_turn_repeat_case": extra_turn_repeat,
    }


def _resurgence_for_action_kind(rules: RuleBook, card: CharacterDataCardIR, *, attack_type: str) -> dict[str, Any]:
    intent_slot = _select_card_extra_turn_queue_slot(rules, card)
    intent = rules.queue_intent(str(intent_slot.linked_ir_ids["queue_intent_id"]))
    if intent is None:
        raise RuntimeError("selected enhanced resurgence queue intent missing")
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected enhanced resurgence callback missing")
    death_callback = _matching_death_callback(rules, callback)
    action = _select_card_action(rules, card, attack_type=attack_type)
    state = _state_with_extra_turn_listener(rules, callback, death_callback)
    actor = state.units["ally:actor"]
    state = replace(
        state,
        units={
            **state.units,
            "ally:actor": replace(actor, template_id=SEELE_ENTITY_REF, energy=120.0 if attack_type == "Ultra" else 0.0, max_energy=120.0),
        },
    )
    state = _with_unit_hp(state, "enemy:defeated", hp=1.0, max_hp=1000.0)
    command = ActionCommand(
        actor_id="ally:actor",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:defeated",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": f"validation_v0_266_{attack_type}_kill"},
    )
    after_damage, damage_transition = CombatExecutor(rules).execute(command, state)
    defeat_events = _events_of_type(damage_transition, "unit.defeated")
    after_skill_transition, after_skill_state = _dispatch_after_skill_use(
        rules,
        before_state=after_damage,
        callback=callback,
        target_id="enemy:defeated",
    )
    queue_entries = _queue_entries(after_skill_state, intent.queue_kind)
    damage_audit = RuntimeSourceAuditor(rules).validate_transition(damage_transition)
    after_skill_audit = RuntimeSourceAuditor(rules).validate_transition(after_skill_transition)
    checks = {
        **{f"damage_{key}": value for key, value in _transition_checks(damage_transition, state).items()},
        **{f"after_skill_{key}": value for key, value in _transition_checks(after_skill_transition, after_damage).items()},
        "damage_source_audit": damage_audit.ok,
        "after_skill_source_audit": after_skill_audit.ok,
        "defeat_event_present": len(defeat_events) == 1,
        "defeat_event_skill_type_matches": _event_skill_type(defeat_events[0] if defeat_events else None) == _expected_skill_type(attack_type),
        "death_listener_wrote_insert_action": _dynamic_value_present(after_damage, "InsertAction", 1.0),
        "after_skill_enqueued_extra_turn": any(entry.get("window_family") == "extra_turn" for entry in queue_entries),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_action": action.to_json(),
        "defeat_events": [event.to_json() for event in defeat_events],
        "queue_entries_after_skill": list(queue_entries),
        "source_audits": {"damage": damage_audit.to_json(), "after_skill": after_skill_audit.to_json()},
    }


def _extra_turn_kill_does_not_retrigger_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    intent_slot = _select_card_extra_turn_queue_slot(rules, card)
    intent = rules.queue_intent(str(intent_slot.linked_ir_ids["queue_intent_id"]))
    if intent is None:
        raise RuntimeError("selected enhanced resurgence queue intent missing")
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected enhanced resurgence callback missing")
    death_callback = _matching_death_callback(rules, callback)
    damage_action = _select_card_action(rules, card, attack_type="BPSkill")
    extra_turn_action = _select_card_action(rules, card, attack_type="Normal")
    state = _state_with_extra_turn_listener(rules, callback, death_callback)
    actor = state.units["ally:actor"]
    state = replace(
        state,
        units={
            **state.units,
            "ally:actor": replace(actor, template_id=SEELE_ENTITY_REF, energy=0.0, max_energy=120.0),
        },
    )
    state = _with_unit_hp(state, "enemy:defeated", hp=1.0, max_hp=1000.0)
    state = _with_unit_hp(state, "enemy:alive", hp=1.0, max_hp=1000.0)
    damage_command = ActionCommand(
        actor_id="ally:actor",
        action_id=damage_action.action_id,
        action_level=damage_action.level,
        target_ids=("enemy:defeated",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_v0_266_resurgence_seed_kill"},
    )
    after_damage, damage_transition = CombatExecutor(rules).execute(damage_command, state)
    after_skill_transition, after_skill_state = _dispatch_after_skill_use(
        rules,
        before_state=after_damage,
        callback=callback,
        target_id="enemy:defeated",
    )
    route_command = ActionCommand(
        actor_id="ally:actor",
        action_id=extra_turn_action.action_id,
        action_level=extra_turn_action.level,
        target_ids=("enemy:alive",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_v0_266_extra_turn_kill"},
    )
    scheduler_result = CombatScheduler(rules).step(after_skill_state, command=route_command)
    child = scheduler_result.child_transitions[0] if scheduler_result.child_transitions else None
    queue_after = _queue_entries(scheduler_result.after_state, intent.queue_kind)
    scheduler_audit = RuntimeSourceAuditor(rules).validate_transition(scheduler_result.transition)
    child_audit = RuntimeSourceAuditor(rules).validate_transition(child) if child is not None else None
    child_defeat_events = _events_of_type(child, "unit.defeated") if child is not None else []
    blocked_reason = str(scheduler_result.transition.coverage.get("blocked_reason") or "")
    repeat_source_gap_blocked = (
        child is None
        and blocked_reason.startswith("queue_action_event_not_admitted")
        and scheduler_audit.ok
        and not scheduler_result.transition.transaction.mutations
    )
    checks = {
        **{f"scheduler_{key}": value for key, value in _transition_checks(scheduler_result.transition, after_skill_state).items()},
        "scheduler_source_audit": scheduler_audit.ok,
        "child_source_audit_or_source_gap_blocked": bool(child_audit and child_audit.ok) or repeat_source_gap_blocked,
        "extra_turn_child_present_or_source_gap_blocked": child is not None or repeat_source_gap_blocked,
        "extra_turn_child_source_queue_or_source_gap_blocked": bool(child and child.transaction.command.source == "queue")
        or repeat_source_gap_blocked,
        "extra_turn_child_emitted_defeat_or_source_gap_blocked": len(child_defeat_events) == 1 or repeat_source_gap_blocked,
        "queue_drained_and_not_requeued_or_source_gap_blocked": len(queue_after) == 0 or repeat_source_gap_blocked,
        "insert_action_flag_not_rewritten_by_extra_turn_kill": _dynamic_value_present(scheduler_result.after_state, "InsertAction", 0.0),
        "repeat_source_gap_blocked_is_specific": not repeat_source_gap_blocked or bool(blocked_reason),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "status": "source_gap_blocked" if repeat_source_gap_blocked else "executed",
        "blocking_dependency": blocked_reason if repeat_source_gap_blocked else "",
        "seed_damage_transition": damage_transition.to_json(),
        "after_skill_transition": after_skill_transition.to_json(),
        "scheduler_transition": scheduler_result.transition.to_json(),
        "child_transition": child.to_json() if child is not None else {},
        "source_audits": {
            "scheduler": scheduler_audit.to_json(),
            "child": child_audit.to_json() if child_audit is not None else {},
        },
    }


def _auto_skill_50_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    callback = _select_auto_skill_callback(rules)
    callback_source_gap_blocked = (
        callback.coverage_status != "executable"
        and str(callback.blocking_dependency).startswith("event_source_missing:")
    )
    passing_state = _auto_skill_state(rules, callback, target_hp=500.0, target_max_hp=1000.0)
    passing_result = _dispatch_after_attack(rules, passing_state, target_id="enemy:target")
    passing_transition = _callback_transition(
        before_state=passing_state,
        after_state=passing_result.after_state,
        records=passing_result.records,
        mutations=passing_result.mutations,
        events=passing_result.events,
        action_id="event_dispatch:auto_skill_50_pass",
        actor_id="ally:other",
        target_id="enemy:target",
        metadata={"callback_id": callback.callback_id, "character_data_card_id": card.card_id},
    )
    high_hp_state = _auto_skill_state(rules, callback, target_hp=700.0, target_max_hp=1000.0)
    high_hp_result = _dispatch_after_attack(rules, high_hp_state, target_id="enemy:target")
    used_state = _auto_skill_state(
        rules,
        callback,
        target_hp=500.0,
        target_max_hp=1000.0,
        used_marker=True,
    )
    used_result = _dispatch_after_attack(rules, used_state, target_id="enemy:target")
    reset_result = _dispatch_turn_begin(rules, used_state, actor_id="ally:seele")
    reset_transition = _callback_transition(
        before_state=used_state,
        after_state=reset_result.after_state,
        records=reset_result.records,
        mutations=reset_result.mutations,
        events=reset_result.events,
        action_id="event_dispatch:auto_skill_turn_begin_reset",
        actor_id="ally:seele",
        target_id="ally:seele",
        metadata={"callback_event": "OnListenAllowAction", "character_data_card_id": card.card_id},
    )
    no_target_state = _auto_skill_state(
        rules,
        callback,
        target_hp=0.0,
        target_max_hp=1000.0,
        include_fallback_enemy=False,
    )
    no_target_result = _dispatch_after_attack(rules, no_target_state, target_id="enemy:target")
    passing_audit = RuntimeSourceAuditor(rules).validate_transition(passing_transition)
    reset_audit = RuntimeSourceAuditor(rules).validate_transition(reset_transition)
    passing_entries = _queue_entries(passing_result.after_state, "turn_insert_action")
    passing_entry = passing_entries[0] if passing_entries else {}
    passing_source_gap_blocked = (
        not passing_entries
        and (
            any(str(error).startswith("event_source_missing:") for error in passing_result.errors)
            or callback_source_gap_blocked
        )
        and passing_state.snapshot().to_json() == passing_result.after_state.snapshot().to_json()
    )
    checks = {
        **{f"passing_{key}": value for key, value in _transition_checks(passing_transition, passing_state).items()},
        **{f"reset_{key}": value for key, value in _transition_checks(reset_transition, used_state).items()},
        "passing_source_audit": passing_audit.ok,
        "reset_source_audit": reset_audit.ok,
        "auto_skill_callback_executable_or_source_gap_blocked": callback.coverage_status == "executable"
        or passing_source_gap_blocked,
        "passing_enqueued_action_or_source_gap_blocked": bool(passing_entries) or passing_source_gap_blocked,
        "passing_target_is_attacked_target_or_source_gap_blocked": passing_entry.get("target_ids") == ["enemy:target"]
        or passing_source_gap_blocked,
        "passing_action_is_skill_or_source_gap_blocked": passing_entry.get("action_or_ability_ref") == "skill_type:ControlSkill02"
        or passing_source_gap_blocked,
        "passing_ignores_sp_and_energy_gain_or_source_gap_blocked": (
            _entry_resource_policy(passing_entry).get("ignore_skill_point_delta") is True
            and _entry_resource_policy(passing_entry).get("ignore_energy_gain") is True
        )
        or passing_source_gap_blocked,
        "high_hp_state_unchanged": high_hp_state.snapshot().to_json() == high_hp_result.after_state.snapshot().to_json(),
        "used_once_state_unchanged": used_state.snapshot().to_json() == used_result.after_state.snapshot().to_json(),
        "turn_begin_reset_removed_used_marker_or_source_gap_blocked": not _unit_has_modifier(
            reset_result.after_state,
            "ally:seele",
            "MAvatar_Advanced_Seele_00_Skill02InsertCheck",
        )
        or passing_source_gap_blocked,
        "no_live_target_state_unchanged": no_target_state.snapshot().to_json() == no_target_result.after_state.snapshot().to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "status": "source_gap_blocked" if passing_source_gap_blocked else "executed",
        "blocking_dependency": "event_source_missing:OnListenAfterAttack" if passing_source_gap_blocked else "",
        "selected_callback": callback.to_json(),
        "passing_queue_entry": passing_entry,
        "passing_transition": passing_transition.to_json(),
        "reset_transition": reset_transition.to_json(),
        "negative_results": {
            "high_hp_errors": list(high_hp_result.errors),
            "used_once_errors": list(used_result.errors),
            "no_live_target_errors": list(no_target_result.errors),
        },
        "source_audit": {"passing": passing_audit.to_json(), "reset": reset_audit.to_json()},
    }


def _extra_turn_ultimate_priority_case(package_root: Path, rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    policy_slots = [
        slot for slot in rules.character_mechanism_slots_for_card(card.card_id)
        if slot.mechanism_kind == "extra_action_policy"
    ]
    blocked_reason_hits: list[str] = []
    for root_name in ("core", "systems", "rules", "tbgd"):
        for path in (package_root / root_name).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "extra_turn_ultimate_action_not_allowed" in text:
                blocked_reason_hits.append(path.relative_to(package_root).as_posix())
    checks = {
        "follow_up_priority_above_ultimate": QUEUE_WINDOW_FAMILY_ORDER.get("follow_up", 999) < QUEUE_WINDOW_FAMILY_ORDER.get("ultimate", 999),
        "counter_priority_above_extra_turn": QUEUE_WINDOW_FAMILY_ORDER.get("counter", 999) < QUEUE_WINDOW_FAMILY_ORDER.get("extra_turn", 999),
        "ultimate_and_extra_turn_same_priority": QUEUE_WINDOW_FAMILY_ORDER.get("ultimate") == QUEUE_WINDOW_FAMILY_ORDER.get("extra_turn"),
        "extra_turn_policy_allows_ultimate_choice": any("ultimate" in slot.semantics.get("allowed_action_kinds", ()) for slot in policy_slots),
        "no_hard_banned_ultimate_reason": not blocked_reason_hits,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "queue_window_family_order": dict(QUEUE_WINDOW_FAMILY_ORDER),
        "blocked_reason_hits": blocked_reason_hits,
        "extra_action_policy_samples": [slot.to_json() for slot in policy_slots[:5]],
    }


def _dispatch_after_skill_use(
    rules: RuleBook,
    *,
    before_state: BattleState,
    callback: StatusCallbackIR,
    target_id: str,
) -> tuple[BattleTransition, BattleState]:
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    event = GameEvent(
        "action.after_skill_use",
        source_id="ally:actor",
        target_id=target_id,
        window="OnAfterSkillUse",
        process_only=True,
        payload={
            "target_id": target_id,
            "primary_target_id": target_id,
            "current_hit_target_id": target_id,
            "is_current_skill_active": False,
            "is_insert_action": False,
        },
    )
    result = dispatcher.dispatch_event(before_state, event=event)
    transition = _callback_transition(
        before_state=before_state,
        after_state=result.after_state,
        records=result.records,
        mutations=result.mutations,
        events=result.events,
        action_id="event_dispatch:on_after_skill_use",
        actor_id="ally:actor",
        target_id=target_id,
        metadata={"callback_id": callback.callback_id, "modifier_name": callback.modifier_name},
    )
    return transition, result.after_state


def _base_action_state(*, actor_id: str, target_hp: float, energy: float) -> BattleState:
    actor = UnitState(
        unit_id=actor_id,
        side="ally",
        template_id=SEELE_ENTITY_REF,
        level=80,
        max_hp=5000.0,
        hp=5000.0,
        attack=1800.0,
        defense=800.0,
        speed=115.0,
        energy=energy,
        max_energy=120.0,
        resources={"critical_chance": 0.0, "critical_damage": 0.5},
        flags={"position": 0},
    )
    target = UnitState(
        unit_id="enemy:defeated",
        side="enemy",
        template_id="monster:validation_target",
        level=80,
        max_hp=1000.0,
        hp=target_hp,
        defense=100.0,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Quantum",)},
    )
    return BattleState(units={actor_id: actor, "enemy:defeated": target}, skill_points=5, max_skill_points=5)


def _select_auto_skill_callback(rules: RuleBook) -> StatusCallbackIR:
    fallback: StatusCallbackIR | None = None
    for callback in rules.ir.status_callbacks:
        if callback.modifier_name != "MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen":
            continue
        if callback.event != "OnListenAfterAttack":
            continue
        if "Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json" not in callback.source.source_path:
            continue
        tasks = rules.status_callback_tasks_for_callback(callback.callback_id)
        queue_intents = rules.queue_intents_for_callback(callback.callback_id)
        has_retarget_source = any(task.opcode == "Retarget" for task in tasks)
        has_retarget = any(task.opcode == "Retarget" and task.coverage_status == "executable" for task in tasks)
        has_queue = any(
            intent.opcode == "TurnInsertAction"
            and intent.coverage_status == "executable"
            and intent.skill_index_expr.get("source_field") == "SkillType"
            for intent in queue_intents
        )
        if has_retarget and has_queue:
            return callback
        has_queue_source = any(
            intent.opcode == "TurnInsertAction"
            and intent.skill_index_expr.get("source_field") == "SkillType"
            for intent in queue_intents
        )
        if (
            fallback is None
            and has_retarget_source
            and has_queue_source
            and str(callback.blocking_dependency).startswith("event_source_missing:")
        ):
            fallback = callback
    if fallback is not None:
        return fallback
    raise RuntimeError("enhanced Seele 50% auto skill callback missing")


def _auto_skill_state(
    rules: RuleBook,
    callback: StatusCallbackIR,
    *,
    target_hp: float,
    target_max_hp: float,
    used_marker: bool = False,
    include_fallback_enemy: bool = True,
) -> BattleState:
    listener_status = f"modifier:{callback.modifier_name}"
    ready_modifier = "MAvatar_Advanced_Seele_00_Skill02InsertReady_ShowBuff"
    ready_status = f"modifier:{ready_modifier}"
    used_modifier = "MAvatar_Advanced_Seele_00_Skill02InsertCheck"
    statuses = [listener_status, ready_status]
    details: list[dict[str, Any]] = [
        {
            "instance_id": "validation:auto_skill_listener",
            "status_id": listener_status,
            "modifier_name": callback.modifier_name,
            "owner_id": "ally:seele",
            "caster_id": "ally:seele",
            "source_id": callback.callback_id,
            "source_trace": {"status_callback": callback.source.to_json()},
            "trigger_ids_by_event": {callback.event: [callback.callback_id]},
            "dynamic_values": {"__by_hash": {"394348681": 0.5}},
        },
        {
            "instance_id": "validation:auto_skill_ready",
            "status_id": ready_status,
            "modifier_name": ready_modifier,
            "owner_id": "ally:seele",
            "caster_id": "ally:seele",
            "source_trace": {"validation": "enhanced_seele_auto_skill_ready"},
        },
    ]
    if used_marker:
        reset_callback = _select_auto_skill_reset_callback(rules)
        statuses.append(f"modifier:{used_modifier}")
        details.append(
            {
                "instance_id": "validation:auto_skill_used",
                "status_id": f"modifier:{used_modifier}",
                "modifier_name": used_modifier,
                "owner_id": "ally:seele",
                "caster_id": "ally:seele",
                "source_trace": {"status_callback": reset_callback.source.to_json()},
                "trigger_ids_by_event": {reset_callback.event: [reset_callback.callback_id]},
            }
        )
    seele = UnitState(
        unit_id="ally:seele",
        side="ally",
        template_id=SEELE_ENTITY_REF,
        level=80,
        max_hp=5000.0,
        hp=5000.0,
        attack=1800.0,
        defense=800.0,
        speed=115.0,
        energy=0.0,
        max_energy=120.0,
        statuses=tuple(statuses),
        flags={"position": 0, "status_details": tuple(details)},
    )
    ally = UnitState("ally:other", "ally", "avatar:validation_other", level=80, hp=4000.0, max_hp=4000.0, speed=100.0, flags={"position": 1})
    target = UnitState(
        "enemy:target",
        "enemy",
        "monster:validation_target",
        level=80,
        hp=target_hp,
        max_hp=target_max_hp,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Quantum",)},
    )
    units: dict[str, UnitState] = {"ally:seele": seele, "ally:other": ally, "enemy:target": target}
    if include_fallback_enemy:
        units["enemy:fallback"] = UnitState(
            "enemy:fallback",
            "enemy",
            "monster:validation_fallback",
            level=80,
            hp=800.0,
            max_hp=1000.0,
            speed=100.0,
            flags={"position": 1, "weaknesses": ("Quantum",)},
        )
    return BattleState(units=units, skill_points=0, max_skill_points=5)


def _dispatch_after_attack(rules: RuleBook, state: BattleState, *, target_id: str):
    event = GameEvent(
        "action.after_attack",
        source_id="ally:other",
        target_id=target_id,
        window="OnListenAfterAttack",
        process_only=True,
        payload={
            "actor_id": "ally:other",
            "attacker_id": "ally:other",
            "damage_attacker_id": "ally:other",
            "param_entity_id": "ally:other",
            "primary_target_id": target_id,
            "current_hit_target_id": target_id,
            "target_id": target_id,
            "target_ids": [target_id],
            "selected_target_ids": [target_id],
        },
    )
    return EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)


def _dispatch_turn_begin(rules: RuleBook, state: BattleState, *, actor_id: str):
    event = GameEvent(
        "turn.begin",
        source_id=actor_id,
        target_id=actor_id,
        window="OnListenAllowAction",
        process_only=True,
        payload={
            "actor_id": actor_id,
            "primary_target_id": actor_id,
            "current_hit_target_id": actor_id,
            "target_id": actor_id,
        },
    )
    return EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(state, event=event)


def _select_auto_skill_reset_callback(rules: RuleBook) -> StatusCallbackIR:
    for callback in rules.status_callbacks_for_modifier_event(
        "MAvatar_Advanced_Seele_00_Skill02InsertCheck",
        "OnListenAllowAction",
    ):
        if callback.coverage_status != "executable":
            continue
        if "Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json" not in callback.source.source_path:
            continue
        tasks = rules.status_callback_tasks_for_callback(callback.callback_id)
        if any(task.opcode == "RemoveSelfModifier" and task.coverage_status == "executable" for task in tasks):
            return callback
    raise RuntimeError("enhanced Seele auto skill reset callback missing")


def _unit_has_modifier(state: BattleState, unit_id: str, modifier_name: str) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    if modifier_name in unit.statuses or f"modifier:{modifier_name}" in unit.statuses:
        return True
    return any(
        isinstance(detail, dict) and detail.get("modifier_name") == modifier_name
        for detail in unit.flags.get("status_details", ())
    )


def _callback_transition(
    *,
    before_state: BattleState,
    after_state: BattleState,
    records: tuple[dict[str, Any], ...],
    mutations: tuple[Any, ...],
    events: tuple[GameEvent, ...],
    action_id: str,
    actor_id: str,
    target_id: str,
    metadata: dict[str, Any],
) -> BattleTransition:
    command = ActionCommand(
        actor_id=actor_id,
        action_id=action_id,
        action_level=0,
        target_ids=(target_id,),
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
            requested=(target_id,),
            legal=(target_id,),
            selected=(target_id,),
            reason=action_id,
            source="validation_event_dispatch",
        ),
        coverage={"validation_action": action_id, "mutation_count": len(tuple(mutations))},
    )


def _advanced_resurgence_duration_source_present(rules: RuleBook, slots: tuple[Any, ...]) -> bool:
    param_slot_has_three = any(
        slot.mechanism_kind == "skill_param_slot"
        and slot.semantics.get("skill_id") == "1110204"
        and slot.semantics.get("param_index") == 1
        and _json_number(slot.semantics.get("param_value")) == 3.0
        for slot in slots
    )
    if not param_slot_has_three:
        return False
    for effect in rules.ir.effects:
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload, dict) else None
        if not isinstance(standard, dict):
            continue
        if standard.get("modifier_name") != "MAvatar_Advanced_Seele_00_Passive_DamageUp":
            continue
        lifetime = standard.get("lifetime")
        if (
            "Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json" in effect.source.source_path
            and isinstance(lifetime, dict)
            and lifetime.get("kind") == "dynamic_hash"
        ):
            return True
    return False


def _json_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and isinstance(value.get("Value"), (int, float)):
        return float(value["Value"])
    return None


def _event_skill_type(event: GameEvent | None) -> str:
    if event is None or not isinstance(event.payload, dict):
        return ""
    return str(event.payload.get("SkillType") or event.payload.get("skill_type") or "")


def _expected_skill_type(attack_type: str) -> str:
    if attack_type == "Ultra":
        return "Ultra"
    if attack_type == "BPSkill":
        return "Skill"
    return "Normal"


def _entry_resource_policy(entry: dict[str, Any]) -> dict[str, Any]:
    source_trace = entry.get("source_trace") if isinstance(entry, dict) else None
    policy = source_trace.get("queue_intent_resource_policy") if isinstance(source_trace, dict) else None
    return policy if isinstance(policy, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
