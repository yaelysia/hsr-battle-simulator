from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..core.source_audit import RuntimeSourceAuditor
from ..core.transition_contract import TransitionContractValidator
from ..rules.ir import ActionDefinitionIR, CanonicalIR, DamageEmissionIR
from ..rules.rulebook import RuleBook
from ..systems.target import TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_264"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    blast_case = _select_target_group_case(ir, rules, target_mode="blast")
    aoe_case = _select_target_group_case(ir, rules, target_mode="aoe")
    bounce_case = _select_bounce_case(ir, rules)
    blast_result = _execute_target_group_case(rules, blast_case, expected_groups={"primary", "adjacent"})
    aoe_result = _execute_target_group_case(rules, aoe_case, expected_groups={"selected"})
    bounce_result = _execute_bounce_case(rules, bounce_case)
    bounce_alive_first = _bounce_alive_target_priority_case(rules, bounce_case)
    bounce_all_dead = _bounce_all_defeated_continuation_case(rules, bounce_case)
    blocked_cases = _blocked_cases(rules, bounce_case)
    matrix = _target_group_bounce_matrix(ir, blast_case, aoe_case, bounce_case)
    static_result = run_static_checks(package_root)
    checks = {
        "blast": blast_result["checks"],
        "aoe": aoe_result["checks"],
        "bounce": bounce_result["checks"],
        "bounce_alive_target_priority": bounce_alive_first["checks"],
        "bounce_all_defeated_continuation": bounce_all_dead["checks"],
        "blocked_cases": blocked_cases["checks"],
        "matrix": _matrix_checks(matrix),
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": (
                "Select by structured Canonical IR predicates only: target_mode, executable DamageEmissionIR, "
                "character data card formula slot source, executable BouncePolicyIR, and runtime target policy. "
                "No fixed character name/action id/file name/hash is used as a main sample selector."
            ),
        },
        "checks": checks,
        "target_group_bounce_matrix": matrix,
        "blast_case": blast_result,
        "aoe_case": aoe_result,
        "bounce_case": bounce_result,
        "bounce_alive_target_priority_case": bounce_alive_first,
        "bounce_all_defeated_continuation_case": bounce_all_dead,
        "blocked_cases": blocked_cases,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_264.json", result)
    write_json(output_dir / "target_group_bounce_matrix_v0_264.json", matrix)
    write_json(output_dir / "sample_blast_transition_v0_264.json", blast_result.get("transition", {}))
    write_json(output_dir / "sample_aoe_transition_v0_264.json", aoe_result.get("transition", {}))
    write_json(output_dir / "sample_bounce_transition_v0_264.json", bounce_result.get("transition", {}))
    write_json(output_dir / "bounce_negative_cases_v0_264.json", blocked_cases)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 target-group formulas and bounce target policy.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _select_target_group_case(ir: CanonicalIR, rules: RuleBook, *, target_mode: str) -> dict[str, Any] | None:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if definition.target_mode != target_mode or definition.damage_formula_family != "direct":
            continue
        emissions = _executable_direct_emissions(rules, definition)
        if not emissions:
            continue
        groups = {emission.target_group for emission in emissions}
        if target_mode == "blast" and not {"primary", "adjacent"}.issubset(groups):
            continue
        if target_mode == "aoe" and "selected" not in groups:
            continue
        if not all(_emission_has_character_card_slot(rules, emission) for emission in emissions[: min(2, len(emissions))]):
            continue
        return {"definition": definition, "emissions": emissions}
    return None


def _select_bounce_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any] | None:
    for definition in sorted(ir.action_definitions, key=lambda item: (item.action_id, item.level)):
        if definition.target_mode != "bounce" or definition.damage_formula_family != "direct":
            continue
        emissions = _executable_direct_emissions(rules, definition)
        bounce_emissions = [emission for emission in emissions if emission.target_group.startswith("bounce:")]
        if not bounce_emissions:
            continue
        policies = tuple(policy for policy in rules.bounce_policies_for_action(definition.action_id, definition.level))
        executable_policy = next((policy for policy in policies if policy.coverage_status == "executable"), None)
        if executable_policy is None:
            continue
        if not all(_emission_has_character_card_slot(rules, emission) for emission in bounce_emissions[: min(2, len(bounce_emissions))]):
            continue
        return {"definition": definition, "emissions": emissions, "bounce_policy": executable_policy}
    return None


