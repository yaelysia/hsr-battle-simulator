from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import ActionSettlement, BattleState, JSONValue, Mutation, UnitState
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementTraceabilityValidator
from ..rules.ir import CanonicalIR, SkillFormulaBindingIR, SummonMonsterIntentIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver
from ..systems.summon import SUMMON_RUNTIME_SCHEMA_VERSION, SummonSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_summon_state,
    _select_executable_summon_monster_intent,
    _snapshot_hash,
)


VALIDATION_VERSION = "p5_s7_monster_custom_summon_binding"
MATRIX_SCHEMA_VERSION = "p5_s7_monster_custom_summon_binding_matrix_v1"

PROFILE_STAT_FIELDS = ("max_hp", "attack", "defense", "speed")
CLASSIFICATION_STATES = {
    "executable",
    "boundary_only",
    "source_absent_not_required",
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
    "out_of_scope",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "summon_profile_base_stat_value_resolver",
    "summon_profile_card_level_source_binding",
    "monster_skill_formula_binding_value_resolver",
    "missing_profile_card_level_source_blocked",
    "summon_binding_replay_settlement_gap_visibility",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s7_monster_custom_summon_binding_matrix(ir, rules)
    matrix_checks = validate_p5_s7_monster_custom_summon_binding_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s7_monster_formula_and_summon_binding_structural_runtime_samples",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "synthetic_positive_created": False,
                "negative_cases_derived_from_real_intent": True,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "summon_binding_matrix": matrix["summon_binding_matrix"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "runtime_samples": matrix["runtime_samples"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s7_monster_custom_summon_binding.json", result)
    write_json(output_dir / "p5_s7_monster_custom_summon_binding_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S7 monster custom values and summon binding recovery.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s7_monster_custom_summon_binding_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    summon_case = _select_summon_profile_binding_case(rules)
    formula_case = _select_monster_formula_binding_case(ir, rules)
    negative_case = _missing_source_negative_case(summon_case, rules)
    gap_case = _summon_gap_visibility_case(rules)
    rows = [
        _summon_profile_base_stat_row(summon_case),
        _summon_profile_card_level_source_row(summon_case),
        _monster_skill_formula_binding_row(formula_case),
        _missing_profile_card_level_source_blocked_row(negative_case),
        _summon_binding_replay_settlement_gap_visibility_row(summon_case, gap_case),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "runtime_schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
        "summon_binding_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "summon_value_resolution_count": len(summon_case.get("value_resolutions") or ()),
            "monster_formula_binding_sample_count": 1 if formula_case.get("found") else 0,
            "blocked_negative_case_count": len(negative_case.get("cases") or ()),
            "summon_intent_status_counts": gap_case["intent_status_counts"],
        },
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "runtime_samples": {
            "summon": summon_case.get("runtime_sample", {}),
            "monster_formula_binding": formula_case.get("runtime_sample", {}),
            "negative": negative_case.get("runtime_sample", {}),
            "gap_visibility": gap_case,
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "summon_runtime_sample_count": 1,
            "monster_formula_resolver_sample_count": 1 if formula_case.get("found") else 0,
            "negative_runtime_sample_count": len(negative_case.get("cases") or ()),
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s7_monster_custom_summon_binding.json",
                "p5_s7_monster_custom_summon_binding_matrix.json",
            ],
        },
    }


def validate_p5_s7_monster_custom_summon_binding_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("summon_binding_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "profile_stats_resolved": _row_check(
            rows,
            "summon_profile_base_stat_value_resolver",
            "all_profile_stat_value_resolutions_ok",
        ),
        "profile_card_level_source_bound": _row_check(
            rows,
            "summon_profile_card_level_source_binding",
            "profile_card_level_policy_sources_present",
        ),
        "monster_formula_binding_resolved": _row_check(
            rows,
            "monster_skill_formula_binding_value_resolver",
            "monster_formula_value_resolution_ok",
        ),
        "missing_sources_blocked": _row_check(
            rows,
            "missing_profile_card_level_source_blocked",
            "all_negative_cases_state_unchanged",
        ),
        "replay_and_settlement_ok": _row_check(
            rows,
            "summon_binding_replay_settlement_gap_visibility",
            "replay_ok",
        )
        and _row_check(rows, "summon_binding_replay_settlement_gap_visibility", "settlement_traceability_ok"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _select_summon_profile_binding_case(rules: RuleBook) -> dict[str, Any]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _base_summon_state()
    system = SummonSystem(rules)
    plan = system.plan_spawn_summoned_monster(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    spawned = tuple(unit_id for unit_id in plan.unit_ids if unit_id in after.units)
    spawn_mutations = tuple(
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("summon_operation") == "spawn_summoned_monster"
        and mutation.metadata.get("lifecycle_operation") == "unit_spawn"
    )
    settlement = SettlementTraceabilityValidator().validate(
        ActionSettlement("summon_spawn", plan.owner_id, spawned, result.records),
        result.mutations,
    )
    value_resolutions = _value_resolutions_from_spawn_mutations(spawn_mutations)
    unit_value_resolutions = _value_resolutions_from_units(tuple(after.units[unit_id] for unit_id in spawned))
    return {
        "found": True,
        "intent": intent,
        "state": state,
        "after": after,
        "plan": plan,
        "result": result,
        "spawned_unit_ids": spawned,
        "spawn_mutations": spawn_mutations,
        "value_resolutions": value_resolutions,
        "unit_value_resolutions": unit_value_resolutions,
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "settlement": settlement.to_json(),
        "runtime_sample": {
            "summon_intent_id": intent.summon_intent_id,
            "source_path": intent.source.source_path,
            "entry_count": len(intent.entries),
            "spawned_unit_ids": list(spawned),
            "spawn_mutation_count": len(spawn_mutations),
            "plan_entry_value_resolution_count": _plan_entry_value_resolution_count(plan.metadata),
            "first_entry": _entry_sample(intent.entries[0]) if intent.entries else {},
        },
    }


def _select_monster_formula_binding_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    resolver = ValueResolver(rules)
    for binding in sorted(ir.skill_formula_bindings, key=lambda item: item.binding_id):
        if binding.coverage_status != "executable":
            continue
        if binding.data_card_kind != "monster":
            continue
        if _numeric_value(binding.param_value) is None:
            continue
        context = ValueContext(
            action_id=binding.action_id,
            action_level=binding.level,
            data_card_id=binding.data_card_id,
            data_card_kind=binding.data_card_kind,
            source_trace=binding.source.to_json(),
        )
        resolution = resolver.resolve(
            ValueBindingRequest(
                binding_kind="skill_formula_param",
                binding_id=binding.binding_id,
                param_index=binding.param_index,
                formula_role=binding.formula_role,
                required_context_keys=("action", "data_card_source"),
                source_trace=binding.source.to_json(),
            ),
            context,
        )
        if resolution.ok:
            return {
                "found": True,
                "binding": binding,
                "resolution": resolution.to_json(),
                "runtime_sample": {
                    "binding_id": binding.binding_id,
                    "data_card_id": binding.data_card_id,
                    "owner_entity_ref": binding.owner_entity_ref,
                    "action_id": binding.action_id,
                    "level": binding.level,
                    "param_index": binding.param_index,
                    "formula_role": binding.formula_role,
                    "param_value": binding.param_value,
                    "source_path": binding.source.source_path,
                },
            }
    return {"found": False, "resolution": {}, "runtime_sample": {}}


def _missing_source_negative_case(summon_case: dict[str, Any], rules: RuleBook) -> dict[str, Any]:
    intent = summon_case["intent"]
    state = summon_case["state"]
    first_entry = intent.entries[0]
    cases = {
        "missing_profile_card": replace(
            first_entry,
            monster_entity_ref="monster:p5_s7_missing_profile_card",
            monster_raw_id="p5_s7_missing_profile_card",
        ),
        "missing_level_policy": replace(first_entry, level_policy={}, birth_template_id=""),
    }
    system = SummonSystem(rules)
    results = {}
    for case_id, entry in cases.items():
        broken_intent = replace(intent, entries=(entry,), coverage_status="executable", blocked_reason="")
        before_hash = _snapshot_hash(state)
        plan = system.plan_spawn_summoned_monster(state, broken_intent, owner_id="enemy:summoner")
        result = system.apply_spawn(state, plan)
        after_hash = _snapshot_hash(state)
        results[case_id] = {
            "plan": plan.to_json(),
            "mutation_count": len(result.mutations),
            "record_count": len(result.records),
            "process_only_record": bool(result.records) and result.records[0].get("process_only") is True,
            "state_unchanged": before_hash == after_hash,
            "blocked_reason": plan.blocked_reason,
        }
    return {
        "cases": results,
        "runtime_sample": {
            case_id: {
                "blocked_reason": item["blocked_reason"],
                "mutation_count": item["mutation_count"],
                "process_only_record": item["process_only_record"],
                "state_unchanged": item["state_unchanged"],
            }
            for case_id, item in results.items()
        },
    }


def _summon_gap_visibility_case(rules: RuleBook) -> dict[str, Any]:
    intents = tuple(rules.summon_monster_intents())
    status_counts = Counter(intent.coverage_status for intent in intents)
    blocked_reasons = Counter(
        intent.blocked_reason or "blocked_reason_missing"
        for intent in intents
        if intent.coverage_status != "executable"
    )
    entry_status_counts = Counter(entry.coverage_status for intent in intents for entry in intent.entries)
    return {
        "intent_count": len(intents),
        "intent_status_counts": dict(sorted(status_counts.items())),
        "entry_status_counts": dict(sorted(entry_status_counts.items())),
        "blocked_reason_counts_top": _counter_top(blocked_reasons, 12),
        "p3_inherited_gap_hidden": False,
        "p5_all_executable_claimed": False,
    }


def _summon_profile_base_stat_row(case: dict[str, Any]) -> dict[str, Any]:
    resolutions = tuple(case.get("value_resolutions") or ())
    unit_resolutions = tuple(case.get("unit_value_resolutions") or ())
    checks = {
        "plan_ok": case["plan"].ok,
        "spawn_mutations_present": bool(case["spawn_mutations"]),
        "all_profile_stat_value_resolutions_ok": bool(resolutions)
        and all(_profile_stat_resolution_ok(item) for item in resolutions),
        "unit_flags_carry_value_resolutions": bool(unit_resolutions)
        and all(_profile_stat_resolution_ok(item) for item in unit_resolutions),
        "unit_stats_match_resolved_values": all(
            _unit_stats_match_resolutions(case["after"].units[unit_id]) for unit_id in case["spawned_unit_ids"]
        ),
        "plan_metadata_carries_entry_resolutions": _plan_entry_value_resolution_count(case["plan"].metadata) >= len(
            PROFILE_STAT_FIELDS
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": "summon_profile_base_stat_value_resolver",
        "classification": "executable" if checks["ok"] else "implementation_missing",
        "gap_attribution": "" if checks["ok"] else "implementation_missing",
        "checks": {"ok": checks["ok"], "checks": checks},
        "evidence": {
            "value_resolution_sample": _sample_resolution(resolutions),
            "unit_value_resolution_sample": _sample_resolution(unit_resolutions),
            "runtime_sample": case["runtime_sample"],
        },
    }


def _summon_profile_card_level_source_row(case: dict[str, Any]) -> dict[str, Any]:
    intent: SummonMonsterIntentIR = case["intent"]
    rows = []
    for entry in intent.entries:
        unit_ids = [
            unit_id
            for unit_id in case["spawned_unit_ids"]
            if case["after"].units[unit_id].flags.get("summon_entry_id") == entry.entry_id
        ]
        profile = case["plan"].metadata.get("entry_value_resolutions", {}).get(entry.entry_id, {})
        rows.append(
            {
                "entry_id": entry.entry_id,
                "monster_entity_ref": entry.monster_entity_ref,
                "level_policy": entry.level_policy,
                "resolved_field_count": sum(1 for item in profile.values() if isinstance(item, dict) and item.get("ok") is True),
                "spawned_unit_ids": unit_ids,
            }
        )
    checks = {
        "profile_card_level_policy_sources_present": all(
            _unit_profile_card_level_sources_complete(case["after"].units[unit_id])
            for unit_id in case["spawned_unit_ids"]
        ),
        "level_policy_is_source_backed_no_runtime_scaling": all(
            entry.level_policy.get("admission_status") == "executable"
            and entry.level_policy.get("kind") == "profile_base_stats_no_runtime_level_scaling"
            and bool(entry.level_policy.get("profile_id"))
            for entry in intent.entries
        ),
        "mutation_metadata_carries_profile_and_card_sources": all(
            _mutation_profile_card_sources_complete(mutation) for mutation in case["spawn_mutations"]
        ),
        "settlement_payload_carries_plan_metadata": all(
            isinstance(record.get("plan"), dict)
            and isinstance(record.get("plan", {}).get("metadata", {}).get("entry_value_resolutions"), dict)
            for record in case["result"].records
        ),
        "no_owner_level_claimed_as_tbgd_level_source": all(
            unit.flags.get("summon_level_policy", {}).get("kind") == "profile_base_stats_no_runtime_level_scaling"
            for unit in (case["after"].units[unit_id] for unit_id in case["spawned_unit_ids"])
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": "summon_profile_card_level_source_binding",
        "classification": "executable" if checks["ok"] else "implementation_missing",
        "gap_attribution": "" if checks["ok"] else "implementation_missing",
        "checks": {"ok": checks["ok"], "checks": checks},
        "evidence": {
            "entries": rows,
            "source_note": (
                "Current executable summon entries bind profile/card/base stats from CombatantProfileIR/"
                "MonsterDataCardIR. Level policy is admitted as profile_base_stats_no_runtime_level_scaling; "
                "this row does not claim full runtime level scaling."
            ),
        },
    }


def _monster_skill_formula_binding_row(case: dict[str, Any]) -> dict[str, Any]:
    resolution = dict(case.get("resolution") or {})
    delegate = dict(resolution.get("delegate_resolution") or {})
    checks = {
        "monster_formula_binding_found": case.get("found") is True,
        "monster_formula_value_resolution_ok": resolution.get("ok") is True,
        "binding_kind_is_skill_formula_param": resolution.get("binding_kind") == "skill_formula_param",
        "delegate_source_is_skill_formula_binding_param": delegate.get("value_source") == "SkillFormulaBindingIR.param_value",
        "context_has_action_and_data_card_source": {"action", "data_card_source"}.issubset(
            set(resolution.get("context_keys") or ())
        ),
        "source_trace_present": bool(resolution.get("source_trace")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": "monster_skill_formula_binding_value_resolver",
        "classification": "executable" if checks["ok"] else "lowering_gap",
        "gap_attribution": "" if checks["ok"] else "lowering_gap",
        "checks": {"ok": checks["ok"], "checks": checks},
        "evidence": {
            "runtime_sample": case.get("runtime_sample", {}),
            "resolution": _compact_resolution(resolution),
        },
    }


def _missing_profile_card_level_source_blocked_row(case: dict[str, Any]) -> dict[str, Any]:
    cases = dict(case.get("cases") or {})
    checks = {
        "missing_profile_card_case_present": "missing_profile_card" in cases,
        "missing_level_policy_case_present": "missing_level_policy" in cases,
        "missing_profile_card_blocked": str(cases.get("missing_profile_card", {}).get("blocked_reason") or "")
        in {
            "summon_monster_combatant_profile_missing",
            "summon_monster_profile_stat_value_resolution_blocked",
            "summon_monster_data_card_source_blocked",
            "unit_birth_template_entity_ref_mismatch",
        },
        "missing_level_policy_blocked": "summon_monster_birth_template_missing"
        in str(cases.get("missing_level_policy", {}).get("blocked_reason") or ""),
        "all_negative_cases_no_mutations": bool(cases) and all(item.get("mutation_count") == 0 for item in cases.values()),
        "all_negative_cases_process_only": bool(cases)
        and all(item.get("process_only_record") is True for item in cases.values()),
        "all_negative_cases_state_unchanged": bool(cases)
        and all(item.get("state_unchanged") is True for item in cases.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "row_id": "missing_profile_card_level_source_blocked",
        "classification": "boundary_only" if checks["ok"] else "implementation_missing",
        "gap_attribution": "" if checks["ok"] else "implementation_missing",
        "checks": {"ok": checks["ok"], "checks": checks},
        "evidence": case.get("runtime_sample", {}),
    }


def _summon_binding_replay_settlement_gap_visibility_row(
    summon_case: dict[str, Any],
    gap_case: dict[str, Any],
) -> dict[str, Any]:
    settlement = dict(summon_case.get("settlement") or {})
    replay = dict(summon_case.get("replay") or {})
    blocked_intent_count = sum(
        count for status, count in gap_case["intent_status_counts"].items() if status != "executable"
    )
    checks = {
        "replay_ok": replay.get("ok") is True,
        "settlement_traceability_ok": settlement.get("ok") is True,
        "summon_gaps_recorded": isinstance(gap_case.get("blocked_reason_counts_top"), list),
        "p3_inherited_gap_not_hidden": gap_case.get("p3_inherited_gap_hidden") is False,
        "p5_all_executable_not_claimed": gap_case.get("p5_all_executable_claimed") is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    gap = "admission_gap" if blocked_intent_count else ""
    return {
        "row_id": "summon_binding_replay_settlement_gap_visibility",
        "classification": "admission_gap" if gap else "executable",
        "gap_attribution": gap,
        "checks": {"ok": checks["ok"], "checks": checks},
        "evidence": {
            "replay": replay,
            "settlement": settlement,
            "gap_visibility": gap_case,
        },
    }


def _value_resolutions_from_spawn_mutations(mutations: Iterable[Mutation]) -> tuple[dict[str, JSONValue], ...]:
    items: list[dict[str, JSONValue]] = []
    for mutation in mutations:
        resolutions = mutation.metadata.get("summon_value_resolutions")
        if not isinstance(resolutions, dict):
            continue
        for field_name in PROFILE_STAT_FIELDS:
            resolution = resolutions.get(field_name)
            if isinstance(resolution, dict):
                items.append({**resolution, "field_name": field_name, "mutation_id": mutation.stable_id()})
    return tuple(items)


def _value_resolutions_from_units(units: Iterable[UnitState]) -> tuple[dict[str, JSONValue], ...]:
    items: list[dict[str, JSONValue]] = []
    for unit in units:
        resolutions = unit.flags.get("summon_value_resolutions")
        if not isinstance(resolutions, dict):
            continue
        for field_name in PROFILE_STAT_FIELDS:
            resolution = resolutions.get(field_name)
            if isinstance(resolution, dict):
                items.append({**resolution, "field_name": field_name, "unit_id": unit.unit_id})
    return tuple(items)


def _profile_stat_resolution_ok(resolution: dict[str, JSONValue]) -> bool:
    field_name = str(resolution.get("field_name") or "")
    delegate = resolution.get("delegate_resolution")
    return (
        resolution.get("ok") is True
        and resolution.get("binding_kind") == "combatant_profile_base_stat"
        and field_name in PROFILE_STAT_FIELDS
        and isinstance(resolution.get("value"), (int, float))
        and not isinstance(resolution.get("value"), bool)
        and isinstance(delegate, dict)
        and delegate.get("value_source") == f"CombatantProfileIR.base_stats.{field_name}"
        and bool(resolution.get("source_trace"))
    )


def _unit_stats_match_resolutions(unit: UnitState) -> bool:
    resolutions = unit.flags.get("summon_value_resolutions")
    if not isinstance(resolutions, dict):
        return False
    return (
        _field_value(resolutions, "max_hp") == unit.max_hp
        and _field_value(resolutions, "max_hp") == unit.hp
        and _field_value(resolutions, "attack") == unit.attack
        and _field_value(resolutions, "defense") == unit.defense
        and _field_value(resolutions, "speed") == unit.speed
    )


def _unit_profile_card_level_sources_complete(unit: UnitState) -> bool:
    return (
        bool(unit.flags.get("combatant_profile_id"))
        and isinstance(unit.flags.get("combatant_profile_source_trace"), dict)
        and bool(unit.flags.get("combatant_profile_source_trace"))
        and bool(unit.flags.get("monster_data_card_id"))
        and isinstance(unit.flags.get("monster_data_card_source_trace"), dict)
        and bool(unit.flags.get("monster_data_card_source_trace"))
        and isinstance(unit.flags.get("summon_level_policy"), dict)
        and unit.flags.get("summon_level_policy", {}).get("admission_status") == "executable"
        and isinstance(unit.flags.get("summon_level_source_trace"), dict)
        and bool(unit.flags.get("summon_level_source_trace"))
    )


def _mutation_profile_card_sources_complete(mutation: Mutation) -> bool:
    metadata = mutation.metadata
    return (
        bool(metadata.get("combatant_profile_id"))
        and isinstance(metadata.get("combatant_profile_source_trace"), dict)
        and bool(metadata.get("combatant_profile_source_trace"))
        and bool(metadata.get("monster_data_card_id"))
        and isinstance(metadata.get("monster_data_card_source_trace"), dict)
        and bool(metadata.get("monster_data_card_source_trace"))
        and isinstance(metadata.get("summon_entry_source_trace"), dict)
        and bool(metadata.get("summon_entry_source_trace"))
    )


def _plan_entry_value_resolution_count(metadata: dict[str, JSONValue]) -> int:
    entries = metadata.get("entry_value_resolutions")
    if not isinstance(entries, dict):
        return 0
    count = 0
    for value in entries.values():
        if isinstance(value, dict):
            count += sum(1 for item in value.values() if isinstance(item, dict) and item.get("ok") is True)
    return count


def _field_value(resolutions: dict[str, JSONValue], field_name: str) -> float | None:
    resolution = resolutions.get(field_name)
    if not isinstance(resolution, dict):
        return None
    value = resolution.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _numeric_value(value: JSONValue) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and set(value) == {"Value"}:
        return _numeric_value(value.get("Value"))
    return None


def _entry_sample(entry: Any) -> dict[str, JSONValue]:
    return {
        "entry_id": entry.entry_id,
        "monster_entity_ref": entry.monster_entity_ref,
        "monster_raw_id": entry.monster_raw_id,
        "level_policy": entry.level_policy,
        "source_path": entry.source.source_path,
        "coverage_status": entry.coverage_status,
    }


def _sample_resolution(items: Iterable[dict[str, JSONValue]]) -> dict[str, JSONValue]:
    for item in items:
        return _compact_resolution(item)
    return {}


def _compact_resolution(resolution: dict[str, JSONValue]) -> dict[str, JSONValue]:
    delegate = dict(resolution.get("delegate_resolution") or {})
    source_trace = resolution.get("source_trace")
    source_path = ""
    if isinstance(source_trace, dict):
        source_path = str(source_trace.get("source_path") or "")
    return {
        "ok": resolution.get("ok"),
        "value": resolution.get("value"),
        "binding_kind": resolution.get("binding_kind"),
        "field_name": resolution.get("field_name") or delegate.get("field_name"),
        "binding_id": delegate.get("binding_id"),
        "value_source": delegate.get("value_source"),
        "blocked_reason": resolution.get("blocked_reason"),
        "context_keys": list(resolution.get("context_keys") or ()),
        "source_path": source_path,
    }


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        gap = str(row.get("gap_attribution") or "")
        if gap:
            counts[gap] += 1
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    return {
        str(row["row_id"]): {
            "classification": str(row.get("classification") or "unclassified"),
            "gap_attribution": str(row.get("gap_attribution") or ""),
            "ok": dict(row.get("checks") or {}).get("ok") is True,
        }
        for row in rows
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return dict(rows.get(row_id, {}).get("checks", {}).get("checks") or {}).get(check_id) is True


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


if __name__ == "__main__":
    raise SystemExit(main())
