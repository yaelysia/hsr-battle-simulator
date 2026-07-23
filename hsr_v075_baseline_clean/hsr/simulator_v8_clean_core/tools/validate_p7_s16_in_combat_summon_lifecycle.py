from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.decision import DecisionSystem
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.summon import SummonSystem
from ..systems.timeline import TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p7_s16_in_combat_summon_lifecycle"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    return run_validation_with_rules(rules, output_dir)


def run_validation_with_rules(rules: RuleBook, output_dir: Path) -> dict[str, Any]:
    task_case = _in_combat_task_case(rules)
    negative_case = _spawn_negative_case(rules, task_case)
    presence_case = _presence_case(task_case)
    cleanup_case = _owner_cleanup_case(rules)
    cases = {
        "in_combat_spawn": task_case,
        "presence_target_timeline": presence_case,
        "owner_cleanup": cleanup_case,
        "missing_and_tampered_template": negative_case,
        "summon_action_source": _summon_action_case(task_case),
    }
    rows = {name: value["checks"] for name, value in cases.items()}
    ok = all(row.get("ok") is True for row in rows.values())
    result = {
        "version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "summary": {
            "row_count": len(rows),
            "passed": sum(row.get("ok") is True for row in rows.values()),
            "selected_summon_intent_id": task_case.get("summon_intent_id"),
            "selected_task_id": task_case.get("task_id"),
            "selected_servant_definition_id": cleanup_case.get("servant_definition_id"),
        },
        "checks": rows,
        "evidence": {name: _without_state(value) for name, value in cases.items()},
        "resource_budget": {
            "tbgd_lowering_build_count": 1,
            "rulebook_build_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s16_in_combat_summon_lifecycle.json", result)
    write_json(output_dir / "p7_s16_in_combat_summon_matrix.json", {"rows": rows})
    write_json(output_dir / "p7_s16_in_combat_summon_evidence.json", result["evidence"])
    return result


