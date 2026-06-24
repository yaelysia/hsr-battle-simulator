from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState, BattleTransition
from ..core.reducer import MutationReducer
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.source_audit import MUTATION_SOURCE_POLICIES, RuntimeSourceAuditor
from ..rules.ir import CanonicalIR, EffectIR
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
from .validate_v0_213 import (
    _damage_semantics_regression_checks,
    _execute_effect as _execute_status_effect,
    _formula_test_state,
    _select_executable_damage_emission_definition,
    _status_modifier_ledger_regression_checks,
    _target_ids_for_damage_definition,
)
from .validate_v0_214 import (
    HEAL_OPCODES,
    MECHANISM_BAR_OPCODES,
    REMOVE_OPCODES,
    REMOVE_SELF_OPCODES,
    SHIELD_OPCODES,
    _effect_transition,
    _fixed_or_blocked_case,
    _mechanism_bar_case,
    _remove_effect_case,
    _select_blocked_effect,
    _select_effect,
    _select_fixed_amount_effect,
    _with_damaged_actor,
)
from .validate_v0_215 import _modify_sp_case
from .validate_v0_218 import (
    TARGET_MODES,
    _case_json,
    _fixed_damage_family_cases,
    _fixed_damage_family_checks,
    _multi_enemy_state,
    _records_of_type,
    _select_definition,
    _transition_quality_checks,
    _with_crit_mode,
)
from .validate_v0_219 import _preflight_commit_gate_checks, _preflight_negative_cases, _runtime_import_boundary_check
from .validate_v0_221 import _runtime_raw_ability_static_guard
from .validate_v0_223 import (
    _damage_emission_case_json,
    _executable_damage_emission_case,
    _no_executable_damage_emission_case,
    _runtime_damage_emission_path_checks,
    _runtime_damage_opcode_static_guard,
)
from .validate_v0_224 import (
    _canonical_ir_summary,
    _dynamic_value_source_case,
    _executable_ir_source_checks,
    _mutation_source_category_checks,
    _non_mutating_status_checks,
    _sample_source_trace,
    _status_source_case,
    _validation_sample_policy_checks,
)


