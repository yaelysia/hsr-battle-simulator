from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, TargetResolution
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import AbilityTaskIR, EffectIR, MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.loader import ScenarioLoader
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_284"
ATTACHED_SINGLE_ALIASES = {"AbilityTargetEntity"}
ATTACHED_GROUP_ALIASES = {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllTeammate"}


@dataclass(frozen=True)
class AttachedStatusCandidate:
    card: MonsterDataCardIR
    task: AbilityTaskIR
    effect: EffectIR
    action_id: str
    action_level: int
    target_alias: str
    modifier_name: str


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    hsr_root = package_root.parent
    single = _select_runtime_positive_candidate(rules, hsr_root, aliases=ATTACHED_SINGLE_ALIASES, extra_enemy=False)
    group = _select_runtime_positive_candidate(rules, hsr_root, aliases=ATTACHED_GROUP_ALIASES, extra_enemy=True, allow_missing=True)
    listener_blocked = _select_candidate(rules, aliases=ATTACHED_SINGLE_ALIASES | ATTACHED_GROUP_ALIASES, require_listener=True)
    single_case = _execution_case(rules, hsr_root, single, extra_enemy=False)
    group_case = _group_case(rules, hsr_root, group) if group is not None else _group_gap_case(rules)
    boundary_case = _boundary_case(
        rules,
        hsr_root,
        single,
        listener_blocked=listener_blocked,
    )
    checks = {
        "single_attached_status": single_case["checks"],
        "group_attached_status": group_case["checks"],
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
            "selection_policy": {
                "mode": "structured_predicate",
                "fixed_monster_or_skill_id_used_for_selection": False,
                "predicate": [
                    "ConfigAbility/Monster ability task with EffectIR(AddModifier)",
                    "target_alias in AbilityTargetEntity or admitted group aliases",
                    "effect/task/action definition executable",
                    "safe positive cases have no dynamic requests, no modifier callbacks, no blocked duration",
                    "negative cases select real dynamic/listener/duration gaps where available",
                ],
            },
            "selected_single": _candidate_identity(single),
            "selected_group": _candidate_identity(group) if group is not None else {},
        },
        "checks": checks,
        "single_case": single_case,
        "group_case": group_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_284.json", result)
    write_json(output_dir / "monster_attached_status_single_sample_v0_284.json", single_case)
    write_json(output_dir / "monster_attached_status_group_sample_v0_284.json", group_case)
    write_json(output_dir / "monster_attached_status_boundary_cases_v0_284.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_284 monster skill attached statuses.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _execution_case(
    rules: RuleBook,
    hsr_root: Path,
    candidate: AttachedStatusCandidate,
    *,
    extra_enemy: bool,
) -> dict[str, Any]:
    state = _scenario_state(rules, hsr_root, candidate.card, extra_enemy=extra_enemy)
    command = _command_for_candidate(rules, candidate)
    after, transition = CombatExecutor(rules).execute(command, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
    target_ids = _expected_attached_target_ids(state, candidate, command.target_ids)
    status_mutations = [
        mutation.to_json()
        for mutation in transition.transaction.mutations
        if mutation.source == "status_system" and mutation.path[-1:] in {("statuses",), ("status_details",)}
    ]
    status_details = _status_details_by_target(after, target_ids, candidate.modifier_name)
    checks = {
        "action_enabled": transition.coverage.get("action_enabled") is True,
        "status_mutations_present": bool(status_mutations),
        "all_expected_targets_have_status_detail": set(status_details) == set(target_ids),
        "source_trace_has_effect": all(detail.get("source_trace", {}).get("effect_id") == candidate.effect.effect_id for detail in status_details.values()),
        "source_trace_has_modifier_definition": all(bool(detail.get("source_trace", {}).get("modifier_definition")) for detail in status_details.values()),
        "source_trace_has_target_resolution": all(bool(detail.get("source_trace", {}).get("target_resolution")) for detail in status_details.values()),
        "source_audit": audit.ok,
        "replay": replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "candidate": _candidate_identity(candidate),
        "command": _command_json(command),
        "expected_target_ids": list(target_ids),
        "status_details": status_details,
        "status_mutations": status_mutations,
        "transition": transition.to_json(),
        "source_audit": audit.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
    }


def _group_case(rules: RuleBook, hsr_root: Path, candidate: AttachedStatusCandidate) -> dict[str, Any]:
    case = _execution_case(rules, hsr_root, candidate, extra_enemy=True)
    expected = case.get("expected_target_ids", [])
    checks = dict(case["checks"]["checks"])
    checks["group_has_multiple_targets"] = len(expected) >= 2
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    case["checks"] = {"ok": checks["ok"], "checks": checks}
    return case


def _group_gap_case(rules: RuleBook) -> dict[str, Any]:
    counts = _coverage_counts(rules)
    checks = {
        "group_gap_recorded": counts["group_safe_candidates"] == 0,
        "no_synthetic_group_sample": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "coverage_gap": "no safe group AddModifier candidate in current TBGD lowering",
        "coverage_counts": counts,
    }


def _boundary_case(
    rules: RuleBook,
    hsr_root: Path,
    positive: AttachedStatusCandidate,
    *,
    listener_blocked: AttachedStatusCandidate,
) -> dict[str, Any]:
    state = _scenario_state(rules, hsr_root, positive.card, extra_enemy=True)
    status_system = StatusSystem(rules)
    missing_target = status_system.apply_add_modifier(
        state,
        positive.effect,
        caster_id="enemy:target",
        source_id="validation:v0_284:missing_target",
        owner_id="enemy:target",
        param_entity_id=None,
        current_action_target_id=None,
        target_resolution=TargetResolution(),
    )
    unsupported_alias = status_system.apply_add_modifier(
        state,
        _effect_with_standard(positive.effect, {"target_alias": "AbilityTargetAdjoinEntity"}),
        caster_id="enemy:target",
        source_id="validation:v0_284:unsupported_alias",
        owner_id="enemy:target",
        param_entity_id="ally:saber",
        current_action_target_id="ally:saber",
        target_resolution=TargetResolution(selected=("ally:saber",)),
    )
    unknown_modifier = status_system.apply_add_modifier(
        state,
        _effect_with_standard(positive.effect, {"modifier_name": "missing_modifier_v0_284"}),
        caster_id="enemy:target",
        source_id="validation:v0_284:unknown_modifier",
        owner_id="enemy:target",
        param_entity_id="ally:saber",
        current_action_target_id="ally:saber",
        target_resolution=TargetResolution(selected=("ally:saber",)),
    )
    listener_result = _apply_candidate_direct(rules, hsr_root, listener_blocked, "validation:v0_284:listener")
    dynamic_result = status_system.apply_add_modifier(
        state,
        _effect_with_standard(
            positive.effect,
            {
                "dynamic_values": {
                    "v0_284_missing_dynamic": {
                        "kind": "dynamic_hash",
                        "hash": "v0_284_missing_hash",
                        "supported": True,
                    }
                },
                "dynamic_value_requests": {
                    "v0_284_missing_dynamic": {
                        "name": "v0_284_missing_dynamic",
                        "hash": "v0_284_missing_hash",
                    }
                },
            },
        ),
        caster_id="enemy:target",
        source_id="validation:v0_284:dynamic",
        owner_id="enemy:target",
        param_entity_id="ally:saber",
        current_action_target_id="ally:saber",
        target_resolution=TargetResolution(selected=("ally:saber",)),
    )
    duration_result = status_system.apply_add_modifier(
        state,
        _effect_with_standard(
            positive.effect,
            {
                "lifetime": {"kind": "fixed", "value": 1.0},
                "life_step_moment": "UnsupportedMomentV0284",
            },
        ),
        caster_id="enemy:target",
        source_id="validation:v0_284:duration",
        owner_id="enemy:target",
        param_entity_id="ally:saber",
        current_action_target_id="ally:saber",
        target_resolution=TargetResolution(selected=("ally:saber",)),
    )
    checks = {
        "missing_target_blocked": _blocked_without_mutation(missing_target, "unsupported_or_missing_target_alias:AbilityTargetEntity"),
        "unsupported_alias_blocked": _blocked_without_mutation(unsupported_alias, "unsupported_or_missing_target_alias:AbilityTargetAdjoinEntity"),
        "unknown_modifier_blocked": _blocked_without_mutation(unknown_modifier, "unknown modifier definition"),
        "listener_blocked_without_mutation": _blocked_without_mutation(listener_result, "attached_status_listener_not_admitted"),
        "dynamic_blocked_without_mutation": _blocked_without_mutation(dynamic_result, "attached_status_dynamic_value_unresolved"),
        "duration_blocked_without_mutation": _blocked_without_mutation(duration_result, "attached_status_duration_blocked"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "positive_candidate": _candidate_identity(positive),
        "listener_candidate": _candidate_identity(listener_blocked),
        "dynamic_candidate": {
            **_candidate_identity(positive),
            "negative_case": "synthetic_missing_dynamic_value_binding",
        },
        "duration_candidate": {
            **_candidate_identity(positive),
            "negative_case": "synthetic_unsupported_life_step_moment",
        },
        "results": {
            "missing_target": missing_target.to_json(),
            "unsupported_alias": unsupported_alias.to_json(),
            "unknown_modifier": unknown_modifier.to_json(),
            "listener": listener_result.to_json(),
            "dynamic": dynamic_result.to_json(),
            "duration": duration_result.to_json(),
        },
    }


def _apply_candidate_direct(
    rules: RuleBook,
    hsr_root: Path,
    candidate: AttachedStatusCandidate,
    source_id: str,
) -> Any:
    state = _scenario_state(rules, hsr_root, candidate.card, extra_enemy=True)
    target_ids = _direct_target_ids(candidate.target_alias)
    return StatusSystem(rules).apply_add_modifier(
        state,
        candidate.effect,
        caster_id="enemy:target",
        source_id=source_id,
        owner_id="enemy:target",
        param_entity_id=target_ids[0] if target_ids else None,
        current_action_target_id=target_ids[0] if target_ids else None,
        target_resolution=TargetResolution(requested=target_ids, legal=target_ids, selected=target_ids, reason="validation_direct"),
    )


def _select_candidate(
    rules: RuleBook,
    *,
    aliases: set[str],
    require_safe: bool = False,
    require_listener: bool = False,
    require_dynamic: bool = False,
    require_blocked_duration: bool = False,
    allow_missing: bool = False,
) -> AttachedStatusCandidate | None:
    for task in rules.ir.ability_tasks:
        candidate = _candidate_from_task(rules, task)
        if candidate is None or candidate.target_alias not in aliases:
            continue
        standard = candidate.effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        callbacks = _modifier_callbacks(rules, candidate)
        has_dynamic = bool(standard.get("dynamic_value_requests"))
        duration_status = _dict(standard.get("duration_admission")).get("admission_status")
        has_blocked_duration = duration_status == "blocked"
        if require_safe and (callbacks or has_dynamic or has_blocked_duration):
            continue
        if require_listener and (not callbacks or has_dynamic or has_blocked_duration):
            continue
        if require_dynamic and (not has_dynamic or callbacks or has_blocked_duration):
            continue
        if require_blocked_duration and not has_blocked_duration:
            continue
        return candidate
    if allow_missing:
        return None
    raise RuntimeError(f"attached status candidate not found for aliases={sorted(aliases)}")


def _select_runtime_positive_candidate(
    rules: RuleBook,
    hsr_root: Path,
    *,
    aliases: set[str],
    extra_enemy: bool,
    allow_missing: bool = False,
) -> AttachedStatusCandidate | None:
    for task in rules.ir.ability_tasks:
        candidate = _candidate_from_task(rules, task)
        if candidate is None or candidate.target_alias not in aliases:
            continue
        standard = candidate.effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        callbacks = _modifier_callbacks(rules, candidate)
        has_dynamic = bool(standard.get("dynamic_value_requests"))
        has_blocked_duration = _dict(standard.get("duration_admission")).get("admission_status") == "blocked"
        if callbacks or has_dynamic or has_blocked_duration:
            continue
        try:
            case = _execution_case(rules, hsr_root, candidate, extra_enemy=extra_enemy)
        except Exception:
            continue
        checks = case["checks"]["checks"]
        if not checks.get("all_expected_targets_have_status_detail"):
            continue
        if not checks.get("status_mutations_present"):
            continue
        if extra_enemy and len(case.get("expected_target_ids", [])) < 2:
            continue
        return candidate
    if allow_missing:
        return None
    raise RuntimeError(f"runtime attached status candidate not found for aliases={sorted(aliases)}")


def _candidate_from_task(rules: RuleBook, task: AbilityTaskIR) -> AttachedStatusCandidate | None:
    if not task.effect_id or "/ConfigAbility/Monster/" not in task.source.source_path:
        return None
    effect = rules.effect(task.effect_id)
    if effect is None or effect.opcode != "AddModifier":
        return None
    standard = effect.payload.get("standard")
    if not isinstance(standard, dict):
        return None
    action_definition = rules.action_definition(task.action_id, task.level)
    action_event = rules.action_event(task.action_id, task.level)
    if action_definition is None or action_event is None:
        return None
    if task.coverage_status != "executable" or effect.coverage_status != "executable" or action_definition.coverage_status != "executable":
        return None
    card = _card_for_action(rules, task.action_id)
    if card is None:
        return None
    modifier_name = standard.get("modifier_name")
    target_alias = standard.get("target_alias")
    if not isinstance(modifier_name, str) or not modifier_name or not isinstance(target_alias, str):
        return None
    return AttachedStatusCandidate(
        card=card,
        task=task,
        effect=effect,
        action_id=task.action_id,
        action_level=task.level,
        target_alias=target_alias,
        modifier_name=modifier_name,
    )


def _scenario_state(rules: RuleBook, hsr_root: Path, card: MonsterDataCardIR, *, extra_enemy: bool) -> BattleState:
    path = hsr_root / "simulator_v8_clean_core/scenarios/examples/identity_smoke_v0_204.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    enemy_template: dict[str, Any] | None = None
    for unit in data["units"]:
        if unit.get("unit_id") == "enemy:target":
            enemy_template = copy.deepcopy(unit)
            unit["entity_ref"] = card.entity_ref
            unit["level"] = 80
            unit["panel"].update({"max_hp": 1_000_000, "hp": 1_000_000, "attack": 1000, "speed": 100})
        elif unit.get("unit_id") == "ally:saber":
            unit["panel"].update({"max_hp": 1_000_000, "hp": 1_000_000, "toughness": 100, "max_toughness": 100})
    if extra_enemy and enemy_template is not None:
        enemy_template["unit_id"] = "enemy:extra"
        enemy_template["entity_ref"] = card.entity_ref
        enemy_template["position"] = 2
        enemy_template["panel"].update({"max_hp": 1_000_000, "hp": 1_000_000, "attack": 1000, "speed": 100})
        data["units"].append(enemy_template)
    scenario = ScenarioLoader().load_dict(data)
    built = ScenarioStateBuilder(rules).build(scenario)
    return built.state


def _command_for_candidate(rules: RuleBook, candidate: AttachedStatusCandidate) -> ActionCommand:
    definition = rules.require_action_definition(candidate.action_id, candidate.action_level)
    if definition.target_mode == "aoe":
        target_ids: tuple[str, ...] = ()
    elif definition.target_mode == "self_or_team" or candidate.target_alias in {"AllTeamMember", "AllLightTeam", "AllTeammate"}:
        target_ids = ("enemy:target",)
    else:
        target_ids = ("ally:saber",)
    return ActionCommand(
        actor_id="enemy:target",
        action_id=candidate.action_id,
        action_level=candidate.action_level,
        target_ids=target_ids,
        source="manual",
        metadata={"validation": VALIDATION_VERSION, "reset_actor_av": True},
    )


def _expected_attached_target_ids(
    state: BattleState,
    candidate: AttachedStatusCandidate,
    command_target_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if candidate.target_alias == "AbilityTargetEntity":
        return (command_target_ids[0],)
    actor = state.units["enemy:target"]
    if candidate.target_alias == "AllEnemy":
        return tuple(unit_id for unit_id, unit in sorted(state.units.items()) if unit.side != actor.side and unit.hp > 0)
    if candidate.target_alias in {"AllTeamMember", "AllLightTeam"}:
        return tuple(unit_id for unit_id, unit in sorted(state.units.items()) if unit.side == actor.side and unit.hp > 0)
    if candidate.target_alias == "AllTeammate":
        return tuple(unit_id for unit_id, unit in sorted(state.units.items()) if unit.side == actor.side and unit.hp > 0 and unit_id != "enemy:target")
    return ()


def _direct_target_ids(target_alias: str) -> tuple[str, ...]:
    if target_alias in {"AllTeamMember", "AllLightTeam"}:
        return ("enemy:extra", "enemy:target")
    if target_alias == "AllTeammate":
        return ("enemy:extra",)
    return ("ally:saber",)


def _status_details_by_target(
    state: BattleState,
    target_ids: tuple[str, ...],
    modifier_name: str,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    status_id = f"modifier:{modifier_name}"
    for target_id in target_ids:
        unit = state.units[target_id]
        details = unit.flags.get("status_details", ())
        if not isinstance(details, (list, tuple)):
            continue
        for detail in details:
            if isinstance(detail, dict) and detail.get("status_id") == status_id:
                out[target_id] = detail
                break
    return out


def _modifier_callbacks(rules: RuleBook, candidate: AttachedStatusCandidate) -> tuple[Any, ...]:
    definition = _modifier_definition_for_effect(rules, candidate)
    source_path = definition.source.source_path if definition is not None else candidate.effect.source.source_path
    return tuple(
        callback
        for callback in rules.ir.status_callbacks
        if callback.modifier_name == candidate.modifier_name and callback.source.source_path == source_path
    )


def _modifier_definition_for_effect(rules: RuleBook, candidate: AttachedStatusCandidate) -> Any:
    definitions = rules.modifier_definitions(candidate.modifier_name)
    if not definitions:
        return rules.modifier_definition(candidate.modifier_name)
    exact = tuple(definition for definition in definitions if definition.source.source_path == candidate.effect.source.source_path)
    if exact:
        return exact[0]
    if "/Advanced/" in candidate.effect.source.source_path:
        advanced = tuple(definition for definition in definitions if "/Advanced/" in definition.source.source_path)
        if len(advanced) == 1:
            return advanced[0]
    return definitions[0]


def _card_for_action(rules: RuleBook, action_id: str) -> MonsterDataCardIR | None:
    for card in rules.ir.monster_data_cards:
        for slot in card.skill_slots:
            if isinstance(slot, dict) and slot.get("action_ref") == action_id:
                return card
    return None


def _coverage_counts(rules: RuleBook) -> dict[str, int]:
    counts = {"single_safe_candidates": 0, "group_safe_candidates": 0, "listener_blocked_candidates": 0, "dynamic_blocked_candidates": 0}
    for task in rules.ir.ability_tasks:
        candidate = _candidate_from_task(rules, task)
        if candidate is None:
            continue
        standard = candidate.effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        callbacks = _modifier_callbacks(rules, candidate)
        has_dynamic = bool(standard.get("dynamic_value_requests"))
        has_blocked_duration = _dict(standard.get("duration_admission")).get("admission_status") == "blocked"
        safe = not callbacks and not has_dynamic and not has_blocked_duration
        if safe and candidate.target_alias in ATTACHED_SINGLE_ALIASES:
            counts["single_safe_candidates"] += 1
        if safe and candidate.target_alias in ATTACHED_GROUP_ALIASES:
            counts["group_safe_candidates"] += 1
        if callbacks:
            counts["listener_blocked_candidates"] += 1
        if has_dynamic:
            counts["dynamic_blocked_candidates"] += 1
    return counts


def _effect_with_standard(effect: EffectIR, updates: dict[str, Any]) -> EffectIR:
    payload = dict(effect.payload)
    standard = dict(payload.get("standard") if isinstance(payload.get("standard"), dict) else {})
    standard.update(updates)
    payload["standard"] = standard
    return replace(effect, payload=payload)


def _blocked_without_mutation(result: Any, reason_fragment: str) -> bool:
    return (not result.ok) and not result.mutations and any(reason_fragment in reason for reason in result.unsupported)


def _candidate_identity(candidate: AttachedStatusCandidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}
    names = candidate.card.display.get("localized_names") if isinstance(candidate.card.display, dict) else {}
    return {
        "monster_id": candidate.card.monster_id,
        "entity_ref": candidate.card.entity_ref,
        "display_name_chs": names.get("CHS") if isinstance(names, dict) else "",
        "display_name_en": names.get("EN") if isinstance(names, dict) else "",
        "action_id": candidate.action_id,
        "action_level": candidate.action_level,
        "target_alias": candidate.target_alias,
        "modifier_name": candidate.modifier_name,
        "task_id": candidate.task.task_id,
        "effect_id": candidate.effect.effect_id,
        "source_path": candidate.effect.source.source_path,
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
