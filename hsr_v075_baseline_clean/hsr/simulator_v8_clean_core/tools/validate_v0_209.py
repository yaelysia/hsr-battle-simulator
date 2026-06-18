from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
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


VALIDATION_VERSION = "v0_209"
DIRECT_BUCKETS = {
    "crit",
    "damage_bonus",
    "defense",
    "resistance",
    "damage_taken",
    "damage_reduction",
    "toughness_state",
}


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
    scenario_path: Path,
    max_ability_files: int | None = None,
) -> dict[str, object]:
    discovery = TBGDDiscovery(tbgd_root).scan()
    ir = TBGDLowering(tbgd_root, LoweringLimits(max_ability_files=max_ability_files)).build()
    coverage = build_coverage_matrix(discovery, ir)
    fidelity = build_fidelity_matrix(discovery, ir)
    rules = RuleBook(ir)

    write_json(output_dir / "canonical_ir_v0_209.json", ir.to_json())
    write_json(output_dir / "coverage_matrix_v0_209.json", coverage.to_json())
    write_json(output_dir / "fidelity_matrix_v0_209.json", fidelity.to_json())

    scenario = ScenarioLoader().load_path(scenario_path)
    identity_result = IdentityResolver(rules).validate(scenario)
    build_result = ScenarioStateBuilder(rules).build(scenario)
    formula_state = _formula_test_state(build_result.state)
    base_command = _damage_emission_command(ir, rules, build_result.commands[0])
    crit_command = _with_crit_mode(base_command, "crit")
    noncrit_command = _with_crit_mode(base_command, "noncrit")
    auto_command = replace(base_command, metadata={key: value for key, value in base_command.metadata.items() if key != "crit_mode"})

    executor = CombatExecutor(rules)
    crit_after, crit_transition = executor.execute(crit_command, formula_state)
    noncrit_after, noncrit_transition = executor.execute(noncrit_command, formula_state)
    auto_after_1, auto_transition_1 = executor.execute(auto_command, formula_state)
    auto_after_2, auto_transition_2 = executor.execute(auto_command, formula_state)

    snapshot_validator = SnapshotCompletenessValidator()
    transition_validator = TransitionContractValidator()
    settlement_validator = SettlementTraceabilityValidator()
    reducer = MutationReducer()
    crit_snapshot = snapshot_validator.validate(formula_state.snapshot())
    crit_contract = transition_validator.validate(crit_transition)
    crit_traceability = settlement_validator.validate(
        crit_transition.transaction.settlement,
        crit_transition.transaction.mutations,
    )
    crit_replay = reducer.replay_snapshot(
        formula_state,
        crit_transition.transaction.mutations,
        crit_after.snapshot().to_json(),
    )

    checks = {
        "direct_formula_contract": _direct_formula_contract_checks(crit_transition),
        "forced_crit_modes": _forced_crit_checks(crit_transition, noncrit_transition, crit_after, noncrit_after),
        "deterministic_rng": _deterministic_rng_checks(auto_transition_1, auto_transition_2, auto_after_1, auto_after_2),
        "direct_bucket_coverage": _direct_bucket_checks(crit_transition),
        "fixed_damage_families": _fixed_damage_family_checks(formula_state, base_command),
        "damage_taxonomy": _damage_taxonomy_checks(ir),
    }
    static_result = run_static_checks(package_root)

    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(
            (
                identity_result.ok,
                static_result.ok,
                crit_snapshot.ok,
                crit_contract.ok,
                crit_traceability.ok,
                crit_replay.ok,
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
                "action_id": base_command.action_id,
                "action_level": base_command.action_level,
                "target_ids": list(base_command.target_ids),
            },
        },
        "checks": checks,
        "snapshot_completeness": crit_snapshot.to_json(),
        "transition_contract": crit_contract.to_json(),
        "settlement_traceability": crit_traceability.to_json(),
        "replay": {
            "ok": crit_replay.ok,
            "errors": list(crit_replay.errors),
            "mutation_count": len(crit_transition.transaction.mutations),
        },
        "static_checks": static_result.to_json(),
        "fidelity": fidelity.to_json()["summary"],
    }
    write_json(output_dir / "validation_summary_v0_209.json", result)
    write_json(output_dir / "sample_executor_transition_v0_209.json", crit_transition.to_json())
    write_json(output_dir / "sample_auto_rng_transition_v0_209.json", auto_transition_1.to_json())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 direct damage formula and ledger contract.")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("validation_outputs_v0_209"))
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--max-ability-files", type=int, default=None)
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