VALIDATION_VERSION = "v0_225"
TRUSTED = "trusted_for_current_scope"
STRUCTURAL = "structural_only"
BLOCKED = "blocked"
NEEDS_FIX = "needs_fix"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
    write_full_ir: bool = False,
    write_diagnostics: bool = False,
    write_matrices: bool = False,
) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    rules = RuleBook(ir)

    if write_full_ir:
        write_json(output_dir / "canonical_ir_v0_225.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_225.json", _canonical_ir_summary(ir))
    matrix_summary = _matrix_summary_not_written()
    if write_matrices:
        discovery = TBGDDiscovery(tbgd_root).scan()
        coverage = build_coverage_matrix(discovery, ir)
        fidelity = build_fidelity_matrix(discovery, ir)
        write_json(output_dir / "coverage_matrix_v0_225.json", coverage.to_json())
        write_json(output_dir / "fidelity_matrix_v0_225.json", fidelity.to_json())
        matrix_summary = {
            "written": True,
            "discovery_files": len(discovery.files),
            "fidelity": fidelity.to_json()["summary"],
        }

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )
    formula_state = _formula_test_state(build_result.state)
    formula_command = _with_crit_mode(build_result.commands[0], "crit")

    damage_case = _with_replay(_executable_damage_emission_case(ir, rules, base_state, base_command))
    no_fake_damage_case = _with_replay(_no_executable_damage_emission_case(ir, rules, base_state, base_command))
    status_case = _with_replay(_status_source_case(ir, rules, formula_state, formula_command))
    status_ledger_case = _status_ledger_case(ir, rules, formula_state, formula_command)
    status_ledger_transition = status_ledger_case.get("transition")
    dynamic_value_case = _with_replay(_dynamic_value_source_case(ir, rules, formula_state, formula_command))
    effect_cases = _existing_effect_cases(ir, rules, formula_state, formula_command)

    definitions = {mode: _select_definition(ir, mode) for mode in TARGET_MODES}
    negative_cases = {
        name: _with_replay(case)
        for name, case in _preflight_negative_cases(ir, rules, base_state, base_command, definitions).items()
    }
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, build_result.commands[0])

    audit_transitions = _audit_transition_map(
        {
            "damage_executor": damage_case,
            "no_fake_damage": no_fake_damage_case,
            "status_ledger_damage": status_ledger_case,
            "status_add_modifier": status_case,
            "effect_dynamic_value_store": dynamic_value_case,
            **effect_cases,
            **{f"negative_{name}": case for name, case in negative_cases.items()},
        }
    )
    source_audit_full = _source_audit_full_checks(rules, audit_transitions)
    source_audit_summary = _source_audit_summary(source_audit_full)
    sample_trace = _sample_source_trace(source_audit_full["results"])
    negative_snapshot = _negative_snapshot_checks(negative_cases)
    mechanism_matrix = _mechanism_trust_matrix(
        source_audit_full,
        negative_snapshot,
        damage_case,
        no_fake_damage_case,
        status_case,
        dynamic_value_case,
        effect_cases,
        fixed_damage_cases,
    )

    static_result = run_static_checks(package_root)
    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    transition_quality = _transition_quality_checks(
        {
            "damage_executor": damage_case,
            "no_fake_damage": no_fake_damage_case,
            "status_ledger_damage": status_ledger_case,
            "status_add_modifier": status_case,
            "effect_dynamic_value_store": dynamic_value_case,
            **_cases_with_transitions(effect_cases),
            **{f"negative_{name}": case for name, case in negative_cases.items()},
        }
    )
    checks = {
        "source_audit": source_audit_summary,
        "source_audit_trace_sample": sample_trace,
        "mutation_source_categories": _mutation_source_category_checks(audit_transitions),
        "mutation_source_policy_coverage": _mutation_source_policy_checks(package_root),
        "negative_snapshot_unchanged": negative_snapshot,
        "preflight_commit_gate": _preflight_commit_gate_checks(negative_cases),
        "damage_emission_runtime_path": _runtime_damage_emission_path_checks(damage_case),
        "non_mutating_status_guard": _non_mutating_status_checks(ir, audit_transitions),
        "executable_ir_sources": _executable_ir_source_checks(ir),
        "sample_selection_policy": _sample_selection_policy_checks(package_root, damage_case, no_fake_damage_case, status_case, dynamic_value_case, effect_cases),
        "mechanism_trust_matrix": _trust_matrix_checks(mechanism_matrix),
        "transition_quality": transition_quality,
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
        "runtime_import_boundary": _runtime_import_boundary_check(static_result.to_json()),
        "runtime_raw_ability_static_guard": _runtime_raw_ability_static_guard(static_result.to_json()),
        "runtime_damage_opcode_static_guard": _runtime_damage_opcode_static_guard(static_result.to_json()),
    }

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                snapshot_result.ok,
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": matrix_summary.get("discovery_files", None),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_action_events": len(ir.action_events),
                "ir_hit_profiles": len(ir.hit_profiles),
                "ir_ability_tasks": len(ir.ability_tasks),
                "ir_damage_emissions": len(ir.damage_emissions),
                "ir_effects": len(ir.effects),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "command": {
                "actor_id": base_command.actor_id,
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "matrices": matrix_summary,
    }

    write_json(output_dir / "validation_summary_v0_225.json", result)
    write_json(output_dir / "source_audit_summary_v0_225.json", source_audit_summary)
    write_json(output_dir / "sample_source_audit_trace_v0_225.json", sample_trace)
    write_json(output_dir / "mechanism_trust_matrix_v0_225.json", mechanism_matrix)
    if write_diagnostics:
        write_json(output_dir / "source_audit_full_v0_225.json", source_audit_full)
        write_json(output_dir / "sample_negative_cases_v0_225.json", _negative_cases_json(negative_cases))
        write_json(output_dir / "sample_damage_emission_case_v0_225.json", _damage_emission_case_json(damage_case))
        write_json(output_dir / "sample_no_fake_damage_case_v0_225.json", _damage_emission_case_json(no_fake_damage_case))
        _write_transition_samples(output_dir, audit_transitions)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 existing mechanism source trust audit.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_225"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
    parser.add_argument("--write-full-ir", action="store_true")
    parser.add_argument("--write-diagnostics", action="store_true")
    parser.add_argument("--write-matrices", action="store_true")
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
        write_diagnostics=args.write_diagnostics,
        write_matrices=args.write_matrices,
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _existing_effect_cases(
    ir: CanonicalIR,
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
) -> dict[str, dict[str, Any]]:
    registry = EffectRegistry(StatusSystem(rules))
    cases: dict[str, dict[str, Any]] = {}
    remove_effect = _select_effect(ir, REMOVE_OPCODES, coverage_status="executable")
    cases["effect_remove_modifier"] = _with_replay(
        _mark_effect_case(
            _remove_effect_case(rules, registry, state, command, remove_effect, "v0_225_real_remove_modifier"),
            "structured_predicate",
            "RemoveModifier",
        )
    )
    remove_self_effect = _select_effect(ir, REMOVE_SELF_OPCODES, coverage_status="executable")
    cases["effect_remove_self_modifier"] = _with_replay(
        _mark_effect_case(
            _remove_effect_case(
                rules,
                registry,
                state,
                command,
                remove_self_effect,
                "v0_225_real_remove_self_modifier",
            ),
            "structured_predicate",
            "RemoveSelfModifier",
        )
    )
    heal_case = _bound_numeric_effect_case(
        rules,
        registry,
        _with_damaged_actor(state, command.actor_id),
        command,
        HEAL_OPCODES,
        "heal",
        _select_blocked_effect(ir, HEAL_OPCODES),
    )
    cases["effect_heal"] = _with_replay(_mark_effect_case(heal_case, "structured_predicate_or_blocked", "HealHP"))
    shield_case = _bound_numeric_effect_case(
        rules,
        registry,
        state,
        command,
        SHIELD_OPCODES,
        "shield",
        _select_blocked_effect(ir, SHIELD_OPCODES),
    )
    cases["effect_shield"] = _with_replay(_mark_effect_case(shield_case, "structured_predicate_or_blocked", "Shield"))
    mechanism_case = _mechanism_bar_case(
        registry,
        state,
        command,
        _select_effect(ir, MECHANISM_BAR_OPCODES, coverage_status="executable"),
        _select_blocked_effect(ir, MECHANISM_BAR_OPCODES),
    )
    cases["effect_mechanism_bar"] = _with_replay(_mark_effect_case(mechanism_case, "structured_predicate_or_blocked", "mechanism_bar_state"))
    modify_sp = _modify_sp_case(ir, registry, state, command)
    cases["effect_modify_sp"] = _with_replay(
        _mark_effect_case(modify_sp, "manual_input_binding_smoke", "ModifySPNew")
    )
    return cases


