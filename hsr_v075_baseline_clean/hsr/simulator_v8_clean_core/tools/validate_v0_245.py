from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import ActionCommand, ActionSettlement, ActionTransaction, BattleState, BattleTransition, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_229 import _scenario_dict
from .validate_v0_235 import _select_break_family_case, _state_with_toughness_binding, _transition_checks


VALIDATION_VERSION = "v0_245"
SUPPORTED_MOMENTS = {"ModifierPhase1End", "ActionPhaseEnd"}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    coverage = build_coverage_matrix(discovery, ir)
    static_result = run_static_checks(package_root)

    modifier_tick = _modifier_phase_tick_case(rules)
    modifier_expire = _modifier_phase_expire_case(rules, modifier_tick["after_state"])
    action_expire = _action_phase_scheduler_case(ir, rules)
    negative_cases = _negative_cases(rules, modifier_tick["added_state"])

    checks = {
        "coverage": _coverage_checks(coverage.to_json(), rules),
        "modifier_phase_tick": modifier_tick["checks"],
        "modifier_phase_expire": modifier_expire["checks"],
        "action_phase_scheduler": action_expire["checks"],
        "negative_cases": negative_cases["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selected_modifier_phase_effect": modifier_tick["effect"],
            "selected_action_phase_effect": action_expire["effect"],
        },
        "checks": checks,
        "static_checks": static_result.to_json(),
        "source_audits": {
            "modifier_phase_tick": modifier_tick["source_audit"],
            "modifier_phase_expire": modifier_expire["source_audit"],
            "action_phase_scheduler": action_expire["source_audit"],
            "negative_cases": negative_cases["source_audits"],
        },
        "trust_matrix": _trust_matrix(checks),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_245.json", result)
    write_json(output_dir / "sample_modifier_phase_tick_transition_v0_245.json", modifier_tick["transition"])
    write_json(output_dir / "sample_modifier_phase_expire_transition_v0_245.json", modifier_expire["transition"])
    write_json(output_dir / "sample_action_phase_scheduler_transition_v0_245.json", action_expire["transition"])
    write_json(output_dir / "coverage_summary_v0_245.json", coverage.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_245 status duration lifecycle.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _modifier_phase_tick_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules, "ModifierPhase1End", min_duration=2.0)
    state = _base_state()
    add_result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="duration_validation_modifier_phase",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    added_state = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(added_state)
    owner_id = str(detail.get("owner_id") or "ally:actor")
    active_state = _with_active_turn(added_state, owner_id)
    result = CombatScheduler(rules).end_current_turn(active_state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, active_state)
    updated_detail = _status_detail_by_instance(result.after_state, str(detail.get("instance_id") or ""))
    checks.update(
        {
            "add_status_ok": add_result.ok,
            "selected_moment": detail.get("life_step_moment") == "ModifierPhase1End",
            "source_audit": source_audit.ok,
            "tick_mutation_present": any(
                mutation.source == "status_system"
                and mutation.metadata.get("operation") == "tick"
                for mutation in result.transition.transaction.mutations
            ),
            "remaining_duration_decremented": isinstance(updated_detail, dict)
            and updated_detail.get("remaining_duration") == float(detail.get("remaining_duration", 0.0)) - 1,
            "status_not_expired": isinstance(updated_detail, dict)
            and owner_id in result.after_state.units
            and updated_detail.get("status_id") in result.after_state.units[owner_id].statuses,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "effect": _effect_selection(rules, effect),
        "added_state": added_state,
        "after_state": result.after_state,
        "transition": result.transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _modifier_phase_expire_case(rules: RuleBook, state_after_tick: BattleState) -> dict[str, Any]:
    original_detail = _first_status_detail(state_after_tick)
    owner_id = str(original_detail.get("owner_id") or "ally:actor")
    current_state = state_after_tick
    active_state = _with_active_turn(current_state, owner_id)
    result = CombatScheduler(rules).end_current_turn(active_state)
    for _ in range(8):
        if any(
            mutation.source == "status_system" and mutation.metadata.get("operation") == "expire"
            for mutation in result.transition.transaction.mutations
        ):
            break
        current_detail = _status_detail_by_instance(result.after_state, str(original_detail.get("instance_id") or ""))
        if current_detail is None:
            break
        current_state = result.after_state
        active_state = _with_active_turn(current_state, owner_id)
        result = CombatScheduler(rules).end_current_turn(active_state)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, active_state)
    checks.update(
        {
            "source_audit": source_audit.ok,
            "expire_mutation_present": any(
                mutation.source == "status_system"
                and mutation.metadata.get("operation") == "expire"
                for mutation in result.transition.transaction.mutations
            ),
            "status_removed": owner_id in result.after_state.units
            and str(original_detail.get("status_id") or "") not in result.after_state.units[owner_id].statuses,
            "detail_removed": _status_detail_by_instance(
                result.after_state,
                str(original_detail.get("instance_id") or ""),
            )
            is None,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": checks, "transition": result.transition.to_json(), "source_audit": source_audit.to_json()}


def _action_phase_scheduler_case(ir, rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules, "ActionPhaseEnd", min_duration=1.0, max_duration=1.0)
    state, command = _scheduler_action_state_and_command(ir, rules)
    add_result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="duration_validation_action_phase",
        owner_id="ally:actor",
        param_entity_id="enemy:profile_target",
        current_action_target_id="enemy:profile_target",
    )
    added_state = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(added_state)
    scheduled_state = _make_actor_next(added_state)
    result = CombatScheduler(rules).step(scheduled_state, command)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    checks = _transition_checks(result.transition, scheduled_state)
    checks.update(
        {
            "add_status_ok": add_result.ok,
            "selected_moment": detail.get("life_step_moment") == "ActionPhaseEnd",
            "source_audit": source_audit.ok,
            "action_phase_expire_mutation": any(
                mutation.source == "status_system"
                and mutation.metadata.get("operation") == "expire"
                for mutation in result.transition.transaction.mutations
            ),
            "detail_removed": _status_detail_by_instance(result.after_state, str(detail.get("instance_id") or "")) is None,
            "scheduler_child_action_present": len(result.child_transitions) == 3,
        }
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": checks,
        "effect": _effect_selection(rules, effect),
        "transition": result.transition.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _negative_cases(rules: RuleBook, base_state: BattleState) -> dict[str, Any]:
    detail = _first_status_detail(base_state)
    negative_details = {
        "unknown_life_step_moment": {
            **detail,
            "life_step_moment": "UnknownMoment",
            "duration_admission": {
                **_duration_admission(detail),
                "admission_status": "blocked",
                "blocked_reason": "unsupported_life_step_moment:UnknownMoment",
                "life_step_moment": "UnknownMoment",
            },
        },
        "dynamic_lifetime_unbound": {
            **detail,
            "duration_admission": {
                **_duration_admission(detail),
                "admission_status": "blocked",
                "blocked_reason": "unbound_dynamic_lifetime",
            },
        },
        "permanent_or_unknown": {
            **detail,
            "remaining_duration": None,
            "duration_admission": {
                "admission_status": "not_applicable",
                "blocked_reason": "lifetime_missing",
            },
        },
    }
    checks: dict[str, bool] = {}
    source_audits: dict[str, Any] = {}
    transitions: dict[str, Any] = {}
    for name, patched_detail in negative_details.items():
        owner_id = str(patched_detail.get("owner_id") or "ally:actor")
        state = _replace_single_detail(base_state, patched_detail)
        result = StatusSystem(rules).apply_lifecycle_tick(
            state,
            owner_id,
            patched_detail,
            str(patched_detail.get("life_step_moment") or "ModifierPhase1End"),
        )
        transition = _status_result_transition(state, result, name)
        source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        transition_checks = _transition_checks(transition, state)
        checks[f"{name}_contract"] = transition_checks["transition_contract"]
        checks[f"{name}_traceability"] = transition_checks["settlement_traceability"]
        checks[f"{name}_replay"] = transition_checks["replay"]
        checks[f"{name}_source_audit"] = source_audit.ok
        checks[f"{name}_after_unchanged"] = transition.after.to_json() == state.snapshot().to_json()
        checks[f"{name}_no_mutations"] = not transition.transaction.mutations
        source_audits[name] = source_audit.to_json()
        transitions[name] = transition.to_json()
    checks["ok"] = all(checks.values())
    return {"checks": checks, "source_audits": source_audits, "transitions": transitions}


def _select_duration_effect(
    rules: RuleBook,
    life_step_moment: str,
    *,
    min_duration: float,
    max_duration: float | None = None,
) -> EffectIR:
    failures: list[dict[str, Any]] = []
    status_system = StatusSystem(rules)
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        if _source_mode(effect.source.source_path) != "mainline":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
            continue
        standard_duration = standard.get("duration_admission")
        known_duration = (
            standard_duration
            if isinstance(standard_duration, dict) and standard_duration.get("admission_status") == "executable"
            else _duration_admission_for_effect(rules, effect)
        )
        if isinstance(known_duration, dict) and known_duration.get("admission_status") == "executable":
            if known_duration.get("life_step_moment") != life_step_moment:
                continue
            standard_remaining = known_duration.get("remaining_duration")
            if not (
                isinstance(standard_remaining, (int, float))
                and float(standard_remaining) >= min_duration
                and (max_duration is None or float(standard_remaining) <= max_duration)
            ):
                continue
        else:
            modifier_name = str(standard.get("modifier_name") or "")
            if life_step_moment != "ModifierPhase1End" or not _modifier_defaults_to_phase_end(rules, modifier_name):
                continue
        probe = status_system.apply_add_modifier(
            _base_state(),
            effect,
            caster_id="ally:actor",
            source_id="duration_selection_probe",
            owner_id="ally:actor",
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        )
        admission = probe.status_instance.duration_admission if probe.status_instance else {}
        duration = admission.get("remaining_duration") if isinstance(admission, dict) else None
        if (
            probe.ok
            and isinstance(admission, dict)
            and admission.get("admission_status") == "executable"
            and admission.get("life_step_moment") == life_step_moment
            and isinstance(duration, (int, float))
            and float(duration) >= min_duration
            and (max_duration is None or float(duration) <= max_duration)
        ):
            return effect
        failures.append(
            {
                "effect_id": effect.effect_id,
                "unsupported": list(probe.unsupported),
                "duration_admission": admission if isinstance(admission, dict) else {},
            }
        )
    raise RuntimeError(f"no executable duration effect found for {life_step_moment}; failures={failures[:5]}")


def _modifier_defaults_to_phase_end(rules: RuleBook, modifier_name: str) -> bool:
    if not modifier_name:
        return False
    entity = rules.status_entity_for_modifier(modifier_name)
    if entity is None:
        return False
    status_type = str(entity.fields.get("StatusType") or entity.fields.get("status_type") or "").strip().lower()
    return status_type in {"buff", "debuff"}


def _duration_admission_for_effect(rules: RuleBook, effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    admission = standard.get("duration_admission")
    if isinstance(admission, dict) and admission.get("admission_status") != "not_applicable":
        return admission
    modifier_name = standard.get("modifier_name")
    definition = rules.modifier_definition(str(modifier_name)) if modifier_name else None
    definition_admission = definition.fields.get("duration_admission") if definition else None
    return definition_admission if isinstance(definition_admission, dict) else {}


def _scheduler_action_state_and_command(ir, rules: RuleBook) -> tuple[BattleState, ActionCommand]:
    case = _select_break_family_case(ir, rules)
    scenario = ScenarioLoader().load_dict(
        _scenario_dict(
            case["profile"],
            case["action"],
            case["avatar"],
            enemy_panel={"max_hp": 100000.0, "hp": 100000.0},
        )
    )
    identity_result = IdentityResolver(rules).validate(scenario)
    if not identity_result.ok:
        raise RuntimeError(f"duration scheduler scenario identity failed: {identity_result.errors}")
    build_result = ScenarioStateBuilder(rules).build(scenario)
    enemy = build_result.state.units["enemy:profile_target"]
    state = _state_with_toughness_binding(build_result.state, case["toughness_emission"], enemy.toughness)
    return state, build_result.commands[0]


def _base_state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:duration_actor",
                max_hp=3000.0,
                hp=3000.0,
                attack=3000.0,
                defense=900.0,
                speed=100.0,
                action_value=0.0,
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="monster:duration_target",
                max_hp=10000.0,
                hp=10000.0,
                defense=1000.0,
                speed=100.0,
                action_value=50.0,
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "duration_validation", "current_window": "idle"},
    )


def _with_active_turn(state: BattleState, actor_id: str = "ally:actor") -> BattleState:
    return replace(
        state,
        global_flags={
            **state.global_flags,
            "active_turn": {"actor_id": actor_id, "turn_kind": "regular", "turn_sequence_index": 1},
            "turn_owner_id": actor_id,
            "current_window": "turn_active",
        },
    )


def _make_actor_next(state: BattleState) -> BattleState:
    units = {}
    for unit_id, unit in state.units.items():
        if unit_id == "ally:actor":
            units[unit_id] = replace(unit, action_value=0.0)
        elif unit.side == "enemy":
            units[unit_id] = replace(unit, action_value=40.0, flags={**unit.flags, "ai_policy_admitted": False})
        else:
            units[unit_id] = replace(unit, action_value=80.0)
    return replace(state, units=units, skill_points=max(5, state.skill_points), global_flags={**state.global_flags, "current_window": "idle"})


def _first_status_detail(state: BattleState) -> dict[str, Any]:
    for unit in state.units.values():
        details = unit.flags.get("status_details", ())
        if isinstance(details, (list, tuple)):
            for item in details:
                if isinstance(item, dict):
                    return dict(item)
    raise RuntimeError("status detail missing")


def _status_detail_by_instance(state: BattleState, instance_id: str) -> dict[str, Any] | None:
    for unit in state.units.values():
        details = unit.flags.get("status_details", ())
        if isinstance(details, (list, tuple)):
            for item in details:
                if isinstance(item, dict) and item.get("instance_id") == instance_id:
                    return dict(item)
    return None


def _replace_single_detail(state: BattleState, detail: dict[str, Any]) -> BattleState:
    owner_id = str(detail.get("owner_id") or "ally:actor")
    unit = state.units[owner_id]
    updated = replace(unit, flags={**unit.flags, "status_details": [detail]})
    return replace(state, units={**state.units, owner_id: updated})


def _duration_admission(detail: dict[str, Any]) -> dict[str, Any]:
    admission = detail.get("duration_admission")
    return dict(admission) if isinstance(admission, dict) else {}


def _status_result_transition(state: BattleState, result, name: str) -> BattleTransition:
    after_state = MutationReducer().apply_all(state, result.mutations)
    command = ActionCommand(actor_id="ally:actor", action_id=f"duration_negative:{name}", action_level=0)
    return BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            mutations=result.mutations,
            settlement=ActionSettlement(command.action_id, command.actor_id, (), result.records),
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(reason=name, source="duration_validation"),
        coverage={"negative_case": name},
    )


def _source_mode(source_path: str) -> str:
    markers = (
        "/Activity/",
        "/Rogue/",
        "/GridFight/",
        "/Fate/",
        "/Story/",
        "/Level/",
        "/SubLevelGraph/",
        "/ElationBattle/",
        "Config/Level/",
        "Config/Gameplays/",
    )
    return "special_mode" if any(marker in source_path for marker in markers) else "mainline"


def _effect_selection(rules: RuleBook, effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    probe = StatusSystem(rules).apply_add_modifier(
        _base_state(),
        effect,
        caster_id="ally:actor",
        source_id="duration_selection_report",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    return {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "source_path": effect.source.source_path,
        "modifier_name": standard.get("modifier_name"),
        "duration_admission": probe.status_instance.duration_admission if probe.status_instance else {},
        "selection_mode": "structured_duration_admission",
    }


def _coverage_checks(coverage_json: dict[str, Any], rules: RuleBook) -> dict[str, object]:
    found = {moment: False for moment in SUPPORTED_MOMENTS}
    for effect in rules.ir.effects:
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        if _source_mode(effect.source.source_path) != "mainline":
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        if standard.get("target_alias") not in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
            continue
        admission = _duration_admission_for_effect(rules, effect)
        if admission.get("admission_status") == "executable":
            moment = str(admission.get("life_step_moment") or "")
            if moment in found:
                found[moment] = True
        elif _modifier_defaults_to_phase_end(rules, str(standard.get("modifier_name") or "")):
            found["ModifierPhase1End"] = True
    checks = {
        "coverage_has_effects": coverage_json.get("ir_summary", {}).get("effects", 0) > 0,
        "modifier_phase_sample_available": found["ModifierPhase1End"],
        "action_phase_sample_available": found["ActionPhaseEnd"],
    }
    return {"ok": all(checks.values()), "checks": checks}


def _trust_matrix(checks: dict[str, Any]) -> dict[str, object]:
    return {
        "full_status_duration_tick": {
            "semantic_status": "trusted_for_current_scope"
            if checks["modifier_phase_tick"]["ok"]
            and checks["modifier_phase_expire"]["ok"]
            and checks["action_phase_scheduler"]["ok"]
            else "blocked",
            "scope": "fixed numeric LifeTime with admitted ModifierPhase1End or ActionPhaseEnd",
        },
        "unknown_life_step_moment": {
            "semantic_status": "blocked",
            "blocking_dependency": "specific LifeStepMoment admission",
        },
        "dynamic_or_postfix_lifetime": {
            "semantic_status": "blocked",
            "blocking_dependency": "dynamic/postfix lifetime numeric admission",
        },
    }

if __name__ == "__main__":
    raise SystemExit(main())