def _damage_emission_command(ir: CanonicalIR, rules: RuleBook, base_command: ActionCommand) -> ActionCommand:
    for emission in sorted(
        ir.damage_emissions,
        key=lambda item: (item.source.source_path, item.action_id, item.level, item.source_task_id, item.hit_profile_id),
    ):
        if emission.coverage_status != "executable" or emission.damage_formula_family != "direct":
            continue
        definition = rules.action_definition(emission.action_id, emission.level)
        if definition is None:
            continue
        target_ids = _target_ids_for_damage_definition(definition, base_command.actor_id)
        if target_ids is None:
            continue
        return replace(
            base_command,
            action_id=definition.action_id,
            action_level=definition.level,
            target_ids=target_ids,
        )
    return base_command


def _target_ids_for_damage_definition(definition: ActionDefinitionIR, actor_id: str) -> tuple[str, ...] | None:
    if definition.target_mode == "aoe":
        return ()
    if definition.target_mode in {"single", "blast"}:
        return ("enemy:target",)
    if definition.target_mode == "self_or_team":
        return (actor_id,)
    return None


def _direct_formula_contract_checks(transition) -> dict[str, object]:
    record = _damage_record(transition)
    payload = record.get("payload", {}) if isinstance(record, dict) else {}
    formula = payload.get("formula_result", {}) if isinstance(payload, dict) else {}
    ledger = payload.get("modifier_ledger", {}) if isinstance(payload, dict) else {}
    transition_text = json.dumps(transition.to_json(), sort_keys=True, ensure_ascii=False)
    checks = {
        "has_damage_record": bool(record),
        "has_formula_result": isinstance(formula, dict) and formula.get("calculation_mode") == "v0_209_direct_damage_formula",
        "has_modifier_ledger": isinstance(ledger, dict) and ledger.get("formula_family") == "direct",
        "has_crit_resolution": isinstance(payload.get("crit_resolution"), dict),
        "no_v0_208_base_amount": "v0_208_base_amount_only" not in transition_text,
        "record_linked_to_damage_mutation": bool(record.get("mutation_id")),
        "transition_has_rng_event": bool(transition.rng_events),
        "transition_has_all_mutation_sources": _has_required_mutation_sources(transition),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "formula_result": formula,
    }


def _forced_crit_checks(crit_transition, noncrit_transition, crit_after, noncrit_after) -> dict[str, object]:
    crit_formula = _formula_result(crit_transition)
    noncrit_formula = _formula_result(noncrit_transition)
    crit_resolution = crit_formula.get("crit_resolution", {}) if isinstance(crit_formula, dict) else {}
    noncrit_resolution = noncrit_formula.get("crit_resolution", {}) if isinstance(noncrit_formula, dict) else {}
    checks = {
        "crit_mode_is_crit": crit_resolution.get("is_crit") is True and crit_resolution.get("multiplier") == 2.0,
        "noncrit_mode_is_noncrit": noncrit_resolution.get("is_crit") is False and noncrit_resolution.get("multiplier") == 1.0,
        "crit_damage_greater_than_noncrit": _final_damage(crit_transition) > _final_damage(noncrit_transition),
        "crit_after_hp_lower": crit_after.units["enemy:target"].hp < noncrit_after.units["enemy:target"].hp,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "crit_resolution": crit_resolution,
        "noncrit_resolution": noncrit_resolution,
    }


def _deterministic_rng_checks(first_transition, second_transition, first_after, second_after) -> dict[str, object]:
    first_rng = [event.to_json() for event in first_transition.rng_events]
    second_rng = [event.to_json() for event in second_transition.rng_events]
    checks = {
        "has_rng_event": bool(first_rng),
        "rng_events_match": first_rng == second_rng,
        "final_damage_matches": _final_damage(first_transition) == _final_damage(second_transition),
        "after_hp_matches": first_after.units["enemy:target"].hp == second_after.units["enemy:target"].hp,
    }
    return {"ok": all(checks.values()), "checks": checks, "rng_events": first_rng}