def _in_combat_task_case(rules: RuleBook) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for intent in rules.summon_monster_intents():
        if intent.coverage_status != "executable":
            continue
        task = rules.ability_task(intent.source_task_id)
        if task is None or task.action_id.startswith("standalone_ability:"):
            continue
        binding = rules.action_ability_binding(task.action_id, task.level)
        admission_binding = next(
            (
                (admission, card)
                for admission in rules.ir.action_admissions
                if admission.action_id == task.action_id
                and admission.action_level == task.level
                and admission.coverage_status == "executable"
                if (card := rules.monster_data_card_for_entity(admission.owner_entity_ref)) is not None
            ),
            None,
        )
        if binding is None or admission_binding is None:
            failures.append(
                {
                    "intent_id": intent.summon_intent_id,
                    "task_id": task.task_id,
                    "reason": "summon_action_binding_or_owner_card_missing",
                }
            )
            continue
        admission, card = admission_binding
        base_owner = _owner(admission.owner_entity_ref)
        owner = replace(
            base_owner,
            action_value=0.0,
            flags={
                **base_owner.flags,
                "monster_data_card_id": card.card_id,
            },
        )
        target = _target()
        initial_state = BattleState(
            units={owner.unit_id: owner, target.unit_id: target},
            skill_points=5,
            max_skill_points=5,
            global_flags={
                "phase": "running",
                "current_window": "idle",
                "combat_phase": "idle",
                "summon_runtime": SummonSystem(rules).view(BattleState()).runtime,
            },
        )
        decisions = DecisionSystem(rules)
        advance = decisions.advance_to_decision(initial_state)
        state = advance.after_state
        decision = advance.decision
        choice = next(
            (
                item
                for item in decision.availability.choices
                if item.action_id == task.action_id and item.action_level == task.level
            ),
            None,
        )
        if not decision.ready or decision.token is None or choice is None:
            failures.append(
                {
                    "intent_id": intent.summon_intent_id,
                    "task_id": task.task_id,
                    "reason": "summon_action_not_queryable",
                    "decision_ready": decision.ready,
                    "decision_blocked_reason": decision.blocked_reason,
                    "queried_action_ids": sorted({item.action_id for item in decision.availability.choices}),
                }
            )
            continue
        target_ids = tuple(choice.auto_target_ids or choice.selectable_target_ids[:1])
        command = ActionCommand(
            actor_id=owner.unit_id,
            action_id=task.action_id,
            action_level=task.level,
            target_ids=target_ids,
            source="validation",
        )
        step = decisions.submit(state, decision.token, command)
        after = step.after_state
        transition = step.transition
        mutations = transition.transaction.mutations
        events = transition.transaction.events
        spawned = tuple(unit_id for unit_id in after.units if unit_id not in state.units)
        replay = MutationReducer().replay_snapshot(state, mutations, after.snapshot().to_json())
        contract = TransitionContractValidator().validate(transition)
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        selected_task_node = next(
            (node for node in transition.outcome.node_results if node.node_id == task.task_id),
            None,
        )
        if (
            not transition.outcome.successor_eligible
            or not spawned
            or not replay.ok
            or not contract.ok
            or not audit.ok
            or selected_task_node is None
            or selected_task_node.status != "complete"
        ):
            failures.append(
                {
                    "intent_id": intent.summon_intent_id,
                    "task_id": task.task_id,
                    "reason": "summon_action_not_committed",
                    "outcome_category": transition.outcome.category,
                    "outcome_reason_codes": list(transition.outcome.reason_codes),
                    "spawned": list(spawned),
                    "replay_ok": replay.ok,
                    "contract_ok": contract.ok,
                    "source_audit_ok": audit.ok,
                    "source_audit_violation_reasons": [
                        violation.reason for violation in audit.violations
                    ],
                }
            )
            continue
        units = tuple(after.units[unit_id] for unit_id in spawned)
        checks = _checks(
            {
                "real_intent_executable": True,
                "task_binding_exact": intent.source_task_id == task.task_id,
                "real_on_start_callback_source": task.callback_kind == "OnStart",
                "query_token_submit_round_trip": decision.ready and choice.target_status == "ok",
                "external_enemy_selection": choice.metadata.get("selection_controller") == "external",
                "selected_graph_committed": transition.outcome.successor_eligible,
                "selected_graph_contains_summon_task": selected_task_node.status == "complete",
                "spawned_during_scheduler_execution": bool(mutations) and bool(spawned),
                "unit_birth_template_used": all(entry.birth_template_id for entry in intent.entries)
                and sum(mutation.op == "spawn" for mutation in mutations) == len(units),
                "owner_relation_exact": all(unit.flags.get("owner_id") == owner.unit_id for unit in units),
                "spawn_event_present": any(event.event_type == "summon.spawned" for event in events),
                "replay_ok": replay.ok,
                "transition_contract_ok": contract.ok,
                "source_audit_ok": audit.ok,
            }
        )
        return {
            "checks": checks,
            "rules": rules,
            "before_state": state,
            "after_state": after,
            "intent": intent,
            "task": task,
            "summon_intent_id": intent.summon_intent_id,
            "task_id": task.task_id,
            "monster_data_card_id": card.card_id,
            "action_binding_id": binding.binding_id,
            "choice_id": choice.choice_id,
            "owner_id": owner.unit_id,
            "spawned_unit_ids": list(spawned),
            "spawned_units": [unit.to_snapshot() for unit in units],
            "mutation_count": len(mutations),
            "event_types": [event.event_type for event in events],
            "replay": replay.to_json(),
            "transition_outcome": transition.outcome.to_json(),
            "transition_contract": contract.to_json(),
            "source_audit": audit.to_json(),
        }
    raise RuntimeError(f"no executable in-combat summon action selected; failures={failures[:5]}")


