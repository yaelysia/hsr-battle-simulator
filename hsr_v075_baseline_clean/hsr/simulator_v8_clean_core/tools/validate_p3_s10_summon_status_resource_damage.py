from __future__ import annotations

import argparse
import json
from collections import Counter
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
    JSONValue,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..core.transition_outcome import ExecutionNodeResult, classify_transition_outcome
from ..rules.ir import ActionDefinitionIR, ServantDefinitionIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.damage import DamagePacket, DamageSourceFrame, DamageSystem
from ..systems.summon import SummonSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _first_servant_id,
    _select_executable_servant_definition,
)
from .validate_p3_s5_servant_lifecycle import _formal_servant_state
from .validate_p3_s6_summon_action_execution import _command_from_choice


VALIDATION_VERSION = "p3_s10_summon_status_resource_damage"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    definition = _select_executable_servant_definition(rules)
    groups = {
        "servant_status_holder_positive": _servant_status_holder_case(rules, definition),
        "servant_damage_stat_boundary": _servant_damage_stat_boundary_case(rules, definition),
        "resource_ownership_boundary": _resource_ownership_boundary_case(rules, definition),
        "kill_attribution_source_frame_boundary": _kill_attribution_source_frame_case(rules, definition),
        "removed_summon_damage_negative": _removed_summon_damage_negative_case(rules, definition),
        "source_matrix": _source_matrix_case(tbgd_root, rules),
    }
    checks = {
        **{name: group["checks"] for name, group in groups.items()},
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_summon_status_resource_damage_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "servant_definition_id": definition.servant_definition_id,
            },
            "resource_budget": {
                "rulebook_build_count": 1,
                "large_artifacts_written": False,
                "output_scope": "summary_matrix_and_compact_case_audit_only",
            },
        },
        "summary": {
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
            "status_positive_action_id": groups["servant_status_holder_positive"]["action_id"],
            "status_positive_replay_ok": groups["servant_status_holder_positive"]["replay"]["ok"],
            "status_positive_source_audit_ok": groups["servant_status_holder_positive"]["source_audit"]["ok"],
            "damage_transition_committed": groups["servant_damage_stat_boundary"].get(
                "classification"
            )
            == "executable",
            "damage_mutation_count": groups["servant_damage_stat_boundary"].get(
                "damage_mutation_count",
                0,
            ),
            "damage_boundary_reason": groups["servant_damage_stat_boundary"]["coverage"].get(
                "summon_damage_stat_blocked_reason",
                "",
            ),
            "kill_attribution_owner": groups["kill_attribution_source_frame_boundary"]["defeat_payload"].get("kill_credit_owner_id", ""),
            "kill_attribution_attacker": groups["kill_attribution_source_frame_boundary"]["defeat_payload"].get("attacker_id", ""),
            "servant_damage_action_ir_count": groups["source_matrix"]["servant_hp_damage_action_ir_count"],
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s10_summon_status_resource_damage.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S10 summon status/resource/damage boundaries.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _servant_status_holder_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state, servant_id = _spawn_servant_turn_state(rules, definition)
    effect, status_result = _select_servant_status_effect(rules, state, servant_id)
    after = MutationReducer().apply_all(state, status_result.mutations)
    command = ActionCommand(
        actor_id=servant_id,
        action_id=f"status_effect:{effect.effect_id}",
        action_level=0,
        target_ids=(servant_id,),
        source="validation",
    )
    node = ExecutionNodeResult(
        node_kind="status_application",
        node_id=effect.effect_id,
        status="complete",
    )
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=status_result.events,
            mutations=status_result.mutations,
            settlement=ActionSettlement(
                command.action_id,
                servant_id,
                command.target_ids,
                status_result.records,
            ),
        ),
        after=after.snapshot(),
        target_resolution=TargetResolution(
            requested=(servant_id,),
            legal=(servant_id,),
            selected=(servant_id,),
            reason="servant_status_holder_validation",
            source="status_system",
        ),
        rng_events=status_result.rng_events,
        outcome=classify_transition_outcome(
            (node,),
            state_changed=state.snapshot().to_json() != after.snapshot().to_json(),
            mutation_count=len(status_result.mutations),
        ),
        coverage={"validation": VALIDATION_VERSION, "effect_id": effect.effect_id},
    )
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    contract = TransitionContractValidator().validate(transition)
    records = transition.transaction.settlement.records if transition.transaction.settlement is not None else ()
    status_mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "status_system"]
    servant_after = after.units[servant_id]
    checks = {
        "actor_is_servant": state.units[servant_id].flags.get("summon_kind") == "servant",
        "target_is_same_servant": command.target_ids == (servant_id,),
        "status_application_complete": status_result.ok and transition.outcome.successor_eligible,
        "status_mutations_present": bool(status_mutations),
        "status_holder_is_servant": bool(servant_after.statuses),
        "status_mutation_targets_servant": any(len(mutation.path) > 1 and mutation.path[1] == servant_id for mutation in status_mutations),
        "status_settlement_records_present": any(
            str(record.get("record_type") or "").startswith("status") for record in records
        ),
        "no_damage_from_status_holder_probe": not any(mutation.source == "damage_system" for mutation in status_result.mutations),
        "resource_not_defaulted_to_owner": after.skill_points == state.skill_points
        and after.units["ally:servant_owner"].energy == state.units["ally:servant_owner"].energy,
        "replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
        "transition_contract_ok": contract.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable_status_holder_primitive",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "action_id": command.action_id,
        "effect_id": effect.effect_id,
        "effect_source": effect.source.to_json(),
        "command": _command_json(command),
        "coverage": _compact_coverage(transition.coverage),
        "mutation_source_counts": _mutation_source_counts(transition.transaction.mutations),
        "status_mutation_paths": [list(mutation.path) for mutation in status_mutations],
        "after_servant_statuses": list(servant_after.statuses),
        "record_types": [str(record.get("record_type") or "") for record in records[:30]],
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit.to_json()),
        "transition_contract": contract.to_json(),
    }