MAINLINE_EFFECT_PREFIXES = (
    "Config/ConfigAbility/Avatar/",
    "Config/ConfigAbility/Monster/",
    "Config/ConfigAbility/Servant/",
)
EXCLUDED_EFFECT_SOURCE_MARKERS = (
    "Activity",
    "AetherDivide",
    "BattleEvent",
    "Currency",
    "Fate",
    "GridFight",
    "MazeBuff",
    "Rogue",
    "Story",
)
SUPPORTED_VALIDATION_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}


def _bound_numeric_effect_case(
    rules: RuleBook,
    registry: EffectRegistry,
    base_state: BattleState,
    command: ActionCommand,
    opcodes: tuple[str, ...],
    record_type: str,
    blocked_effect: EffectIR | None,
) -> dict[str, Any]:
    selected = _select_fixed_or_status_bound_amount_effect(rules.ir, rules, opcodes)
    if selected is None:
        return {
            "mode": "blocked_no_executable_mainline_sample",
            "effect": blocked_effect,
            "transition": None,
            "selection": _effect_selection(blocked_effect, "structured_predicate_blocked", record_type),
        }
    effect, binding = selected
    state = base_state
    if binding:
        state = _with_status_dynamic_binding(base_state, command.actor_id, effect, binding)
    target_id = _effect_target_id(effect, command.actor_id)
    result = registry.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=command.actor_id,
            source_id=f"validation:{VALIDATION_VERSION}:{record_type}:structured:{effect.effect_id}",
            owner_id=command.actor_id,
            param_entity_id=command.actor_id,
            current_action_target_id=command.actor_id,
        ),
    )
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _effect_transition(
        command=command,
        before_state=state,
        after_state=after,
        effect=effect,
        effect_result=result,
        target_id=target_id,
        coverage_id=f"{VALIDATION_VERSION}_{record_type}_structured",
    )
    selection = _effect_selection(effect, "structured_predicate", record_type)
    selection.update(
        {
            "amount_kind": _amount_kind(effect),
            "binding_source": binding["source_type"] if binding else "fixed_amount",
            "binding_hash": binding.get("hash", "") if binding else "",
            "modifier_definition_source": binding.get("modifier_definition_source", {}) if binding else {},
        }
    )
    return {
        "mode": "status_bound_dynamic_executable" if binding else "fixed_executable",
        "effect": effect,
        "result": result,
        "transition": transition,
        "before_state": state,
        "selection": selection,
        "binding": binding or {},
    }


