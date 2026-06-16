from __future__ import annotations

import argparse
from pathlib import Path

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.model import ActionSettlement, ActionTransaction, BattleTransition, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
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


VALIDATION_VERSION = "v0_207"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int = 120,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    write_json(output_dir / "canonical_ir_v0_207.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_207.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_207.json", fidelity.to_json())

    loader = ScenarioLoader()
    scenario = loader.load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    command = build_result.commands[0]
    action_definition = rules.require_action_definition(command.action_id, command.action_level)

    executor = CombatExecutor(rules)
    after_prelude_state, prelude_transition = executor.execute(command, build_result.state)
    reducer = MutationReducer()
    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    prelude_replay = reducer.replay_snapshot(
        build_result.state,
        prelude_transition.transaction.mutations,
        after_prelude_state.snapshot().to_json(),
    )
    prelude_contract = transition_validator.validate(prelude_transition)

    damage_transition, damage_after_state = _direct_damage_transition(
        rules,
        build_result.state,
        command,
    )
    damage_snapshot = snapshot_validator.validate(build_result.state.snapshot())
    damage_contract = transition_validator.validate(damage_transition)
    damage_replay = reducer.replay_snapshot(
        build_result.state,
        damage_transition.transaction.mutations,
        damage_after_state.snapshot().to_json(),
    )
    damage_traceability = settlement_validator.validate(
        damage_transition.transaction.settlement,
        damage_transition.transaction.mutations,
    )

    taxonomy_checks = _taxonomy_checks(action_definition, damage_transition)
    damage_system_checks = _damage_system_checks(rules, build_result.state, command)
    matrix_checks = _matrix_checks(coverage.to_json(), fidelity.to_json())
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                prelude_contract.ok,
                prelude_replay.ok,
                damage_snapshot.ok,
                damage_contract.ok,
                damage_replay.ok,
                damage_traceability.ok,
                taxonomy_checks["ok"],
                damage_system_checks["ok"],
                matrix_checks["ok"],
            )
        ),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "scenario_path": scenario_path.as_posix(),
            "summary": {
                "discovery_files": len(discovery.files),
                "ir_entities": len(ir.entities),
                "ir_action_definitions": len(ir.action_definitions),
                "ir_formulas": len(ir.formulas),
                "coverage_formula_status": sorted(coverage.to_json()["formula_status"].keys()),
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
        "prelude_contract": prelude_contract.to_json(),
        "prelude_replay": {
            "ok": prelude_replay.ok,
            "errors": list(prelude_replay.errors),
        },
        "taxonomy": taxonomy_checks,
        "damage_system": damage_system_checks,
        "damage_transition": {
            "snapshot_completeness": damage_snapshot.to_json(),
            "transition_contract": damage_contract.to_json(),
            "settlement_traceability": damage_traceability.to_json(),
            "replay": {
                "ok": damage_replay.ok,
                "errors": list(damage_replay.errors),
                "mutation_count": len(damage_transition.transaction.mutations),
            },
        },
        "matrix_checks": matrix_checks,
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_207.json", result)
    write_json(output_dir / "sample_damage_transition_v0_207.json", damage_transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 damage taxonomy and mainline damage skeleton.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_207"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=120)
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
    )
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _direct_damage_transition(rules: RuleBook, state, command) -> tuple[BattleTransition, object]:
    action_definition = rules.require_action_definition(command.action_id, command.action_level)
    source_trace = rules.action_definition_source_trace(command.action_id, command.action_level) or {}
    packet = DamagePacket(
        attacker_id=command.actor_id,
        target_id=command.target_ids[0],
        amount=123.0,
        attack_type="follow_up",
        damage_formula_family="direct",
        element_type=action_definition.element_type,
        source_trace=source_trace,
        metadata={"validation": "v0_207_follow_up_attack_type_direct_damage"},
    )
    damage_result = DamageSystem().apply_packet(state, packet)
    after_state = MutationReducer().apply_all(state, damage_result.mutations)
    settlement = ActionSettlement(
        action_id=command.action_id,
        actor_id=command.actor_id,
        target_ids=command.target_ids,
        records=damage_result.records,
    )
    transition = BattleTransition(
        transaction=ActionTransaction(
            command=command,
            before=state.snapshot(),
            events=damage_result.events,
            mutations=damage_result.mutations,
            settlement=settlement,
        ),
        after=after_state.snapshot(),
        target_resolution=TargetResolution(
            requested=command.target_ids,
            legal=command.target_ids,
            selected=command.target_ids,
            reason="validation_damage_target",
            metadata={"validation": "v0_207"},
        ),
        rng_events=(),
        coverage={
            "executor": "v0_207_damage_taxonomy",
            "damage_formula_family": packet.damage_formula_family,
            "attack_type": packet.attack_type,
            "element_type": packet.element_type,
            "damage_ok": damage_result.ok,
        },
    )
    return transition, after_state


def _taxonomy_checks(action_definition, damage_transition: BattleTransition) -> dict[str, object]:
    records = damage_transition.transaction.settlement.records if damage_transition.transaction.settlement else ()
    damage_records = [record for record in records if record.get("record_type") == "damage"]
    mutation_metadata = (
        damage_transition.transaction.mutations[0].metadata if damage_transition.transaction.mutations else {}
    )
    checks = {
        "action_definition_has_attack_type_axis": action_definition.attack_type == "Normal",
        "action_definition_has_damage_family_axis": action_definition.damage_formula_family == "direct",
        "action_definition_has_element_axis": action_definition.element_type == "Wind",
        "action_definition_source_mode_mainline": action_definition.source_mode == "mainline",
        "follow_up_attack_type_allowed": mutation_metadata.get("attack_type") == "follow_up",
        "follow_up_not_damage_family": mutation_metadata.get("damage_formula_family") == "direct",
        "damage_record_linked": bool(damage_records) and all(record.get("mutation_id") for record in damage_records),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "action_definition": action_definition.to_json(),
        "damage_record_count": len(damage_records),
    }


def _damage_system_checks(rules: RuleBook, state, command) -> dict[str, object]:
    source_trace = rules.action_definition_source_trace(command.action_id, command.action_level) or {}
    invalid_follow_up_family = False
    invalid_follow_up_error = ""
    try:
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=command.target_ids[0],
            amount=1.0,
            attack_type="Normal",
            damage_formula_family="follow_up",
        )
    except ValueError as exc:
        invalid_follow_up_family = True
        invalid_follow_up_error = str(exc)

    elation_packet = DamagePacket(
        attacker_id=command.actor_id,
        target_id=command.target_ids[0],
        amount=1.0,
        attack_type="Normal",
        damage_formula_family="elation",
        source_trace=source_trace,
    )
    elation_result = DamageSystem().apply_packet(state, elation_packet)
    elation_records = [record for record in elation_result.records if record.get("record_type") == "damage_blocked"]
    checks = {
        "invalid_follow_up_family_rejected": invalid_follow_up_family,
        "invalid_follow_up_error_clear": "attack type" in invalid_follow_up_error,
        "elation_blocked_without_mutation": not elation_result.ok and not elation_result.mutations,
        "elation_blocked_process_only_record": bool(elation_records)
        and all(record.get("process_only") for record in elation_records),
        "elation_reason_not_simulated_universe": "mainline 4.0" in "".join(elation_result.errors),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "invalid_follow_up_error": invalid_follow_up_error,
        "elation_result": elation_result.to_json(),
    }


