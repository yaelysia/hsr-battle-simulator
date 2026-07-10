from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, UnitState
from ..rules.rulebook import RuleBook
from ..systems.summon import SummonSystem
from ..systems.wave import WAVE_RUNTIME_SCHEMA_VERSION, WaveSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p1_3_summon_assistant_servant import (
    _base_servant_state,
    _base_summon_state,
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
)
from .validate_p1_8_battle_setup import _select_two_wave_definition


VALIDATION_VERSION = "p6_s2_s3_unit_spawn_birth_plan"
MATRIX_SCHEMA_VERSION = "p6_s2_s3_unit_spawn_birth_plan_matrix_v2"

CLASSIFICATION_STATES = {"executable", "boundary_guard", "implementation_missing"}
REQUIRED_ROWS = {
    "unit_birth_template_ir_projection",
    "summoned_monster_birth_plan_positive",
    "summoned_monster_missing_birth_plan_negative",
    "summoned_monster_incomplete_birth_plan_negative",
    "summoned_monster_tampered_birth_plan_negative",
    "servant_birth_plan_positive",
    "servant_missing_birth_plan_negative",
    "servant_incomplete_birth_plan_negative",
    "servant_tampered_birth_plan_negative",
    "wave_birth_plan_positive",
    "wave_missing_birth_plan_negative",
    "wave_incomplete_birth_plan_negative",
    "wave_tampered_birth_plan_negative",
    "wave_stage_level_source_contract",
    "apply_stage_static_guard",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    matrix = build_matrix(package_root, rules)
    matrix_checks = validate_matrix(matrix)
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": matrix_checks["ok"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_summon_servant_wave_birth_plan_samples",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
            },
        },
        "checks": {"matrix": matrix_checks},
        "summary": matrix["summary"],
        "unit_spawn_birth_plan_matrix": matrix["unit_spawn_birth_plan_matrix"],
        "resource_budget": matrix["resource_budget"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p6_s2_s3_unit_spawn_birth_plan.json", result)
    write_json(output_dir / "p6_s2_s3_unit_spawn_birth_plan_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P6-S2/S3 unit spawn birth-plan boundary.")
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
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_matrix(package_root: Path, rules: RuleBook) -> dict[str, Any]:
    summon_case = _summon_case(rules)
    servant_case = _servant_case(rules)
    wave_case = _wave_case(rules)
    rows = [
        _unit_birth_template_ir_projection_row(package_root, rules),
        _summon_positive_row(summon_case),
        _summon_negative_row(summon_case),
        _summon_incomplete_negative_row(summon_case),
        _summon_tampered_negative_row(summon_case),
        _servant_positive_row(servant_case),
        _servant_negative_row(servant_case),
        _servant_incomplete_negative_row(servant_case),
        _servant_tampered_negative_row(servant_case),
        _wave_positive_row(wave_case),
        _wave_negative_row(wave_case),
        _wave_incomplete_negative_row(wave_case),
        _wave_tampered_negative_row(wave_case),
        _wave_stage_level_source_row(package_root, wave_case),
        _static_guard_row(package_root),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "unit_spawn_birth_plan_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "summon_spawn_plan_count": len(summon_case["spawn_plans"]),
            "servant_spawn_plan_count": len(servant_case["spawn_plans"]),
            "wave_spawn_plan_count": len(wave_case["spawn_plans"]),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "summon_runtime_sample_count": 1,
            "servant_runtime_sample_count": 1,
            "wave_runtime_sample_count": 1,
            "negative_missing_birth_plan_count": 3,
            "negative_incomplete_birth_plan_count": 14,
            "negative_tampered_birth_plan_count": 17,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p6_s2_s3_unit_spawn_birth_plan.json",
                "p6_s2_s3_unit_spawn_birth_plan_matrix.json",
            ],
        },
    }