def _select_fixed_or_status_bound_amount_effect(
    ir: CanonicalIR,
    rules: RuleBook,
    opcodes: tuple[str, ...],
) -> tuple[EffectIR, dict[str, Any] | None] | None:
    for effect in sorted(ir.effects, key=lambda item: (item.source.source_path, item.effect_id)):
        if effect.opcode not in opcodes or effect.coverage_status != "executable":
            continue
        if not _is_mainline_effect_source(effect.source.source_path):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict) or standard.get("target_alias") not in SUPPORTED_VALIDATION_ALIASES:
            continue
        amount = standard.get("amount")
        if _fixed_amount_value(amount) is not None:
            return effect, None
        hash_key = _dynamic_hash_key(amount)
        if not hash_key:
            continue
        binding = _modifier_dynamic_hash_binding(rules, effect.source.raw_id, hash_key)
        if binding is not None:
            return effect, binding
    return None


def _is_mainline_effect_source(source_path: str) -> bool:
    return source_path.startswith(MAINLINE_EFFECT_PREFIXES) and not any(
        marker in source_path for marker in EXCLUDED_EFFECT_SOURCE_MARKERS
    )


def _fixed_amount_value(amount: object) -> float | None:
    if isinstance(amount, dict) and amount.get("kind") == "fixed" and isinstance(amount.get("value"), (int, float)):
        return float(amount["value"])
    return None


def _dynamic_hash_key(amount: object) -> str:
    if isinstance(amount, dict) and amount.get("kind") == "dynamic_hash" and amount.get("hash") is not None:
        return str(amount["hash"])
    return ""


def _modifier_dynamic_hash_binding(
    rules: RuleBook,
    modifier_name: str,
    hash_key: str,
) -> dict[str, Any] | None:
    definition = rules.modifier_definition(modifier_name)
    if definition is None:
        return None
    bindings = definition.fields.get("dynamic_value_bindings")
    by_hash = bindings.get("by_hash") if isinstance(bindings, dict) else None
    binding = by_hash.get(hash_key) if isinstance(by_hash, dict) else None
    if not isinstance(binding, dict):
        return None
    return {
        "hash": hash_key,
        "value": 123.0,
        "source_type": "status_instance",
        "modifier_name": modifier_name,
        "modifier_definition_source": definition.source.to_json(),
        "binding": binding,
    }


def _with_status_dynamic_binding(
    state: BattleState,
    unit_id: str,
    effect: EffectIR,
    binding: dict[str, Any],
) -> BattleState:
    unit = state.units[unit_id]
    modifier_name = str(binding["modifier_name"])
    instance_id = f"status_instance:validation:{VALIDATION_VERSION}:{modifier_name}"
    detail = {
        "instance_id": instance_id,
        "status_id": modifier_name,
        "modifier_name": modifier_name,
        "owner_id": unit_id,
        "source_id": f"validation:{VALIDATION_VERSION}:status_dynamic_binding:{effect.effect_id}",
        "source_trace": {
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "modifier_definition_source": binding["modifier_definition_source"],
            "dynamic_value_binding": binding["binding"],
        },
        "dynamic_values": {"__by_hash": {str(binding["hash"]): float(binding["value"])}},
    }
    details = tuple(item for item in unit.flags.get("status_details", ()) if isinstance(item, dict))
    flags = {**unit.flags, "status_details": [*details, detail]}
    statuses = tuple(dict.fromkeys((*unit.statuses, modifier_name)))
    updated_unit = replace(unit, statuses=statuses, flags=flags)
    return replace(state, units={**state.units, unit_id: updated_unit})


def _effect_target_id(effect: EffectIR, actor_id: str) -> str:
    standard = effect.payload.get("standard")
    alias = standard.get("target_alias") if isinstance(standard, dict) else ""
    if alias in {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}:
        return actor_id
    return actor_id


def _amount_kind(effect: EffectIR) -> str:
    standard = effect.payload.get("standard")
    amount = standard.get("amount") if isinstance(standard, dict) else None
    return str(amount.get("kind") or "") if isinstance(amount, dict) else ""


