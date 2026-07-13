from __future__ import annotations

import argparse
import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, BattleState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..systems.enemy_action import EnemyActionCandidate, EnemyActionSystem
from ..systems.decision import DecisionSystem
from ..systems.scheduler import CombatScheduler
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_283"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _select_fixed_sequence_card(rules)
    scenario_data = _scenario_data(package_root.parent, card)
    candidate_case = _candidate_case(rules, scenario_data, card)
    execution_case = _execution_case(rules, scenario_data, card)
    boundary_case = _boundary_case(rules, scenario_data, card)
    queue_case = _queue_priority_case(rules, scenario_data)
    checks = {
        "candidate": candidate_case["checks"],
        "execution": execution_case["checks"],
        "boundary": boundary_case["checks"],
        "queue_priority": queue_case["checks"],
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
                "mode": "structured_predicate",
                "fixed_monster_id_used_for_selection": False,
                "predicate": [
                    "MonsterDataCardIR.ai_policy.admission_status=executable",
                "至少两段 action_sequence，优先第一段 target_mode=single",
                "action_ref 在 RuleBook 中有 ActionDefinitionIR/ActionEventIR",
                "第一段动作至少具有 ability binding、damage emission；完整 selected graph 另行按 query 结果分类",
                "无 summon_refs，目标枚举能找到合法目标",
                ],
            },
            "selected_monster": _card_identity(card),
        },
        "checks": checks,
        "candidate_case": candidate_case,
        "execution_case": execution_case,
        "boundary_case": boundary_case,
        "queue_priority_case": queue_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_283.json", result)
    write_json(output_dir / "enemy_action_candidate_sample_v0_283.json", candidate_case)
    write_json(output_dir / "enemy_action_execution_sample_v0_283.json", execution_case)
    write_json(output_dir / "enemy_action_boundary_cases_v0_283.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_283 enemy fixed sequence action candidates.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _candidate_case(rules: RuleBook, scenario_data: dict[str, Any], card: MonsterDataCardIR) -> dict[str, Any]:
    scheduler, state = _initialized_scheduler_state(rules, scenario_data)
    result = scheduler.step(state)
    candidate = scheduler.enemy_actions.next_candidate(result.after_state, "enemy:target")
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    records = result.transition.transaction.settlement.records if result.transition.transaction.settlement else ()
    combat_mutation_sources = {"damage_system", "toughness_system", "break_system", "status_system", "effect_system", "enemy_action_system"}
    checks = {
        "natural_turn_not_blocked": not result.transition.coverage.get("blocked_reason"),
        "candidate_available": candidate.status == "available",
        "candidate_actor_enemy": candidate.actor_id == "enemy:target",
        "candidate_card_matches_unit": candidate.monster_data_card_id == card.card_id,
        "candidate_action_matches_sequence": candidate.action_ref == str(card.action_sequence[0].get("action_ref") or ""),
        "candidate_has_targets": bool(candidate.selectable_target_ids or candidate.auto_target_ids),
        "candidate_record_process_only": any(record.get("record_type") == "enemy_action_candidate" and record.get("process_only") is True for record in records),
        "candidate_event_present": any(event.event_type == "enemy.action.candidate" for event in result.transition.transaction.events),
        "no_combat_mutation_from_candidate": not any(mutation.source in combat_mutation_sources for mutation in result.transition.transaction.mutations),
        "source_audit": audit.ok,
        "after_state_replay": MutationReducer().replay_snapshot(state, result.transition.transaction.mutations, result.transition.after.to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster": _card_identity(card),
        "candidate": candidate.to_json(),
        "transition": result.transition.to_json(),
        "source_audit": audit.to_json(),
    }


def _execution_case(rules: RuleBook, scenario_data: dict[str, Any], card: MonsterDataCardIR) -> dict[str, Any]:
    scheduler, state = _initialized_scheduler_state(rules, scenario_data)
    begin = scheduler.step(state)
    candidate = scheduler.enemy_actions.next_candidate(begin.after_state, "enemy:target")
    target_ids = _selected_targets_for_candidate(candidate)
    command = scheduler.enemy_actions.command_from_candidate(candidate, target_ids)
    decision = DecisionSystem(rules).current_decision(begin.after_state)
    if not decision.ready or decision.token is None:
        blocked_reasons = [item.reason for item in decision.availability.blocked]
        checks = {
            "candidate_available": candidate.status == "available",
            "incomplete_graph_not_exposed": not decision.availability.choices,
            "implementation_gap_structured": any(
                token in reason
                for reason in blocked_reasons
                for token in ("action_task_not_executable", "effect_coverage_status", "action_event")
            ),
            "query_state_unchanged": begin.after_state.snapshot().to_json() == begin.transition.after.to_json(),
            "cursor_not_advanced": begin.after_state.units["enemy:target"].flags.get("enemy_action_sequence_cursor") is None,
        }
        checks["ok"] = all(value for key, value in checks.items() if key != "ok")
        return {
            "classification": "implementation_missing",
            "checks": {"ok": checks["ok"], "checks": checks},
            "selected_monster": _card_identity(card),
            "command": _command_json(command),
            "candidate": candidate.to_json(),
            "decision": decision.to_json(),
            "blocked_reasons": blocked_reasons,
            "gap": "real fixed-sequence source exists, but the selected action graph contains non-executable tasks",
        }
    result = DecisionSystem(rules).submit(begin.after_state, decision.token, command)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    replay = MutationReducer().replay_snapshot(begin.after_state, result.transition.transaction.mutations, result.transition.after.to_json())
    cursor = result.after_state.units["enemy:target"].flags.get("enemy_action_sequence_cursor")
    next_candidate = scheduler.enemy_actions.next_candidate(result.after_state, "enemy:target")
    action_child = _dict(result.transition.coverage.get("action_child"))
    child_coverage = _dict(action_child.get("coverage"))
    cursor_mutations = [
        mutation for mutation in result.transition.transaction.mutations
        if mutation.source == "enemy_action_system" and mutation.path[-1:] == ("enemy_action_sequence_cursor",)
    ]
    checks = {
        "command_from_candidate": command.actor_id == candidate.actor_id and command.action_id == candidate.action_ref,
        "action_enabled": child_coverage.get("action_enabled") is True,
        "cursor_advanced": cursor == 1,
        "cursor_mutation_present": len(cursor_mutations) == 1,
        "cursor_source_audit": audit.ok,
        "next_candidate_uses_advanced_cursor": next_candidate.sequence_index == (1 % len(card.action_sequence)),
        "damage_or_toughness_mutation_present": any(
            mutation.source in {"damage_system", "toughness_system"} for mutation in result.transition.transaction.mutations
        ),
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "selected_monster": _card_identity(card),
        "command": _command_json(command),
        "candidate": candidate.to_json(),
        "next_candidate": next_candidate.to_json(),
        "transition": result.transition.to_json(),
        "source_audit": audit.to_json(),
        "replay": {
            "ok": replay.ok,
            "errors": list(replay.errors),
        },
        "classification": "executable",
    }


def _boundary_case(rules: RuleBook, scenario_data: dict[str, Any], card: MonsterDataCardIR) -> dict[str, Any]:
    scheduler, state = _initialized_scheduler_state(rules, scenario_data)
    begin = scheduler.step(state)
    active_state = begin.after_state
    system = EnemyActionSystem(rules)
    missing_card_state = _unit_without_flag(active_state, "enemy:target", "monster_data_card_id")
    missing_sequence_rules = _rules_with_card(rules, replace(card, action_sequence=()))
    missing_action_step = {**card.action_sequence[0], "action_ref": "monster_skill:missing_v0_283"}
    missing_action_rules = _rules_with_card(rules, replace(card, action_sequence=(missing_action_step, *card.action_sequence[1:])))
    complex_ai_rules = _rules_with_card(
        rules,
        replace(
            card,
            ai_policy={
                **card.ai_policy,
                "admission_status": "blocked",
                "coverage_status": "blocked",
                "blocked_reason": "synthetic_complex_ai_v0_283",
            },
        ),
    )
    defeated_targets_state = _unit_with_hp(active_state, "ally:saber", 0.0)
    candidate = system.next_candidate(active_state, "enemy:target")
    invalid_target_command = ActionCommand(
        actor_id="enemy:target",
        action_id=candidate.action_ref,
        action_level=candidate.action_level,
        target_ids=("enemy:target",),
        source="ai",
        metadata={"negative_case": "illegal_target"},
    )
    decision = DecisionSystem(rules).current_decision(active_state)
    invalid_target = (
        DecisionSystem(rules).submit(active_state, decision.token, invalid_target_command)
        if decision.ready and decision.token is not None
        else scheduler.step(active_state, invalid_target_command)
    )
    checks = {
        "missing_card_blocked": system.next_candidate(missing_card_state, "enemy:target").blocked_reason == "enemy_monster_data_card_id_missing",
        "missing_sequence_blocked": EnemyActionSystem(missing_sequence_rules).next_candidate(active_state, "enemy:target").blocked_reason == "enemy_action_sequence_missing",
        "missing_action_blocked": EnemyActionSystem(missing_action_rules).next_candidate(active_state, "enemy:target").blocked_reason == "enemy_action_level_missing",
        "complex_ai_blocked": EnemyActionSystem(complex_ai_rules).next_candidate(active_state, "enemy:target").blocked_reason == "enemy_ai_policy_not_fixed_sequence",
        "target_empty_blocked": EnemyActionSystem(rules).next_candidate(defeated_targets_state, "enemy:target").status == "blocked",
        "invalid_command_not_falsely_executed": invalid_target.transition.coverage.get("blocked_reason")
        in {
            "enemy_action_target_not_in_candidate",
            "enemy_action_target_not_in_auto_target_group",
            "decision_token_required",
        },
        "illegal_target_state_unchanged": invalid_target.after_state.snapshot().to_json() == active_state.snapshot().to_json(),
        "illegal_target_no_cursor_mutation": not any(mutation.source == "enemy_action_system" for mutation in invalid_target.transition.transaction.mutations),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_candidates": {
            "missing_card": system.next_candidate(missing_card_state, "enemy:target").to_json(),
            "missing_sequence": EnemyActionSystem(missing_sequence_rules).next_candidate(active_state, "enemy:target").to_json(),
            "missing_action": EnemyActionSystem(missing_action_rules).next_candidate(active_state, "enemy:target").to_json(),
            "complex_ai": EnemyActionSystem(complex_ai_rules).next_candidate(active_state, "enemy:target").to_json(),
            "target_empty": EnemyActionSystem(rules).next_candidate(defeated_targets_state, "enemy:target").to_json(),
        },
        "illegal_target_transition": invalid_target.transition.to_json(),
        "decision": decision.to_json(),
    }


def _queue_priority_case(rules: RuleBook, scenario_data: dict[str, Any]) -> dict[str, Any]:
    scheduler, state = _initialized_scheduler_state(rules, scenario_data)
    state = _unit_with_energy(state, "ally:saber", 120.0, 120.0)
    enqueue = scheduler.enqueue_manual_ultimate(
        state,
        ActionCommand(
            actor_id="ally:saber",
            action_id="avatar_skill:101403",
            action_level=1,
            target_ids=("enemy:target",),
            source="manual",
            metadata={"validation": "v0_283_queue_priority"},
        ),
    )
    result = scheduler.step(enqueue.after_state)
    checks = {
        "manual_ultimate_enqueued": any(enqueue.after_state.queues.values()),
        "queue_drain_attempt_preempts_natural_enemy": result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "no_natural_enemy_candidate": not _dict(result.transition.coverage.get("enemy_action_candidate")),
        "queue_blocked_or_dequeued_before_enemy_candidate": str(result.transition.coverage.get("blocked_reason") or "").startswith("queue_")
        or any(mutation.source == "queue_system" for mutation in result.transition.transaction.mutations),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "enqueue_transition": enqueue.transition.to_json(),
        "drain_transition": result.transition.to_json(),
    }


def _select_fixed_sequence_card(rules: RuleBook) -> MonsterDataCardIR:
    preferred: list[MonsterDataCardIR] = []
    fallback: list[MonsterDataCardIR] = []
    for card in rules.ir.monster_data_cards:
        if card.ai_policy.get("admission_status") != "executable":
            continue
        if len(card.action_sequence) < 2 or card.summon_refs:
            continue
        first = _action_for_step(rules, card.action_sequence[0])
        second = _action_for_step(rules, card.action_sequence[1])
        if first is None or second is None:
            continue
        first_definition, first_level = first
        second_definition, second_level = second
        if first_definition.target_mode not in {"single", "blast", "aoe", "bounce"}:
            continue
        if second_definition.target_mode not in {"single", "blast", "aoe", "bounce"}:
            continue
        if not _action_runtime_ready(rules, str(card.action_sequence[0].get("action_ref") or ""), first_level):
            continue
        if first_definition.target_mode == "single":
            preferred.append(card)
        else:
            fallback.append(card)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    raise RuntimeError("fixed sequence enemy action candidate sample not found")


def _action_for_step(rules: RuleBook, step: dict[str, Any]) -> tuple[Any, int] | None:
    action_ref = str(step.get("action_ref") or "")
    levels = rules.action_levels(action_ref)
    if not levels:
        return None
    level = min(levels)
    definition = rules.action_definition(action_ref, level)
    event = rules.action_event(action_ref, level)
    if definition is None or event is None:
        return None
    if definition.coverage_status != "executable" or event.coverage_status == "blocked":
        return None
    return definition, level


def _action_runtime_ready(rules: RuleBook, action_ref: str, level: int) -> bool:
    binding = rules.action_ability_binding(action_ref, level)
    return bool(
        binding
        and binding.coverage_status == "executable"
        and any(emission.coverage_status == "executable" for emission in rules.damage_emissions_for_action(action_ref, level))
    )


def _initialized_scheduler_state(rules: RuleBook, scenario_data: dict[str, Any]) -> tuple[CombatScheduler, BattleState]:
    scenario = ScenarioLoader().load_dict(scenario_data)
    built = ScenarioStateBuilder(rules).build(scenario)
    scheduler = CombatScheduler(rules)
    initialized = scheduler.initialize_timeline(built.state, explicit_overrides=("enemy:target", "ally:saber"))
    flags = dict(initialized.after_state.global_flags)
    flags.pop("turn_owner_id", None)
    flags.pop("active_turn", None)
    flags["current_window"] = "idle"
    return scheduler, replace(initialized.after_state, global_flags=flags)


def _scenario_data(hsr_root: Path, card: MonsterDataCardIR) -> dict[str, Any]:
    path = hsr_root / "simulator_v8_clean_core/scenarios/examples/identity_smoke_v0_204.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    metadata = data.setdefault("metadata", {})
    aliases = metadata.setdefault("ui_aliases", {})
    units_alias = aliases.setdefault("units", {})
    names = card.display.get("localized_names") if isinstance(card.display, dict) else {}
    if isinstance(names, dict):
        units_alias["enemy:target"] = names.get("CHS") or names.get("EN") or card.entity_ref
    for unit in data["units"]:
        if unit.get("unit_id") == "enemy:target":
            unit["entity_ref"] = card.entity_ref
            unit["level"] = 80
            panel = unit.setdefault("panel", {})
            panel.update(
                {
                    "action_value": 0,
                    "attack": 1000,
                    "hp": 1_000_000,
                    "max_hp": 1_000_000,
                    "speed": 100,
                    "toughness": 100,
                    "max_toughness": 100,
                }
            )
        if unit.get("unit_id") == "ally:saber":
            panel = unit.setdefault("panel", {})
            panel.update(
                {
                    "action_value": 1000,
                    "hp": 1_000_000,
                    "max_hp": 1_000_000,
                    "energy": 120,
                    "max_energy": 120,
                    "toughness": 100,
                    "max_toughness": 100,
                }
            )
    return data


def _rules_with_card(rules: RuleBook, replacement_card: MonsterDataCardIR) -> RuleBook:
    cards = tuple(replacement_card if card.card_id == replacement_card.card_id else card for card in rules.ir.monster_data_cards)
    ir = replace(rules.ir, monster_data_cards=cards)
    return RuleBook(ir)


def _selected_targets_for_candidate(candidate: EnemyActionCandidate) -> tuple[str, ...]:
    if candidate.selectable_target_ids:
        return (candidate.selectable_target_ids[0],)
    return tuple(candidate.auto_target_ids)


def _unit_without_flag(state: BattleState, unit_id: str, flag_key: str) -> BattleState:
    unit = state.units[unit_id]
    flags = dict(unit.flags)
    flags.pop(flag_key, None)
    units = {**state.units, unit_id: replace(unit, flags=flags)}
    return replace(state, units=units)


def _unit_with_hp(state: BattleState, unit_id: str, hp: float) -> BattleState:
    unit = state.units[unit_id]
    units = {**state.units, unit_id: replace(unit, hp=hp)}
    return replace(state, units=units)


def _unit_with_energy(state: BattleState, unit_id: str, energy: float, max_energy: float) -> BattleState:
    unit = state.units[unit_id]
    units = {**state.units, unit_id: replace(unit, energy=energy, max_energy=max_energy)}
    return replace(state, units=units)


def _card_identity(card: MonsterDataCardIR) -> dict[str, Any]:
    names = card.display.get("localized_names") if isinstance(card.display, dict) else {}
    return {
        "monster_id": card.monster_id,
        "entity_ref": card.entity_ref,
        "template_id": card.template_id,
        "rank": card.rank,
        "display_name_chs": names.get("CHS") if isinstance(names, dict) else "",
        "display_name_en": names.get("EN") if isinstance(names, dict) else "",
        "action_sequence_length": len(card.action_sequence),
    }


def _command_json(command: ActionCommand) -> dict[str, Any]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