def validate_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("unit_spawn_birth_plan_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "") not in CLASSIFICATION_STATES
    )
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "positive_birth_plans_present": _row_check(rows, "summoned_monster_birth_plan_positive", "birth_plans_present")
        and _row_check(rows, "servant_birth_plan_positive", "birth_plans_present")
        and _row_check(rows, "wave_birth_plan_positive", "birth_plans_present"),
        "missing_birth_plan_blocks": _row_check(rows, "summoned_monster_missing_birth_plan_negative", "no_mutations")
        and _row_check(rows, "servant_missing_birth_plan_negative", "no_mutations")
        and _row_check(rows, "wave_missing_birth_plan_negative", "no_mutations"),
        "incomplete_birth_plan_blocks": _row_check(rows, "summoned_monster_incomplete_birth_plan_negative", "all_variants_blocked")
        and _row_check(rows, "servant_incomplete_birth_plan_negative", "all_variants_blocked")
        and _row_check(rows, "wave_incomplete_birth_plan_negative", "all_variants_blocked"),
        "tampered_birth_plan_blocks": _row_check(rows, "summoned_monster_tampered_birth_plan_negative", "all_variants_blocked")
        and _row_check(rows, "servant_tampered_birth_plan_negative", "all_variants_blocked")
        and _row_check(rows, "wave_tampered_birth_plan_negative", "all_variants_blocked"),
        "birth_templates_are_first_class_ir": _row_check(
            rows, "unit_birth_template_ir_projection", "all_executable_sources_reference_templates"
        )
        and _row_check(rows, "unit_birth_template_ir_projection", "runtime_materializer_has_no_rulebook"),
        "wave_level_is_source_backed": _row_check(rows, "wave_stage_level_source_contract", "spawned_level_matches_stage")
        and _row_check(rows, "wave_stage_level_source_contract", "hard_level_source_present")
        and _row_check(rows, "wave_stage_level_source_contract", "no_level_80_literal_in_spawn_runtime"),
        "static_guard_ok": _row_check(rows, "apply_stage_static_guard", "summon_apply_no_unit_from_entry_call")
        and _row_check(rows, "apply_stage_static_guard", "servant_apply_no_unit_from_definition_call")
        and _row_check(rows, "apply_stage_static_guard", "wave_apply_no_unit_from_wave_entry_call"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _summon_case(rules: RuleBook) -> dict[str, Any]:
    intent = _select_executable_summon_monster_intent(rules)
    state = _base_summon_state()
    system = SummonSystem(rules)
    plan = system.plan_spawn_from_intent(state, intent, owner_id="enemy:summoner")
    result = system.apply_spawn(state, plan)
    spawn_plans = _spawn_plans(plan.metadata)
    missing_plan = replace(plan, metadata={**plan.metadata, "unit_spawn_plans": []})
    missing_result = system.apply_spawn(state, missing_plan)
    state_before = state.snapshot().to_json()
    incomplete_results = {
        label: system.apply_spawn(state, replace(plan, metadata=_metadata_with_first_spawn_plan(plan.metadata, spawn_plan)))
        for label, spawn_plan in _incomplete_summon_spawn_plans(spawn_plans).items()
    }
    tampered_results = {
        label: system.apply_spawn(state, replace(plan, metadata=_metadata_with_first_spawn_plan(plan.metadata, spawn_plan)))
        for label, spawn_plan in _tampered_summon_spawn_plans(spawn_plans).items()
    }
    return {
        "intent_id": intent.summon_intent_id,
        "plan": plan,
        "result": result,
        "spawn_plans": spawn_plans,
        "missing_result": missing_result,
        "incomplete_results": incomplete_results,
        "incomplete_state_unchanged": state.snapshot().to_json() == state_before,
        "tampered_results": tampered_results,
        "tampered_state_unchanged": state.snapshot().to_json() == state_before,
    }


def _servant_case(rules: RuleBook) -> dict[str, Any]:
    definition = _select_executable_servant_definition(rules)
    state = _base_servant_state(definition)
    owner_id = next(iter(state.units))
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id=owner_id)
    result = system.apply_spawn_servant(state, plan)
    spawn_plans = _spawn_plans(plan.metadata)
    missing_plan = replace(plan, metadata={**plan.metadata, "unit_spawn_plans": []})
    missing_result = system.apply_spawn_servant(state, missing_plan)
    state_before = state.snapshot().to_json()
    incomplete_results = {
        label: system.apply_spawn_servant(
            state,
            replace(plan, metadata=_metadata_with_first_spawn_plan(plan.metadata, spawn_plan)),
        )
        for label, spawn_plan in _incomplete_servant_spawn_plans(spawn_plans).items()
    }
    tampered_results = {
        label: system.apply_spawn_servant(
            state,
            replace(plan, metadata=_metadata_with_first_spawn_plan(plan.metadata, spawn_plan)),
        )
        for label, spawn_plan in _tampered_servant_spawn_plans(spawn_plans).items()
    }
    return {
        "servant_definition_id": definition.servant_definition_id,
        "plan": plan,
        "result": result,
        "spawn_plans": spawn_plans,
        "missing_result": missing_result,
        "incomplete_results": incomplete_results,
        "incomplete_state_unchanged": state.snapshot().to_json() == state_before,
        "tampered_results": tampered_results,
        "tampered_state_unchanged": state.snapshot().to_json() == state_before,
    }


