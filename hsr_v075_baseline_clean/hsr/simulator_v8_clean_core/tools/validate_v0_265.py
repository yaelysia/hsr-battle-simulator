from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, GameEvent, UnitState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, CharacterDataCardIR, CharacterMechanismSlotIR, CanonicalIR
from ..rules.rulebook import RuleBook
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import (
    _duration_guard_value,
    _is_ultimate_action,
    _matching_death_callback,
    _queue_entries,
    _select_non_ultimate_action_for_callback_source,
    _state_with_extra_turn_listener,
    _system_transition,
    _transition_checks,
)
from .validate_v0_255 import _dynamic_value_present, _events_of_type, _kill_attribution_case, _with_unit_hp


VALIDATION_VERSION = "v0_265"
SEELE_ENTITY_REF = "avatar:1102"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    card_contract = _card_contract_case(ir, rules, card)
    runtime_boundary = _runtime_boundary_case(package_root)
    action_case = _seele_action_execution_case(rules, card)
    resurgence_case = _seele_resurgence_case(rules, card)
    trace_case = _trace_and_eidolon_case(rules, card)
    kill_attribution = _kill_attribution_case(rules)
    checks = {
        "card_contract": card_contract["checks"],
        "runtime_boundary": runtime_boundary["checks"],
        "seele_action_execution": action_case["checks"],
        "seele_resurgence": resurgence_case["checks"],
        "trace_and_eidolon_interface": trace_case["checks"],
        "kill_attribution_regression": kill_attribution["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "character_data_card_count": len(ir.character_data_cards),
            "character_mechanism_slot_count": len(ir.character_mechanism_slots),
            "character_trace_node_count": len(ir.character_trace_nodes),
            "character_eidolon_slot_count": len(ir.character_eidolon_slots),
            "selection_policy": {
                "sample_card": (
                    "Seele is the user-requested example card. Runtime/core code is still checked for no "
                    "character-name special case; the example selector only targets the card output."
                ),
                "actions": "Selected from Seele CharacterDataCardIR.skill_ids and ActionDefinitionIR attack_type.",
                "resurgence": "Selected from Seele card queue/status callback mechanism slots; no runtime name special case.",
            },
        },
        "checks": checks,
        "card_contract_case": card_contract,
        "runtime_boundary_case": runtime_boundary,
        "seele_action_execution_case": action_case,
        "seele_resurgence_case": resurgence_case,
        "trace_and_eidolon_case": trace_case,
        "kill_attribution_case": kill_attribution,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_265.json", result)
    write_json(output_dir / "seele_character_data_card_v0_265.json", card_contract["seele_card"])
    write_json(output_dir / "seele_action_execution_v0_265.json", action_case)
    write_json(output_dir / "seele_resurgence_chain_v0_265.json", resurgence_case)
    write_json(output_dir / "character_card_contract_matrix_v0_265.json", card_contract["contract_matrix"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_265 character data card contract and Seele sample card.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _seele_card(rules: RuleBook) -> CharacterDataCardIR:
    card = rules.character_data_card_for_entity(SEELE_ENTITY_REF)
    if card is None:
        raise RuntimeError("Seele character data card missing")
    return card


def _card_contract_case(ir: CanonicalIR, rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    slots = rules.character_mechanism_slots_for_card(card.card_id)
    trace_nodes = rules.character_trace_nodes_for_card(card.card_id)
    eidolon_slots = rules.character_eidolon_slots_for_card(card.card_id)
    formula_slots = [slot for slot in slots if slot.mechanism_kind == "formula_slot"]
    queue_slots = [slot for slot in slots if slot.mechanism_kind == "queue_intent"]
    extra_action_slots = [slot for slot in slots if slot.mechanism_kind == "extra_action_policy"]
    callback_slots = [slot for slot in slots if slot.mechanism_kind == "status_callback"]
    executable_formula_slots = [slot for slot in formula_slots if slot.coverage_status == "executable"]
    card_json = card.to_json()
    json_roundtrip = json.loads(json.dumps(card_json, ensure_ascii=False))
    required_sections = set(card.card_contract.get("required_sections", []))
    checks = {
        "seele_card_exists": bool(card),
        "card_executable": card.coverage_status == "executable",
        "schema_version_current": card.schema_version in {"v0_265", "v0_267"},
        "json_roundtrip": json_roundtrip == card_json,
        "contract_sections_present": {
            "identity",
            "base_profile_source",
            "action_set",
            "formula_slots",
            "status_and_dynamic_values",
            "listeners",
            "extra_actions",
            "traces",
            "eidolon_interface",
        }.issubset(required_sections),
        "formula_slots_present": bool(formula_slots),
        "executable_formula_slots_have_basis_multiplier_target_source": all(
            _formula_slot_complete(slot) for slot in executable_formula_slots
        ),
        "status_listener_slots_present": bool(callback_slots),
        "extra_turn_queue_slots_present": any(slot.semantics.get("window_family") == "extra_turn" for slot in queue_slots),
        "extra_action_policy_slots_present": bool(extra_action_slots),
        "trace_nodes_present": bool(trace_nodes),
        "eidolon_slots_present": len(eidolon_slots) == 6
        and all(slot.rank == index + 1 and slot.rank_id for index, slot in enumerate(eidolon_slots)),
        "rulebook_slot_ids_resolve": all(rules.character_mechanism_slot(slot_id) is not None for slot_id in card.mechanism_slot_ids),
        "rulebook_trace_ids_resolve": all(rules.character_trace_node(trace_id) is not None for trace_id in card.trace_node_ids),
        "rulebook_eidolon_ids_resolve": all(rules.character_eidolon_slot(slot_id) is not None for slot_id in card.eidolon_slot_ids),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    matrix = {
        "card_id": card.card_id,
        "mechanism_slot_counts": _slot_counts(slots),
        "trace_node_count": len(trace_nodes),
        "eidolon_slot_count": len(eidolon_slots),
        "executable_formula_slot_count": len(executable_formula_slots),
        "blocked_slot_samples": [
            slot.to_json() for slot in slots if slot.coverage_status == "blocked" and slot.blocked_reason
        ][:8],
    }
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "contract_matrix": matrix,
        "seele_card": card_json,
    }


def _runtime_boundary_case(package_root: Path) -> dict[str, Any]:
    runtime_roots = [package_root / "core", package_root / "systems", package_root / "rules"]
    disallowed_tokens = ("TextMap", "SkillDesc", "AvatarSkillConfig.json", "turnbasedgamedata-main", "Seele")
    violations: list[dict[str, Any]] = []
    for root in runtime_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in disallowed_tokens:
                if token in text:
                    violations.append({"path": path.relative_to(package_root).as_posix(), "token": token})
    checks = {
        "runtime_no_textmap_or_raw_tbgd": not violations,
    }
    checks["ok"] = all(checks.values())
    return {"checks": {"ok": checks["ok"], "checks": checks}, "violations": violations}


def _seele_action_execution_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    actions = {
        "basic": _select_card_action(rules, card, attack_type="Normal"),
        "skill": _select_card_action(rules, card, attack_type="BPSkill"),
        "ultimate": _select_card_action(rules, card, attack_type="Ultra"),
    }
    results = {
        name: _execute_card_action(rules, action, name)
        for name, action in actions.items()
    }
    checks = {
        "basic_action_executed": results["basic"]["checks"]["ok"],
        "skill_action_executed": results["skill"]["checks"]["ok"],
        "ultimate_action_executed": results["ultimate"]["checks"]["ok"],
        "all_actions_from_card_skill_ids": all(
            action.action_id.removeprefix("avatar_skill:") in set(card.skill_ids) for action in actions.values()
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_actions": {name: action.to_json() for name, action in actions.items()},
        "action_results": results,
    }


def _seele_resurgence_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    intent_slot = _select_card_extra_turn_queue_slot(rules, card)
    intent_id = str(intent_slot.linked_ir_ids["queue_intent_id"])
    intent = rules.queue_intent(intent_id)
    if intent is None:
        raise RuntimeError(f"selected Seele extra-turn queue intent missing: {intent_id}")
    callback = rules.status_callback(intent.callback_id)
    if callback is None:
        raise RuntimeError("selected Seele queue intent has no status callback")
    death_callback = _matching_death_callback(rules, callback)
    damage_action = _select_card_action(rules, card, attack_type="BPSkill")
    extra_turn_action = _select_non_ultimate_action_for_callback_source(rules.ir, rules, callback)
    initial_state = _state_with_extra_turn_listener(rules, callback, death_callback)
    actor = initial_state.units["ally:actor"]
    initial_state = replace(
        initial_state,
        units={
            **initial_state.units,
            "ally:actor": replace(actor, template_id=SEELE_ENTITY_REF),
        },
    )
    lethal_state = _with_unit_hp(initial_state, "enemy:defeated", hp=1.0, max_hp=1000.0)
    damage_command = ActionCommand(
        actor_id="ally:actor",
        action_id=damage_action.action_id,
        action_level=damage_action.level,
        target_ids=("enemy:defeated",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_seele_resurgence_kill"},
    )
    after_damage_state, damage_transition = CombatExecutor(rules).execute(damage_command, lethal_state)
    defeat_events = _events_of_type(damage_transition, "unit.defeated")

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
        action_id="event_dispatch:seele_after_skill_use",
        metadata={
            "callback_id": callback.callback_id,
            "modifier_name": callback.modifier_name,
            "selected_queue_intent_id": intent.queue_intent_id,
            "character_data_card_id": card.card_id,
        },
    )
    route_command = ActionCommand(
        actor_id="ally:actor",
        action_id=extra_turn_action.action_id,
        action_level=extra_turn_action.level,
        target_ids=("enemy:alive",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": "validation_seele_resurgence_extra_turn_choice"},
    )
    scheduler_result = CombatScheduler(rules).step(after_skill_result.after_state, command=route_command)
    child = scheduler_result.child_transitions[0] if scheduler_result.child_transitions else None

    nonlethal_state = _with_unit_hp(initial_state, "enemy:defeated", hp=1_000_000_000.0, max_hp=1_000_000_000.0)
    nonlethal_after, nonlethal_transition = CombatExecutor(rules).execute(damage_command, nonlethal_state)

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
    checks = {
        **{f"damage_{key}": value for key, value in _transition_checks(damage_transition, lethal_state).items()},
        **{f"after_skill_{key}": value for key, value in _transition_checks(after_skill_transition, after_damage_state).items()},
        **{f"scheduler_{key}": value for key, value in _transition_checks(scheduler_result.transition, after_skill_result.after_state).items()},
        "selected_intent_from_card_slot": intent_slot.character_data_card_id == card.card_id,
        "damage_source_audit": damage_audit.ok,
        "after_skill_source_audit": after_skill_audit.ok,
        "scheduler_source_audit": scheduler_audit.ok,
        "child_source_audit": bool(child_audit and child_audit.ok),
        "lethal_damage_emitted_defeat_event": len(defeat_events) == 1,
        "death_listener_wrote_insert_action_flag": _dynamic_value_present(after_damage_state, "InsertAction", 1.0),
        "after_skill_enqueued_extra_turn": bool(queue_entries_after_skill),
        "scheduler_drained_queue_first": scheduler_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "queue_removed_after_drain": len(queue_entries_after_scheduler) < len(queue_entries_after_skill),
        "child_transition_present": child is not None,
        "child_source_queue": bool(child and child.transaction.command.source == "queue"),
        "child_action_is_non_ultimate": bool(child and not _is_ultimate_action(extra_turn_action)),
        "child_window_family_extra_turn": child_window_plan.get("window_family") == "extra_turn",
        "ordinary_turn_begin_end_not_emitted": "turn.begin" not in scheduler_events and "turn.end" not in scheduler_events,
        "extra_turn_begin_and_end_events": "extra_turn.begin" in scheduler_events and "extra_turn.end" in scheduler_events,
        "ordinary_duration_not_consumed": initial_duration == final_duration == 2,
        "child_action_did_not_emit_turn_lifecycle": "turn.begin" not in child_events and "turn.end" not in child_events,
        "nonlethal_no_defeat_event": not _events_of_type(nonlethal_transition, "unit.defeated"),
        "nonlethal_no_insert_action_flag": not _dynamic_value_present(nonlethal_after, "InsertAction", 1.0),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_card_slot": intent_slot.to_json(),
        "selected_queue_intent": intent.to_json(),
        "selected_status_callback": callback.to_json(),
        "selected_death_callback": death_callback.to_json(),
        "selected_damage_action": damage_action.to_json(),
        "selected_extra_turn_action": extra_turn_action.to_json(),
        "source_audits": {
            "damage": damage_audit.to_json(),
            "after_skill": after_skill_audit.to_json(),
            "scheduler": scheduler_audit.to_json(),
            "child": child_audit.to_json() if child_audit is not None else {},
        },
        "transitions": {
            "damage_action": damage_transition.to_json(),
            "after_skill_listener": after_skill_transition.to_json(),
            "scheduler": scheduler_result.transition.to_json(),
            "child_action": child.to_json() if child is not None else {},
            "nonlethal_damage": nonlethal_transition.to_json(),
        },
    }


def _trace_and_eidolon_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    traces = rules.character_trace_nodes_for_card(card.card_id)
    slots = rules.character_mechanism_slots_for_card(card.card_id)
    trace_slot_ids = {slot_id for node in traces for slot_id in node.linked_mechanism_slot_ids}
    trace_slots = [slot for slot in slots if slot.mechanism_slot_id in trace_slot_ids]
    eidolons = rules.character_eidolon_slots_for_card(card.card_id)
    trace_with_slot = next((node for node in traces if node.linked_mechanism_slot_ids), None)
    enabled_trace_ids = {trace_with_slot.trace_node_id} if trace_with_slot is not None else set()
    active_with_trace = _active_trace_slots(trace_slots, enabled_trace_ids)
    active_without_trace = _active_trace_slots(trace_slots, set())
    checks = {
        "trace_nodes_present": bool(traces),
        "trace_slots_present": bool(trace_slots),
        "trace_toggle_enables_slots": bool(active_with_trace),
        "trace_toggle_disables_slots": not active_without_trace,
        "trace_unimplemented_runtime_slots_have_blocker": all(
            slot.coverage_status != "executable" and bool(slot.blocked_reason) for slot in trace_slots
        ),
        "eidolon_interface_has_six_slots": len(eidolons) == 6,
        "eidolon_prefix_slots_have_sources": all(
            slot.coverage_status == "executable"
            and slot.activation.get("kind") == "eidolon_prefix_toggle"
            and slot.activation.get("prefix_closed") is True
            and slot.linked_mechanism_slot_ids
            for slot in eidolons
        ),
        "eidolon_runtime_effect_slots_still_blocked": all(
            slot.coverage_status != "executable" and bool(slot.blocked_reason)
            for slot in slots
            if slot.mechanism_kind == "eidolon_rank_effect"
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "sample_trace_nodes": [node.to_json() for node in traces[:8]],
        "sample_trace_slots": [slot.to_json() for slot in trace_slots[:8]],
        "eidolon_slots": [slot.to_json() for slot in eidolons],
    }


def _select_card_action(rules: RuleBook, card: CharacterDataCardIR, *, attack_type: str) -> ActionDefinitionIR:
    action_ids = {f"avatar_skill:{skill_id}" for skill_id in card.skill_ids}
    candidates: list[ActionDefinitionIR] = []
    for action in rules.ir.action_definitions:
        if action.action_id not in action_ids or action.attack_type != attack_type:
            continue
        if action.coverage_status != "executable" or action.damage_kind != "hp_damage":
            continue
        if not any(emission.coverage_status == "executable" for emission in rules.damage_emissions_for_action(action.action_id, action.level)):
            continue
        candidates.append(action)
    if not candidates:
        raise RuntimeError(f"no executable Seele {attack_type} action found")
    return sorted(candidates, key=lambda item: item.level)[-1]


def _execute_card_action(rules: RuleBook, action: ActionDefinitionIR, action_kind: str) -> dict[str, Any]:
    state = _action_state()
    command = ActionCommand(
        actor_id="ally:seele",
        action_id=action.action_id,
        action_level=action.level,
        target_ids=("enemy:target",),
        source="manual",
        metadata={"crit_mode": "noncrit", "route_source": f"validation_seele_{action_kind}"},
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    damage_mutations = [
        mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"
    ]
    checks = {
        **_transition_checks(transition, state),
        "source_audit": audit.ok,
        "state_changed": state.snapshot().to_json() != after.snapshot().to_json(),
        "damage_mutations_present": bool(damage_mutations),
        "damage_uses_character_card_formula": all(
            mutation.metadata.get("multiplier_source", {}).get("source_kind") == "character_data_card_skill_formula"
            for mutation in damage_mutations
        ),
        "formula_slot_source_present": all(
            bool(mutation.metadata.get("multiplier_source", {}).get("skill_formula_binding_id"))
            for mutation in damage_mutations
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "after_hp": after.units["enemy:target"].hp,
        "damage_mutation_count": len(damage_mutations),
        "source_audit": audit.to_json(),
        "transition": transition.to_json(),
    }


def _action_state() -> BattleState:
    actor = UnitState(
        unit_id="ally:seele",
        side="ally",
        template_id=SEELE_ENTITY_REF,
        level=80,
        max_hp=5000.0,
        hp=5000.0,
        attack=1800.0,
        defense=800.0,
        speed=115.0,
        energy=120.0,
        max_energy=120.0,
        resources={"critical_chance": 0.0, "critical_damage": 0.5},
        flags={"position": 0},
    )
    target = UnitState(
        unit_id="enemy:target",
        side="enemy",
        template_id="monster:validation_target",
        level=80,
        max_hp=500_000.0,
        hp=500_000.0,
        defense=100.0,
        speed=100.0,
        flags={"position": 0, "weaknesses": ("Quantum",)},
    )
    return BattleState(
        units={"ally:seele": actor, "enemy:target": target},
        skill_points=5,
        max_skill_points=5,
    )


def _select_card_extra_turn_queue_slot(rules: RuleBook, card: CharacterDataCardIR) -> CharacterMechanismSlotIR:
    candidates: list[CharacterMechanismSlotIR] = []
    for slot in rules.character_mechanism_slots_for_card(card.card_id):
        if slot.mechanism_kind != "queue_intent":
            continue
        if slot.coverage_status != "executable":
            continue
        if slot.semantics.get("window_family") != "extra_turn":
            continue
        intent_id = slot.linked_ir_ids.get("queue_intent_id")
        if not isinstance(intent_id, str) or rules.queue_intent(intent_id) is None:
            continue
        candidates.append(slot)
    for slot in candidates:
        intent = rules.queue_intent(str(slot.linked_ir_ids["queue_intent_id"]))
        callback = rules.status_callback(intent.callback_id) if intent is not None else None
        if callback is not None and callback.event == "OnAfterSkillUse":
            return slot
    if candidates:
        return candidates[0]
    raise RuntimeError("Seele card has no executable extra-turn queue intent slot")


def _formula_slot_complete(slot: CharacterMechanismSlotIR) -> bool:
    basis = slot.semantics.get("basis_expr")
    return (
        isinstance(basis, dict)
        and basis.get("source_kind") == "character_data_card_skill_formula"
        and bool(basis.get("character_data_card_id"))
        and isinstance(slot.semantics.get("multiplier_param_index"), int)
        and slot.semantics.get("multiplier_param_value") is not None
        and bool(slot.semantics.get("target_group_hint"))
        and bool(slot.source.source_path)
    )


def _slot_counts(slots: tuple[CharacterMechanismSlotIR, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        counts[slot.mechanism_kind] = counts.get(slot.mechanism_kind, 0) + 1
    return counts


def _active_trace_slots(
    trace_slots: list[CharacterMechanismSlotIR],
    enabled_trace_ids: set[str],
) -> list[CharacterMechanismSlotIR]:
    return [
        slot
        for slot in trace_slots
        if isinstance(slot.activation.get("trace_node_id"), str)
        and slot.activation["trace_node_id"] in enabled_trace_ids
    ]


if __name__ == "__main__":
    raise SystemExit(main())