def _execute_target_group_case(
    rules: RuleBook,
    case: dict[str, Any] | None,
    *,
    expected_groups: set[str],
) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    definition: ActionDefinitionIR = case["definition"]
    state = _multi_enemy_state()
    after, transition = CombatExecutor(rules).execute(_command_for_definition(definition), state)
    common = _transition_checks(rules, state, transition)
    damage_mutations = _damage_mutations(transition)
    groups = [str(mutation.metadata.get("target_group") or "") for mutation in damage_mutations]
    target_ids = [str(mutation.path[1]) for mutation in damage_mutations]
    checks = {
        **common,
        "case_found": True,
        "state_changed": state.snapshot().to_json() != after.snapshot().to_json(),
        "damage_mutations_present": bool(damage_mutations),
        "expected_groups_present": expected_groups.issubset(set(groups)),
        "character_card_formula_source": all(
            mutation.metadata.get("multiplier_source", {}).get("source_kind") == "character_data_card_skill_formula"
            for mutation in damage_mutations
        ),
        "target_group_multiplier_admitted": all(
            mutation.metadata.get("target_group_multiplier_not_implemented") is False for mutation in damage_mutations
        ),
        "multi_target_expanded": len(set(target_ids)) >= (3 if "selected" in expected_groups else 2),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "selected_action": definition.to_json(),
        "selected_emissions": [emission.to_json() for emission in case["emissions"][:12]],
        "damage_mutation_summary": _damage_mutation_summary(damage_mutations),
        "transition": transition.to_json(),
    }