def _effect_selection(effect: EffectIR | None, selection_mode: str, mechanism: str) -> dict[str, Any]:
    if effect is None:
        return {"selection_mode": selection_mode, "mechanism": mechanism, "missing_effect": True}
    return {
        "selection_mode": selection_mode,
        "mechanism": mechanism,
        "opcode": effect.opcode,
        "coverage_status": effect.coverage_status,
        "source_trace": effect.source.to_json(),
    }


def _status_ledger_case(
    ir: CanonicalIR,
    rules: RuleBook,
    base_state: BattleState,
    command: ActionCommand,
) -> dict[str, Any]:
    from .validate_v0_210 import _select_status_damage_bonus_effect
    from ..core.executor import CombatExecutor

    effect = _select_status_damage_bonus_effect(ir, rules)
    definition = _select_character_card_damage_definition(ir, rules) or _select_executable_damage_emission_definition(ir, rules)
    if effect is None or definition is None:
        return {"transition": None, "before": base_state, "after": base_state, "error": "missing status ledger inputs"}
    command = replace(
        command,
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=_target_ids_for_damage_definition(definition, command.actor_id),
    )
    effect_result = _execute_status_effect(rules, base_state, effect, command, source_suffix="v0_225_status_ledger")
    status_state = MutationReducer().apply_all(base_state, effect_result.mutations)
    after, transition = CombatExecutor(rules).execute(command, status_state)
    replay = MutationReducer().replay_snapshot(status_state, transition.transaction.mutations, after.snapshot().to_json())
    return {
        "transition": transition,
        "before": status_state,
        "after": after,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "selection": {
            "selection_mode": "structured_predicate",
            "mechanism": "status_modifier_ledger_damage_regression",
            "effect_id": effect.effect_id,
            "action_id": definition.action_id,
            "action_level": definition.level,
            "source_trace": effect.source.to_json(),
        },
    }


def _select_character_card_damage_definition(ir: CanonicalIR, rules: RuleBook):
    for emission in sorted(ir.damage_emissions, key=lambda item: item.damage_emission_id):
        if emission.coverage_status != "executable" or emission.damage_formula_family != "direct":
            continue
        if emission.scaling_basis_expr.get("source_kind") != "character_data_card_skill_formula":
            continue
        definition = rules.action_definition(emission.action_id, emission.level)
        if definition is None:
            continue
        if definition.damage_kind == "hp_damage" and definition.damage_formula_family == "direct":
            return definition
    return None


def _mark_effect_case(case: dict[str, Any], selection_mode: str, mechanism: str) -> dict[str, Any]:
    effect = case.get("effect")
    if isinstance(effect, EffectIR):
        case.setdefault(
            "selection",
            {
                "selection_mode": selection_mode,
                "mechanism": mechanism,
                "opcode": effect.opcode,
                "coverage_status": effect.coverage_status,
                "source_trace": effect.source.to_json(),
            },
        )
    return case


def _audit_transition_map(cases: dict[str, dict[str, Any]]) -> dict[str, BattleTransition]:
    transitions: dict[str, BattleTransition] = {}
    for name, case in cases.items():
        transition = case.get("transition")
        if isinstance(transition, BattleTransition):
            transitions[name] = transition
    return transitions


def _cases_with_transitions(cases: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        name: case
        for name, case in cases.items()
        if isinstance(case.get("transition"), BattleTransition)
    }


def _source_audit_full_checks(
    rules: RuleBook,
    transitions: dict[str, BattleTransition],
) -> dict[str, Any]:
    auditor = RuntimeSourceAuditor(rules)
    results: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    mutation_total = 0
    for name, transition in sorted(transitions.items()):
        audit = auditor.validate_transition(transition)
        results[name] = audit.to_json()
        checks[f"{name}_audit_ok"] = audit.ok
        mutation_total += audit.checked_mutations
    checks["at_least_one_runtime_mutation_audited"] = mutation_total > 0
    checks["policy_declares_known_sources"] = set(MUTATION_SOURCE_POLICIES) >= {
        "combat_executor.timeline",
        "combat_executor.resources",
        "damage_system",
        "status_system",
        "effect_system",
        "queue_system",
        "combat_executor.queue",
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "checked_transition_count": len(transitions),
        "checked_mutation_count": mutation_total,
        "policy": auditor.policy_matrix(),
        "results": results,
    }


