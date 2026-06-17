from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.action_plan import build_action_execution_plan
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, CanonicalIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.damage import DamagePacket, DamageSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_213 import (
    _damage_semantics_regression_checks,
    _formula_test_state,
    _status_ledger_transition,
    _status_modifier_ledger_regression_checks,
)


VALIDATION_VERSION = "v0_218"
TARGET_MODES = ("single", "aoe", "blast", "bounce", "unknown")


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
        write_json(output_dir / "canonical_ir_v0_218.json", ir.to_json())
    write_json(output_dir / "canonical_ir_summary_v0_218.json", _canonical_ir_summary(ir))
    write_json(output_dir / "coverage_matrix_v0_218.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_218.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    base_state = _multi_enemy_state(build_result.state)
    base_command = replace(
        build_result.commands[0],
        target_ids=("enemy:target",),
        metadata={**build_result.commands[0].metadata, "crit_mode": "noncrit", "reset_actor_av": False},
    )

    definitions = {mode: _select_definition(ir, mode) for mode in TARGET_MODES}
    execution_cases = {
        mode: _execute_mode_case(rules, base_state, base_command, definition, mode)
        for mode, definition in definitions.items()
    }
    plan_cases = {
        mode: build_action_execution_plan(
            definition,
            rules.require_action_event(definition.action_id, definition.level),
            rules.hit_profiles_for_action(definition.action_id, definition.level),
            requested_target_ids=("enemy:target",),
            resolved_target_groups={},
            source_trace=definition.source.to_json(),
        ).to_json()
        for mode, definition in definitions.items()
        if definition is not None
    }

    formula_state = _formula_test_state(build_result.state)
    status_ledger_transition = _status_ledger_transition(ir, rules, formula_state, _with_crit_mode(build_result.commands[0], "crit"))
    fixed_damage_cases = _fixed_damage_family_cases(formula_state, build_result.commands[0])

    snapshot_result = SnapshotCompletenessValidator().validate(base_state.snapshot())
    checks = {
        "definition_selection": _definition_selection_checks(definitions),
        "action_execution_plan": _execution_plan_checks(execution_cases, plan_cases),
        "target_modes": _target_mode_checks(execution_cases),
        "multi_target_damage": _multi_target_damage_checks(execution_cases),
        "blocked_modes": _blocked_mode_checks(execution_cases, plan_cases),
        "transition_quality": _transition_quality_checks(execution_cases),
        "status_modifier_ledger_regression": _status_modifier_ledger_regression_checks(status_ledger_transition),
        "damage_semantics_regression": _damage_semantics_regression_checks(status_ledger_transition),
        "fixed_damage_families": _fixed_damage_family_checks(fixed_damage_cases),
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
                *(item["ok"] for item in checks.values()),
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_effects": len(ir.effects),
                "sampled": ir.metadata.get("sampled", {}),
            },
        },
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "identity": identity_result.to_json(),
            "base_command": {
                "actor_id": base_command.actor_id,
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": snapshot_result.to_json(),
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_218.json", result)
    write_json(output_dir / "sample_action_execution_plans_v0_218.json", plan_cases)
    for mode, case in execution_cases.items():
        write_json(output_dir / f"sample_{mode}_target_case_v0_218.json", _case_json(case))
        transition = case.get("transition")
        if transition is not None:
            write_json(output_dir / f"sample_{mode}_transition_v0_218.json", transition.to_json())
    if status_ledger_transition is not None:
        write_json(output_dir / "sample_status_ledger_transition_v0_218.json", status_ledger_transition.to_json())
    write_json(output_dir / "sample_fixed_damage_families_v0_218.json", _damage_case_json(fixed_damage_cases))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 ActionExecutionPlan and target/hit plan skeleton.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_218"))
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


def _canonical_ir_summary(ir: CanonicalIR) -> dict[str, object]:
    target_mode_counts: dict[str, int] = {}
    for definition in ir.action_definitions:
        target_mode_counts[definition.target_mode] = target_mode_counts.get(definition.target_mode, 0) + 1
    return {
        "version": ir.version,
        "metadata": ir.metadata,
        "counts": {
            "entities": len(ir.entities),
            "action_definitions": len(ir.action_definitions),
            "action_events": len(ir.action_events),
            "hit_profiles": len(ir.hit_profiles),
            "triggers": len(ir.triggers),
            "effects": len(ir.effects),
            "conditions": len(ir.conditions),
            "formulas": len(ir.formulas),
        },
        "target_mode_counts": dict(sorted(target_mode_counts.items())),
    }


def _select_definition(ir: CanonicalIR, target_mode: str) -> ActionDefinitionIR | None:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.source.source_path, item.action_id, item.level)):
        if definition.target_mode != target_mode:
            continue
        if target_mode == "unknown":
            return definition
        if definition.damage_kind != "hp_damage":
            continue
        if definition.damage_formula_family != "direct":
            continue
        if not definition.param_list:
            continue
        if not ir.hit_profiles:
            continue
        return definition
    return None