def _direct_bucket_checks(transition) -> dict[str, object]:
    ledger = _formula_result(transition).get("modifier_ledger", {})
    buckets = ledger.get("buckets", []) if isinstance(ledger, dict) else []
    bucket_names = {bucket.get("bucket") for bucket in buckets if isinstance(bucket, dict)}
    applied_counts = {
        str(bucket.get("bucket")): len(bucket.get("applied_terms", []))
        for bucket in buckets
        if isinstance(bucket, dict)
    }
    checks = {
        "all_required_buckets_present": DIRECT_BUCKETS.issubset(bucket_names),
        "each_bucket_has_applied_terms": all(applied_counts.get(bucket, 0) > 0 for bucket in DIRECT_BUCKETS),
        "has_skipped_terms": int(ledger.get("skipped_count", 0)) >= 1 if isinstance(ledger, dict) else False,
        "final_damage_positive": _final_damage(transition) > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "bucket_names": sorted(str(name) for name in bucket_names),
        "applied_counts": applied_counts,
    }


def _fixed_damage_family_checks(state: BattleState, command: ActionCommand) -> dict[str, object]:
    damage_system = DamageSystem()
    true_result = damage_system.apply_packet(
        state,
        DamagePacket(
            attacker_id=command.actor_id,
            target_id=command.target_ids[0],
            amount=37.0,
            attack_type="TrueDamage",
            damage_formula_family="true_damage",
            source_trace={"validation": "v0_209_true_damage"},
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
            source_trace={"validation": "v0_209_hp_loss"},
        ),
    )
    true_record = true_result.records[0] if true_result.records else {}
    hp_loss_record = hp_loss_result.records[0] if hp_loss_result.records else {}
    checks = {
        "true_damage_record_type": true_record.get("record_type") == "damage",
        "true_damage_bypasses": _bypasses_without_ledger(true_record),
        "hp_loss_record_type": hp_loss_record.get("record_type") == "hp_loss",
        "hp_loss_bypasses": _bypasses_without_ledger(hp_loss_record),
        "both_mutate_hp": bool(true_result.mutations) and bool(hp_loss_result.mutations),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "true_damage": true_result.to_json(),
        "hp_loss": hp_loss_result.to_json(),
    }


def _damage_taxonomy_checks(ir: CanonicalIR) -> dict[str, object]:
    follow_up_defaults = [
        definition for definition in ir.action_definitions if definition.damage_formula_family == "follow_up"
    ]
    executable_unknown = [
        definition
        for definition in ir.action_definitions
        if definition.damage_formula_family == "unknown" and definition.coverage_status == "executable"
    ]
    checks = {
        "no_follow_up_family": not follow_up_defaults,
        "unknown_family_not_executable": not executable_unknown,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "counts": {
            "follow_up_family": len(follow_up_defaults),
            "executable_unknown_family": len(executable_unknown),
        },
    }


def _damage_record(transition) -> dict[str, Any]:
    records = transition.transaction.settlement.records if transition.transaction.settlement else ()
    for record in records:
        if record.get("record_type") == "damage":
            return record
    return {}


def _formula_result(transition) -> dict[str, Any]:
    record = _damage_record(transition)
    payload = record.get("payload", {})
    formula = payload.get("formula_result", {}) if isinstance(payload, dict) else {}
    return formula if isinstance(formula, dict) else {}


def _final_damage(transition) -> float:
    formula = _formula_result(transition)
    value = formula.get("final_damage")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _has_required_mutation_sources(transition) -> bool:
    sources = {mutation.source for mutation in transition.transaction.mutations}
    return {
        "combat_executor.timeline",
        "combat_executor.resources",
        "damage_system",
    }.issubset(sources)


def _bypasses_without_ledger(record: dict[str, Any]) -> bool:
    payload = record.get("payload", {})
    return (
        isinstance(payload, dict)
        and payload.get("bypasses_normal_multipliers") is True
        and payload.get("normal_multiplier_terms") == []
        and "modifier_ledger" not in payload
        and "formula_result" not in payload
    )


if __name__ == "__main__":
    raise SystemExit(main())