def _matrix_checks(coverage_json: dict[str, object], fidelity_json: dict[str, object]) -> dict[str, object]:
    coverage_formula = coverage_json.get("formula_status", {})
    fidelity_formula = fidelity_json.get("formula_status", {})
    coverage_elation = coverage_formula.get("elation_damage", {}) if isinstance(coverage_formula, dict) else {}
    fidelity_elation = fidelity_formula.get("elation_damage", {}) if isinstance(fidelity_formula, dict) else {}
    coverage_properties = coverage_elation.get("properties", []) if isinstance(coverage_elation, dict) else []
    fidelity_properties = fidelity_elation.get("properties", []) if isinstance(fidelity_elation, dict) else []
    checks = {
        "coverage_has_elation_damage": "ElationDamageAddedRatio" in coverage_properties,
        "coverage_elation_blocked": coverage_elation.get("fidelity_status") == "blocked",
        "coverage_elation_reason": bool(coverage_elation.get("reason")),
        "fidelity_has_elation_damage": "ElationDamageAddedRatio" in fidelity_properties,
        "fidelity_elation_blocked": fidelity_elation.get("fidelity_status") == "blocked",
        "fidelity_elation_reason": bool(fidelity_elation.get("reason")),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "coverage_elation_damage": coverage_elation,
        "fidelity_elation_damage": fidelity_elation,
    }


if __name__ == "__main__":
    raise SystemExit(main())