def _execute_mode_case(
    rules: RuleBook,
    state: BattleState,
    base_command: ActionCommand,
    definition: ActionDefinitionIR | None,
    mode: str,
) -> dict[str, Any]:
    if definition is None:
        return {"definition": None, "transition": None, "after": None, "error": f"missing {mode} definition"}
    target_ids = () if mode == "aoe" else ("enemy:target",)
    if mode == "unknown":
        target_ids = ("enemy:target",)
    command = replace(
        base_command,
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=target_ids,
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, after.snapshot().to_json())
    return {
        "definition": definition,
        "before": state,
        "command": command,
        "transition": transition,
        "after": after,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "selection": {
            "selection_mode": "structured_predicate",
            "target_mode": mode,
            "damage_kind": definition.damage_kind,
            "damage_formula_family": definition.damage_formula_family,
            "source_trace": definition.source.to_json(),
        },
    }


def _multi_enemy_state(state: BattleState) -> BattleState:
    actor = state.units["ally:saber"]
    primary = state.units["enemy:target"]
    units = dict(state.units)
    units[actor.unit_id] = replace(actor, flags={**actor.flags, "position": 1})
    units[primary.unit_id] = replace(primary, flags={**primary.flags, "position": 2})
    for unit_id, position in (("enemy:left", 1), ("enemy:right", 3)):
        units[unit_id] = UnitState(
            unit_id=unit_id,
            side="enemy",
            template_id=primary.template_id,
            level=primary.level,
            max_hp=primary.max_hp,
            hp=primary.hp,
            attack=primary.attack,
            defense=primary.defense,
            speed=primary.speed,
            energy=primary.energy,
            max_energy=primary.max_energy,
            toughness=primary.toughness,
            max_toughness=primary.max_toughness,
            action_value=primary.action_value,
            flags={**primary.flags, "position": position},
            resources=dict(primary.resources),
        )
    return replace(state, units=units, skill_points=state.max_skill_points)


def _definition_selection_checks(definitions: dict[str, ActionDefinitionIR | None]) -> dict[str, object]:
    checks = {f"{mode}_definition_selected": definitions.get(mode) is not None for mode in TARGET_MODES}
    checks.update(
        {
            f"{mode}_source_is_action_definition": isinstance(definitions.get(mode), ActionDefinitionIR)
            and bool(definitions[mode].source.source_path)
            for mode in TARGET_MODES
        }
    )
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "definitions": {
            mode: definition.to_json() if definition is not None else None
            for mode, definition in definitions.items()
        },
    }