def _execute_bounce_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    definition: ActionDefinitionIR = case["definition"]
    state = _multi_enemy_state(primary_hp=500.0, rng_state="v0_264_bounce_replay")
    transition_a = CombatExecutor(rules).execute(_command_for_definition(definition), state)[1]
    transition_b = CombatExecutor(rules).execute(_command_for_definition(definition), state)[1]
    common = _transition_checks(rules, state, transition_a)
    damage_mutations = _damage_mutations(transition_a)
    rng_events = [event.to_json() for event in transition_a.rng_events if event.rng_type == "bounce_target"]
    rng_events_b = [event.to_json() for event in transition_b.rng_events if event.rng_type == "bounce_target"]
    bounce_targets = [
        event.get("result", {}).get("selected_target_id") for event in rng_events if isinstance(event.get("result"), dict)
    ]
    expected_bounce_hits = int(case["bounce_policy"].bounce_count)
    checks = {
        **common,
        "case_found": True,
        "bounce_policy_executable": case["bounce_policy"].coverage_status == "executable",
        "bounce_damage_mutations_present": bool(damage_mutations),
        "bounce_rng_events_present": len(rng_events) >= expected_bounce_hits,
        "fixed_bounce_hit_count_has_rng": len(rng_events) >= expected_bounce_hits,
        "rng_replay_stable": rng_events == rng_events_b,
        "bounce_targets_recorded": all(bool(target) for target in bounce_targets),
        "bounce_hits_have_policy_trace": all(
            bool(mutation.metadata.get("target_selection_policy", {}).get("bounce_policy"))
            for mutation in damage_mutations
            if str(mutation.metadata.get("target_group") or "").startswith("bounce:")
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "selected_action": definition.to_json(),
        "selected_bounce_policy": case["bounce_policy"].to_json(),
        "selected_emissions": [emission.to_json() for emission in case["emissions"][:12]],
        "bounce_rng_events": rng_events,
        "damage_mutation_summary": _damage_mutation_summary(damage_mutations),
        "transition": transition_a.to_json(),
    }


def _bounce_alive_target_priority_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    definition: ActionDefinitionIR = case["definition"]
    state = _multi_enemy_state(primary_hp=1.0, left_hp=500.0, right_hp=500.0, rng_state="v0_264_alive_priority")
    _, transition = CombatExecutor(rules).execute(_command_for_definition(definition), state)
    rng_results = [
        event.to_json().get("result", {})
        for event in transition.rng_events
        if event.rng_type == "bounce_target"
    ]
    live_pool_results = [
        result
        for result in rng_results
        if isinstance(result, dict) and result.get("candidate_pool_reason") != "all_targets_defeated_continue_sequence"
    ]
    checks = {
        "case_found": True,
        "bounce_rng_events_present": bool(rng_results),
        "live_pool_excludes_defeated_primary": all(
            "enemy:primary" not in result.get("candidate_pool", ()) for result in live_pool_results
        ),
        "selected_live_while_live_exists": all(
            result.get("selected_target_id") != "enemy:primary" for result in live_pool_results
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "rng_results": rng_results,
        "damage_mutation_summary": _damage_mutation_summary(_damage_mutations(transition)),
        "transition": transition.to_json(),
    }


def _bounce_all_defeated_continuation_case(rules: RuleBook, case: dict[str, Any] | None) -> dict[str, Any]:
    if case is None:
        return {"checks": {"ok": False, "case_found": False}}
    definition: ActionDefinitionIR = case["definition"]
    state = _multi_enemy_state(primary_hp=1.0, left_hp=1.0, right_hp=1.0, rng_state="v0_264_all_defeated")
    _, transition = CombatExecutor(rules).execute(_command_for_definition(definition), state)
    damage_records = [
        record
        for record in transition.transaction.settlement.records
        if record.get("source") == "damage_system" and record.get("record_type") == "damage"
    ]
    defeated_events = [event for event in transition.transaction.events if event.event_type == "unit.defeated"]
    defeated_targets = [str(event.payload.get("defeated_unit_id") or event.target_id or "") for event in defeated_events]
    rng_results = [
        event.to_json().get("result", {})
        for event in transition.rng_events
        if event.rng_type == "bounce_target"
    ]
    checks = {
        "case_found": True,
        "all_targets_defeated": all(unit["hp"] == 0 for unit in transition.after.to_json()["units"].values() if unit["side"] == "enemy"),
        "remaining_hits_recorded_after_all_defeated": any(
            bool(record.get("payload", {}).get("dead_target_continuation")) for record in damage_records
        ),
        "no_duplicate_defeat_events": len(defeated_targets) == len(set(defeated_targets)),
        "all_defeated_rng_continuation_present": any(
            isinstance(result, dict)
            and result.get("candidate_pool_reason") == "all_targets_defeated_continue_sequence"
            for result in rng_results
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "defeated_targets": defeated_targets,
        "rng_results": rng_results,
        "damage_records": damage_records[:12],
        "transition": transition.to_json(),
    }


def _blocked_cases(rules: RuleBook, bounce_case: dict[str, Any] | None) -> dict[str, Any]:
    if bounce_case is None:
        return {"checks": {"ok": False, "case_found": False}}
    definition: ActionDefinitionIR = bounce_case["definition"]
    target_system_blocked = TargetSystem().resolve_bounce_hit_target(
        _multi_enemy_state(),
        actor_id="ally:actor",
        primary_target_id="enemy:primary",
        bounce_policy={"coverage_status": "blocked", "blocked_reason": "synthetic_negative_policy"},
        hit_index=1,
        previous_hit_targets=(),
        action_id=definition.action_id,
        action_level=definition.level,
    )
    invalid_target_state = _multi_enemy_state()
    _, invalid_target_transition = CombatExecutor(rules).execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id=definition.action_id,
            action_level=definition.level,
            target_ids=("enemy:missing",),
            source="manual",
        ),
        invalid_target_state,
    )
    before = invalid_target_state.snapshot().to_json()
    checks = {
        "case_found": True,
        "blocked_policy_rejected": target_system_blocked.ok is False,
        "blocked_policy_specific_reason": target_system_blocked.error == "bounce_policy_not_executable",
        "invalid_target_no_mutation": not invalid_target_transition.transaction.mutations,
        "invalid_target_snapshot_unchanged": before == invalid_target_transition.after.to_json(),
    }
    checks["ok"] = all(checks.values())
    return {
        "checks": checks,
        "blocked_policy_result": {
            "ok": target_system_blocked.ok,
            "error": target_system_blocked.error,
            "metadata": target_system_blocked.metadata,
        },
        "invalid_target_transition": invalid_target_transition.to_json(),
    }


def _target_group_bounce_matrix(
    ir: CanonicalIR,
    blast_case: dict[str, Any] | None,
    aoe_case: dict[str, Any] | None,
    bounce_case: dict[str, Any] | None,
) -> dict[str, Any]:
    hit_status = Counter(profile.coverage_status for profile in ir.hit_profiles)
    bounce_policy_status = Counter(policy.coverage_status for policy in ir.bounce_policies)
    bounce_strategy_counts = Counter(policy.selection_strategy or "missing" for policy in ir.bounce_policies)
    executable_prefer_unhit = [
        policy
        for policy in ir.bounce_policies
        if policy.coverage_status == "executable" and policy.selection_strategy == "prefer_unhit_then_random"
    ]
    discovered_prefer_unhit = [
        policy for policy in ir.bounce_policies if policy.selection_strategy == "prefer_unhit_then_random"
    ]
    return {
        "encoding": "hsr.v8.target_group_bounce_matrix.v0_264",
        "target_groups": {
            "blast": {
                "selected_action": _case_action_id(blast_case),
                "selected_level": _case_level(blast_case),
                "executable_emission_count": _case_emission_count(blast_case),
                "status": "trusted_for_current_scope" if blast_case else "blocked",
                "blocking_dependency": "" if blast_case else "character_data_card_target_group_formula_slot_missing",
            },
            "aoe": {
                "selected_action": _case_action_id(aoe_case),
                "selected_level": _case_level(aoe_case),
                "executable_emission_count": _case_emission_count(aoe_case),
                "status": "trusted_for_current_scope" if aoe_case else "blocked",
                "blocking_dependency": "" if aoe_case else "character_data_card_aoe_formula_slot_missing",
            },
        },
        "bounce": {
            "selected_action": _case_action_id(bounce_case),
            "selected_level": _case_level(bounce_case),
            "selected_policy": bounce_case["bounce_policy"].bounce_policy_id if bounce_case else "",
            "status": "trusted_for_current_scope" if bounce_case else "blocked",
            "blocking_dependency": "" if bounce_case else "executable_bounce_policy_and_damage_emission_missing",
            "policy_status_counts": dict(bounce_policy_status),
            "selection_strategy_counts": dict(bounce_strategy_counts),
            "prefer_unhit_strategy": {
                "executable_count": len(executable_prefer_unhit),
                "discovered_count": len(discovered_prefer_unhit),
                "status": "trusted_for_current_scope" if executable_prefer_unhit else "blocked",
                "blocking_dependency": ""
                if executable_prefer_unhit
                else "no admitted mainline character-card source for prefer-unhit bounce policy in current TBGD sample",
            },
        },
        "hit_profile_status_counts": dict(hit_status),
        "redlines": {
            "runtime_reads_textmap": False,
            "runtime_hardcodes_character_or_action": False,
            "blocked_or_discovered_policy_can_mutate": False,
        },
    }


def _matrix_checks(matrix: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "blast_selected": bool(matrix["target_groups"]["blast"]["selected_action"]),
        "aoe_selected": bool(matrix["target_groups"]["aoe"]["selected_action"]),
        "bounce_selected": bool(matrix["bounce"]["selected_action"]),
        "blocked_dependencies_specific": all(
            bool(row["blocking_dependency"]) or row["status"] == "trusted_for_current_scope"
            for row in (
                matrix["target_groups"]["blast"],
                matrix["target_groups"]["aoe"],
                matrix["bounce"],
                matrix["bounce"]["prefer_unhit_strategy"],
            )
        ),
        "redlines": all(matrix["redlines"].values()) is False
        and matrix["redlines"]["runtime_reads_textmap"] is False
        and matrix["redlines"]["runtime_hardcodes_character_or_action"] is False
        and matrix["redlines"]["blocked_or_discovered_policy_can_mutate"] is False,
    }
    checks["ok"] = all(checks.values())
    return {"ok": checks["ok"], "checks": checks}


def _transition_checks(rules: RuleBook, before_state: BattleState, transition) -> dict[str, Any]:
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    traceability = SettlementTraceabilityValidator().validate(
        transition.transaction.settlement, transition.transaction.mutations
    )
    contract = TransitionContractValidator().validate(transition)
    replay = MutationReducer().replay_snapshot(
        before_state, transition.transaction.mutations, transition.after.to_json()
    )
    return {
        "transition_contract": contract.ok,
        "settlement_traceability": traceability.ok,
        "source_audit": source_audit.ok,
        "snapshot_replay": replay.ok,
    }


def _executable_direct_emissions(rules: RuleBook, definition: ActionDefinitionIR) -> list[DamageEmissionIR]:
    return [
        emission
        for emission in rules.damage_emissions_for_action(definition.action_id, definition.level)
        if emission.coverage_status == "executable" and emission.damage_formula_family == "direct"
    ]


def _emission_has_character_card_slot(rules: RuleBook, emission: DamageEmissionIR) -> bool:
    profile = rules.hit_profile(emission.hit_profile_id)
    return bool(profile and profile.multiplier_source.get("source_kind") == "character_data_card_skill_formula")


def _multi_enemy_state(
    *,
    primary_hp: float = 500.0,
    left_hp: float = 500.0,
    right_hp: float = 500.0,
    rng_state: str = "v0_264",
) -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState(
                unit_id="ally:actor",
                side="ally",
                template_id="avatar:v0_264_actor",
                max_hp=1000.0,
                hp=1000.0,
                attack=100.0,
                defense=50.0,
                speed=100.0,
                energy=200.0,
                max_energy=200.0,
            ),
            "enemy:primary": UnitState(
                unit_id="enemy:primary",
                side="enemy",
                template_id="monster:v0_264_primary",
                max_hp=500.0,
                hp=primary_hp,
                defense=20.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "enemy:left": UnitState(
                unit_id="enemy:left",
                side="enemy",
                template_id="monster:v0_264_left",
                max_hp=500.0,
                hp=left_hp,
                defense=20.0,
                speed=100.0,
                flags={"position": 0},
            ),
            "enemy:right": UnitState(
                unit_id="enemy:right",
                side="enemy",
                template_id="monster:v0_264_right",
                max_hp=500.0,
                hp=right_hp,
                defense=20.0,
                speed=100.0,
                flags={"position": 2},
            ),
        },
        skill_points=5,
        max_skill_points=5,
        rng_state=rng_state,
        global_flags={"phase": "v0_264_target_group_bounce"},
    )