def _wave_case(rules: RuleBook) -> dict[str, Any]:
    definition = _select_two_wave_definition(rules)
    current_entry = rules.wave_entries_for_wave(definition.wave_definition_id, 0)[0]
    current_unit_id = _wave_unit_id(definition.stage_id, current_entry.wave_index, current_entry.position)
    state = BattleState(
        units={
            "ally:p6_wave": UnitState(
                unit_id="ally:p6_wave",
                side="ally",
                template_id="validation:p6_wave_ally",
                max_hp=1000.0,
                hp=1000.0,
                speed=100.0,
                flags={"position": 0},
            ),
            current_unit_id: UnitState(
                unit_id=current_unit_id,
                side="enemy",
                template_id=current_entry.monster_entity_ref,
                max_hp=1000.0,
                hp=0.0,
                speed=100.0,
                flags={
                    "position": current_entry.position,
                    "lifecycle_status": "defeated",
                    "defeat_record": {"reason": "p6_s3_wave_transition_fixture"},
                    "wave_member_kind": "stage_wave_enemy",
                    "wave_clear_policy": "counts",
                    "wave_index": current_entry.wave_index,
                },
            ),
        },
        wave_index=0,
        global_flags={
            "wave_runtime": {
                "schema_version": WAVE_RUNTIME_SCHEMA_VERSION,
                "wave_definition_id": definition.wave_definition_id,
                "current_wave_index": 0,
                "total_waves": int(definition.wave_count),
                "status": "active",
                "current_wave_unit_ids": [current_unit_id],
                "source_trace": definition.source.to_json(),
            }
        },
    )
    system = WaveSystem(rules)
    plan = system.plan_transition(state)
    result = system.apply_transition(state, plan)
    spawn_plans = tuple(plan.spawn_unit_plans)
    missing_plan = replace(plan, spawn_unit_plans=())
    missing_result = system.apply_transition(state, missing_plan)
    state_before = state.snapshot().to_json()
    incomplete_results = {
        label: system.apply_transition(state, replace(plan, spawn_unit_plans=(spawn_plan, *spawn_plans[1:])))
        for label, spawn_plan in _incomplete_wave_spawn_plans(spawn_plans).items()
    }
    tampered_results = {
        label: system.apply_transition(state, replace(plan, spawn_unit_plans=(spawn_plan, *spawn_plans[1:])))
        for label, spawn_plan in _tampered_wave_spawn_plans(spawn_plans).items()
    }
    return {
        "definition": definition,
        "wave_definition_id": definition.wave_definition_id,
        "plan": plan,
        "result": result,
        "spawn_plans": spawn_plans,
        "missing_result": missing_result,
        "incomplete_results": incomplete_results,
        "incomplete_state_unchanged": state.snapshot().to_json() == state_before,
        "tampered_results": tampered_results,
        "tampered_state_unchanged": state.snapshot().to_json() == state_before,
    }


def _unit_birth_template_ir_projection_row(package_root: Path, rules: RuleBook) -> dict[str, JSONValue]:
    templates = rules.unit_birth_templates()
    template_by_id = {template.birth_template_id: template for template in templates}
    executable_sources = [
        *(entry for intent in rules.summon_monster_intents() if intent.coverage_status == "executable" for entry in intent.entries),
        *(definition for definition in rules.servant_definitions() if definition.coverage_status == "executable"),
        *(
            entry
            for definition in rules.wave_definitions()
            if definition.coverage_status == "executable"
            for entry in definition.entries
            if entry.coverage_status == "executable"
        ),
    ]
    referenced_templates = [template_by_id.get(item.birth_template_id) for item in executable_sources]
    unit_spawn_source = (package_root / "systems" / "unit_spawn.py").read_text(encoding="utf-8")
    summon_source = (package_root / "systems" / "summon.py").read_text(encoding="utf-8")
    wave_source = (package_root / "systems" / "wave.py").read_text(encoding="utf-8")
    checks = _checks(
        {
            "templates_present": bool(templates),
            "all_template_kinds_present": {"summoned_monster", "servant", "wave_enemy"}.issubset(
                {template.spawn_kind for template in templates}
            ),
            "all_executable_sources_reference_templates": bool(executable_sources)
            and all(template is not None and template.coverage_status == "executable" for template in referenced_templates),
            "runtime_materializer_has_no_rulebook": "RuleBook" not in unit_spawn_source,
            "runtime_materializer_has_no_content_ir_types": all(
                token not in unit_spawn_source
                for token in ("CombatantProfileIR", "MonsterDataCardIR", "ServantDefinitionIR", "WaveDefinitionIR")
            ),
            "summon_runtime_consumes_template_accessor": "self.rules.unit_birth_template(" in summon_source,
            "wave_runtime_consumes_template_accessor": "self.rules.unit_birth_template(" in wave_source,
        }
    )
    return _row(
        "unit_birth_template_ir_projection",
        checks,
        {
            "template_count": len(templates),
            "template_kind_counts": dict(sorted(Counter(template.spawn_kind for template in templates).items())),
            "executable_source_count": len(executable_sources),
            "executable_referenced_template_count": sum(
                1 for template in referenced_templates if template is not None and template.coverage_status == "executable"
            ),
        },
        "boundary_guard",
    )