def _execution_plan_checks(cases: dict[str, dict[str, Any]], plans: dict[str, dict[str, Any]]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    for mode, case in cases.items():
        transition = case.get("transition")
        records = _records_of_type(transition, "action_execution_plan")
        checks[f"{mode}_transition_has_action_execution_plan_record"] = bool(records)
        checks[f"{mode}_coverage_has_action_execution_plan"] = bool(
            transition is not None and isinstance(transition.coverage.get("action_execution_plan"), dict)
        )
        if mode in plans:
            checks[f"{mode}_plan_marks_derived"] = plans[mode].get("derived_from_action_definition") is True
    return {"ok": all(checks.values()), "checks": checks, "plans": plans}


def _target_mode_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    details: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for mode in ("single", "aoe", "blast"):
        transition = cases[mode].get("transition")
        metadata = transition.target_resolution.metadata if transition is not None else {}
        groups = metadata.get("target_groups", {}) if isinstance(metadata, dict) else {}
        checks[f"{mode}_target_groups_present"] = isinstance(groups, dict) and bool(groups)
        details[mode] = transition.target_resolution.to_json() if transition is not None else None
    checks["single_selects_one"] = len(cases["single"]["transition"].target_resolution.selected) == 1
    checks["aoe_selects_all_enemies"] = len(cases["aoe"]["transition"].target_resolution.selected) >= 3
    blast_groups = cases["blast"]["transition"].target_resolution.metadata.get("target_groups", {})
    checks["blast_has_primary"] = bool(blast_groups.get("primary"))
    checks["blast_has_adjacent"] = len(blast_groups.get("adjacent", [])) >= 2
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _multi_target_damage_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    checks = {
        "aoe_multiple_damage_mutations": _damage_mutation_count(cases["aoe"].get("transition")) >= 3,
        "blast_multiple_damage_mutations": _damage_mutation_count(cases["blast"].get("transition")) >= 3,
        "aoe_damage_records_traceable": len(_records_of_type(cases["aoe"].get("transition"), "damage")) >= 3,
        "blast_damage_records_traceable": len(_records_of_type(cases["blast"].get("transition"), "damage")) >= 3,
        "damage_metadata_has_hit_index": _damage_records_have_metadata(cases["blast"].get("transition"), "hit_index"),
        "damage_metadata_has_multiplier_source": _damage_records_have_metadata(cases["blast"].get("transition"), "multiplier_source"),
        "damage_metadata_marks_multi_hit_pending": _damage_records_have_metadata(cases["blast"].get("transition"), "multi_hit_not_implemented"),
        "aoe_metadata_marks_target_group_multiplier_pending": _damage_records_have_metadata_value(
            cases["aoe"].get("transition"),
            "target_group_multiplier_not_implemented",
            True,
        ),
        "blast_metadata_marks_target_group_multiplier_pending": _damage_records_have_metadata_value(
            cases["blast"].get("transition"),
            "target_group_multiplier_not_implemented",
            True,
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _blocked_mode_checks(cases: dict[str, dict[str, Any]], plans: dict[str, dict[str, Any]]) -> dict[str, object]:
    bounce_transition = cases["bounce"].get("transition")
    checks = {
        "bounce_has_blocked_reason": _plan_blocked_reason(bounce_transition) == "bounce_not_executable",
        "bounce_action_disabled": bounce_transition is not None and bounce_transition.coverage.get("action_enabled") is False,
        "bounce_has_no_mutations": _mutation_count(bounce_transition) == 0,
        "bounce_has_no_trigger_windows": bounce_transition is not None and not bounce_transition.transaction.trigger_windows,
        "bounce_has_no_damage_mutation": _damage_mutation_count(bounce_transition) == 0,
        "bounce_records_blocked": bool(_records_of_type(bounce_transition, "damage_blocked")),
        "unknown_plan_has_blocked_reason": plans.get("unknown", {}).get("target_plan", {}).get("blocked_reason")
        == "unknown_target_mode_not_executable",
        "unknown_action_disabled": cases["unknown"].get("transition") is not None
        and cases["unknown"]["transition"].coverage.get("action_enabled") is False,
        "unknown_has_no_mutations": _mutation_count(cases["unknown"].get("transition")) == 0,
        "unknown_has_no_trigger_windows": cases["unknown"].get("transition") is not None
        and not cases["unknown"]["transition"].transaction.trigger_windows,
        "unknown_has_no_damage_plan": not plans.get("unknown", {}).get("damage_plan"),
        "unknown_snapshot_unchanged": _case_snapshot_unchanged(cases["unknown"]),
        "bounce_snapshot_unchanged": _case_snapshot_unchanged(cases["bounce"]),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _transition_quality_checks(cases: dict[str, dict[str, Any]]) -> dict[str, object]:
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for mode, case in cases.items():
        transition = case.get("transition")
        if transition is None:
            checks[f"{mode}_transition_exists"] = False
            continue
        contract = transition_validator.validate(transition)
        traceability = settlement_validator.validate(transition.transaction.settlement, transition.transaction.mutations)
        replay_ok = bool(case.get("replay", {}).get("ok"))
        checks[f"{mode}_contract_ok"] = contract.ok
        checks[f"{mode}_traceability_ok"] = traceability.ok
        checks[f"{mode}_replay_ok"] = replay_ok
        details[mode] = {
            "contract": contract.to_json(),
            "traceability": traceability.to_json(),
            "replay": case.get("replay"),
        }
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _fixed_damage_family_cases(state: BattleState, command: ActionCommand) -> dict[str, Any]:
    target_id = command.target_ids[0] if command.target_ids else command.actor_id
    true_result = DamageSystem().apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=target_id,
            attack_type="true_damage_validation",
            damage_formula_family="true_damage",
            amount=100.0,
            source_trace={"validation": VALIDATION_VERSION},
        ),
    )
    hp_loss_result = DamageSystem().apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=target_id,
            attack_type="hp_loss_validation",
            damage_formula_family="hp_loss",
            amount=50.0,
            source_trace={"validation": VALIDATION_VERSION},
        ),
    )
    return {"true_damage": true_result, "hp_loss": hp_loss_result}