def _source_audit_summary(source_audit: dict[str, Any]) -> dict[str, Any]:
    results = source_audit.get("results", {})
    failures: dict[str, Any] = {}
    if isinstance(results, dict):
        for name, result in results.items():
            if isinstance(result, dict) and not result.get("ok"):
                failures[str(name)] = {
                    "checked_mutations": result.get("checked_mutations"),
                    "failures": result.get("failures", []),
                }
    return {
        "ok": bool(source_audit.get("ok")),
        "checked_transition_count": source_audit.get("checked_transition_count", 0),
        "checked_mutation_count": source_audit.get("checked_mutation_count", 0),
        "policy_sources": sorted(source_audit.get("policy", {}).keys()) if isinstance(source_audit.get("policy"), dict) else [],
        "failed_transition_count": len(failures),
        "failures": failures,
    }


def _matrix_summary_not_written() -> dict[str, Any]:
    return {
        "written": False,
        "reason": "coverage/fidelity matrices are skipped by default; pass --write-matrices for diagnostic output",
    }


def _negative_snapshot_checks(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for name, case in sorted(cases.items()):
        transition = case.get("transition")
        before = case.get("before")
        after = case.get("after")
        unchanged = isinstance(before, BattleState) and isinstance(after, BattleState) and before.snapshot().to_json() == after.snapshot().to_json()
        no_mutations = isinstance(transition, BattleTransition) and not transition.transaction.mutations
        checks[f"{name}_exists"] = isinstance(transition, BattleTransition)
        checks[f"{name}_snapshot_unchanged"] = unchanged
        checks[f"{name}_no_mutations"] = no_mutations
        details[name] = {
            "coverage": transition.coverage if isinstance(transition, BattleTransition) else {},
            "mutation_count": len(transition.transaction.mutations) if isinstance(transition, BattleTransition) else None,
            "replay": case.get("replay"),
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _mutation_source_policy_checks(package_root: Path) -> dict[str, Any]:
    runtime_roots = [package_root / "core", package_root / "systems"]
    entries: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for root in runtime_roots:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(package_root).as_posix()
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "Mutation(" not in line:
                    continue
                block = "\n".join(lines[index : index + 32])
                source_literal = _extract_source_literal(block)
                parameterized = any(
                    marker in block
                    for marker in (
                        "source=source",
                        "source=plan.source",
                        "source=energy_mutation.source",
                        "source=timeline_mutation.source",
                    )
                )
                entry = {
                    "path": relative,
                    "line": index + 1,
                    "source_literal": source_literal,
                    "parameterized_source": parameterized,
                }
                entries.append(entry)
                if source_literal and source_literal not in MUTATION_SOURCE_POLICIES:
                    violations.append({**entry, "reason": "source_literal_missing_policy"})
                if not source_literal and not parameterized:
                    violations.append({**entry, "reason": "mutation_source_not_static_or_parameterized"})
                if parameterized and relative not in {"systems/resource.py", "systems/queue.py", "systems/status.py", "systems/timeline.py"}:
                    violations.append({**entry, "reason": "unexpected_parameterized_source"})
    return {
        "ok": not violations,
        "policy_sources": sorted(MUTATION_SOURCE_POLICIES),
        "mutation_constructor_count": len(entries),
        "entries": entries,
        "violations": violations,
    }


def _extract_source_literal(block: str) -> str:
    marker = 'source="'
    if marker not in block:
        return ""
    start = block.index(marker) + len(marker)
    end = block.find('"', start)
    return block[start:end] if end >= start else ""


def _sample_selection_policy_checks(
    package_root: Path,
    damage_case: dict[str, Any],
    no_fake_damage_case: dict[str, Any],
    status_case: dict[str, Any],
    dynamic_value_case: dict[str, Any],
    effect_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    base = _validation_sample_policy_checks(package_root)
    cases = {
        "damage_executor": damage_case,
        "no_fake_damage": no_fake_damage_case,
        "status_add_modifier": status_case,
        "effect_dynamic_value_store": dynamic_value_case,
        **effect_cases,
    }
    checks: dict[str, bool] = {"legacy_fixed_token_scan_ok": bool(base.get("ok"))}
    details: dict[str, Any] = {"legacy_fixed_token_scan": base}
    allowed_modes = {"structured_predicate", "structured_predicate_or_blocked", "manual_input_binding_smoke"}
    for name, case in sorted(cases.items()):
        selection = case.get("selection", {})
        transition = case.get("transition")
        mode = selection.get("selection_mode") if isinstance(selection, dict) else None
        if transition is None:
            checks[f"{name}_no_transition_allows_missing_selection"] = True
            details[name] = {"selection": selection, "transition": None}
            continue
        checks[f"{name}_selection_mode_allowed"] = mode in allowed_modes
        checks[f"{name}_selection_has_source_trace"] = isinstance(selection, dict) and bool(selection.get("source_trace"))
        details[name] = {"selection": selection}
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _mechanism_trust_matrix(
    source_audit: dict[str, Any],
    negative_snapshot: dict[str, Any],
    damage_case: dict[str, Any],
    no_fake_damage_case: dict[str, Any],
    status_case: dict[str, Any],
    dynamic_value_case: dict[str, Any],
    effect_cases: dict[str, dict[str, Any]],
    fixed_damage_cases: dict[str, Any],
) -> dict[str, Any]:
    audit_ok = bool(source_audit.get("ok"))
    negative_ok = bool(negative_snapshot.get("ok"))
    audited_sources = _audited_sources(source_audit)
    entries = {
        "action_preflight": _trust_entry(negative_ok, negative_ok, TRUSTED, "failed/blocked action snapshot unchanged is covered"),
        "target": _trust_entry(audit_ok, negative_ok, TRUSTED, "explicit/single target and preflight failure are covered; full target policy remains scoped"),
        "resource": _trust_entry("combat_executor.resources" in audited_sources, negative_ok, TRUSTED, "action cost/energy mutations require executable ActionDefinitionIR and ActionEventIR"),
        "timeline": _trust_entry("combat_executor.timeline" in audited_sources, negative_ok, TRUSTED, "action-open mutations require executable ActionDefinitionIR and ActionEventIR"),
        "action_event": _trust_entry(audit_ok, negative_ok, TRUSTED, "runtime transitions use executable ActionEventIR for mutating action paths"),
        "hit_profile": _trust_entry("damage_system" in audited_sources, False, TRUSTED, "damage mutation requires executable HitProfileIR"),
        "damage_emission": _trust_entry(_has_transition(damage_case), bool(no_fake_damage_case.get("transition")), TRUSTED, "damage packets are emitted from executable DamageEmissionIR only"),
        "direct_damage": _trust_entry("damage_system" in audited_sources, False, TRUSTED, "single-hit direct formula is trusted only for current scoped buckets"),
        "true_damage": _trust_entry(False, False, STRUCTURAL, "bypass semantics are regression-tested with unit smoke; executable TBGD emission source is not established yet"),
        "hp_loss": _trust_entry(False, False, STRUCTURAL, "bypass semantics are regression-tested with unit smoke; executable TBGD emission source is not established yet"),
        "status_lifecycle": _trust_entry("status_system" in audited_sources, False, TRUSTED, "Add/Remove lifecycle mutations require executable EffectIR and modifier definition"),
        "add_modifier": _trust_entry(_has_transition(status_case), False, TRUSTED, "real TBGD AddModifier source is audited"),
        "remove_modifier": _trust_entry(_has_transition(effect_cases.get("effect_remove_modifier")), False, TRUSTED, "real TBGD RemoveModifier source is audited"),
        "heal": _effect_trust_entry(effect_cases.get("effect_heal"), "fixed or status-bound HealHP source is audited when present; unsupported formula families remain blocked"),
        "shield": _effect_trust_entry(effect_cases.get("effect_shield"), "fixed or status-bound shield source is audited when present; unsupported formula families remain blocked"),
        "resource_delta": _resource_delta_trust_entry(effect_cases.get("effect_modify_sp")),
        "dynamic_value_store": _trust_entry(_has_transition(dynamic_value_case), False, TRUSTED, "real dynamic value effect writes DynamicValueStore through effect_system"),
        "trigger_window": _trust_entry(_has_trigger_window(damage_case), False, STRUCTURAL, "actor/primary-target local trigger windows are represented; global/per-hit scope remains partial"),
        "ability_task": _trust_entry(_has_transition(damage_case), False, TRUSTED, "phase task graph is present and mutating effects/damage are source-audited"),
        "condition_evaluator": _trust_entry(False, True, STRUCTURAL, "condition evaluator has separate regression coverage; v0_225 does not source-audit condition-only smoke because it does not mutate"),
        "queue": _trust_entry(False, False, BLOCKED, "queue mutation policy exists, but no executable queue mechanism is admitted yet"),
    }
    fixed_checks = _fixed_damage_family_checks(fixed_damage_cases)
    entries["true_damage"]["regression_ok"] = bool(fixed_checks["checks"].get("true_damage_ok"))
    entries["hp_loss"]["regression_ok"] = bool(fixed_checks["checks"].get("hp_loss_ok"))
    return {
        "ok": all(entry["semantic_status"] != NEEDS_FIX for entry in entries.values()),
        "allowed_statuses": [TRUSTED, STRUCTURAL, BLOCKED],
        "entries": entries,
    }


def _effect_trust_entry(case: dict[str, Any] | None, risk: str) -> dict[str, Any]:
    if case is None:
        return _trust_entry(False, False, BLOCKED, "case missing")
    if _has_transition(case):
        return _trust_entry(True, False, TRUSTED, risk)
    return _trust_entry(False, False, BLOCKED, risk)


def _resource_delta_trust_entry(case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return _trust_entry(False, False, BLOCKED, "ModifySPNew case missing")
    selection = case.get("selection", {})
    selection_mode = selection.get("selection_mode") if isinstance(selection, dict) else ""
    if _has_transition(case) and selection_mode == "structured_predicate":
        return _trust_entry(
            True,
            False,
            TRUSTED,
            "ModifySPNew fixed skill point delta is selected from real executable TBGD EffectIR; ratio/max/set SP operations remain blocked",
        )
    if _has_transition(case):
        return _trust_entry(
            True,
            False,
            STRUCTURAL,
            "ModifySPNew executable path still depends on manual dynamic binding; fixed source was not found",
        )
    return _trust_entry(False, False, BLOCKED, "No executable ModifySPNew effect transition")


def _trust_entry(
    source_audit_covered: bool,
    negative_case_covered: bool,
    semantic_status: str,
    remaining_risk: str,
) -> dict[str, Any]:
    blocking_issue = ""
    if semantic_status == TRUSTED and not source_audit_covered:
        semantic_status = NEEDS_FIX
        blocking_issue = "trusted item lacks source audit coverage"
    return {
        "source_audit_covered": source_audit_covered,
        "negative_case_covered": negative_case_covered,
        "semantic_status": semantic_status,
        "remaining_risk": remaining_risk,
        "blocking_issue": blocking_issue,
    }


def _trust_matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    entries = matrix.get("entries", {})
    needs_fix = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict) and entry.get("semantic_status") == NEEDS_FIX
    }
    invalid = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict) and entry.get("semantic_status") not in {TRUSTED, STRUCTURAL, BLOCKED}
    }
    return {
        "ok": not needs_fix and not invalid,
        "needs_fix": needs_fix,
        "invalid": invalid,
        "entry_count": len(entries),
    }