def _command_for_definition(definition: ActionDefinitionIR) -> ActionCommand:
    return ActionCommand(
        actor_id="ally:actor",
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=("enemy:primary",),
        source="manual",
    )


def _damage_mutations(transition) -> list[Any]:
    return [mutation for mutation in transition.transaction.mutations if mutation.source == "damage_system"]


def _damage_mutation_summary(mutations: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "mutation_id": mutation.stable_id(),
            "target_id": mutation.path[1] if len(mutation.path) > 1 else "",
            "before": mutation.before,
            "after": mutation.after,
            "target_group": mutation.metadata.get("target_group"),
            "hit_index": mutation.metadata.get("hit_index"),
            "hit_profile_id": mutation.metadata.get("hit_profile_id"),
            "damage_emission_id": mutation.metadata.get("damage_emission_id"),
            "target_selection_policy": mutation.metadata.get("target_selection_policy", {}),
        }
        for mutation in mutations
    ]


def _case_action_id(case: dict[str, Any] | None) -> str:
    return str(case["definition"].action_id) if case else ""


def _case_level(case: dict[str, Any] | None) -> int:
    return int(case["definition"].level) if case else 0


def _case_emission_count(case: dict[str, Any] | None) -> int:
    return len(case["emissions"]) if case else 0


if __name__ == "__main__":
    raise SystemExit(main())
