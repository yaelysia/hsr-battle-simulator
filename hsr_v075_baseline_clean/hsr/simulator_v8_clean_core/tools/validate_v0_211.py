from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR, EffectIR, TriggerIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.status import StatusSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_211"
SUPPORTED_TRIGGER_EVENTS = ("OnBeforeSkillUse", "OnBeforeAttack", "OnAfterAttack", "OnAfterSkillUse")
SUPPORTED_ADD_MODIFIER_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
NON_MAINLINE_PREFIXES = (
    "Config/ConfigAbility/Rogue",
    "Config/ConfigAbility/Fate",
    "Config/ConfigAbility/BattleEvent/",
)


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
    write_full_ir: bool = False,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    if write_full_ir:
        write_json(output_dir / "canonical_ir_v0_211.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_211.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_211.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_211.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _formula_test_state(build_result.state)
    command = _with_crit_mode(build_result.commands[0], "crit")

    sample = _select_trigger_spine_sample(ir, rules)
    pre_status_result = None
    trigger_state = base_state
    if sample:
        pre_status_result = _execute_effect(
            rules,
            base_state,
            sample["pre_effect"],
            command,
            source_suffix="pre_status",
        )
        trigger_state = MutationReducer().apply_all(base_state, pre_status_result.mutations)

    executor = CombatExecutor(rules)
    action_after, action_transition = executor.execute(command, trigger_state)

    unsupported_alias_effect = _select_unsupported_target_alias_effect(ir, rules)
    unsupported_alias_result = (
        _execute_effect(rules, base_state, unsupported_alias_effect, command, source_suffix="unsupported_alias")
        if unsupported_alias_effect
        else None
    )
    unsupported_effect_sample = _select_unsupported_effect_sample(ir, rules)
    unsupported_effect_transition = _sample_transition_from_pre_effect(
        rules,
        base_state,
        command,
        unsupported_effect_sample["pre_effect"] if unsupported_effect_sample else None,
    )
    blocked_condition_sample = _select_blocked_condition_sample(ir, rules)
    blocked_condition_transition = _sample_transition_from_pre_effect(
        rules,
        base_state,
        command,
        blocked_condition_sample["pre_effect"] if blocked_condition_sample else None,
    )
    status_ledger_transition = _status_ledger_transition(ir, rules, base_state, command)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    snapshot_result = snapshot_validator.validate(trigger_state.snapshot())
    action_contract = transition_validator.validate(action_transition)
    action_traceability = settlement_validator.validate(action_transition.transaction.settlement, action_transition.transaction.mutations)
    action_replay = MutationReducer().replay_snapshot(
        trigger_state,
        action_transition.transaction.mutations,
        action_after.snapshot().to_json(),
    )

    checks = {
        "trigger_spine_selection": _trigger_spine_selection_checks(sample),
        "pre_status_application": _pre_status_checks(sample, pre_status_result, trigger_state),
        "trigger_windows_contract": _trigger_windows_contract_checks(action_transition),
        "trigger_executes_add_modifier": _trigger_executes_add_modifier_checks(sample, action_transition),
        "unsupported_paths": _unsupported_checks(
            unsupported_alias_effect,
            unsupported_alias_result,
            unsupported_effect_sample,
            unsupported_effect_transition,
            blocked_condition_sample,
            blocked_condition_transition,
        ),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(action_transition),
    }
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                snapshot_result.ok,
                action_contract.ok,
                action_traceability.ok,
                action_replay.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_entities": len(ir.entities),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_effects": len(ir.effects),
                "ir_triggers": len(ir.triggers),
                "ir_formulas": len(ir.formulas),
                "sampled": ir.metadata.get("sampled", {}),
                "modifier_status": coverage.to_json().get("modifier_status", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "action_id": command.action_id,
                "action_level": command.action_level,
                "target_ids": list(command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "action_transition_contract": action_contract.to_json(),
        "action_settlement_traceability": action_traceability.to_json(),
        "action_replay": {"ok": action_replay.ok, "errors": list(action_replay.errors)},
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_211.json", result)
    write_json(output_dir / "sample_trigger_executor_transition_v0_211.json", action_transition.to_json())
    write_json(output_dir / "sample_pre_status_application_v0_211.json", _effect_result_json(pre_status_result))
    if unsupported_effect_transition is not None:
        write_json(output_dir / "sample_unsupported_effect_transition_v0_211.json", unsupported_effect_transition.to_json())
    if blocked_condition_transition is not None:
        write_json(output_dir / "sample_blocked_condition_transition_v0_211.json", blocked_condition_transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_211.json", status_ledger_transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 trigger window and effect execution spine.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_211"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
    parser.add_argument("--write-full-ir", action="store_true")
    args = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(package_root)
    scenario_path = args.scenario or package_root / "scenarios/examples/identity_smoke_v0_204.json"
    result = run_validation(
        package_root,
        tbgd_root,
        args.output_dir,
        scenario_path,
        max_ability_files=args.max_ability_files,
        write_full_ir=args.write_full_ir,
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _formula_test_state(state: BattleState) -> BattleState:
    actor = state.units["ally:saber"]
    target = state.units["enemy:target"]
    actor = replace(
        actor,
        resources={
            **actor.resources,
            "critical_chance": 0.5,
            "critical_damage": 1.0,
            "damage_added_ratio": 0.2,
            "Wind_damage_added_ratio": 0.1,
            "def_ignore": 0.1,
            "Wind_res_pen": 0.05,
            "all_res_pen": 0.02,
        },
    )
    target = replace(
        target,
        toughness=60.0,
        max_toughness=60.0,
        resources={
            **target.resources,
            "def_reduction": 0.2,
            "Wind_resistance": 0.2,
            "damage_taken_ratio": 0.15,
            "damage_reduction": 0.1,
        },
        flags={**target.flags, "broken": False},
    )
    return replace(state, units={**state.units, actor.unit_id: actor, target.unit_id: target})


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    entity_type_counts: dict[str, int] = {}
    effect_opcode_counts: dict[str, int] = {}
    trigger_event_counts: dict[str, int] = {}
    for entity in ir.entities:
        entity_type_counts[entity.entity_type] = entity_type_counts.get(entity.entity_type, 0) + 1
    for effect in ir.effects:
        effect_opcode_counts[effect.opcode] = effect_opcode_counts.get(effect.opcode, 0) + 1
    for trigger in ir.triggers:
        trigger_event_counts[trigger.event] = trigger_event_counts.get(trigger.event, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "entity_type_counts": dict(sorted(entity_type_counts.items())),
        "effect_opcode_counts": dict(sorted(effect_opcode_counts.items())),
        "trigger_event_counts": dict(sorted(trigger_event_counts.items())),
        "sample_triggers": [trigger.to_json() for trigger in ir.triggers[:5]],
    }


def _select_trigger_spine_sample(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    effects = {effect.effect_id: effect for effect in ir.effects}
    for pre_effect in _add_modifier_effects(ir):
        modifier_name = str(pre_effect.payload["standard"].get("modifier_name") or "")
        for trigger in rules.triggers_for_modifier(modifier_name):
            if trigger.event not in SUPPORTED_TRIGGER_EVENTS:
                continue
            if trigger.conditions:
                continue
            if trigger.source.source_path.startswith(NON_MAINLINE_PREFIXES):
                continue
            for effect_id in trigger.effects:
                effect = effects.get(effect_id)
                if effect and effect.opcode == "AddModifier" and effect.coverage_status == "executable":
                    return {"pre_effect": pre_effect, "trigger": trigger, "trigger_effect": effect}
    return None


def _select_unsupported_effect_sample(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    effects = {effect.effect_id: effect for effect in ir.effects}
    for pre_effect in _add_modifier_effects(ir):
        modifier_name = str(pre_effect.payload["standard"].get("modifier_name") or "")
        for trigger in rules.triggers_for_modifier(modifier_name):
            if trigger.event not in SUPPORTED_TRIGGER_EVENTS:
                continue
            if trigger.conditions:
                continue
            for effect_id in trigger.effects:
                effect = effects.get(effect_id)
                if effect and effect.opcode != "AddModifier":
                    return {"pre_effect": pre_effect, "trigger": trigger, "unsupported_effect": effect}
    return None


def _select_blocked_condition_sample(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    conditions = {condition.condition_id: condition for condition in ir.conditions}
    for pre_effect in _add_modifier_effects(ir):
        modifier_name = str(pre_effect.payload["standard"].get("modifier_name") or "")
        for trigger in rules.triggers_for_modifier(modifier_name):
            if trigger.event not in SUPPORTED_TRIGGER_EVENTS or not trigger.conditions:
                continue
            for condition_id in trigger.conditions:
                condition = conditions.get(condition_id)
                if condition and condition.coverage_status != "executable":
                    return {"pre_effect": pre_effect, "trigger": trigger, "condition": condition}
    return None


def _select_unsupported_target_alias_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard:
            continue
        if standard.get("target_alias") in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        if rules.modifier_definition(str(standard.get("modifier_name") or "")) is not None:
            return effect
    return None


def _status_ledger_transition(
    ir: CanonicalIR,
    rules: RuleBook,
    base_state: BattleState,
    command: ActionCommand,
):
    effect = _select_status_damage_bonus_effect(ir, rules)
    if effect is None:
        return None
    effect_result = _execute_effect(rules, base_state, effect, command, source_suffix="status_ledger")
    status_state = MutationReducer().apply_all(base_state, effect_result.mutations)
    _, transition = CombatExecutor(rules).execute(command, status_state)
    return transition


def _select_status_damage_bonus_effect(ir: CanonicalIR, rules: RuleBook) -> EffectIR | None:
    for effect in _add_modifier_effects(ir):
        modifier_name = str(effect.payload["standard"].get("modifier_name") or "")
        definition = rules.modifier_definition(modifier_name)
        if definition is None:
            continue
        stack_properties = definition.fields.get("stack_properties")
        if not isinstance(stack_properties, list):
            continue
        for item in stack_properties:
            if not isinstance(item, dict):
                continue
            if item.get("property") != "AllDamageTypeAddedRatio":
                continue
            expr = item.get("value_expr")
            if isinstance(expr, dict) and expr.get("kind") == "fixed" and isinstance(expr.get("value"), (int, float)):
                return effect
    return None


def _add_modifier_effects(ir: CanonicalIR) -> tuple[EffectIR, ...]:
    effects: list[EffectIR] = []
    for effect in ir.effects:
        standard = _standard_payload(effect)
        if not standard:
            continue
        if effect.coverage_status != "executable":
            continue
        if standard.get("target_alias") not in SUPPORTED_ADD_MODIFIER_ALIASES:
            continue
        if not isinstance(standard.get("modifier_name"), str):
            continue
        effects.append(effect)
    return tuple(effects)


def _standard_payload(effect: EffectIR) -> dict[str, Any] | None:
    if effect.opcode != "AddModifier":
        return None
    standard = effect.payload.get("standard")
    return standard if isinstance(standard, dict) else None


def _execute_effect(
    rules: RuleBook,
    state: BattleState,
    effect: EffectIR,
    command: ActionCommand,
    *,
    source_suffix: str,
):
    return EffectRegistry(StatusSystem(rules)).execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{source_suffix}:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.target_ids[0] if command.target_ids else None,
        ),
    )


def _sample_transition_from_pre_effect(
    rules: RuleBook,
    base_state: BattleState,
    command: ActionCommand,
    pre_effect: EffectIR | None,
):
    if pre_effect is None:
        return None
    pre_result = _execute_effect(rules, base_state, pre_effect, command, source_suffix="negative_pre_status")
    state = MutationReducer().apply_all(base_state, pre_result.mutations)
    _, transition = CombatExecutor(rules).execute(command, state)
    return transition


def _trigger_spine_selection_checks(sample: dict[str, Any] | None) -> dict[str, object]:
    checks = {
        "found_pre_add_modifier": bool(sample and sample.get("pre_effect")),
        "found_status_trigger": bool(sample and sample.get("trigger")),
        "found_trigger_add_modifier_effect": bool(sample and sample.get("trigger_effect")),
    }
    return {"ok": all(checks.values()), "checks": checks, "sample": _sample_json(sample)}


def _pre_status_checks(sample: dict[str, Any] | None, effect_result, state: BattleState) -> dict[str, object]:
    status_instance = _status_instance(effect_result)
    trigger = sample.get("trigger") if sample else None
    owner_id = str(status_instance.get("owner_id") or "") if status_instance else ""
    unit = state.units.get(owner_id)
    trigger_map = status_instance.get("trigger_ids_by_event", {}) if isinstance(status_instance, dict) else {}
    checks = {
        "pre_status_applied": bool(effect_result and effect_result.mutations),
        "status_instance_present": bool(status_instance),
        "status_has_trigger_map": isinstance(trigger_map, dict) and bool(trigger_map),
        "sample_trigger_bound_to_status": bool(
            isinstance(trigger_map, dict)
            and trigger
            and trigger.trigger_id in trigger_map.get(trigger.event, [])
        ),
        "unit_contains_status": bool(unit and status_instance and status_instance.get("status_id") in unit.statuses),
    }
    return {"ok": all(checks.values()), "checks": checks, "status_instance": status_instance}


def _trigger_windows_contract_checks(transition) -> dict[str, object]:
    transition_json = transition.to_json()
    windows = transition_json.get("trigger_windows", [])
    names = [window.get("canonical_window") for window in windows if isinstance(window, dict)]
    required = {"before_skill_use", "before_attack", "after_attack", "after_skill_use"}
    checks = {
        "transition_has_trigger_windows": isinstance(windows, list),
        "all_required_windows_present": required.issubset(set(names)),
        "settlement_has_trigger_window_records": any(
            record.get("record_type") == "trigger_window"
            for record in transition.transaction.settlement.records
        ) if transition.transaction.settlement else False,
        "coverage_counts_trigger_windows": transition.coverage.get("trigger_window_count", 0) >= 4,
    }
    return {"ok": all(checks.values()), "checks": checks, "window_names": names}


def _trigger_executes_add_modifier_checks(sample: dict[str, Any] | None, transition) -> dict[str, object]:
    trigger = sample.get("trigger") if sample else None
    effect = sample.get("trigger_effect") if sample else None
    windows = transition.to_json().get("trigger_windows", [])
    matched_windows = [
        window
        for window in windows
        if isinstance(window, dict) and trigger and window.get("trigger_id") == trigger.trigger_id
    ]
    effect_hits = [
        effect_result
        for window in matched_windows
        for effect_result in window.get("effect_results", [])
        if isinstance(effect_result, dict) and effect and effect_result.get("effect_id") == effect.effect_id
    ]
    status_mutations = [
        mutation.to_json()
        for mutation in transition.transaction.mutations
        if mutation.source == "status_system"
    ]
    checks = {
        "trigger_window_found": bool(matched_windows),
        "trigger_effect_found": bool(effect_hits),
        "trigger_effect_ok": bool(effect_hits) and all(hit.get("ok") is True for hit in effect_hits),
        "trigger_created_status_mutation": bool(status_mutations),
        "coverage_counts_trigger_mutations": transition.coverage.get("trigger_mutation_count", 0) > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "matched_windows": matched_windows,
        "status_mutations": status_mutations,
    }


def _unsupported_checks(
    unsupported_alias_effect: EffectIR | None,
    unsupported_alias_result,
    unsupported_effect_sample: dict[str, Any] | None,
    unsupported_effect_transition,
    blocked_condition_sample: dict[str, Any] | None,
    blocked_condition_transition,
) -> dict[str, object]:
    alias_reasons = list(unsupported_alias_result.unsupported) if unsupported_alias_result else []
    unsupported_effect_records = _records_of_type(unsupported_effect_transition, "effect_unsupported")
    blocked_windows = [
        window
        for window in (blocked_condition_transition.to_json().get("trigger_windows", []) if blocked_condition_transition else [])
        if isinstance(window, dict) and str(window.get("blocked_reason", "")).startswith("blocked_condition")
    ]
    checks = {
        "found_unsupported_target_alias": unsupported_alias_effect is not None,
        "target_alias_has_reason": any("unsupported_or_missing_target_alias" in reason for reason in alias_reasons),
        "found_unsupported_effect_sample": unsupported_effect_sample is not None,
        "unsupported_effect_recorded": bool(unsupported_effect_records),
        "found_blocked_condition_sample": blocked_condition_sample is not None,
        "blocked_condition_recorded": bool(blocked_windows),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "unsupported_alias": {
            "effect": unsupported_alias_effect.to_json() if unsupported_alias_effect else None,
            "reasons": alias_reasons,
        },
        "unsupported_effect_records": unsupported_effect_records,
        "blocked_condition_windows": blocked_windows,
    }


def _status_modifier_ledger_regression_checks(transition) -> dict[str, object]:
    terms = _modifier_terms(transition) if transition is not None else []
    status_terms = [
        term for term in terms if term.get("source_type") in {"actor.status", "target.status"}
    ]
    checks = {
        "has_status_ledger_transition": transition is not None,
        "has_status_source_term": bool(status_terms),
        "has_damage_bonus_status_term": any(term.get("bucket") == "damage_bonus" for term in status_terms),
    }
    return {"ok": all(checks.values()), "checks": checks, "status_terms": status_terms}


def _damage_semantics_regression_checks(transition) -> dict[str, object]:
    record = _damage_record(transition)
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    checks = {
        "has_direct_damage": payload.get("damage_formula_family") == "direct",
        "direct_damage_has_ledger": isinstance(payload.get("modifier_ledger"), dict),
        "direct_damage_not_bypassing": payload.get("bypasses_normal_multipliers") is False,
        "no_follow_up_family": payload.get("damage_formula_family") != "follow_up",
    }
    return {"ok": all(checks.values()), "checks": checks}


def _sample_json(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sample:
        return None
    return {
        key: value.to_json() if hasattr(value, "to_json") else value
        for key, value in sample.items()
    }


def _status_instance(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    for record in effect_result.records:
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        status_instance = payload.get("status_instance") if isinstance(payload, dict) else None
        if isinstance(status_instance, dict):
            return status_instance
    return None


def _effect_result_json(effect_result) -> dict[str, Any] | None:
    if effect_result is None:
        return None
    return {
        "events": [event.to_json() for event in effect_result.events],
        "mutations": [mutation.to_json() for mutation in effect_result.mutations],
        "records": list(effect_result.records),
        "unsupported": list(effect_result.unsupported),
    }


def _records_of_type(transition, record_type: str) -> list[dict[str, Any]]:
    if transition is None or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if record.get("record_type") == record_type
    ]


def _damage_record(transition) -> dict[str, Any]:
    if transition is None or transition.transaction.settlement is None:
        return {}
    for record in transition.transaction.settlement.records:
        if record.get("record_type") == "damage":
            return record
    return {}


def _formula_result(transition) -> dict[str, Any]:
    record = _damage_record(transition)
    payload = record.get("payload", {})
    formula = payload.get("formula_result", {}) if isinstance(payload, dict) else {}
    return formula if isinstance(formula, dict) else {}


def _modifier_terms(transition) -> list[dict[str, Any]]:
    ledger = _formula_result(transition).get("modifier_ledger", {})
    terms = ledger.get("applied_terms", []) if isinstance(ledger, dict) else []
    return [term for term in terms if isinstance(term, dict)]


if __name__ == "__main__":
    raise SystemExit(main())