def _presence_case(task_case: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = task_case["after_state"]
    unit_id = str(task_case["spawned_unit_ids"][0])
    unit = state.units[unit_id]
    lifecycle = UnitLifecycleSystem()
    active_view = lifecycle.view(state, unit_id)
    lifecycle_source = dict(unit.flags.get("lifecycle_source") or {})
    backline_unit = replace(
        unit,
        flags={
            **unit.flags,
            "lifecycle_source": {**lifecycle_source, "presence": "backline", "admission_status": "executable"},
        },
    )
    backline_state = replace(state, units={**state.units, unit_id: backline_unit})
    backline_view = lifecycle.view(backline_state, unit_id)
    missing_targetable = replace(
        unit,
        flags={
            **unit.flags,
            "lifecycle_source": {
                key: value for key, value in lifecycle_source.items() if key != "targetable"
            },
        },
    )
    missing_state = replace(state, units={**state.units, unit_id: missing_targetable})
    rules: RuleBook = task_case["rules"]
    timeline = TimelineSystem().plan_next_actor(backline_state, rules.default_timeline_rule())
    checks = _checks(
        {
            "field_presence_admitted": active_view.is_present,
            "targetability_from_source": active_view.can_be_targeted_alive,
            "backline_not_targetable": not backline_view.can_be_targeted_alive,
            "backline_not_actionable": not backline_view.can_be_action_actor,
            "backline_skipped_by_timeline": any(
                item.get("unit_id") == unit_id for item in timeline.skipped_units
            ),
            "missing_targetable_not_default_true": not lifecycle.view(missing_state, unit_id).can_be_targeted_alive,
        }
    )
    return {"checks": checks, "active_view": active_view.to_json(), "backline_view": backline_view.to_json()}


def _spawn_negative_case(rules: RuleBook, task_case: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = task_case["before_state"]
    intent = task_case["intent"]
    owner_id = str(task_case["owner_id"])
    system = SummonSystem(rules)
    plan = system.plan_spawn_from_intent(state, intent, owner_id=owner_id)
    plans = list(plan.metadata.get("unit_spawn_plans") or [])
    assert plans
    tampered = [dict(item) for item in plans]
    tampered_unit = dict(tampered[0].get("unit") or {})
    tampered_unit["template_id"] = "monster:tampered"
    tampered[0] = {**tampered[0], "unit": tampered_unit}
    tampered_plan = replace(plan, metadata={**plan.metadata, "unit_spawn_plans": tampered})
    tampered_result = system.apply_spawn(state, tampered_plan)
    missing_entry = replace(intent.entries[0], birth_template_id="birth:missing")
    missing_intent = replace(intent, entries=(missing_entry, *intent.entries[1:]))
    missing_plan = system.plan_spawn_from_intent(state, missing_intent, owner_id=owner_id)
    checks = _checks(
        {
            "tampered_plan_blocked": not tampered_result.plan.ok,
            "tampered_no_mutations": not tampered_result.mutations,
            "missing_template_blocked": not missing_plan.ok,
            "missing_template_reason": "birth_template_missing" in missing_plan.blocked_reason,
            "before_state_unchanged": state.snapshot().to_json() == task_case["before_state"].snapshot().to_json(),
        }
    )
    return {
        "checks": checks,
        "tampered_reason": tampered_result.plan.blocked_reason,
        "missing_reason": missing_plan.blocked_reason,
    }


def _owner_cleanup_case(rules: RuleBook) -> dict[str, Any]:
    system = SummonSystem(rules)
    for definition in rules.servant_definitions():
        if definition.coverage_status != "executable" or definition.representation != "unit":
            continue
        if not definition.owner_entity_refs:
            continue
        owner = _owner(definition.owner_entity_refs[0])
        state = BattleState(units={owner.unit_id: owner})
        plan = system.plan_spawn_servant(state, definition, owner_id=owner.unit_id)
        result = system.apply_spawn_servant(state, plan)
        if not result.plan.ok:
            continue
        spawned_state = MutationReducer().apply_all(state, result.mutations)
        original_servant_id = result.plan.unit_ids[0]
        original_servant = spawned_state.units[original_servant_id]
        defeated_servant = replace(
            original_servant,
            hp=0.0,
            flags={**original_servant.flags, "lifecycle_status": "defeated"},
        )
        defeated_state = replace(
            spawned_state,
            units={**spawned_state.units, original_servant_id: defeated_servant},
        )
        replacement_plan = system.plan_spawn_servant(defeated_state, definition, owner_id=owner.unit_id)
        lifecycle_source = dict(definition.lifecycle_source)
        replacement_policy = dict(lifecycle_source.get("replacement_policy") or {})
        lifecycle_source["replacement_policy"] = {
            key: value
            for key, value in replacement_policy.items()
            if key not in {"source_path", "predicate_path", "create_task_path", "evidence", "source_trace"}
        }
        audit_trimmed_definition = replace(definition, lifecycle_source=lifecycle_source)
        audit_trimmed_rules = RuleBook(
            replace(
                rules.ir,
                servant_definitions=tuple(
                    audit_trimmed_definition
                    if item.servant_definition_id == definition.servant_definition_id
                    else item
                    for item in rules.ir.servant_definitions
                ),
            )
        )
        audit_trimmed_plan = SummonSystem(audit_trimmed_rules).plan_spawn_servant(
            defeated_state,
            audit_trimmed_definition,
            owner_id=owner.unit_id,
        )
        replacement = system.apply_spawn_servant(defeated_state, replacement_plan)
        replacement_reduction = MutationReducer().apply_all_result(defeated_state, replacement.mutations)
        if not replacement.plan.ok or not replacement_reduction.ok:
            continue
        replaced_state = replacement_reduction.after_state
        replacement_servant_id = replacement.plan.unit_ids[0]
        removed_owner = replace(owner, flags={**owner.flags, "lifecycle_status": "removed"})
        cleanup_state = replace(replaced_state, units={**replaced_state.units, owner.unit_id: removed_owner})
        cleanup_plan = system.plan_owner_cleanup(cleanup_state, owner.unit_id)
        cleanup = system.apply_remove(cleanup_state, cleanup_plan)
        if not cleanup.plan.ok:
            continue
        reduction = MutationReducer().apply_all_result(cleanup_state, cleanup.mutations)
        servant_id = replacement_servant_id
        view = UnitLifecycleSystem().view(reduction.after_state, servant_id)
        original_view = UnitLifecycleSystem().view(replaced_state, original_servant_id)
        checks = _checks(
            {
                "real_servant_source": True,
                "owner_policy_admitted": cleanup_plan.ok,
                "cleanup_reducer_ok": reduction.ok,
                "replacement_policy_real_source": replacement_plan.metadata.get("replacement_policy", {}).get("source_path", "")
                .startswith("Config/ConfigAbility/Avatar/"),
                "replacement_policy_audit_clear_behavior_equal": (
                    replacement_plan.ok,
                    replacement_plan.operation,
                    replacement_plan.blocked_reason,
                    replacement_plan.unit_ids,
                    replacement_plan.metadata.get("replacement_unit_ids"),
                )
                == (
                    audit_trimmed_plan.ok,
                    audit_trimmed_plan.operation,
                    audit_trimmed_plan.blocked_reason,
                    audit_trimmed_plan.unit_ids,
                    audit_trimmed_plan.metadata.get("replacement_unit_ids"),
                ),
                "defeated_instance_removed_before_replacement": original_view.is_removed,
                "replacement_instance_active": UnitLifecycleSystem().view(replaced_state, replacement_servant_id).is_active,
                "replacement_events_auditable": {event.event_type for event in replacement.events}
                == {"summon.removed", "summon.spawned"},
                "replacement_replay_ok": MutationReducer().replay_snapshot(
                    defeated_state,
                    replacement.mutations,
                    replaced_state.snapshot().to_json(),
                ).ok,
                "servant_removed": view.is_removed,
                "cleanup_event_present": any(event.event_type == "summon.removed" for event in cleanup.events),
                "replay_ok": MutationReducer().replay_snapshot(
                    cleanup_state,
                    cleanup.mutations,
                    reduction.after_state.snapshot().to_json(),
                ).ok,
            }
        )
        return {
            "checks": checks,
            "servant_definition_id": definition.servant_definition_id,
            "servant_id": servant_id,
            "replaced_servant_id": original_servant_id,
            "replacement_plan": replacement_plan.to_json(),
            "cleanup_plan": cleanup_plan.to_json(),
            "after_view": view.to_json(),
        }
    raise RuntimeError("no executable real servant owner-cleanup source selected")


def _summon_action_case(task_case: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = task_case["after_state"]
    unit = state.units[str(task_case["spawned_unit_ids"][0])]
    rules: RuleBook = task_case["rules"]
    admission = unit.flags.get("summon_action_admission")
    query_state = replace(
        state,
        global_flags={
            **state.global_flags,
            "turn_owner_id": unit.unit_id,
            "phase": "scenario",
            "current_window": "idle",
            "combat_phase": "awaiting_decision",
        },
    )
    availability = ActionAvailabilitySystem(rules).view(query_state)
    choices = availability.choices
    owner_entity_ref = str(unit.flags.get("owner_entity_ref") or unit.template_id)
    expected_card_id = admission.get("monster_data_card_id") if isinstance(admission, dict) else ""
    callback_ids = tuple(
        callback_id
        for detail in unit.flags.get("status_details") or ()
        if isinstance(detail, dict)
        if isinstance(detail.get("trigger_ids_by_event"), dict)
        for callback_id in detail["trigger_ids_by_event"].get("OnCreate", ())
        if isinstance(callback_id, str) and callback_id
    )
    attachment_effects = tuple(
        effect
        for callback_id in callback_ids
        for task in rules.status_callback_tasks_for_callback(callback_id)
        if task.opcode == "OwnerEntityAddAbility"
        if (effect := rules.effect(task.effect_id)) is not None
        if effect.coverage_status == "executable"
    )
    attachment_effect = attachment_effects[0] if len(attachment_effects) == 1 else None
    effect_registry = EffectRegistry()
    effect_context = EffectExecutionContext(
        state=state,
        caster_id=str(unit.flags.get("summoner_id") or unit.unit_id),
        source_id="validation:owner_entity_ability_attachment",
        owner_id=unit.unit_id,
    )
    missing_name_result = None
    malformed_registry_result = None
    duplicate_result = None
    if attachment_effect is not None:
        standard = attachment_effect.payload.get("standard")
        missing_name_result = effect_registry.execute(
            replace(
                attachment_effect,
                payload={
                    **attachment_effect.payload,
                    "standard": {**standard, "ability_name": ""} if isinstance(standard, dict) else {},
                },
            ),
            effect_context,
        )
        malformed_unit = replace(
            unit,
            flags={**unit.flags, "attached_ability_names": {"invalid": True}},
        )
        malformed_state = replace(state, units={**state.units, unit.unit_id: malformed_unit})
        malformed_registry_result = effect_registry.execute(
            attachment_effect,
            replace(effect_context, state=malformed_state),
        )
        duplicate_result = effect_registry.execute(attachment_effect, effect_context)
    checks = _checks(
        {
            "actionable_flag_source_backed": unit.flags.get("summon_action_admitted") is True,
            "action_admission_present": isinstance(admission, dict)
            and admission.get("coverage_status") == "executable",
            "own_monster_card_bound": isinstance(admission, dict) and bool(admission.get("monster_data_card_id")),
            "lifecycle_can_act": UnitLifecycleSystem().view(state, unit.unit_id).can_be_action_actor,
            "read_only_action_query_nonempty": bool(choices),
            "query_actor_is_summon": availability.actor.actor_id == unit.unit_id,
            "all_choices_owned_by_summon_card": bool(choices)
            and all(choice.owner_entity_ref == owner_entity_ref for choice in choices),
            "all_choices_use_bound_card": bool(choices)
            and all(
                choice.source_trace.get("actor_data_card", {}).get("card_id") == expected_card_id
                for choice in choices
            ),
            "all_choices_executable_with_targets": bool(choices)
            and all(
                choice.coverage_status == "executable"
                and choice.target_status == "ok"
                and choice.resource_status == "ok"
                for choice in choices
            ),
            "owner_entity_ability_attachment_committed": bool(unit.flags.get("attached_ability_names")),
            "ability_attachment_source_exact": attachment_effect is not None,
            "ability_name_missing_blocked": missing_name_result is not None
            and bool(missing_name_result.unsupported)
            and not missing_name_result.mutations,
            "malformed_attachment_registry_blocked": malformed_registry_result is not None
            and bool(malformed_registry_result.unsupported)
            and not malformed_registry_result.mutations,
            "duplicate_attachment_is_idempotent": duplicate_result is not None
            and not duplicate_result.unsupported
            and not duplicate_result.mutations,
        }
    )
    return {
        "checks": checks,
        "action_admission": admission,
        "query_mode": availability.mode,
        "choice_ids": [choice.choice_id for choice in choices],
        "choice_action_ids": [choice.action_id for choice in choices],
        "attached_ability_names": list(unit.flags.get("attached_ability_names") or ()),
        "attachment_effect_id": attachment_effect.effect_id if attachment_effect is not None else "",
        "missing_name_unsupported": list(missing_name_result.unsupported) if missing_name_result is not None else [],
        "malformed_registry_unsupported": list(malformed_registry_result.unsupported)
        if malformed_registry_result is not None
        else [],
    }


def _owner(template_id: str) -> UnitState:
    return UnitState(
        unit_id="enemy:summoner",
        side="enemy",
        template_id=template_id,
        level=80,
        max_hp=1000.0,
        hp=1000.0,
        attack=500.0,
        defense=500.0,
        speed=100.0,
        action_value=100.0,
        flags={"position": 0, "team_side": "enemy", "lifecycle_status": "active"},
    )


def _target() -> UnitState:
    return UnitState(
        unit_id="ally:target",
        side="ally",
        template_id="avatar:validation_target",
        level=80,
        max_hp=3000.0,
        hp=3000.0,
        attack=1000.0,
        defense=800.0,
        speed=100.0,
        action_value=100.0,
        flags={"position": 0, "team_side": "ally", "lifecycle_status": "active"},
    )


def _sequence_step_level(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(value)
        except ValueError:
            return fallback
    return fallback


def _without_state(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"rules", "before_state", "after_state", "intent", "task"}
    }


def _checks(values: dict[str, bool]) -> dict[str, Any]:
    return {"ok": all(values.values()), **values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S16 in-combat summon lifecycle.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root or find_tbgd_root(package_root.parent)
    result = run_validation(tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['summary']['row_count']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