def _summon_positive_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "plan_ok": case["plan"].ok,
            "birth_plans_present": bool(case["spawn_plans"]),
            "birth_plan_count_matches_units": len(case["spawn_plans"]) == len(case["plan"].unit_ids),
            "spawn_mutation_present": bool(case["result"].mutations),
            "spawn_mutation_uses_birth_plan_unit": all(
                mutation.after.get("unit_id") in case["plan"].unit_ids
                for mutation in case["result"].mutations
                if isinstance(mutation.after, dict) and mutation.metadata.get("lifecycle_operation") == "unit_spawn"
            ),
        }
    )
    return _row("summoned_monster_birth_plan_positive", checks, case, "executable")


def _summon_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    result = case["missing_result"]
    checks = _checks(
        {
            "blocked": not result.plan.ok,
            "blocked_reason_present": bool(result.plan.blocked_reason),
            "no_mutations": not result.mutations,
            "process_only_record": bool(result.records) and all(record.get("process_only") for record in result.records),
        }
    )
    return _row("summoned_monster_missing_birth_plan_negative", checks, {"blocked_reason": result.plan.blocked_reason}, "boundary_guard")


def _summon_incomplete_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _incomplete_birth_plan_row(
        "summoned_monster_incomplete_birth_plan_negative",
        case,
        expected_reason_prefix="summon_unit_spawn_plan_invalid:",
    )


def _summon_tampered_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _tampered_birth_plan_row(
        "summoned_monster_tampered_birth_plan_negative",
        case,
        expected_reason_prefix="summon_unit_spawn_plan_invalid:",
    )


def _servant_positive_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "plan_ok": case["plan"].ok,
            "birth_plans_present": bool(case["spawn_plans"]),
            "birth_plan_count_matches_units": len(case["spawn_plans"]) == len(case["plan"].unit_ids),
            "spawn_mutation_present": bool(case["result"].mutations),
        }
    )
    return _row("servant_birth_plan_positive", checks, case, "executable")


def _servant_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    result = case["missing_result"]
    checks = _checks(
        {
            "blocked": not result.plan.ok,
            "blocked_reason_present": bool(result.plan.blocked_reason),
            "no_mutations": not result.mutations,
            "process_only_record": bool(result.records) and all(record.get("process_only") for record in result.records),
        }
    )
    return _row("servant_missing_birth_plan_negative", checks, {"blocked_reason": result.plan.blocked_reason}, "boundary_guard")


def _servant_incomplete_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _incomplete_birth_plan_row(
        "servant_incomplete_birth_plan_negative",
        case,
        expected_reason_prefix="servant_unit_spawn_plan_invalid:",
    )


def _servant_tampered_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _tampered_birth_plan_row(
        "servant_tampered_birth_plan_negative",
        case,
        expected_reason_prefix="servant_unit_spawn_plan_invalid:",
    )


def _wave_positive_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    checks = _checks(
        {
            "plan_advances": case["plan"].status == "advance_to_next_wave",
            "birth_plans_present": bool(case["spawn_plans"]),
            "birth_plan_count_matches_entries": len(case["spawn_plans"]) == len(case["plan"].spawn_entries),
            "spawn_mutation_present": any(
                mutation.metadata.get("lifecycle_operation") == "unit_spawn" for mutation in case["result"].mutations
            ),
        }
    )
    return _row("wave_birth_plan_positive", checks, case, "executable")


def _wave_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    result = case["missing_result"]
    checks = _checks(
        {
            "blocked": not result.plan.ok,
            "blocked_reason_present": bool(result.plan.blocked_reason),
            "no_mutations": not result.mutations,
            "process_only_record": bool(result.records) and all(record.get("process_only") for record in result.records),
        }
    )
    return _row("wave_missing_birth_plan_negative", checks, {"blocked_reason": result.plan.blocked_reason}, "boundary_guard")


def _wave_incomplete_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _incomplete_birth_plan_row(
        "wave_incomplete_birth_plan_negative",
        case,
        expected_reason_prefix="wave_unit_spawn_plan_invalid:",
    )


def _wave_tampered_negative_row(case: dict[str, Any]) -> dict[str, JSONValue]:
    return _tampered_birth_plan_row(
        "wave_tampered_birth_plan_negative",
        case,
        expected_reason_prefix="wave_unit_spawn_plan_invalid:",
    )


