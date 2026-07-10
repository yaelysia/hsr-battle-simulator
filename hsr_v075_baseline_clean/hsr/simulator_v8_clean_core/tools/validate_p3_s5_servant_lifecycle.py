from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import ServantDefinitionIR, UnitBirthTemplateIR
from ..rules.rulebook import RuleBook
from ..systems.summon import SummonSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _base_servant_state,
    _first_servant_id,
    _select_executable_servant_definition,
)


VALIDATION_VERSION = "p3_s5_servant_lifecycle"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    definition = _select_executable_servant_definition(rules)
    groups = {
        "servant_definition_matrix": _servant_definition_matrix(tbgd_root, rules),
        "servant_spawn_owner_lifecycle": _servant_spawn_owner_lifecycle_case(rules, definition),
        "servant_negative_boundaries": _servant_negative_boundary_cases(rules, definition),
    }
    checks = {
        **{name: group["checks"] for name, group in groups.items()},
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_servant_definition_owner_stat_lifecycle_predicates",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "selected_servant_definition_id": definition.servant_definition_id,
                "selected_owner_entity_ref": definition.owner_entity_ref,
            },
        },
        "summary": {
            "definition_count": groups["servant_definition_matrix"]["definition_count"],
            "raw_count": groups["servant_definition_matrix"]["raw_count"],
            "executable_definition_count": groups["servant_definition_matrix"]["executable_definition_count"],
            "blocked_definition_count": groups["servant_definition_matrix"]["blocked_definition_count"],
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
            "negative_case_count": groups["servant_negative_boundaries"]["negative_case_count"],
            "spawn_replay_ok": groups["servant_spawn_owner_lifecycle"]["replay"]["spawn_ok"],
            "cleanup_replay_ok": groups["servant_spawn_owner_lifecycle"]["replay"]["cleanup_ok"],
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s5_servant_lifecycle.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S5 servant definition/stat/lifecycle/owner contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _servant_definition_matrix(tbgd_root: Path, rules: RuleBook) -> dict[str, Any]:
    definitions = tuple(rules.servant_definitions())
    executable = tuple(item for item in definitions if item.coverage_status == "executable")
    blocked = tuple(item for item in definitions if item.coverage_status == "blocked")
    raw_rows = _raw_servant_rows(tbgd_root)
    component_keys = ("hp_base", "hp_inherit", "speed_base", "speed_inherit")
    executable_components = [
        (definition.servant_definition_id, key, ((definition.stat_source.get("components") or {}).get(key) or {}))
        for definition in executable
        for key in component_keys
    ]
    checks = {
        "raw_ir_count_matches": len(raw_rows) == len(definitions),
        "definitions_present": bool(definitions),
        "executable_definition_present": bool(executable),
        "rulebook_lookup_by_id": all(rules.servant_definition(item.servant_definition_id) == item for item in definitions),
        "rulebook_lookup_by_owner": all(
            item in rules.servant_definitions_for_owner(item.owner_entity_ref)
            for item in executable
            if item.owner_entity_ref
        ),
        "owner_entity_source_admitted": all(
            isinstance(item.stat_source.get("owner_source"), dict)
            and item.stat_source["owner_source"].get("admission_status") == "executable"
            and item.owner_entity_ref == item.stat_source["owner_source"].get("owner_entity_ref")
            for item in executable
        ),
        "action_set_has_executable_bindings": all(item.action_set.get("executable_binding_ids") for item in executable),
        "skipped_skill_slots_audited": all(isinstance(item.action_set.get("skipped_slots"), list) for item in executable),
        "stat_components_executable": all(component.get("admission_status") == "executable" for _, _, component in executable_components),
        "stat_components_have_source_trace": all(component.get("source_trace") for _, _, component in executable_components),
        "stat_formula_declared": all(
            item.stat_source.get("formula", {}).get("max_hp") == "owner.max_hp * hp_inherit + hp_base"
            and item.stat_source.get("formula", {}).get("speed") == "owner.speed * speed_inherit + speed_base"
            for item in executable
        ),
        "attack_defense_boundary_declared": all(
            item.stat_source.get("schema_carry_fields", {}).get("attack", {}).get("source_status") == "schema_carry_only"
            and item.stat_source.get("schema_carry_fields", {}).get("defense", {}).get("source_status") == "schema_carry_only"
            for item in executable
        ),
        "timeline_source_executable": all(
            item.timeline_source.get("admission_status") == "executable" and item.timeline_source.get("source_trace")
            for item in executable
        ),
        "lifecycle_source_executable": all(
            item.lifecycle_source.get("admission_status") == "executable"
            and item.lifecycle_source.get("owner_removed_policy") == "remove"
            and item.lifecycle_source.get("source_trace")
            for item in executable
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "raw_count": len(raw_rows),
        "definition_count": len(definitions),
        "executable_definition_count": len(executable),
        "blocked_definition_count": len(blocked),
        "component_keys": list(component_keys),
        "sample_definition": executable[0].to_json() if executable else {},
    }


def _servant_spawn_owner_lifecycle_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    state = _base_servant_state(definition)
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(state, definition, owner_id="ally:servant_owner")
    result = system.apply_spawn_servant(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    servant_id = _first_servant_id(after)
    servant = after.units[servant_id]
    runtime = after.global_flags.get("summon_runtime") if isinstance(after.global_flags.get("summon_runtime"), dict) else {}
    runtime_entry = (runtime.get("entities") or {}).get(servant_id) if isinstance(runtime.get("entities"), dict) else {}
    servant_runtime_entry = (runtime.get("servants") or {}).get(servant_id) if isinstance(runtime.get("servants"), dict) else {}
    spawn_mutation = _first_spawn_mutation(result.mutations)
    expected_stats = _expected_servant_stats(state.units["ally:servant_owner"], definition)
    cleanup_plan = system.plan_owner_cleanup(after, "ally:servant_owner")
    cleanup_result = system.apply_remove(after, cleanup_plan)
    after_cleanup = MutationReducer().apply_all(after, cleanup_result.mutations)
    cleanup_replay = MutationReducer().replay_snapshot(after, cleanup_result.mutations, after_cleanup.snapshot().to_json())
    cleanup_runtime = after_cleanup.global_flags.get("summon_runtime")
    cleanup_entry = (
        cleanup_runtime.get("entities", {}).get(servant_id)
        if isinstance(cleanup_runtime, dict) and isinstance(cleanup_runtime.get("entities"), dict)
        else {}
    )
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    record_mutation_ids = {
        str(record.get("mutation_id") or "")
        for record in result.records
        if record.get("process_only") is False
    }
    checks = {
        "spawn_plan_ok": plan.ok and plan.operation == "servant_spawn",
        "spawned_unit_is_owner_bound_servant": servant.flags.get("summon_kind") == "servant"
        and servant.flags.get("owner_id") == "ally:servant_owner"
        and servant.flags.get("owner_entity_ref") == definition.owner_entity_ref
        and servant.template_id == definition.servant_ref,
        "hp_speed_match_source_formula": _near(servant.max_hp, expected_stats["max_hp"])
        and _near(servant.hp, expected_stats["max_hp"])
        and _near(servant.speed, expected_stats["speed"]),
        "attack_defense_boundary_carried": servant.flags.get("servant_runtime_stat_values", {}).get("attack_source_status")
        == "schema_carry_only"
        and servant.flags.get("servant_runtime_stat_values", {}).get("defense_source_status") == "schema_carry_only"
        and _near(servant.attack, state.units["ally:servant_owner"].attack)
        and _near(servant.defense, state.units["ally:servant_owner"].defense),
        "timeline_and_action_admitted": servant.flags.get("timeline_admitted") is True
        and servant.action_value > 0.0
        and servant.flags.get("summon_action_admitted") is True
        and bool(servant.flags.get("summon_action_admission", {}).get("ability_graph_ids")),
        "owner_cleanup_source_present": servant.flags.get("owner_death_policy") == "remove"
        and isinstance(servant.flags.get("owner_death_policy_source_trace"), dict)
        and servant.flags.get("owner_death_policy_admission", {}).get("remove_source_admitted") is True,
        "runtime_entity_complete": _runtime_servant_entry_complete(runtime_entry, servant_runtime_entry, servant_id),
        "spawn_mutation_source_audit": spawn_mutation is not None
        and bool(spawn_mutation.metadata.get("servant_stat_source", {}).get("source_trace"))
        and bool(spawn_mutation.metadata.get("servant_timeline_source", {}).get("source_trace"))
        and bool(spawn_mutation.metadata.get("servant_lifecycle_source", {}).get("source_trace"))
        and bool(spawn_mutation.metadata.get("servant_action_set", {}).get("source_trace")),
        "settlement_records_cover_mutations": mutation_ids == record_mutation_ids,
        "spawn_replay_ok": replay.ok,
        "owner_cleanup_plan_ok": cleanup_plan.ok and cleanup_plan.operation == "owner_removed_cleanup",
        "owner_cleanup_removed_unit": after_cleanup.units[servant_id].flags.get("lifecycle_status") == "removed",
        "owner_cleanup_runtime_retains_audit": isinstance(cleanup_entry, dict)
        and cleanup_entry.get("status") == "removed"
        and cleanup_entry.get("removed_reason") == "owner_removed_cleanup",
        "cleanup_replay_ok": cleanup_replay.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "servant_definition_id": definition.servant_definition_id,
        "servant_unit_id": servant_id,
        "expected_stats": expected_stats,
        "actual_stats": {
            "max_hp": servant.max_hp,
            "hp": servant.hp,
            "attack": servant.attack,
            "defense": servant.defense,
            "speed": servant.speed,
            "action_value": servant.action_value,
        },
        "runtime_entry": runtime_entry if isinstance(runtime_entry, dict) else {},
        "spawn_mutation_metadata": spawn_mutation.metadata if spawn_mutation is not None else {},
        "records": list(result.records),
        "cleanup_plan": cleanup_plan.to_json(),
        "replay": {
            "spawn_ok": replay.ok,
            "spawn_errors": list(replay.errors),
            "cleanup_ok": cleanup_replay.ok,
            "cleanup_errors": list(cleanup_replay.errors),
        },
    }


def _servant_negative_boundary_cases(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    system = SummonSystem(rules)
    base_state = _base_servant_state(definition)
    template = rules.unit_birth_template(definition.birth_template_id)
    if template is None:
        raise RuntimeError("executable servant definition must reference a unit birth template")
    cases = {
        "owner_missing": _blocked_spawn_case(system, base_state, definition, "ally:missing", "servant_owner_missing"),
        "owner_entity_mismatch": _blocked_spawn_case(
            system,
            _state_with_owner_template(base_state, "avatar:not_the_owner"),
            definition,
            "ally:servant_owner",
            "servant_owner_entity_mismatch",
        ),
        "non_positive_runtime_stats": _blocked_spawn_case(
            SummonSystem(_TemplateOverrideRuleBook(rules, _template_with_non_positive_stats(template))),
            base_state,
            definition,
            "ally:servant_owner",
            "unit_birth_template_materialization_invalid:unit_spawn_plan_max_hp_non_positive",
        ),
        "action_set_blocked": _blocked_spawn_case(
            SummonSystem(
                _TemplateOverrideRuleBook(
                    rules,
                    replace(template, coverage_status="blocked", blocked_reason="validation_missing_action_set"),
                )
            ),
            base_state,
            definition,
            "ally:servant_owner",
            "validation_missing_action_set",
        ),
        "timeline_source_blocked": _blocked_spawn_case(
            SummonSystem(
                _TemplateOverrideRuleBook(
                    rules,
                    replace(template, coverage_status="blocked", blocked_reason="validation_missing_timeline_source"),
                )
            ),
            base_state,
            definition,
            "ally:servant_owner",
            "validation_missing_timeline_source",
        ),
        "lifecycle_source_blocked": _blocked_spawn_case(
            SummonSystem(
                _TemplateOverrideRuleBook(
                    rules,
                    replace(template, coverage_status="blocked", blocked_reason="validation_missing_lifecycle_source"),
                )
            ),
            base_state,
            definition,
            "ally:servant_owner",
            "validation_missing_lifecycle_source",
        ),
        "duplicate_active_servant": _duplicate_servant_case(rules, definition),
    }
    checks = {
        f"{name}_blocked": case["checks"]["ok"]
        for name, case in cases.items()
    }
    checks["all_negative_cases_state_unchanged"] = all(case["checks"]["checks"]["state_unchanged"] for case in cases.values())
    checks["all_negative_cases_process_only"] = all(case["checks"]["checks"]["process_only_record"] for case in cases.values())
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "negative_case_count": len(cases),
        "cases": cases,
    }


def _blocked_spawn_case(
    system: SummonSystem,
    state: BattleState,
    definition: ServantDefinitionIR,
    owner_id: str,
    expected_reason: str,
) -> dict[str, Any]:
    before = state.snapshot().to_json()
    plan = system.plan_spawn_servant(state, definition, owner_id=owner_id)
    result = system.apply_spawn_servant(state, plan)
    after = MutationReducer().apply_all(state, result.mutations)
    reason_ok = plan.blocked_reason == expected_reason or expected_reason in plan.blocked_reason
    checks = {
        "plan_blocked": not plan.ok and reason_ok,
        "no_mutations": not result.mutations,
        "process_only_record": bool(result.records) and result.records[0].get("process_only") is True,
        "state_unchanged": after.snapshot().to_json() == before,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expected_reason": expected_reason,
        "plan": plan.to_json(),
        "records": list(result.records),
    }


def _duplicate_servant_case(rules: RuleBook, definition: ServantDefinitionIR) -> dict[str, Any]:
    system = SummonSystem(rules)
    state = _base_servant_state(definition)
    first_plan = system.plan_spawn_servant(state, definition, owner_id="ally:servant_owner")
    first_result = system.apply_spawn_servant(state, first_plan)
    after_first = MutationReducer().apply_all(state, first_result.mutations)
    return _blocked_spawn_case(
        system,
        after_first,
        definition,
        "ally:servant_owner",
        "servant_duplicate_active_policy_missing",
    )


class _TemplateOverrideRuleBook:
    def __init__(self, rules: RuleBook, template: UnitBirthTemplateIR) -> None:
        self._rules = rules
        self._template = template

    def unit_birth_template(self, birth_template_id: str) -> UnitBirthTemplateIR | None:
        if birth_template_id == self._template.birth_template_id:
            return self._template
        return self._rules.unit_birth_template(birth_template_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rules, name)


def _template_with_non_positive_stats(template: UnitBirthTemplateIR) -> UnitBirthTemplateIR:
    unit_field_specs = deepcopy(template.unit_field_specs)
    spec = dict(unit_field_specs.get("max_hp") or {})
    spec["scale"] = 0.0
    spec["offset"] = 0.0
    unit_field_specs["max_hp"] = spec
    return replace(template, unit_field_specs=unit_field_specs)


def _state_with_owner_template(state: BattleState, template_id: str) -> BattleState:
    owner = state.units["ally:servant_owner"]
    units = dict(state.units)
    units["ally:servant_owner"] = replace(owner, template_id=template_id)
    return replace(state, units=units)


def _raw_servant_rows(tbgd_root: Path) -> list[dict[str, Any]]:
    path = tbgd_root / "ExcelOutput" / "AvatarServantConfig.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [row for row in data if isinstance(row, dict)]


def _expected_servant_stats(owner: UnitState, definition: ServantDefinitionIR) -> dict[str, float]:
    components = definition.stat_source.get("components") if isinstance(definition.stat_source, dict) else {}
    hp_base = _component_value(components, "hp_base")
    hp_inherit = _component_value(components, "hp_inherit")
    speed_base = _component_value(components, "speed_base")
    speed_inherit = _component_value(components, "speed_inherit")
    return {
        "max_hp": float(owner.max_hp) * hp_inherit + hp_base,
        "speed": float(owner.speed) * speed_inherit + speed_base,
    }


def _component_value(components: Any, key: str) -> float:
    if not isinstance(components, dict):
        return 0.0
    component = components.get(key)
    if not isinstance(component, dict):
        return 0.0
    value = component.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _runtime_servant_entry_complete(entry: Any, servant_entry: Any, servant_id: str) -> bool:
    if not isinstance(entry, dict) or not isinstance(servant_entry, dict):
        return False
    return (
        entry.get("unit_id") == servant_id
        and entry.get("summon_kind") == "servant"
        and entry.get("owner_id") == "ally:servant_owner"
        and entry.get("status") == "active"
        and isinstance(entry.get("source_trace"), dict)
        and isinstance(entry.get("timeline"), dict)
        and entry["timeline"].get("admitted") is True
        and isinstance(entry.get("targetability"), dict)
        and entry["targetability"].get("targetable") is True
        and isinstance(entry.get("actionability"), dict)
        and entry["actionability"].get("actionable") is True
        and isinstance(entry.get("lifetime"), dict)
        and entry["lifetime"].get("kind") == "permanent_until_removed_or_owner_removed"
        and bool(servant_entry.get("servant_ref"))
    )


def _first_spawn_mutation(mutations: tuple[Any, ...]) -> Any | None:
    for mutation in mutations:
        if mutation.metadata.get("lifecycle_operation") == "unit_spawn":
            return mutation
    return None


def _near(left: float, right: float, *, eps: float = 1e-6) -> bool:
    return abs(float(left) - float(right)) <= eps


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