def _servant_damage_stat_boundary_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state, servant_id = _spawn_servant_turn_state(rules, definition)
    view = ActionAvailabilitySystem(rules).view(state)
    candidates = []
    for choice in view.choices:
        action = rules.action_definition(choice.action_id, choice.action_level)
        target_ids = choice.auto_target_ids or choice.selectable_target_ids[:1]
        if (
            action is None
            or action.damage_kind != "hp_damage"
            or action.coverage_status != "executable"
            or not target_ids
        ):
            continue
        candidates.append((choice, action, tuple(target_ids)))
    attempts: list[dict[str, Any]] = []
    selected = None
    for choice, action, target_ids in candidates:
        command = _command_from_choice(choice, target_ids)
        after, transition = CombatExecutor(rules).execute(command, state)
        replay = MutationReducer().replay_snapshot(
            state,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        damage_mutations = tuple(
            mutation
            for mutation in transition.transaction.mutations
            if mutation.source == "damage_system"
        )
        attempt = {
            "action_id": choice.action_id,
            "action_level": choice.action_level,
            "target_ids": list(target_ids),
            "action_enabled": transition.coverage.get("action_enabled") is True,
            "outcome_category": transition.outcome.category,
            "successor_eligible": transition.outcome.successor_eligible,
            "mutation_count": len(transition.transaction.mutations),
            "damage_mutation_count": len(damage_mutations),
            "replay_ok": replay.ok,
            "source_audit_ok": source_audit.ok,
            "blocked_reason": str(
                transition.coverage.get("blocked_reason")
                or transition.coverage.get("plan_blocked_reason")
                or ""
            ),
        }
        attempts.append(attempt)
        if (
            attempt["action_enabled"]
            and attempt["outcome_category"] == "committed"
            and attempt["successor_eligible"]
            and damage_mutations
            and replay.ok
            and source_audit.ok
        ):
            selected = (
                choice,
                action,
                command,
                after,
                transition,
                replay,
                source_audit,
                damage_mutations,
            )
            break
    if selected is None:
        checks = {
            "action_query_external_selectable": view.mode == "external_selectable",
            "source_backed_hp_damage_choice_present": bool(candidates),
            "committed_damage_transition_found": False,
        }
        return {
            "checks": {"ok": False, "checks": checks},
            "classification": "implementation_missing",
            "servant_definition_id": definition.servant_definition_id,
            "servant_unit_id": servant_id,
            "choice_count": len(view.choices),
            "hp_damage_choice_count": len(candidates),
            "attempts": attempts,
            "coverage": {},
        }
    choice, action, command, after, transition, replay, source_audit, damage_mutations = selected
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    damage_stat_admission = state.units[servant_id].flags.get(
        "servant_damage_stat_admission"
    )
    damage_stat_bindings = (
        tuple(damage_stat_admission.get("stat_bindings") or ())
        if isinstance(damage_stat_admission, dict)
        else ()
    )
    checks = {
        "servant_hp_damage_action_present": action.damage_kind == "hp_damage" and action.coverage_status == "executable",
        "action_selected_by_query": view.mode == "external_selectable"
        and choice in view.choices,
        "choice_source_trace_complete": bool(choice.source_trace.get("summon_action_admission"))
        and bool(choice.source_trace.get("action_definition"))
        and bool(choice.source_trace.get("action_event")),
        "damage_stats_source_backed": isinstance(damage_stat_admission, dict)
        and damage_stat_admission.get("coverage_status") == "executable"
        and len(damage_stat_bindings) == 4
        and all(
            isinstance(binding, dict) and binding.get("sources")
            for binding in damage_stat_bindings
        ),
        "action_enabled": transition.coverage.get("action_enabled") is True,
        "transition_committed": transition.outcome.category == "committed"
        and transition.outcome.successor_eligible,
        "damage_mutations_present": bool(damage_mutations),
        "settlement_records_present": bool(records),
        "source_audit_ok": source_audit.ok,
        "replay_ok": replay.ok,
        "after_matches_transition": after.snapshot().to_json()
        == transition.after.to_json(),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "action": _action_summary(action),
        "choice": _compact_choice(choice.to_json()),
        "command": _command_json(command),
        "coverage": _compact_coverage(transition.coverage),
        "mutation_count": len(transition.transaction.mutations),
        "damage_mutation_count": len(damage_mutations),
        "mutation_source_counts": _mutation_source_counts(
            transition.transaction.mutations
        ),
        "record_types": [str(record.get("record_type") or "") for record in records[:20]],
        "outcome": {
            "category": transition.outcome.category,
            "reason_codes": list(transition.outcome.reason_codes),
            "successor_eligible": transition.outcome.successor_eligible,
        },
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": _compact_source_audit(source_audit.to_json()),
        "attempts": attempts,
    }


def _resource_ownership_boundary_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state, servant_id = _spawn_servant_turn_state(rules, definition)
    view = ActionAvailabilitySystem(rules).view(state)
    resource_choices = [
        choice
        for choice in view.choices
        if (rules.action_definition(choice.action_id, choice.action_level) is not None)
        and rules.require_action_definition(choice.action_id, choice.action_level).bp_need > 0
    ]
    resource_action_sources = [
        action
        for action in rules.ir.action_definitions
        if action.action_id.startswith("servant_skill:") and action.bp_need > 0
    ]
    checks = {
        "servant_action_query_classified": view.mode in {"external_selectable", "blocked"},
        "resource_query_matches_source_or_action_gap": bool(resource_choices) or not resource_action_sources or not view.choices,
        "no_synthetic_resource_case": not resource_choices,
        "owner_energy_not_declared_default_resource_owner": all(
            choice.metadata.get("summon_kind") == "servant" for choice in view.choices
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "source_absent_not_required" if not resource_action_sources else "implementation_missing",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "choice_count": len(view.choices),
        "resource_costing_choice_count": len(resource_choices),
        "resource_costing_action_source_count": len(resource_action_sources),
        "note": "Current executable servant actions have no positive skill-point cost; resource ownership mutation is not synthesized.",
    }


def _kill_attribution_source_frame_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state, servant_id = _spawn_servant_turn_state(rules, definition)
    victim_id = "enemy:target"
    victim = state.units[victim_id]
    state = replace(state, units={**state.units, victim_id: replace(victim, hp=10.0, max_hp=10.0)})
    source_trace = state.units[servant_id].flags.get("servant_definition_source_trace")
    packet = DamagePacket(
        attacker_id=servant_id,
        target_id=victim_id,
        attack_type="validation_summon_source_frame",
        damage_formula_family="hp_loss",
        damage_kind="hp_loss",
        amount=20.0,
        amount_stage="fixed_final",
        source_frame=DamageSourceFrame(
            owner_id="ally:servant_owner",
            source_id=f"summon_action:{definition.servant_definition_id}",
            source_kind="summon_damage_source_frame_boundary",
            sequence_id=f"summon:{servant_id}:validation_damage",
            target_id=victim_id,
            can_continue_after_lethal=False,
            source_trace=source_trace if isinstance(source_trace, dict) else {},
        ),
        source_trace=source_trace if isinstance(source_trace, dict) else {},
        metadata={
            "damage_source_owner_id": "ally:servant_owner",
            "damage_source_id": f"summon_action:{definition.servant_definition_id}",
            "damage_source_kind": "summon_damage_source_frame_boundary",
            "damage_sequence_id": f"summon:{servant_id}:validation_damage",
            "primary_action_target_id": victim_id,
            "validation_boundary": VALIDATION_VERSION,
        },
    )
    result = DamageSystem().apply_packet(state, packet)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    defeat_event = next((event.to_json() for event in result.events if event.event_type == "unit.defeated"), {})
    defeat_payload = defeat_event.get("payload") if isinstance(defeat_event.get("payload"), dict) else {}
    checks = {
        "damage_boundary_mutations_present": bool(result.mutations),
        "victim_defeated": after.units[victim_id].flags.get("lifecycle_status") == "defeated",
        "attacker_is_servant": defeat_payload.get("attacker_id") == servant_id,
        "kill_credit_owner_is_owner": defeat_payload.get("kill_credit_owner_id") == "ally:servant_owner",
        "kill_credit_source_is_source_frame": defeat_payload.get("kill_credit_source_id")
        == f"summon_action:{definition.servant_definition_id}",
        "source_kind_preserved": defeat_payload.get("kill_credit_source_kind") == "summon_damage_source_frame_boundary",
        "replay_ok": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "engine_source_frame_boundary_not_servant_damage_formula_executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "mutation_source_counts": _mutation_source_counts(result.mutations),
        "record_types": [str(record.get("record_type") or "") for record in result.records],
        "defeat_event": defeat_event,
        "defeat_payload": defeat_payload,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _removed_summon_damage_negative_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state, servant_id = _spawn_servant_turn_state(rules, definition)
    system = SummonSystem(rules)
    remove_plan = system.plan_owner_cleanup(state, "ally:servant_owner")
    remove_result = system.apply_remove(state, remove_plan)
    removed_state = MutationReducer().apply_all(state, remove_result.mutations)
    packet = DamagePacket(
        attacker_id="enemy:target",
        target_id=servant_id,
        attack_type="validation_removed_summon_damage",
        damage_formula_family="hp_loss",
        damage_kind="hp_loss",
        amount=20.0,
        source_trace={"validation": VALIDATION_VERSION},
        metadata={
            "damage_source_owner_id": "enemy:target",
            "damage_source_id": "validation:removed_summon_damage",
            "damage_source_kind": "removed_summon_negative",
            "damage_sequence_id": "validation:removed_summon_damage",
        },
    )
    result = DamageSystem().apply_packet(removed_state, packet)
    payload = result.records[0].get("payload", {}) if result.records else {}
    checks = {
        "remove_plan_ok": remove_plan.ok and remove_plan.operation == "owner_removed_cleanup",
        "servant_removed": removed_state.units[servant_id].flags.get("lifecycle_status") == "removed",
        "damage_to_removed_blocked": not result.mutations,
        "blocked_reason_removed": payload.get("reason") == "damage_source_target_removed",
        "no_defeat_or_hit_event": not result.events,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "negative_removed_summon_no_damage_mutation",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "remove_plan": remove_plan.to_json(),
        "damage_records": list(result.records),
    }


def _source_matrix_case(tbgd_root: Path, rules: RuleBook) -> dict[str, Any]:
    raw_damage_count = _raw_servant_damage_skill_count(tbgd_root)
    hp_damage_actions = [
        action
        for action in rules.ir.action_definitions
        if action.action_id.startswith("servant_skill:")
        and action.damage_kind == "hp_damage"
        and action.coverage_status == "executable"
    ]
    stat_admitted_definitions = [
        definition
        for definition in rules.ir.servant_definitions
        if definition.coverage_status == "executable"
        and definition.stat_source.get("admission_status") == "executable"
        and definition.action_set.get("admission_status") == "executable"
    ]
    checks = {
        "raw_servant_damage_skills_present": raw_damage_count > 0,
        "servant_hp_damage_action_ir_present": bool(hp_damage_actions),
        "source_backed_damage_stat_admission_present": bool(
            stat_admitted_definitions
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "damage_action_ir_and_owned_build_stat_admission_present",
        "raw_servant_damage_skill_count": raw_damage_count,
        "servant_hp_damage_action_ir_count": len(hp_damage_actions),
        "stat_admitted_servant_definition_count": len(
            stat_admitted_definitions
        ),
        "sample_action": _action_summary(hp_damage_actions[0]) if hp_damage_actions else {},
    }


def _spawn_servant_turn_state(rules: RuleBook, definition: ServantDefinitionIR) -> tuple[BattleState, str]:
    state = _formal_servant_state(rules, definition)
    system = SummonSystem(rules)
    result = system.apply_spawn_servant(
        state,
        system.plan_spawn_servant(
            state,
            definition,
            owner_id="ally:servant_owner",
            spawn_source=definition.spawn_sources[0],
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    servant_id = _first_servant_id(after)
    return (
        replace(
            after,
            global_flags={
                **after.global_flags,
                "turn_owner_id": servant_id,
                "phase": "scenario",
                "current_window": "idle",
                "combat_phase": "awaiting_decision",
            },
        ),
        servant_id,
    )


def _select_servant_status_effect(rules: RuleBook, state: BattleState, servant_id: str):
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("target_alias") not in {
            "Caster",
            "ModifierOwnerEntity",
            "ParamEntity",
            "CurrentActionTarget",
        }:
            continue
        result = StatusSystem(rules).apply_add_modifier(
            state,
            effect,
            caster_id=servant_id,
            source_id=f"validation:p3_s10:{effect.effect_id}",
            owner_id=servant_id,
            param_entity_id=servant_id,
            current_action_target_id=servant_id,
        )
        if result.ok and result.mutations and all(
            len(mutation.path) > 1 and mutation.path[0] == "units" and mutation.path[1] == servant_id
            for mutation in result.mutations
        ):
            return effect, result
        failures.append({"effect_id": effect.effect_id, "unsupported": list(result.unsupported)})
    raise RuntimeError(f"no executable AddModifier status-holder probe selected; failures={failures[:5]}")


def _select_servant_hp_damage_action(rules: RuleBook) -> ActionDefinitionIR:
    for action in sorted(rules.ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if action.action_id.startswith("servant_skill:") and action.damage_kind == "hp_damage" and action.coverage_status == "executable":
            return action
    raise RuntimeError("no executable servant hp-damage ActionDefinitionIR selected by structured predicate")


def _raw_servant_damage_skill_count(tbgd_root: Path) -> int:
    path = tbgd_root / "ExcelOutput" / "AvatarServantSkillConfig.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        1
        for row in data
        if isinstance(row, dict)
        and (row.get("AttackType") == "Servant" or row.get("StanceDamageType") or row.get("StanceDamageDisplay"))
    )


def _compact_choice(choice: dict[str, JSONValue]) -> dict[str, JSONValue]:
    metadata = choice.get("metadata") if isinstance(choice.get("metadata"), dict) else {}
    action = metadata.get("action_definition") if isinstance(metadata.get("action_definition"), dict) else {}
    return {
        "choice_id": str(choice.get("choice_id") or ""),
        "choice_kind": str(choice.get("choice_kind") or ""),
        "actor_id": str(choice.get("actor_id") or ""),
        "action_id": str(choice.get("action_id") or ""),
        "action_level": int(choice.get("action_level") or 0),
        "selectable_target_ids": list(choice.get("selectable_target_ids") or []),
        "skill_effect": str(action.get("skill_effect") or ""),
        "damage_kind": str(action.get("damage_kind") or ""),
    }


def _command_json(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "metadata": command.metadata,
    }


def _action_summary(action: ActionDefinitionIR) -> dict[str, JSONValue]:
    return {
        "action_id": action.action_id,
        "level": action.level,
        "definition_id": action.definition_id,
        "coverage_status": action.coverage_status,
        "attack_type": action.attack_type,
        "skill_effect": action.skill_effect,
        "damage_kind": action.damage_kind,
        "damage_formula_family": action.damage_formula_family,
        "source": action.source.to_json(),
    }


def _compact_coverage(coverage: dict[str, JSONValue]) -> dict[str, JSONValue]:
    keys = (
        "action_enabled",
        "blocked_reason",
        "plan_blocked_reason",
        "target_ok",
        "resource_ok",
        "binding_ok",
        "event_ok",
        "summon_execution_blocked_reason",
        "summon_damage_stat_blocked_reason",
        "damage_mutation_count",
        "toughness_mutation_count",
        "resource_mutation_count",
        "ability_task_mutation_count",
    )
    return {key: coverage.get(key) for key in keys if key in coverage}


def _compact_source_audit(audit: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "ok": bool(audit.get("ok")),
        "checked_mutations": int(audit.get("checked_mutations") or 0),
        "checked_records": int(audit.get("checked_records") or 0),
        "violations": audit.get("violations", []),
        "trace_origins": [trace.get("origin", {}) for trace in audit.get("traces", []) if isinstance(trace, dict)],
    }


def _mutation_source_counts(mutations) -> dict[str, int]:
    return dict(Counter(str(mutation.source) for mutation in mutations))


if __name__ == "__main__":
    raise SystemExit(main())