def _fixed_damage_family_checks(cases: dict[str, Any]) -> dict[str, object]:
    details: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, result in cases.items():
        records = list(result.records)
        payloads = [record.get("payload", {}) for record in records if isinstance(record, dict)]
        checks[f"{name}_ok"] = result.ok
        checks[f"{name}_bypasses_normal_multipliers"] = any(
            payload.get("bypasses_normal_multipliers") is True for payload in payloads if isinstance(payload, dict)
        )
        checks[f"{name}_no_normal_multiplier_terms"] = all(
            payload.get("normal_multiplier_terms") == [] for payload in payloads if isinstance(payload, dict)
        )
        details[name] = result.to_json()
    return {"ok": all(checks.values()), "checks": checks, "details": details}


def _records_of_type(transition, record_type: str) -> list[dict[str, Any]]:
    if transition is None or transition.transaction.settlement is None:
        return []
    return [
        record
        for record in transition.transaction.settlement.records
        if isinstance(record, dict) and record.get("record_type") == record_type
    ]


def _damage_mutation_count(transition) -> int:
    if transition is None:
        return 0
    return sum(1 for mutation in transition.transaction.mutations if mutation.source == "damage_system")


def _mutation_count(transition) -> int:
    return 0 if transition is None else len(transition.transaction.mutations)


def _case_snapshot_unchanged(case: dict[str, Any]) -> bool:
    before = case.get("before")
    after = case.get("after")
    if not isinstance(before, BattleState) or not isinstance(after, BattleState):
        return False
    return before.snapshot().to_json() == after.snapshot().to_json()


def _damage_records_have_metadata(transition, key: str) -> bool:
    records = _records_of_type(transition, "damage")
    if not records:
        return False
    for record in records:
        payload = record.get("payload", {})
        metadata = payload.get("packet_metadata", {}) if isinstance(payload, dict) else {}
        if not isinstance(metadata, dict) or key not in metadata:
            return False
    return True


def _damage_records_have_metadata_value(transition, key: str, expected: object) -> bool:
    records = _records_of_type(transition, "damage")
    if not records:
        return False
    for record in records:
        payload = record.get("payload", {})
        metadata = payload.get("packet_metadata", {}) if isinstance(payload, dict) else {}
        if not isinstance(metadata, dict) or metadata.get(key) != expected:
            return False
    return True


def _plan_blocked_reason(transition) -> str:
    if transition is None:
        return ""
    plan = transition.coverage.get("action_execution_plan", {})
    if not isinstance(plan, dict):
        return ""
    target_plan = plan.get("target_plan", {})
    if not isinstance(target_plan, dict):
        return ""
    return str(target_plan.get("blocked_reason") or "")


def _with_crit_mode(command: ActionCommand, crit_mode: str) -> ActionCommand:
    return replace(command, metadata={**command.metadata, "crit_mode": crit_mode})


def _case_json(case: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in case.items():
        if isinstance(value, BattleState):
            encoded[key] = {"snapshot": value.snapshot().to_json()}
        elif isinstance(value, ActionDefinitionIR):
            encoded[key] = value.to_json()
        elif isinstance(value, ActionCommand):
            encoded[key] = {
                "actor_id": value.actor_id,
                "action_id": value.action_id,
                "action_level": value.action_level,
                "target_ids": list(value.target_ids),
                "metadata": value.metadata,
            }
        elif hasattr(value, "to_json"):
            encoded[key] = value.to_json()
        else:
            encoded[key] = value
    return encoded


def _damage_case_json(cases: dict[str, Any]) -> dict[str, Any]:
    return {name: result.to_json() for name, result in cases.items()}


if __name__ == "__main__":
    raise SystemExit(main())
