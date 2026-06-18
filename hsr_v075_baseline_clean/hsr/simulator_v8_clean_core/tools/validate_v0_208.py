from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.fidelity import build_fidelity_matrix
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.snapshot_contract import SnapshotCompletenessValidator
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.target import TargetPolicy, TargetSystem
from ..tbgd.coverage import build_coverage_matrix
from ..tbgd.discovery import TBGDDiscovery
from ..tbgd.lowering import LoweringLimits, TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_209 import _damage_emission_command


VALIDATION_VERSION = "v0_208"


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = 120,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    write_json(output_dir / "canonical_ir_v0_208.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_208.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_208.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    command = _damage_emission_command(ir, rules, build_result.commands[0])

    executor = CombatExecutor(rules)
    after_state, transition = executor.execute(command, build_result.state)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    snapshot_result = snapshot_validator.validate(build_result.state.snapshot())
    transition_contract = transition_validator.validate(transition)
    traceability = settlement_validator.validate(transition.transaction.settlement, transition.transaction.mutations)
    replay = reducer.replay_snapshot(
        build_result.state,
        transition.transaction.mutations,
        after_state.snapshot().to_json(),
    )

    checks = {
        "full_key_tables": _full_key_table_checks(coverage.to_json()),
        "damage_taxonomy": _damage_taxonomy_checks(ir),
        "matrix": _matrix_checks(coverage.to_json(), fidelity.to_json()),
        "target_policy": _target_policy_checks(build_result.state),
        "executor_damage": _executor_damage_checks(build_result.state, after_state, transition),
        "fixed_damage_families": _fixed_damage_family_checks(build_result.state, command),
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
                transition_contract.ok,
                traceability.ok,
                replay.ok,
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
                "ir_formulas": len(ir.formulas),
                "sampled": ir.metadata.get("sampled", {}),
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
        "transition_contract": transition_contract.to_json(),
        "settlement_traceability": traceability.to_json(),
        "replay": {
            "ok": replay.ok,
            "errors": list(replay.errors),
            "mutation_count": len(transition.transaction.mutations),
        },
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_208.json", result)
    write_json(output_dir / "sample_executor_transition_v0_208.json", transition.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 foundation corrections.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_208"))
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


def _full_key_table_checks(coverage_json: dict[str, Any]) -> dict[str, object]:
    table_status = coverage_json.get("table_status", {})
    required = {
        "ExcelOutput/AvatarSkillConfig.json": 6657,
        "ExcelOutput/MonsterConfig.json": 2509,
        "ExcelOutput/MonsterTemplateConfig.json": 577,
        "action_definitions:ExcelOutput/AvatarSkillConfig.json": 6657,
    }
    checks = {}
    for table, min_raw_count in required.items():
        status = table_status.get(table, {}) if isinstance(table_status, dict) else {}
        checks[f"{table}:raw_count"] = int(status.get("raw_count", 0)) >= min_raw_count
        checks[f"{table}:not_sampled"] = status.get("skipped_count") == 0 and not bool(status.get("sampled"))
    return {"ok": all(checks.values()), "checks": checks}


def _damage_taxonomy_checks(ir: CanonicalIR) -> dict[str, object]:
    elation_actions = [definition for definition in ir.action_definitions if definition.attack_type == "ElationDamage"]
    true_actions = [definition for definition in ir.action_definitions if definition.attack_type == "TrueDamage"]
    follow_up_defaults = [
        definition for definition in ir.action_definitions if definition.damage_formula_family == "follow_up"
    ]
    executable_unknown = [
        definition
        for definition in ir.action_definitions
        if definition.damage_formula_family == "unknown" and definition.coverage_status == "executable"
    ]
    checks = {
        "elation_actions_present": len(elation_actions) >= 100,
        "elation_actions_classified": bool(elation_actions)
        and all(definition.damage_formula_family == "elation" for definition in elation_actions),
        "true_damage_actions_classified": all(
            definition.damage_formula_family == "true_damage" for definition in true_actions
        ),
        "no_follow_up_family": not follow_up_defaults,
        "unknown_family_not_executable": not executable_unknown,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "counts": {
            "elation_actions": len(elation_actions),
            "true_damage_actions": len(true_actions),
            "follow_up_family": len(follow_up_defaults),
            "executable_unknown_family": len(executable_unknown),
        },
        "sample_elation_definition": elation_actions[0].to_json() if elation_actions else None,
    }


def _matrix_checks(coverage_json: dict[str, Any], fidelity_json: dict[str, Any]) -> dict[str, object]:
    coverage_formula = coverage_json.get("formula_status", {})
    fidelity_formula = fidelity_json.get("formula_status", {})
    checks = {
        "coverage_elation": _formula_lowered(coverage_formula, "elation_damage"),
        "coverage_true_damage": _formula_lowered(coverage_formula, "true_damage"),
        "coverage_hp_loss": _formula_lowered(coverage_formula, "hp_loss"),
        "fidelity_elation": _formula_lowered(fidelity_formula, "elation_damage"),
        "fidelity_true_damage": _formula_lowered(fidelity_formula, "true_damage"),
        "fidelity_hp_loss": _formula_lowered(fidelity_formula, "hp_loss"),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _target_policy_checks(state) -> dict[str, object]:
    actor = state.units["ally:saber"]
    friend = replace(actor, unit_id="ally:friend")
    policy_state = replace(state, units={**state.units, "ally:friend": friend})
    target_system = TargetSystem()
    default_result = target_system.resolve_explicit_targets(policy_state, "ally:saber", ("ally:friend",))
    ally_policy_result = target_system.resolve_explicit_targets(
        policy_state,
        "ally:saber",
        ("ally:friend",),
        policy=TargetPolicy(policy_id="ally_support", allow_enemy=False, allow_ally=True, allow_self=True),
    )
    checks = {
        "default_rejects_ally_for_damage": not default_result.ok and "ally:friend" in default_result.resolution.rejected,
        "ally_policy_accepts_ally": ally_policy_result.ok and ally_policy_result.resolution.selected == ("ally:friend",),
        "rejection_is_policy_based": any("policy_rejected" in error for error in default_result.errors),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "default_resolution": default_result.resolution.to_json(),
        "ally_policy_resolution": ally_policy_result.resolution.to_json(),
    }


def _executor_damage_checks(before_state, after_state, transition) -> dict[str, object]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    damage_records = [record for record in records if record.get("record_type") == "damage"]
    damage_mutations = [mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"]
    checks = {
        "has_damage_mutation": bool(damage_mutations),
        "has_linked_damage_record": bool(damage_records) and all(record.get("mutation_id") for record in damage_records),
        "target_hp_changed": after_state.units["enemy:target"].hp < before_state.units["enemy:target"].hp,
        "coverage_reports_damage": transition.coverage.get("damage_mutation_count", 0) > 0
        and transition.coverage.get("damage_formula_family") == "direct",
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "damage_mutations": [mutation.to_json() for mutation in damage_mutations],
        "damage_records": damage_records,
        "coverage": transition.coverage,
    }


def _fixed_damage_family_checks(state, command) -> dict[str, object]:
    damage_system = DamageSystem()
    true_result = damage_system.apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=command.target_ids[0],
            amount=37.0,
            attack_type="TrueDamage",
            damage_formula_family="true_damage",
            source_trace={"validation": "v0_208_true_damage"},
        ),
    )
    hp_loss_result = damage_system.apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=command.target_ids[0],
            amount=29.0,
            attack_type="DirectlyLoseHp",
            damage_formula_family="hp_loss",
            source_trace={"validation": "v0_208_hp_loss"},
        ),
    )
    true_record = true_result.records[0] if true_result.records else {}
    hp_loss_record = hp_loss_result.records[0] if hp_loss_result.records else {}
    checks = {
        "true_damage_record_type": true_record.get("record_type") == "damage",
        "true_damage_bypasses": _bypasses_without_terms(true_record),
        "hp_loss_record_type": hp_loss_record.get("record_type") == "hp_loss",
        "hp_loss_bypasses": _bypasses_without_terms(hp_loss_record),
        "both_mutate_hp": bool(true_result.mutations) and bool(hp_loss_result.mutations),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "true_damage": true_result.to_json(),
        "hp_loss": hp_loss_result.to_json(),
    }


def _formula_lowered(formula_status: object, key: str) -> bool:
    if not isinstance(formula_status, dict):
        return False
    item = formula_status.get(key, {})
    return isinstance(item, dict) and int(item.get("lowered", 0)) > 0 and bool(item.get("reason"))


def _bypasses_without_terms(record: dict[str, Any]) -> bool:
    payload = record.get("payload", {})
    return (
        isinstance(payload, dict)
        and payload.get("bypasses_normal_multipliers") is True
        and payload.get("normal_multiplier_terms") == []
    )


if __name__ == "__main__":
    raise SystemExit(main())
