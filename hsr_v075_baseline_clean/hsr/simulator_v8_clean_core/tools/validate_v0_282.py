from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import BattleState, GameEvent, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import (
    AbilityTaskIR,
    ActionDefinitionIR,
    CanonicalIR,
    DamageEmissionIR,
    EffectIR,
    MonsterDataCardIR,
    QueueIntentIR,
    StandaloneAbilityGraphIR,
    StatusCallbackIR,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_282"

PRESENTATION_OPCODES = {
    "ChangeBodyState",
    "DamagePerformFinish",
    "LookAt",
    "PlayAnim",
    "PlayEffect",
    "ShowUIPage",
    "VCameraConfigChange",
    "WaitAnimState",
}


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    *,
    example_output: Path | None = None,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    sample = _select_counter_sample(rules)
    positive_case = _counter_route_case(package_root.parent, rules, sample)
    negative_case = _negative_cases(rules, sample, positive_case)
    coverage_case = _coverage_gap_case(rules, sample)
    boundary_case = _boundary_case(rules, sample)
    positive_report = _strip_runtime(positive_case)
    checks = {
        "structured_selection": sample["checks"],
        "positive_counter_route": positive_case["checks"],
        "negative_conditions": negative_case["checks"],
        "coverage_gaps": coverage_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": sample["selection_policy"],
        },
        "checks": checks,
        "sample": sample["sample"],
        "positive_counter_route_case": positive_report,
        "negative_case": negative_case,
        "coverage_gap_case": coverage_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_282.json", result)
    write_json(output_dir / "sample_monster_counter_route_v0_282.json", positive_report)
    write_json(output_dir / "sample_monster_counter_negative_v0_282.json", negative_case)
    if example_output is not None:
        write_json(example_output, positive_report)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_282 monster status listener counter slice.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--example-output", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir, example_output=args.example_output)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_counter_sample(rules: RuleBook) -> dict[str, Any]:
    first_failures: list[dict[str, Any]] = []
    for callback in rules.ir.status_callbacks:
        if callback.event != "OnAfterBeingAttacked":
            continue
        if callback.scope_kind != "being_hit_target_local":
            continue
        if callback.coverage_status != "executable":
            first_failures.append({"callback_id": callback.callback_id, "reason": callback.blocked_reason})
            continue
        if not _is_mainline_monster_source(callback.source.source_path):
            continue
        if not _has_on_create_dynamic_initializer(rules, callback.modifier_name):
            first_failures.append({"callback_id": callback.callback_id, "reason": "on_create_dynamic_initializer_missing"})
            continue
        intents = tuple(
            intent
            for intent in rules.queue_intents_for_callback(callback.callback_id)
            if intent.opcode == "TurnInsertAbility"
        )
        if not intents:
            first_failures.append({"callback_id": callback.callback_id, "reason": "turn_insert_ability_intent_missing"})
            continue
        for intent in intents:
            intent_reason = _counter_intent_blocked_reason(rules, intent)
            if intent_reason:
                first_failures.append({"callback_id": callback.callback_id, "intent_id": intent.queue_intent_id, "reason": intent_reason})
                continue
            graph = _single_executable_graph(rules, intent.action_ref_or_ability_name)
            if graph is None:
                first_failures.append({"callback_id": callback.callback_id, "intent_id": intent.queue_intent_id, "reason": "standalone_graph_missing_or_blocked"})
                continue
            counter_action_id = f"standalone_ability:{graph.ability_name}"
            counter_emissions = _standalone_graph_damage_emissions(rules, graph)
            if not counter_emissions:
                first_failures.append({"callback_id": callback.callback_id, "intent_id": intent.queue_intent_id, "reason": "counter_damage_emission_missing"})
                continue
            setup = _find_setup_action_for_modifier(rules, callback.modifier_name)
            if setup is None:
                first_failures.append({"callback_id": callback.callback_id, "reason": "setup_add_modifier_action_missing"})
                continue
            card = _monster_card_for_action(rules, setup["action_id"])
            if card is None:
                first_failures.append({"callback_id": callback.callback_id, "reason": "monster_card_for_setup_action_missing"})
                continue
            attack = _find_attack_action_for_card(rules, card, excluded_actions={setup["action_id"]})
            if attack is None:
                first_failures.append({"callback_id": callback.callback_id, "reason": "same_card_attack_action_missing"})
                continue
            dynamic_tasks = tuple(
                task
                for task in rules.status_callback_tasks_for_callback(callback.callback_id)
                if task.opcode in {"DefineDynamicValue", "SetDynamicValue", "SetDynamicValueByAddValue"}
                and task.coverage_status == "executable"
            )
            checks = {
                "callback_from_monster_ability": _is_mainline_monster_source(callback.source.source_path),
                "callback_event_after_being_attacked": callback.event == "OnAfterBeingAttacked",
                "callback_scope_being_hit_target_local": callback.scope_kind == "being_hit_target_local",
                "callback_executable": callback.coverage_status == "executable",
                "has_counter_dynamic_task": bool(dynamic_tasks),
                "has_on_create_dynamic_initializer": _has_on_create_dynamic_initializer(rules, callback.modifier_name),
                "queue_intent_executable": intent.coverage_status == "executable",
                "queue_priority_from_tbgd": bool(intent.priority_source.get("priority_key") and intent.priority_source.get("source_trace")),
                "queue_target_is_attacker": intent.ability_target_alias == "ParamEntity",
                "queue_actor_is_status_owner": intent.actor_target_alias in {"ModifierOwnerEntity", "Caster"},
                "queue_window_executable": bool(
                    (window := rules.queue_window_for_intent(intent.queue_intent_id))
                    and window.coverage_status == "executable"
                ),
                "queue_resolution_executable": bool(
                    (resolution := rules.queue_resolution_for_intent(intent.queue_intent_id))
                    and resolution.coverage_status == "executable"
                ),
                "standalone_graph_executable": graph.coverage_status == "executable",
                "counter_damage_emissions_executable": bool(counter_emissions),
                "setup_action_adds_listener_status": setup["action_id"].startswith("monster_skill:"),
                "sample_card_is_monster": card.entity_ref.startswith("monster:"),
                "same_card_attack_action_executable": attack["action_id"].startswith("monster_skill:"),
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            return {
                "selection_policy": {
                    "mode": "structured_predicate",
                    "fixed_monster_id_used_for_selection": False,
                    "fixed_skill_id_used_for_selection": False,
                    "fixed_ability_name_used_for_selection": False,
                    "predicate": [
                        "monster ConfigAbility source",
                        "status-local OnAfterBeingAttacked callback",
                        "executable TurnInsertAbility queue intent",
                        "ability target alias is ParamEntity",
                        "queue priority and resolution admitted",
                        "inserted standalone ability has executable direct damage emissions",
                        "a same-card monster action can add the listener modifier",
                    ],
                },
                "checks": {"ok": checks["ok"], "checks": checks},
                "sample": {
                    "monster": _monster_identity(card),
                    "modifier_name": callback.modifier_name,
                    "callback": callback.to_json(),
                    "queue_intent": intent.to_json(),
                    "queue_window": rules.queue_window_for_intent(intent.queue_intent_id).to_json(),
                    "queue_resolution": rules.queue_resolution_for_intent(intent.queue_intent_id).to_json(),
                    "standalone_graph": graph.to_json(),
                    "counter_action_id": counter_action_id,
                    "setup_action": setup,
                    "attack_action": attack,
                    "counter_damage_emissions": [emission.to_json() for emission in counter_emissions],
                    "dynamic_tasks": [task.to_json() for task in dynamic_tasks],
                },
                "_runtime": {
                    "card": card,
                    "callback": callback,
                    "intent": intent,
                    "setup_action": setup,
                    "attack_action": attack,
                    "counter_action_id": counter_action_id,
                    "counter_damage_emissions": counter_emissions,
                },
            }
    raise RuntimeError(f"monster counter listener sample not found; first_failures={first_failures[:8]}")


def _counter_route_case(hsr_root: Path, rules: RuleBook, sample: dict[str, Any]) -> dict[str, Any]:
    runtime = sample["_runtime"]
    card: MonsterDataCardIR = runtime["card"]
    setup_action = runtime["setup_action"]
    attack_action = runtime["attack_action"]
    scenario_path = hsr_root / "simulator_v8_clean_core/scenarios/examples/identity_smoke_v0_204.json"
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    for unit in data["units"]:
        if unit.get("unit_id") == "ally:saber":
            panel = unit.setdefault("panel", {})
            panel.update(
                {
                    "max_hp": 1_000_000,
                    "hp": 1_000_000,
                    "attack": 1000,
                    "defense": 1000,
                    "speed": 100,
                    "toughness": 10_000,
                    "max_toughness": 10_000,
                }
            )
            panel.setdefault("flags", {})["weaknesses"] = ["Ice", "Physical"]
        if unit.get("unit_id") == "enemy:target":
            unit["entity_ref"] = card.entity_ref
            panel = unit.setdefault("panel", {})
            panel.update(
                {
                    "max_hp": 1_000_000,
                    "hp": 1_000_000,
                    "attack": 1000,
                    "defense": 1000,
                    "speed": 100,
                    "toughness": 10_000,
                    "max_toughness": 10_000,
                }
            )
    data["route"] = [
        {
            "actor_id": "enemy:target",
            "action_ref": setup_action["action_id"],
            "action_level": setup_action["level"],
            "target_ids": _setup_target_ids(setup_action),
            "source": "manual",
            "metadata": {"reset_actor_av": True, "label": "monster counter listener setup"},
        },
        {
            "actor_id": "ally:saber",
            "action_ref": attack_action["action_id"],
            "action_level": attack_action["level"],
            "target_ids": ["enemy:target"],
            "source": "manual",
            "metadata": {"reset_actor_av": True, "label": "listener trigger harness action"},
        },
    ]
    built = ScenarioStateBuilder(rules).build(ScenarioLoader().load_dict(data))
    executor = CombatExecutor(rules)
    scheduler = CombatScheduler(rules)
    before_setup = built.state
    after_setup, setup_transition = executor.execute(built.commands[0], before_setup)
    before_attack = after_setup
    after_attack, attack_transition = executor.execute(built.commands[1], before_attack)
    before_drain = after_attack
    drain_result = scheduler.step(before_drain)
    after_drain = drain_result.after_state
    setup_details = _status_details(after_setup, "enemy:target")
    after_attack_entries = _queue_entries(after_attack)
    setup_records = _records(setup_transition)
    attack_records = _records(attack_transition)
    drain_records = _records(drain_result.transition)
    all_records = [*setup_records, *attack_records, *drain_records]
    replay = {
        "setup": _replay_json(before_setup, after_setup, setup_transition),
        "attack": _replay_json(before_attack, after_attack, attack_transition),
        "drain": _replay_json(before_drain, after_drain, drain_result.transition),
    }
    source_audit = {
        "setup": RuntimeSourceAuditor(rules).validate_transition(setup_transition).to_json(),
        "attack": RuntimeSourceAuditor(rules).validate_transition(attack_transition).to_json(),
        "drain": RuntimeSourceAuditor(rules).validate_transition(drain_result.transition).to_json(),
    }
    checks = {
        "setup_action_enabled": setup_transition.coverage.get("action_enabled") is True,
        "listener_status_present": any(detail.get("modifier_name") == sample["sample"]["modifier_name"] for detail in setup_details),
        "listener_trigger_registered": any(
            isinstance(detail.get("trigger_ids_by_event"), dict)
            and "OnAfterBeingAttacked" in detail.get("trigger_ids_by_event", {})
            for detail in setup_details
        ),
        "counter_initial_value_zero": _counter_value(after_setup, "enemy:target") == 0.0,
        "trigger_attack_enabled": attack_transition.coverage.get("action_enabled") is True,
        "damage_hit_listener_recorded": any(
            record.get("record_type") == "event_dispatch"
            and _payload(record).get("event", {}).get("event_type") == "damage.hit"
            for record in attack_records
        ),
        "counter_queue_enqueued": any(record.get("record_type") == "queue_enqueue" for record in attack_records),
        "queue_entry_pending_after_attack": bool(after_attack_entries),
        "counter_value_used_after_attack": _counter_value(after_attack, "enemy:target") == 1.0,
        "scheduler_drained_queue": drain_result.transition.coverage.get("scheduler_step") == "queue_drain_priority",
        "queue_empty_after_drain": not _queue_entries(after_drain),
        "counter_dealt_damage_to_attacker": after_drain.units["ally:saber"].hp < after_attack.units["ally:saber"].hp,
        "counter_damage_records_present": any(
            record.get("record_type") == "damage"
            for record in drain_records
        ),
        "counter_damage_record_count_matches_emissions": (
            _record_summary(drain_records).get("damage", 0) == len(runtime["counter_damage_emissions"])
        ),
        "settlement_records_present": bool(all_records),
        "replay_ok": all(item["ok"] for item in replay.values()),
        "source_audit_present": all("ok" in item for item in source_audit.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "schema_version": "v8_monster_counter_route_v0_282",
        "checks": {"ok": checks["ok"], "checks": checks},
        "scenario": {
            "enemy_entity_ref": card.entity_ref,
            "setup_action": setup_action,
            "trigger_action": attack_action,
            "note": "The trigger action is an admitted monster action used as a harness action for an ally-side unit; it is not game AI.",
        },
        "snapshots": {
            "after_setup_enemy_status_details": setup_details,
            "after_attack_queues": {key: [dict(item) for item in value] for key, value in sorted(after_attack.queues.items())},
            "after_drain_ally_hp": after_drain.units["ally:saber"].hp,
        },
        "record_summary": {
            "setup": _record_summary(setup_records),
            "attack": _record_summary(attack_records),
            "drain": _record_summary(drain_records),
        },
        "source_audit": source_audit,
        "replay": replay,
        "transitions": {
            "setup": setup_transition.to_json(),
            "attack": attack_transition.to_json(),
            "drain": drain_result.transition.to_json(),
            "drain_children": [transition.to_json() for transition in drain_result.child_transitions],
        },
        "_runtime": {
            "after_setup": after_setup,
            "after_attack": after_attack,
            "after_drain": after_drain,
        },
    }


def _negative_cases(rules: RuleBook, sample: dict[str, Any], positive_case: dict[str, Any]) -> dict[str, Any]:
    after_setup: BattleState = positive_case["_runtime"]["after_setup"]
    modifier_name = sample["sample"]["modifier_name"]
    cases: dict[str, Any] = {
        "without_listener_status": _dispatch_negative(rules, _state_without_status(after_setup, "enemy:target", modifier_name), "ally:saber", "enemy:target"),
        "attacker_not_ally": _dispatch_negative(rules, after_setup, "enemy:target", "enemy:target"),
        "owner_broken": _dispatch_negative(rules, _with_unit_flags(after_setup, "enemy:target", broken=True), "ally:saber", "enemy:target"),
        "owner_controlled": _dispatch_negative(rules, _with_unit_flags(after_setup, "enemy:target", behavior_flags=("STAT_CTRL",)), "ally:saber", "enemy:target"),
        "counter_already_used": _dispatch_negative(rules, _with_counter_value(after_setup, "enemy:target", 1.0), "ally:saber", "enemy:target"),
        "attacker_missing": _dispatch_negative(rules, after_setup, "missing:attacker", "enemy:target"),
        "queue_intent_blocked": _blocked_queue_intent_case(rules, sample, after_setup),
    }
    checks = {
        f"{name}_no_queue_mutation": case["no_queue_mutation"]
        for name, case in cases.items()
    }
    checks.update(
        {
            f"{name}_state_unchanged": case["state_unchanged"]
            for name, case in cases.items()
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "schema_version": "v8_monster_counter_negative_v0_282",
        "checks": {"ok": checks["ok"], "checks": checks},
        "cases": cases,
    }


def _coverage_gap_case(rules: RuleBook, sample: dict[str, Any]) -> dict[str, Any]:
    runtime = sample["_runtime"]
    setup_action = runtime["setup_action"]
    counter_action_id = runtime["counter_action_id"]
    callback: StatusCallbackIR = runtime["callback"]
    related_tasks = [
        task
        for task in rules.ir.ability_tasks
        if task.action_id in {setup_action["action_id"], counter_action_id}
        or (
            task.action_id.startswith("standalone_ability:")
            and task.source.source_path == callback.source.source_path
        )
    ]
    presentation_tasks = [
        task
        for task in related_tasks
        if task.opcode in PRESENTATION_OPCODES
    ]
    checks = {
        "presentation_task_coverage_visible": bool(presentation_tasks),
        "presentation_tasks_not_executable": all(task.coverage_status != "executable" for task in presentation_tasks),
        "presentation_tasks_have_no_damage_emissions": all(
            not rules.damage_emissions_for_task(task.task_id)
            for task in presentation_tasks
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "presentation_opcodes": sorted(PRESENTATION_OPCODES),
        "presentation_tasks": [task.to_json() for task in presentation_tasks[:20]],
        "presentation_task_count": len(presentation_tasks),
    }


def _boundary_case(rules: RuleBook, sample: dict[str, Any]) -> dict[str, Any]:
    callback: StatusCallbackIR = sample["_runtime"]["callback"]
    source_paths = {
        "callback_source_path": callback.source.source_path,
        "setup_action_source_path": sample["_runtime"]["setup_action"]["effect_source_path"],
        "queue_intent_source_path": sample["_runtime"]["intent"].source.source_path,
    }
    checks = {
        "ability_name_list_not_treated_as_complete_passive": True,
        "monster_skill_modifier_list_not_passive_source": not any(
            slot.source.evidence.get("source_field") == "MonsterSkill.ModifierList"
            for slot in rules.ir.passive_mechanism_slots
        ),
        "callback_source_is_monster_ability": _is_mainline_monster_source(callback.source.source_path),
        "runtime_sample_uses_canonical_ir_objects": all(
            value.startswith("Config/ConfigAbility/Monster/") or value.startswith("ExcelOutput/")
            for value in source_paths.values()
            if value
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "source_paths": source_paths,
        "note": "AbilityNameList remains a passive entry source, but status callback mechanisms can also come from skill-added modifiers.",
    }


def _counter_intent_blocked_reason(rules: RuleBook, intent: QueueIntentIR) -> str:
    if intent.coverage_status != "executable":
        return intent.blocked_reason or f"queue_intent_not_executable:{intent.coverage_status}"
    if intent.ability_target_alias != "ParamEntity":
        return f"ability_target_alias_not_attacker:{intent.ability_target_alias}"
    if intent.actor_target_alias not in {"ModifierOwnerEntity", "Caster"}:
        return f"actor_alias_not_status_owner:{intent.actor_target_alias}"
    if not intent.priority_source.get("priority_key") or not intent.priority_source.get("source_trace"):
        return "queue_priority_source_missing"
    window = rules.queue_window_for_intent(intent.queue_intent_id)
    if window is None or window.coverage_status != "executable":
        return "queue_window_not_executable"
    resolution = rules.queue_resolution_for_intent(intent.queue_intent_id)
    if resolution is None or resolution.coverage_status != "executable":
        return "queue_resolution_not_executable"
    return ""


def _find_setup_action_for_modifier(rules: RuleBook, modifier_name: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for task in rules.ir.ability_tasks:
        if task.opcode != "AddModifier":
            continue
        if not task.action_id.startswith("monster_skill:"):
            continue
        effect = rules.effect(task.effect_id)
        standard = _effect_standard(effect)
        if standard.get("modifier_name") != modifier_name:
            continue
        definition = rules.action_definition(task.action_id, task.level)
        binding = rules.action_ability_binding(task.action_id, task.level)
        if definition is None or binding is None:
            continue
        if definition.source.source_path not in {"ExcelOutput/MonsterSkillConfig.json", "ExcelOutput/MonsterSkillUniqueConfig.json"}:
            continue
        if binding.coverage_status != "executable" or binding.source_mode != "mainline_monster":
            continue
        executable_damage_count = len(
            [
                emission
                for emission in rules.damage_emissions_for_action(task.action_id, task.level)
                if emission.coverage_status == "executable"
            ]
        )
        candidates.append(
            {
            "action_id": task.action_id,
            "level": task.level,
                "target_mode": definition.target_mode,
                "executable_damage_count": executable_damage_count,
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "effect_source_path": effect.source.source_path if effect else "",
            "modifier_name": modifier_name,
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            0 if item.get("target_mode") in {"self", "self_or_team"} else 1,
            0 if item.get("executable_damage_count") == 0 else 1,
            str(item.get("action_id") or ""),
        ),
    )[0]


def _setup_target_ids(setup_action: dict[str, Any]) -> list[str]:
    if setup_action.get("target_mode") in {"self", "self_or_team"}:
        return ["enemy:target"]
    return ["ally:saber"]


def _has_on_create_dynamic_initializer(rules: RuleBook, modifier_name: str) -> bool:
    for callback in rules.status_callbacks_for_modifier_event(modifier_name, "OnCreate"):
        if callback.coverage_status != "executable":
            continue
        if not _is_mainline_monster_source(callback.source.source_path):
            continue
        if any(
            task.opcode == "DefineDynamicValue" and task.coverage_status == "executable"
            for task in rules.status_callback_tasks_for_callback(callback.callback_id)
        ):
            return True
    return False


def _find_attack_action_for_card(
    rules: RuleBook,
    card: MonsterDataCardIR,
    *,
    excluded_actions: set[str],
) -> dict[str, Any] | None:
    action_refs: list[str] = []
    for slot in card.skill_slots:
        action_ref = str(slot.get("action_ref") or "")
        if action_ref and action_ref not in action_refs:
            action_refs.append(action_ref)
    for step in card.action_sequence:
        action_ref = str(step.get("action_ref") or "")
        if action_ref and action_ref not in action_refs:
            action_refs.append(action_ref)
    for action_ref in action_refs:
        if action_ref in excluded_actions:
            continue
        for level in rules.action_levels(action_ref):
            definition = rules.action_definition(action_ref, level)
            if definition is None or definition.target_mode not in {"single", "aoe"}:
                continue
            emissions = tuple(
                emission
                for emission in rules.damage_emissions_for_action(action_ref, level)
                if emission.coverage_status == "executable"
            )
            if not emissions:
                continue
            binding = rules.action_ability_binding(action_ref, level)
            if binding is None or binding.coverage_status != "executable":
                continue
            return {
                "action_id": action_ref,
                "level": level,
                "target_mode": definition.target_mode,
                "damage_emission_count": len(emissions),
            }
    return None


def _monster_card_for_action(rules: RuleBook, action_id: str) -> MonsterDataCardIR | None:
    candidates: list[MonsterDataCardIR] = []
    for card in rules.ir.monster_data_cards:
        slot_actions = {str(slot.get("action_ref") or "") for slot in card.skill_slots}
        sequence_actions = {str(step.get("action_ref") or "") for step in card.action_sequence}
        if action_id in slot_actions or action_id in sequence_actions:
            candidates.append(card)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.monster_id, item.entity_ref))[0]


def _single_executable_graph(rules: RuleBook, ability_name: str) -> StandaloneAbilityGraphIR | None:
    graphs = tuple(
        graph
        for graph in rules.standalone_ability_graphs_by_name(ability_name)
        if graph.coverage_status == "executable"
    )
    if len(graphs) != 1:
        return None
    return graphs[0]


def _standalone_graph_damage_emissions(
    rules: RuleBook,
    graph: StandaloneAbilityGraphIR,
    *,
    seen: tuple[str, ...] = (),
) -> tuple[DamageEmissionIR, ...]:
    if graph.ability_name in seen:
        return ()
    action_id = f"standalone_ability:{graph.ability_name}"
    direct = tuple(
        emission
        for emission in rules.damage_emissions_for_action(action_id, 0)
        if emission.coverage_status == "executable"
    )
    if direct:
        return direct
    emissions: list[DamageEmissionIR] = []
    for task_id in graph.task_ids:
        task = rules.ability_task(task_id)
        if task is None or task.opcode != "TriggerAbility":
            continue
        effect = rules.effect(task.effect_id)
        standard = _effect_standard(effect)
        child_name = str(standard.get("ability_name") or "")
        if not child_name:
            continue
        child = _single_executable_graph(rules, child_name)
        if child is None:
            continue
        emissions.extend(_standalone_graph_damage_emissions(rules, child, seen=(*seen, graph.ability_name)))
    return tuple(emissions)


def _dispatch_negative(
    rules: RuleBook,
    state: BattleState,
    attacker_id: str,
    target_id: str,
) -> dict[str, Any]:
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    before_snapshot = state.snapshot().to_json()
    result = dispatcher.dispatch_event(
        state,
        event=_damage_hit_event(attacker_id, target_id),
    )
    after_snapshot = result.after_state.snapshot().to_json()
    queue_mutations = [
        mutation.to_json()
        for mutation in result.mutations
        if mutation.path and mutation.path[0] == "queues"
    ]
    queue_records = [record for record in result.records if record.get("record_type") == "queue_enqueue"]
    return {
        "no_queue_mutation": not queue_mutations and not _queue_entries(result.after_state) and not queue_records,
        "state_unchanged": before_snapshot == after_snapshot,
        "mutation_count": len(result.mutations),
        "queue_mutations": queue_mutations,
        "records": result.records,
        "errors": list(result.errors),
    }


def _blocked_queue_intent_case(rules: RuleBook, sample: dict[str, Any], state: BattleState) -> dict[str, Any]:
    callback: StatusCallbackIR = sample["_runtime"]["callback"]
    replacement_callbacks = tuple(
        replace(item, coverage_status="blocked", blocked_reason="queue_priority_source_missing_v0_282_negative")
        if item.callback_id == callback.callback_id
        else item
        for item in rules.ir.status_callbacks
    )
    patched_rules = RuleBook(replace(rules.ir, status_callbacks=replacement_callbacks))
    return _dispatch_negative(patched_rules, state, "ally:saber", "enemy:target")


def _damage_hit_event(attacker_id: str, target_id: str) -> GameEvent:
    return GameEvent(
        "damage.hit",
        source_id=attacker_id,
        target_id=target_id,
        window="damage",
        process_only=False,
        payload={
            "actor_id": attacker_id,
            "attacker_id": attacker_id,
            "damage_attacker_id": attacker_id,
            "param_entity_id": attacker_id,
            "current_hit_target_id": target_id,
            "target_id": target_id,
            "selected_target_ids": [target_id],
            "target_ids": [target_id],
            "is_current_skill_active": True,
            "param_flags": [],
            "backend_target_ids": [],
        },
    )


def _with_unit_flags(state: BattleState, unit_id: str, **updates: Any) -> BattleState:
    unit = state.units[unit_id]
    flags = {**unit.flags, **updates}
    return _replace_unit(state, replace(unit, flags=flags))


def _state_without_status(state: BattleState, unit_id: str, modifier_name: str) -> BattleState:
    unit = state.units[unit_id]
    statuses = tuple(status for status in unit.statuses if modifier_name not in status)
    details = tuple(
        detail
        for detail in unit.flags.get("status_details", ())
        if not isinstance(detail, dict) or detail.get("modifier_name") != modifier_name
    )
    flags = dict(unit.flags)
    flags["status_details"] = details
    return _replace_unit(state, replace(unit, statuses=statuses, flags=flags))


def _with_counter_value(state: BattleState, unit_id: str, value: float) -> BattleState:
    unit = state.units[unit_id]
    flags = dict(unit.flags)
    details: list[Any] = []
    for detail in unit.flags.get("status_details", ()):
        if not isinstance(detail, dict):
            details.append(detail)
            continue
        dynamic_values = detail.get("dynamic_values")
        if not isinstance(dynamic_values, dict):
            details.append(detail)
            continue
        updated_dynamic_values = dict(dynamic_values)
        for key in list(updated_dynamic_values):
            if key.startswith("__"):
                continue
            if "ReturnAttackCounter" in key or isinstance(updated_dynamic_values.get(key), (int, float)):
                updated_dynamic_values[key] = value
        for index_name in ("__by_name", "__by_hash"):
            nested = updated_dynamic_values.get(index_name)
            if isinstance(nested, dict):
                updated_dynamic_values[index_name] = {
                    key: value if ("ReturnAttackCounter" in str(key) or isinstance(item, (int, float))) else item
                    for key, item in nested.items()
                }
        updated = dict(detail)
        updated["dynamic_values"] = updated_dynamic_values
        details.append(updated)
    flags["status_details"] = tuple(details)
    return _replace_unit(state, replace(unit, flags=flags))


def _replace_unit(state: BattleState, unit: UnitState) -> BattleState:
    units = dict(state.units)
    units[unit.unit_id] = unit
    return replace(state, units=units)


def _effect_standard(effect: EffectIR | None) -> dict[str, Any]:
    if effect is None or not isinstance(effect.payload, dict):
        return {}
    standard = effect.payload.get("standard")
    return dict(standard) if isinstance(standard, dict) else {}


def _status_details(state: BattleState, unit_id: str) -> list[dict[str, Any]]:
    return [
        dict(detail)
        for detail in state.units[unit_id].flags.get("status_details", ())
        if isinstance(detail, dict)
    ]


def _counter_value(state: BattleState, unit_id: str) -> float | None:
    for detail in _status_details(state, unit_id):
        dynamic_values = detail.get("dynamic_values")
        if not isinstance(dynamic_values, dict):
            continue
        by_name = dynamic_values.get("__by_name")
        if isinstance(by_name, dict) and isinstance(by_name.get("ReturnAttackCounter"), (int, float)):
            return float(by_name["ReturnAttackCounter"])
        for key, value in dynamic_values.items():
            if "ReturnAttackCounter" in str(key) and isinstance(value, (int, float)):
                return float(value)
    return None


def _queue_entries(state: BattleState) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for queue_entries in state.queues.values():
        for entry in queue_entries:
            if isinstance(entry, dict):
                entries.append(dict(entry))
    return entries


def _records(transition) -> list[dict[str, Any]]:
    if transition.transaction.settlement is None:
        return []
    return [dict(record) for record in transition.transaction.settlement.records if isinstance(record, dict)]


def _record_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for record in records:
        key = str(record.get("record_type") or "unknown")
        summary[key] = summary.get(key, 0) + 1
    return dict(sorted(summary.items()))


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _strip_runtime(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "_runtime"}


def _replay_json(before: BattleState, after: BattleState, transition) -> dict[str, Any]:
    replay = MutationReducer().replay_snapshot(before, transition.transaction.mutations, after.snapshot().to_json())
    return {"ok": replay.ok, "errors": list(replay.errors)}


def _monster_identity(card: MonsterDataCardIR) -> dict[str, Any]:
    return {
        "entity_ref": card.entity_ref,
        "monster_id": card.monster_id,
        "template_id": card.template_id,
        "display_name_chs": _localized(card.display, "localized_names", "CHS"),
        "display_name_en": _localized(card.display, "localized_names", "EN"),
        "rank": card.rank,
    }


def _localized(display: dict[str, Any], key: str, locale: str) -> str:
    values = display.get(key)
    if isinstance(values, dict):
        value = values.get(locale)
        return str(value) if value is not None else ""
    return ""


def _is_mainline_monster_source(source_path: str) -> bool:
    return source_path.startswith("Config/ConfigAbility/Monster/")


if __name__ == "__main__":
    raise SystemExit(main())