def _audited_sources(source_audit: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    results = source_audit.get("results", {})
    if not isinstance(results, dict):
        return sources
    for result in results.values():
        if not isinstance(result, dict):
            continue
        for trace in result.get("traces", []):
            if isinstance(trace, dict):
                mutation = trace.get("mutation", {})
                if isinstance(mutation, dict) and isinstance(mutation.get("source"), str):
                    sources.add(mutation["source"])
    return sources


def _has_transition(case: dict[str, Any] | None) -> bool:
    return isinstance(case, dict) and isinstance(case.get("transition"), BattleTransition)


def _has_trigger_window(case: dict[str, Any]) -> bool:
    transition = case.get("transition")
    return isinstance(transition, BattleTransition) and bool(transition.transaction.trigger_windows)


def _with_replay(case: dict[str, Any]) -> dict[str, Any]:
    transition = case.get("transition")
    before = case.get("before") or case.get("before_state")
    after = case.get("after")
    if isinstance(transition, BattleTransition) and isinstance(before, BattleState):
        if not isinstance(after, BattleState):
            after = _state_from_transition_after(before, transition)
            case["after"] = after
        replay = MutationReducer().replay_snapshot(before, transition.transaction.mutations, transition.after.to_json())
        case["replay"] = {"ok": replay.ok, "errors": list(replay.errors)}
        case.setdefault("before", before)
    return case


def _state_from_transition_after(before: BattleState, transition: BattleTransition) -> BattleState:
    return MutationReducer().apply_all(before, transition.transaction.mutations)


def _negative_cases_json(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {name: _case_json(case) for name, case in sorted(cases.items())}


def _write_transition_samples(output_dir: Path, transitions: dict[str, BattleTransition]) -> None:
    for name, transition in sorted(transitions.items()):
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name)
        write_json(output_dir / f"sample_{safe}_transition_v0_225.json", transition.to_json())


if __name__ == "__main__":
    raise SystemExit(main())