def _wave_stage_level_source_row(package_root: Path, case: dict[str, Any]) -> dict[str, JSONValue]:
    definition = case["definition"]
    spawn_plan = case["spawn_plans"][0] if case["spawn_plans"] else {}
    unit = spawn_plan.get("unit") if isinstance(spawn_plan.get("unit"), dict) else {}
    flags = unit.get("flags") if isinstance(unit.get("flags"), dict) else {}
    runtime_source = "\n".join(
        (package_root / relative).read_text(encoding="utf-8")
        for relative in ("systems/unit_spawn.py", "systems/wave.py")
    )
    checks = _checks(
        {
            "stage_level_positive": isinstance(definition.level, int) and definition.level > 0,
            "hard_level_group_positive": isinstance(definition.hard_level_group, int)
            and definition.hard_level_group > 0,
            "level_policy_executable": definition.level_policy.get("admission_status") == "executable",
            "spawned_level_matches_stage": unit.get("level") == definition.level,
            "hard_level_source_present": flags.get("hard_level_group") == definition.hard_level_group
            and isinstance(flags.get("stage_level_source_trace"), dict)
            and bool(flags.get("stage_level_source_trace")),
            "stage_ratios_applied": flags.get("wave_stat_scaling", {}).get("kind")
            == "combatant_profile_times_stage_hard_level_ratios",
            "no_level_80_literal_in_spawn_runtime": "level=80" not in runtime_source
            and '"level": 80' not in runtime_source,
        }
    )
    return _row(
        "wave_stage_level_source_contract",
        checks,
        {
            "wave_definition_id": definition.wave_definition_id,
            "level": definition.level,
            "hard_level_group": definition.hard_level_group,
            "level_policy": definition.level_policy,
            "spawned_level": unit.get("level"),
        },
        "executable",
    )


def _incomplete_birth_plan_row(
    row_id: str,
    case: dict[str, Any],
    *,
    expected_reason_prefix: str,
) -> dict[str, JSONValue]:
    results = case["incomplete_results"]
    checks = _checks(
        {
            "variant_count": len(results) >= 4,
            "all_variants_blocked": all(not result.plan.ok for result in results.values()),
            "all_reasons_present": all(bool(result.plan.blocked_reason) for result in results.values()),
            "all_reasons_mark_invalid_spawn_plan": all(
                str(result.plan.blocked_reason).startswith(expected_reason_prefix) for result in results.values()
            ),
            "no_mutations": all(not result.mutations for result in results.values()),
            "process_only_records": all(
                bool(result.records) and all(record.get("process_only") for record in result.records)
                for result in results.values()
            ),
            "state_unchanged": bool(case.get("incomplete_state_unchanged")),
        }
    )
    return _row(
        row_id,
        checks,
        {
            "variant_count": len(results),
            "blocked_reasons": {label: result.plan.blocked_reason for label, result in sorted(results.items())},
        },
        "boundary_guard",
    )


def _tampered_birth_plan_row(
    row_id: str,
    case: dict[str, Any],
    *,
    expected_reason_prefix: str,
) -> dict[str, JSONValue]:
    results = case["tampered_results"]
    checks = _checks(
        {
            "variant_count": len(results) >= 5,
            "all_variants_blocked": all(not result.plan.ok for result in results.values()),
            "all_reasons_present": all(bool(result.plan.blocked_reason) for result in results.values()),
            "all_reasons_mark_invalid_spawn_plan": all(
                str(result.plan.blocked_reason).startswith(expected_reason_prefix) for result in results.values()
            ),
            "no_mutations": all(not result.mutations for result in results.values()),
            "process_only_records": all(
                bool(result.records) and all(record.get("process_only") for record in result.records)
                for result in results.values()
            ),
            "state_unchanged": bool(case.get("tampered_state_unchanged")),
        }
    )
    return _row(
        row_id,
        checks,
        {
            "variant_count": len(results),
            "blocked_reasons": {label: result.plan.blocked_reason for label, result in sorted(results.items())},
        },
        "boundary_guard",
    )


def _static_guard_row(package_root: Path) -> dict[str, JSONValue]:
    summon_source = (package_root / "systems" / "summon.py").read_text(encoding="utf-8")
    wave_source = (package_root / "systems" / "wave.py").read_text(encoding="utf-8")
    unit_spawn_source = (package_root / "systems" / "unit_spawn.py").read_text(encoding="utf-8")
    ir_source = (package_root / "rules" / "ir.py").read_text(encoding="utf-8")
    apply_spawn = _function_source(summon_source, "    def apply_spawn(")
    apply_servant = _function_source(summon_source, "    def apply_spawn_servant(")
    apply_wave = _function_source(wave_source, "    def apply_transition(")
    plan_summon = _function_source(summon_source, "    def plan_spawn_summoned_monster(")
    plan_servant = _function_source(summon_source, "    def plan_spawn_servant(")
    plan_wave = _function_source(wave_source, "    def plan_transition(")
    checks = _checks(
        {
            "summon_apply_consumes_birth_plan": "spawn_plans_from_metadata(plan.metadata)" in apply_spawn,
            "summon_apply_no_unit_from_entry_call": "self._unit_from_entry(" not in apply_spawn,
            "servant_apply_consumes_birth_plan": "spawn_plans_from_metadata(plan.metadata)" in apply_servant,
            "servant_apply_no_unit_from_definition_call": "self._unit_from_servant_definition(" not in apply_servant,
            "wave_apply_consumes_birth_plan": "spawn_plans_from_metadata" in apply_wave,
            "wave_apply_no_unit_from_wave_entry_call": "_unit_from_wave_entry(" not in apply_wave,
            "summon_plan_uses_birth_template": "self.rules.unit_birth_template(" in plan_summon
            and "self.unit_spawn.plan(" in plan_summon,
            "servant_plan_uses_birth_template": "self.rules.unit_birth_template(" in plan_servant
            and "self.unit_spawn.plan(" in plan_servant,
            "wave_plan_uses_birth_template": "self.rules.unit_birth_template(" in plan_wave
            and "self.unit_spawn.plan(" in plan_wave,
            "unit_spawn_materializer_no_rulebook": "RuleBook" not in unit_spawn_source,
            "unit_spawn_materializer_no_content_lookup": all(
                token not in unit_spawn_source
                for token in ("combatant_profile(", "monster_data_card_for_entity", "servant_definition(")
            ),
            "unit_birth_template_ir_present": "class UnitBirthTemplateIR:" in ir_source
            and "unit_birth_templates: tuple[UnitBirthTemplateIR" in ir_source,
            "wave_runtime_no_level_80_literal": "level=80" not in wave_source
            and "level=80" not in unit_spawn_source,
        }
    )
    return _row(
        "apply_stage_static_guard",
        checks,
        {
            "checked_files": ["rules/ir.py", "systems/unit_spawn.py", "systems/summon.py", "systems/wave.py"],
            "policy": "L0 projects UnitBirthTemplateIR; runtime materializes and validates request-bound UnitSpawnPlan payloads.",
        },
        "boundary_guard",
    )


def _row(row_id: str, checks: dict[str, JSONValue], details: dict[str, Any], success_classification: str) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": success_classification if checks["ok"] else "implementation_missing",
        "checks": {"ok": bool(checks["ok"]), "checks": checks},
        "details": _compact_details(details),
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _spawn_plans(metadata: dict[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    raw = metadata.get("unit_spawn_plans") if isinstance(metadata, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, dict))


def _metadata_with_first_spawn_plan(
    metadata: dict[str, JSONValue],
    spawn_plan: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    existing = list(_spawn_plans(metadata))
    if existing:
        existing[0] = spawn_plan
    else:
        existing.append(spawn_plan)
    return {**metadata, "unit_spawn_plans": existing}


def _incomplete_summon_spawn_plans(spawn_plans: tuple[dict[str, JSONValue], ...]) -> dict[str, dict[str, JSONValue]]:
    return _incomplete_spawn_plan_variants(
        spawn_plans,
        owner_flag="owner_id",
        source_flag="summon_source_trace",
    )


def _incomplete_servant_spawn_plans(spawn_plans: tuple[dict[str, JSONValue], ...]) -> dict[str, dict[str, JSONValue]]:
    return _incomplete_spawn_plan_variants(
        spawn_plans,
        owner_flag="owner_id",
        source_flag="servant_definition_source_trace",
    )


def _incomplete_wave_spawn_plans(spawn_plans: tuple[dict[str, JSONValue], ...]) -> dict[str, dict[str, JSONValue]]:
    variants = _incomplete_spawn_plan_variants(
        spawn_plans,
        owner_flag="wave_definition_id",
        source_flag="wave_entry_source_trace",
    )
    if spawn_plans:
        variants["missing_level"] = _corrupt_spawn_plan(spawn_plans[0], remove_unit_keys=("level",))
        variants["missing_stage_level_source"] = _corrupt_spawn_plan(
            spawn_plans[0],
            remove_flag_keys=("stage_level_source_trace",),
        )
    return variants


def _tampered_summon_spawn_plans(
    spawn_plans: tuple[dict[str, JSONValue], ...],
) -> dict[str, dict[str, JSONValue]]:
    if not spawn_plans:
        return {}
    first = spawn_plans[0]
    injected_trace = {"source_path": "validation/tampered", "raw_type": "Tampered", "raw_id": "injected"}
    return {
        "unit_identity": _tamper_spawn_plan(
            first,
            plan_updates={"unit_id": "enemy:injected"},
            request_updates={"unit_id": "enemy:injected"},
            unit_updates={"unit_id": "enemy:injected"},
        ),
        "spawn_kind": _tamper_spawn_plan(first, metadata_updates={"spawn_plan_kind": "servant"}),
        "entity_ref": _tamper_spawn_plan(
            first,
            request_updates={"entity_ref": "monster:injected"},
            unit_updates={"template_id": "monster:injected"},
        ),
        "owner": _tamper_spawn_plan(
            first,
            request_updates={"owner_id": "enemy:injected_owner", "summoner_id": "enemy:injected_owner"},
            flag_updates={"owner_id": "enemy:injected_owner", "summoner_id": "enemy:injected_owner"},
        ),
        "summon_source": _tamper_spawn_plan(
            first,
            request_updates={"source_id": "summon_intent:injected", "source_trace": injected_trace},
            flag_updates={"summon_intent_id": "summon_intent:injected", "summon_source_trace": injected_trace},
        ),
        "summon_entry": _tamper_spawn_plan(
            first,
            plan_updates={"source_trace": injected_trace},
            request_updates={"entry_id": "summon_entry:injected", "entry_source_trace": injected_trace},
            flag_updates={"summon_entry_id": "summon_entry:injected", "summon_entry_source_trace": injected_trace},
        ),
    }


def _tampered_servant_spawn_plans(
    spawn_plans: tuple[dict[str, JSONValue], ...],
) -> dict[str, dict[str, JSONValue]]:
    if not spawn_plans:
        return {}
    first = spawn_plans[0]
    injected_trace = {"source_path": "validation/tampered", "raw_type": "Tampered", "raw_id": "injected"}
    return {
        "unit_identity": _tamper_spawn_plan(
            first,
            plan_updates={"unit_id": "summon:servant:injected"},
            request_updates={"unit_id": "summon:servant:injected"},
            unit_updates={"unit_id": "summon:servant:injected"},
        ),
        "spawn_kind": _tamper_spawn_plan(first, metadata_updates={"spawn_plan_kind": "summoned_monster"}),
        "entity_ref": _tamper_spawn_plan(
            first,
            request_updates={"entity_ref": "servant:injected"},
            unit_updates={"template_id": "servant:injected"},
            flag_updates={"servant_ref": "servant:injected"},
        ),
        "owner": _tamper_spawn_plan(
            first,
            request_updates={"owner_id": "ally:injected_owner", "summoner_id": "ally:injected_owner"},
            flag_updates={"owner_id": "ally:injected_owner", "summoner_id": "ally:injected_owner"},
        ),
        "servant_source": _tamper_spawn_plan(
            first,
            plan_updates={"source_trace": injected_trace},
            request_updates={
                "source_id": "servant_definition:injected",
                "entry_id": "servant_definition:injected",
                "source_trace": injected_trace,
                "entry_source_trace": injected_trace,
            },
            flag_updates={
                "servant_definition_id": "servant_definition:injected",
                "summon_intent_id": "servant_definition:injected",
                "summon_source_trace": injected_trace,
                "servant_definition_source_trace": injected_trace,
            },
        ),
    }


def _tampered_wave_spawn_plans(
    spawn_plans: tuple[dict[str, JSONValue], ...],
) -> dict[str, dict[str, JSONValue]]:
    if not spawn_plans:
        return {}
    first = spawn_plans[0]
    injected_trace = {"source_path": "validation/tampered", "raw_type": "Tampered", "raw_id": "injected"}
    return {
        "unit_identity": _tamper_spawn_plan(
            first,
            plan_updates={"unit_id": "enemy:stage:injected"},
            request_updates={"unit_id": "enemy:stage:injected"},
            unit_updates={"unit_id": "enemy:stage:injected"},
        ),
        "spawn_kind": _tamper_spawn_plan(first, metadata_updates={"spawn_plan_kind": "servant"}),
        "entity_ref": _tamper_spawn_plan(
            first,
            request_updates={"entity_ref": "monster:injected"},
            unit_updates={"template_id": "monster:injected"},
        ),
        "wave_definition": _tamper_spawn_plan(
            first,
            request_updates={
                "source_id": "wave_definition:injected",
                "wave_definition_id": "wave_definition:injected",
                "source_trace": injected_trace,
            },
            flag_updates={
                "wave_definition_id": "wave_definition:injected",
                "wave_definition_source_trace": injected_trace,
            },
        ),
        "wave_entry": _tamper_spawn_plan(
            first,
            plan_updates={"source_trace": injected_trace},
            request_updates={"entry_id": "wave_entry:injected", "entry_source_trace": injected_trace},
            flag_updates={"wave_entry_id": "wave_entry:injected", "wave_entry_source_trace": injected_trace},
        ),
        "wave_position": _tamper_spawn_plan(
            first,
            request_updates={"position": 999},
            flag_updates={"position": 999, "wave_position": 999},
        ),
    }


def _tamper_spawn_plan(
    plan: dict[str, JSONValue],
    *,
    plan_updates: dict[str, JSONValue] | None = None,
    request_updates: dict[str, JSONValue] | None = None,
    unit_updates: dict[str, JSONValue] | None = None,
    flag_updates: dict[str, JSONValue] | None = None,
    metadata_updates: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    tampered = _json_safe(plan)
    if not isinstance(tampered, dict):
        return {}
    tampered.update(plan_updates or {})
    request = tampered.get("request")
    if isinstance(request, dict):
        request.update(request_updates or {})
    unit = tampered.get("unit")
    if isinstance(unit, dict):
        unit.update(unit_updates or {})
        flags = unit.get("flags")
        if isinstance(flags, dict):
            flags.update(flag_updates or {})
    metadata = tampered.get("metadata")
    if isinstance(metadata, dict):
        metadata.update(metadata_updates or {})
    return tampered


def _incomplete_spawn_plan_variants(
    spawn_plans: tuple[dict[str, JSONValue], ...],
    *,
    owner_flag: str,
    source_flag: str,
) -> dict[str, dict[str, JSONValue]]:
    if not spawn_plans:
        return {}
    first = spawn_plans[0]
    return {
        "missing_max_hp": _corrupt_spawn_plan(first, remove_unit_keys=("max_hp",)),
        "missing_speed": _corrupt_spawn_plan(first, remove_unit_keys=("speed",)),
        "missing_owner_or_identity": _corrupt_spawn_plan(first, remove_flag_keys=(owner_flag,)),
        "missing_source_trace": _corrupt_spawn_plan(first, remove_plan_keys=("source_trace",), remove_flag_keys=(source_flag,)),
    }


def _corrupt_spawn_plan(
    plan: dict[str, JSONValue],
    *,
    remove_plan_keys: tuple[str, ...] = (),
    remove_unit_keys: tuple[str, ...] = (),
    remove_flag_keys: tuple[str, ...] = (),
) -> dict[str, JSONValue]:
    corrupted = _json_safe(plan)
    if not isinstance(corrupted, dict):
        return {}
    for key in remove_plan_keys:
        corrupted.pop(key, None)
    unit = corrupted.get("unit")
    if isinstance(unit, dict):
        for key in remove_unit_keys:
            unit.pop(key, None)
        flags = unit.get("flags")
        if isinstance(flags, dict):
            for key in remove_flag_keys:
                flags.pop(key, None)
    return corrupted


def _compact_details(value: Any) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, JSONValue] = {}
    for key, item in value.items():
        if key in {"plan", "result", "missing_result"}:
            result[key] = _object_summary(item)
        elif key == "definition" and hasattr(item, "wave_definition_id"):
            result[key] = {
                "wave_definition_id": str(item.wave_definition_id),
                "stage_id": str(item.stage_id),
                "level": item.level,
                "hard_level_group": item.hard_level_group,
            }
        elif key in {"incomplete_results", "tampered_results"} and isinstance(item, dict):
            result[key] = {str(label): _object_summary(value) for label, value in sorted(item.items())}
        elif key == "spawn_plans":
            result[key] = [_spawn_plan_summary(plan) for plan in item]
        elif isinstance(item, (str, int, float, bool)) or item is None:
            result[key] = item
        else:
            result[key] = _json_safe(item)
    return result


def _object_summary(value: Any) -> dict[str, JSONValue]:
    if hasattr(value, "plan") and hasattr(value, "mutations"):
        return {
            "plan": _object_summary(value.plan),
            "mutation_count": len(value.mutations),
            "record_count": len(value.records),
        }
    if hasattr(value, "to_json"):
        raw = value.to_json()
        return {
            "ok": raw.get("ok"),
            "operation": raw.get("operation", ""),
            "status": raw.get("status", ""),
            "blocked_reason": raw.get("blocked_reason", ""),
            "unit_ids": raw.get("unit_ids", []),
            "spawn_unit_plan_count": len(raw.get("spawn_unit_plans", [])) if isinstance(raw.get("spawn_unit_plans"), list) else 0,
        }
    return {}


def _spawn_plan_summary(plan: dict[str, JSONValue]) -> dict[str, JSONValue]:
    unit = plan.get("unit") if isinstance(plan.get("unit"), dict) else {}
    return {
        "ok": plan.get("ok"),
        "unit_id": plan.get("unit_id", ""),
        "blocked_reason": plan.get("blocked_reason", ""),
        "side": unit.get("side", ""),
        "template_id": unit.get("template_id", ""),
        "flag_keys": sorted((unit.get("flags") if isinstance(unit.get("flags"), dict) else {}).keys())[:20],
    }


def _function_source(source: str, marker: str) -> str:
    start = source.find(marker)
    if start < 0:
        return ""
    next_def = source.find("\n    def ", start + len(marker))
    if next_def < 0:
        return source[start:]
    return source[start:next_def]


def _wave_unit_id(stage_id: str, wave_index: int, position: int) -> str:
    return f"enemy:stage:{stage_id}:wave:{wave_index}:pos:{position}"


def _json_safe(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
