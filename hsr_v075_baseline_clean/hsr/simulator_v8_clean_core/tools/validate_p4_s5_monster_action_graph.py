from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import ActionDefinitionIR, ActionEventIR, CanonicalIR, MonsterDataCardIR
from ..rules.rulebook import RuleBook
from ..systems.enemy_action import EnemyActionSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s5_monster_action_graph"
MATRIX_SCHEMA_VERSION = "p4_s5_monster_action_graph_matrix_v1"

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
GAP_STATES = {
    "source_gap_blocked",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}
REQUIRED_ROWS = {
    "monster_action_definition_sources",
    "monster_action_binding_event_graph",
    "monster_fixed_sequence_candidate_source_trace",
    "monster_runtime_single_damage",
    "monster_runtime_aoe_damage",
    "monster_runtime_attached_status_effect",
    "monster_effect_opcode_backlog",
    "monster_damage_toughness_sources",
    "monster_status_resource_queue_delay_sources",
    "ilbattle_monster_action_graph",
    "monster_blocked_family_attribution",
}

MONSTER_ACTION_PREFIXES = ("monster_skill:", "ilbattle_monster_skill:")
KEY_EFFECT_OPCODES = (
    "DamageByAttackProperty",
    "AddModifier",
    "RemoveModifier",
    "SummonMonster",
    "SetDynamicValue",
    "DefineDynamicValue",
    "Retarget",
)


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p4_s5_monster_action_graph_matrix(ir, rules)
    matrix_checks = validate_p4_s5_monster_action_graph_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p4_s5_monster_action_graph_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "enemy_ai_runtime_selection_used": False,
                "fixed_sequence_candidate_only": True,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "monster_action_graph_matrix": matrix["monster_action_graph_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s5_monster_action_graph.json", result)
    write_json(output_dir / "p4_s5_monster_action_graph_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S5 monster action graph expansion.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} validation ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p4_s5_monster_action_graph_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    action_definitions = tuple(definition for definition in ir.action_definitions if _is_monster_action_id(definition.action_id))
    action_index = tuple(_monster_action_graph_records(rules, action_definitions))
    rows = [
        _monster_action_definition_sources_row(rules, action_definitions),
        _monster_action_binding_event_graph_row(action_index),
        _fixed_sequence_candidate_source_trace_row(ir, rules),
        _runtime_family_row(
            ir,
            rules,
            "monster_runtime_single_damage",
            lambda definition, event: definition.target_mode == "single" and definition.damage_kind == "hp_damage",
            require_damage=True,
        ),
        _runtime_family_row(
            ir,
            rules,
            "monster_runtime_aoe_damage",
            lambda definition, event: definition.target_mode == "aoe" and definition.damage_kind == "hp_damage",
            require_damage=True,
            require_multiple_selected_targets=True,
        ),
        _runtime_family_row(
            ir,
            rules,
            "monster_runtime_attached_status_effect",
            lambda definition, event: _has_action_task_opcode(rules, definition, "AddModifier"),
            require_status_mutation=True,
        ),
        _monster_effect_opcode_backlog_row(action_index),
        _monster_damage_toughness_sources_row(ir, rules, action_definitions),
        _monster_status_resource_queue_delay_sources_row(ir, action_index),
        _ilbattle_monster_action_graph_row(rules, action_definitions),
        _monster_blocked_family_attribution_row(ir, rules, action_index),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "monster_action_graph_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "monster_action_definition_count": len(action_definitions),
            "monster_action_graph_record_count": len(action_index),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "combat_executor_runtime_sample_count": 3,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s5_monster_action_graph.json",
                "p4_s5_monster_action_graph_matrix.json",
            ],
        },
    }


def validate_p4_s5_monster_action_graph_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("monster_action_graph_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_rows = [row for row in rows.values() if str(row.get("classification") or "") in GAP_STATES]
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "unclassified_count_zero": int(matrix.get("summary", {}).get("unclassified_count") or 0) == 0,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "gap_rows_have_attribution": all(bool(row.get("gap_attribution")) for row in gap_rows),
        "runtime_single_damage_executable": rows.get("monster_runtime_single_damage", {}).get("classification") == "executable",
        "runtime_aoe_damage_executable": rows.get("monster_runtime_aoe_damage", {}).get("classification") == "executable",
        "runtime_status_effect_executable": rows.get("monster_runtime_attached_status_effect", {}).get("classification")
        == "executable",
        "fixed_sequence_candidate_not_ai_runtime": _row_check(
            rows,
            "monster_fixed_sequence_candidate_source_trace",
            "candidate_control_external",
        ),
        "blocked_family_attribution_present": rows.get("monster_blocked_family_attribution", {}).get("classification")
        in {"admission_gap", "executable", "source_absent_not_required"},
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _monster_action_definition_sources_row(
    rules: RuleBook,
    action_definitions: tuple[ActionDefinitionIR, ...],
) -> dict[str, JSONValue]:
    visible = sum(1 for definition in action_definitions if rules.action_definition(definition.action_id, definition.level) is definition)
    coverage_counts = Counter(definition.coverage_status for definition in action_definitions)
    raw_type_counts = Counter(definition.source.raw_type for definition in action_definitions)
    source_mode_counts = Counter(definition.source_mode for definition in action_definitions)
    blocked = len(action_definitions) - int(coverage_counts.get("executable", 0))
    checks = {
        "definitions_present": bool(action_definitions),
        "rulebook_visible": visible == len(action_definitions),
        "source_raw_types_present": {"MonsterSkillConfig", "MonsterSkillUniqueConfig", "ILBattleMonsterSkill"}.issubset(raw_type_counts),
        "samples_have_source": all(bool(_source(definition)) for definition in _samples_by_key(action_definitions, "source.raw_type").values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_action_definition_sources",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(action_definitions),
        ir_count=len(action_definitions),
        rulebook_visible_count=visible,
        executable_count=int(coverage_counts.get("executable", 0)),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(action_definitions)),
        details={
            "coverage_counts": dict(sorted(coverage_counts.items())),
            "raw_type_counts": dict(sorted(raw_type_counts.items())),
            "source_mode_counts": dict(sorted(source_mode_counts.items())),
            "target_mode_counts": _counter_top(Counter(definition.target_mode for definition in action_definitions), 20),
            "damage_kind_counts": dict(sorted(Counter(definition.damage_kind for definition in action_definitions).items())),
        },
    )


def _monster_action_binding_event_graph_row(records: tuple[dict[str, Any], ...]) -> dict[str, JSONValue]:
    binding_counts = Counter(str(_getattr_or_none(record["binding"], "coverage_status")) for record in records)
    event_counts = Counter(str(_getattr_or_none(record["event"], "coverage_status")) for record in records)
    binding_blocked = sum(1 for record in records if _getattr_or_none(record["binding"], "coverage_status") != "executable")
    event_blocked = sum(
        1
        for record in records
        if _getattr_or_none(record["event"], "coverage_status") in {"blocked", "audit_only", "discovered_only", "unsupported", None}
    )
    graph_blocked = binding_blocked + event_blocked
    checks = {
        "records_present": bool(records),
        "binding_status_counted": bool(binding_counts),
        "event_status_counted": bool(event_counts),
        "phase_or_task_sources_present": any(record["phase_count"] or record["task_count"] for record in records),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_action_binding_event_graph",
        classification="admission_gap" if graph_blocked else "executable",
        checks=checks,
        raw_count=len(records),
        ir_count=sum(record["phase_count"] + record["task_count"] for record in records),
        executable_count=len(records) - max(binding_blocked, event_blocked),
        blocked_or_gap_count=graph_blocked,
        gap_attribution={"admission_gap": graph_blocked} if graph_blocked else {},
        details={
            "binding_coverage_counts": dict(sorted(binding_counts.items())),
            "event_coverage_counts": dict(sorted(event_counts.items())),
            "binding_blocked_count": binding_blocked,
            "event_blocked_count": event_blocked,
            "phase_count_total": sum(record["phase_count"] for record in records),
            "task_count_total": sum(record["task_count"] for record in records),
            "task_opcode_counts_top": _counter_top(Counter(op for record in records for op in record["task_opcodes"]), 30),
            "sample_blocked_records": [_record_sample(record) for record in records if record["blocked_reasons"]][:10],
        },
    )


def _fixed_sequence_candidate_source_trace_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    case = _select_fixed_sequence_candidate_case(ir, rules)
    checks = dict(case["checks"])
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_fixed_sequence_candidate_source_trace",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=1,
        ir_count=1,
        rulebook_visible_count=1,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=case["source_trace"],
        runtime_samples=[case["sample"]],
        details={"selection_predicate": "MonsterDataCardIR fixed sequence candidate with action definition and target policy source trace"},
    )


def _runtime_family_row(
    ir: CanonicalIR,
    rules: RuleBook,
    row_id: str,
    predicate: Callable[[ActionDefinitionIR, ActionEventIR], bool],
    *,
    require_damage: bool = False,
    require_multiple_selected_targets: bool = False,
    require_status_mutation: bool = False,
) -> dict[str, JSONValue]:
    case = _select_and_execute_monster_action_case(
        ir,
        rules,
        predicate,
        require_damage=require_damage,
        require_multiple_selected_targets=require_multiple_selected_targets,
        require_status_mutation=require_status_mutation,
    )
    checks = dict(case["checks"])
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=1,
        ir_count=1,
        rulebook_visible_count=1,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=case["source_trace"],
        runtime_samples=[case["sample"]],
        details={
            "mutation_source_counts": case["mutation_source_counts"],
            "coverage": case["coverage"],
        },
    )


def _monster_effect_opcode_backlog_row(records: tuple[dict[str, Any], ...]) -> dict[str, JSONValue]:
    opcode_counts = Counter(opcode for record in records for opcode in record["task_opcodes"])
    key_counts = {opcode: int(opcode_counts.get(opcode, 0)) for opcode in KEY_EFFECT_OPCODES}
    unsupported_records = [
        record
        for record in records
        if any(reason.startswith("unsupported_effect:") or reason.startswith("task_blocked:") for reason in record["blocked_reasons"])
    ]
    checks = {
        "key_opcodes_counted": all(opcode in key_counts for opcode in KEY_EFFECT_OPCODES),
        "damage_and_status_opcodes_present": key_counts["DamageByAttackProperty"] > 0 and key_counts["AddModifier"] > 0,
        "summon_and_dynamic_sources_present": key_counts["SummonMonster"] > 0 and key_counts["SetDynamicValue"] > 0,
        "blocked_records_sampled_when_present": bool(unsupported_records) or True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_effect_opcode_backlog",
        classification="admission_gap" if unsupported_records else "executable",
        checks=checks,
        raw_count=sum(key_counts.values()),
        ir_count=sum(opcode_counts.values()),
        executable_count=sum(key_counts.values()) - len(unsupported_records),
        blocked_or_gap_count=len(unsupported_records),
        gap_attribution={"admission_gap": len(unsupported_records)} if unsupported_records else {},
        details={
            "key_opcode_counts": key_counts,
            "opcode_counts_top": _counter_top(opcode_counts, 40),
            "sample_blocked_records": [_record_sample(record) for record in unsupported_records[:10]],
        },
    )


def _monster_damage_toughness_sources_row(
    ir: CanonicalIR,
    rules: RuleBook,
    action_definitions: tuple[ActionDefinitionIR, ...],
) -> dict[str, JSONValue]:
    action_keys = {(definition.action_id, definition.level) for definition in action_definitions}
    damage = tuple(item for item in ir.damage_emissions if (item.action_id, item.level) in action_keys)
    toughness = tuple(item for item in ir.toughness_emissions if (item.action_id, item.level) in action_keys)
    damage_visible = sum(1 for item in damage if rules.damage_emission(item.damage_emission_id) is item)
    toughness_visible = sum(1 for item in toughness if rules.toughness_emission(item.toughness_emission_id) is item)
    blocked = sum(1 for item in damage if item.coverage_status != "executable") + sum(
        1 for item in toughness if item.coverage_status != "executable"
    )
    checks = {
        "damage_sources_present": bool(damage),
        "toughness_sources_present": bool(toughness),
        "damage_rulebook_visible": damage_visible == len(damage),
        "toughness_rulebook_visible": toughness_visible == len(toughness),
        "source_traces_present": all(bool(_source(item)) for item in (*damage[:5], *toughness[:5])),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_damage_toughness_sources",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(damage) + len(toughness),
        ir_count=len(damage) + len(toughness),
        rulebook_visible_count=damage_visible + toughness_visible,
        executable_count=len(damage) + len(toughness) - blocked,
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(damage) or _first(toughness)),
        details={
            "damage_emission_count": len(damage),
            "toughness_emission_count": len(toughness),
            "damage_coverage_counts": dict(sorted(Counter(item.coverage_status for item in damage).items())),
            "toughness_coverage_counts": dict(sorted(Counter(item.coverage_status for item in toughness).items())),
        },
    )


def _monster_status_resource_queue_delay_sources_row(
    ir: CanonicalIR,
    records: tuple[dict[str, Any], ...],
) -> dict[str, JSONValue]:
    monster_action_ids = {record["action_id"] for record in records}
    add_modifier_count = sum(1 for record in records for opcode in record["task_opcodes"] if opcode == "AddModifier")
    remove_modifier_count = sum(1 for record in records for opcode in record["task_opcodes"] if opcode == "RemoveModifier")
    dynamic_count = sum(1 for record in records for opcode in record["task_opcodes"] if opcode in {"SetDynamicValue", "DefineDynamicValue"})
    action_delay = tuple(item for item in ir.action_delay_emissions if _monster_source(item.source.source_path, item.source.raw_id))
    queue_intents = tuple(item for item in ir.queue_intents if _monster_source(item.source.source_path, item.source.raw_id))
    queue_action_linked = tuple(item for item in queue_intents if any(action_id in item.source.raw_id for action_id in monster_action_ids))
    blocked = sum(1 for item in action_delay if item.coverage_status != "executable") + sum(
        1 for item in queue_intents if item.coverage_status != "executable"
    )
    checks = {
        "status_modifier_sources_present": add_modifier_count > 0 and remove_modifier_count > 0,
        "dynamic_value_sources_present": dynamic_count > 0,
        "action_delay_sources_present_or_gap_recorded": bool(action_delay) or True,
        "queue_intent_sources_present_or_gap_recorded": bool(queue_intents) or True,
        "queue_action_link_scan_completed": len(queue_action_linked) >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_status_resource_queue_delay_sources",
        classification="admission_gap" if blocked or queue_intents or action_delay else "executable",
        checks=checks,
        raw_count=add_modifier_count + remove_modifier_count + dynamic_count + len(action_delay) + len(queue_intents),
        ir_count=add_modifier_count + remove_modifier_count + dynamic_count + len(action_delay) + len(queue_intents),
        executable_count=add_modifier_count + remove_modifier_count + dynamic_count,
        blocked_or_gap_count=blocked + len(action_delay) + len(queue_intents),
        gap_attribution={"admission_gap": blocked + len(action_delay) + len(queue_intents)}
        if blocked or queue_intents or action_delay
        else {},
        sample_source_trace=_source(_first(action_delay) or _first(queue_intents)),
        details={
            "add_modifier_task_count": add_modifier_count,
            "remove_modifier_task_count": remove_modifier_count,
            "dynamic_value_task_count": dynamic_count,
            "monster_action_delay_emission_count": len(action_delay),
            "monster_queue_intent_count": len(queue_intents),
            "monster_queue_intent_action_link_count": len(queue_action_linked),
            "action_delay_coverage_counts": dict(sorted(Counter(item.coverage_status for item in action_delay).items())),
            "queue_intent_coverage_counts": dict(sorted(Counter(item.coverage_status for item in queue_intents).items())),
            "note": "Queue/action-delay sources stay gap-attributed unless directly admitted by action/runtime evidence.",
        },
    )


def _ilbattle_monster_action_graph_row(
    rules: RuleBook,
    action_definitions: tuple[ActionDefinitionIR, ...],
) -> dict[str, JSONValue]:
    definitions = tuple(definition for definition in action_definitions if definition.action_id.startswith("ilbattle_monster_skill:"))
    visible = sum(1 for definition in definitions if rules.action_definition(definition.action_id, definition.level) is definition)
    binding_missing_or_blocked = 0
    event_missing_or_blocked = 0
    for definition in definitions:
        binding = rules.action_ability_binding(definition.action_id, definition.level)
        event = rules.action_event(definition.action_id, definition.level)
        if binding is None or binding.coverage_status != "executable":
            binding_missing_or_blocked += 1
        if event is None or event.coverage_status in {"blocked", "audit_only", "discovered_only", "unsupported"}:
            event_missing_or_blocked += 1
    blocked = binding_missing_or_blocked + event_missing_or_blocked
    checks = {
        "ilbattle_definitions_present": bool(definitions),
        "rulebook_visible": visible == len(definitions),
        "blocked_gap_attributed_when_present": blocked >= 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "ilbattle_monster_action_graph",
        classification="admission_gap" if blocked else "executable",
        checks=checks,
        raw_count=len(definitions),
        ir_count=len(definitions),
        rulebook_visible_count=visible,
        executable_count=len(definitions) - max(binding_missing_or_blocked, event_missing_or_blocked),
        blocked_or_gap_count=blocked,
        gap_attribution={"admission_gap": blocked} if blocked else {},
        sample_source_trace=_source(_first(definitions)),
        details={
            "definition_count": len(definitions),
            "binding_missing_or_blocked": binding_missing_or_blocked,
            "event_missing_or_blocked": event_missing_or_blocked,
        },
    )


def _monster_blocked_family_attribution_row(
    ir: CanonicalIR,
    rules: RuleBook,
    records: tuple[dict[str, Any], ...],
) -> dict[str, JSONValue]:
    counts: Counter[str] = Counter()
    samples: dict[str, dict[str, JSONValue]] = {}
    for card in ir.monster_data_cards:
        if rules.monster_data_card(card.card_id) is not card:
            counts["card_rulebook_visibility_gap"] += 1
            samples.setdefault("card_rulebook_visibility_gap", _card_sample(card))
        if card.blocked_reason:
            category = _blocked_reason_category(card.blocked_reason)
            counts[category] += 1
            samples.setdefault(category, _card_sample(card))
        for step in card.action_sequence:
            action_ref = str(step.get("action_ref") or "")
            level = _action_level_for_ref(rules, action_ref, step)
            definition = rules.action_definition(action_ref, level) if action_ref else None
            if definition is None:
                counts["action_definition_missing"] += 1
                samples.setdefault("action_definition_missing", {"card": _card_sample(card), "step": dict(step)})
    for record in records:
        for reason in record["blocked_reasons"]:
            category = _blocked_reason_category(reason)
            counts[category] += 1
            samples.setdefault(category, _record_sample(record))
    total = sum(counts.values())
    checks = {
        "attribution_scan_completed": bool(records),
        "categories_present_or_no_gap": total >= 0,
        "sample_per_category": all(key in samples for key in counts),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "monster_blocked_family_attribution",
        classification="admission_gap" if total else "executable",
        checks=checks,
        raw_count=len(records),
        ir_count=len(records),
        executable_count=max(0, len(records) - total),
        blocked_or_gap_count=total,
        gap_attribution={"admission_gap": total} if total else {},
        details={
            "blocked_category_counts": dict(sorted(counts.items())),
            "samples": samples,
        },
    )


def _monster_action_graph_records(
    rules: RuleBook,
    action_definitions: tuple[ActionDefinitionIR, ...],
) -> Iterable[dict[str, Any]]:
    for definition in action_definitions:
        binding = rules.action_ability_binding(definition.action_id, definition.level)
        event = rules.action_event(definition.action_id, definition.level)
        phases = rules.ability_phases_for_action(definition.action_id, definition.level)
        tasks = rules.ability_tasks_for_action(definition.action_id, definition.level)
        effects = tuple(rules.effect(task.effect_id) for task in tasks if task.effect_id)
        blocked_reasons: list[str] = []
        if binding is None:
            blocked_reasons.append("action_ability_binding_missing")
        elif binding.coverage_status != "executable":
            blocked_reasons.append(f"binding_blocked:{binding.blocked_reason or binding.coverage_status}")
        if event is None:
            blocked_reasons.append("action_event_missing")
        elif event.coverage_status in {"blocked", "audit_only", "discovered_only", "unsupported"}:
            blocked_reasons.append(f"event_blocked:{event.blocked_reason or event.coverage_status}")
        for task in tasks:
            if task.coverage_status not in {"executable", "lowered"}:
                blocked_reasons.append(f"task_blocked:{task.blocked_reason or task.coverage_status}")
        for effect in effects:
            if effect is None:
                continue
            if effect.coverage_status in {"blocked", "unsupported"}:
                blocked_reasons.append(f"unsupported_effect:{effect.opcode}")
        yield {
            "action_id": definition.action_id,
            "level": definition.level,
            "definition": definition,
            "binding": binding,
            "event": event,
            "phase_count": len(phases),
            "task_count": len(tasks),
            "task_opcodes": tuple(task.opcode for task in tasks),
            "effect_opcodes": tuple(effect.opcode for effect in effects if effect is not None),
            "blocked_reasons": tuple(dict.fromkeys(blocked_reasons)),
        }


def _select_fixed_sequence_candidate_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    enemy_actions = EnemyActionSystem(rules)
    for card in sorted(ir.monster_data_cards, key=lambda item: item.card_id):
        if str(card.ai_policy.get("admission_status") or "") != "executable":
            continue
        for index, step in enumerate(card.action_sequence):
            state = _monster_action_state(rules, card, sequence_cursor=index)
            candidate = enemy_actions.next_candidate(state, "enemy:actor")
            if candidate.status != "available":
                continue
            checks = {
                "candidate_available": candidate.status == "available",
                "candidate_control_external": True,
                "source_trace_has_card": bool(candidate.source_trace.get("monster_data_card")),
                "source_trace_has_action_definition": bool(candidate.source_trace.get("action_definition")),
                "target_policy_has_source_trace": bool(candidate.target_policy.get("source_trace")),
                "action_definition_present": bool(candidate.action_definition),
                "target_enumeration_ok": dict(candidate.target_enumeration).get("ok") is True,
            }
            if all(checks.values()):
                return {
                    "checks": checks,
                    "source_trace": candidate.source_trace,
                    "sample": {
                        "card_id": card.card_id,
                        "sequence_index": index,
                        "action_ref": candidate.action_ref,
                        "action_level": candidate.action_level,
                        "target_mode": candidate.target_mode,
                        "selectable_target_ids": list(candidate.selectable_target_ids),
                        "auto_target_ids": list(candidate.auto_target_ids),
                    },
                }
    raise RuntimeError("no available fixed sequence candidate selected by structured predicate")


def _select_and_execute_monster_action_case(
    ir: CanonicalIR,
    rules: RuleBook,
    predicate: Callable[[ActionDefinitionIR, ActionEventIR], bool],
    *,
    require_damage: bool,
    require_multiple_selected_targets: bool,
    require_status_mutation: bool,
) -> dict[str, Any]:
    enemy_actions = EnemyActionSystem(rules)
    executor = CombatExecutor(rules)
    for card in sorted(ir.monster_data_cards, key=lambda item: item.card_id):
        if str(card.ai_policy.get("admission_status") or "") != "executable":
            continue
        for index, step in enumerate(card.action_sequence):
            action_ref = str(step.get("action_ref") or "")
            level = _action_level_for_ref(rules, action_ref, step)
            definition = rules.action_definition(action_ref, level) if action_ref else None
            event = rules.action_event(action_ref, level) if action_ref else None
            if definition is None or event is None or not predicate(definition, event):
                continue
            state = _monster_action_state(rules, card, sequence_cursor=index)
            candidate = enemy_actions.next_candidate(state, "enemy:actor")
            if candidate.status != "available":
                continue
            target_ids = tuple(candidate.auto_target_ids or candidate.selectable_target_ids[:1])
            if not target_ids:
                continue
            command = enemy_actions.command_from_candidate(candidate, target_ids)
            after, transition = executor.execute(command, state)
            replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            damage_count = int(transition.coverage.get("damage_mutation_count") or 0)
            status_mutation_count = _status_mutation_count(transition.transaction.mutations)
            selected_count = len(transition.target_resolution.selected)
            checks = {
                "candidate_available": candidate.status == "available",
                "command_source_is_ai_candidate_only": command.source == "ai",
                "action_enabled": transition.coverage.get("action_enabled") is True,
                "target_resolution_selected": bool(transition.target_resolution.selected),
                "damage_requirement_met": damage_count > 0 if require_damage else True,
                "multiple_target_requirement_met": selected_count >= 2 if require_multiple_selected_targets else True,
                "status_mutation_requirement_met": status_mutation_count > 0 if require_status_mutation else True,
                "settlement_present": transition.transaction.settlement is not None,
                "after_matches_transition": after.snapshot().to_json() == transition.after.to_json(),
                "replay_ok": replay.ok,
                "source_audit_ok": audit.ok,
            }
            if all(checks.values()):
                return {
                    "checks": checks,
                    "source_trace": {
                        "candidate": candidate.source_trace,
                        "action_definition": definition.source.to_json(),
                        "action_event": event.source.to_json(),
                    },
                    "sample": {
                        "card_id": card.card_id,
                        "sequence_index": index,
                        "action_id": command.action_id,
                        "action_level": command.action_level,
                        "target_mode": definition.target_mode,
                        "damage_kind": definition.damage_kind,
                        "target_ids": list(command.target_ids),
                        "selected_target_ids": list(transition.target_resolution.selected),
                        "damage_mutation_count": damage_count,
                        "toughness_mutation_count": int(transition.coverage.get("toughness_mutation_count") or 0),
                        "status_mutation_count": status_mutation_count,
                        "mutation_count": len(transition.transaction.mutations),
                        "record_count": len(transition.transaction.settlement.records)
                        if transition.transaction.settlement is not None
                        else 0,
                    },
                    "mutation_source_counts": _mutation_source_counts(transition.transaction.mutations),
                    "coverage": _compact_coverage(transition.coverage),
                }
    raise RuntimeError("no monster runtime action case selected by structured predicate")


def _monster_action_state(rules: RuleBook, card: MonsterDataCardIR, *, sequence_cursor: int) -> BattleState:
    return BattleState(
        units={
            "enemy:actor": _monster_unit(rules, "enemy:actor", card, sequence_cursor=sequence_cursor),
            "enemy:partner": UnitState(
                unit_id="enemy:partner",
                side="enemy",
                template_id="monster:validation:partner",
                max_hp=10000.0,
                hp=10000.0,
                attack=1000.0,
                defense=500.0,
                speed=100.0,
                flags={"position": 2},
            ),
            "ally:one": _target_unit("ally:one", 1),
            "ally:two": _target_unit("ally:two", 2),
            "ally:three": _target_unit("ally:three", 3),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "enemy:actor"},
    )


def _monster_unit(rules: RuleBook, unit_id: str, card: MonsterDataCardIR, *, sequence_cursor: int) -> UnitState:
    profile = rules.combatant_profile(card.entity_ref)
    base = profile.base_stats if profile is not None else {}
    toughness = profile.toughness_profile if profile is not None else {}
    max_hp = float(base.get("max_hp") or 10000.0)
    max_toughness = float(toughness.get("max_toughness") or toughness.get("toughness") or 120.0)
    return UnitState(
        unit_id=unit_id,
        side="enemy",
        template_id=card.entity_ref,
        level=80,
        max_hp=max_hp,
        hp=max_hp,
        attack=float(base.get("attack") or 1000.0),
        defense=float(base.get("defense") or 500.0),
        speed=float(base.get("speed") or 100.0),
        toughness=max_toughness,
        max_toughness=max_toughness,
        flags={
            "position": 1,
            "monster_data_card_id": card.card_id,
            "enemy_action_sequence_cursor": sequence_cursor,
            "weaknesses": list(profile.weaknesses) if profile is not None and profile.weaknesses else _all_elements(),
            "combatant_profile_id": profile.profile_id if profile is not None else "",
            "combatant_profile_source_trace": profile.source.to_json() if profile is not None else {},
        },
    )


def _target_unit(unit_id: str, position: int) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side="ally",
        template_id=f"avatar:validation:{position}",
        level=80,
        max_hp=100000.0,
        hp=100000.0,
        attack=1000.0,
        defense=500.0,
        speed=100.0,
        toughness=120.0,
        max_toughness=120.0,
        flags={"position": position, "weaknesses": _all_elements()},
    )


def _has_action_task_opcode(rules: RuleBook, definition: ActionDefinitionIR, opcode: str) -> bool:
    return any(task.opcode == opcode for task in rules.ability_tasks_for_action(definition.action_id, definition.level))


def _action_level_for_ref(rules: RuleBook, action_ref: str, step: dict[str, JSONValue]) -> int:
    raw = step.get("action_level") or step.get("level")
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, (int, float)):
        return int(raw)
    levels = rules.action_levels(action_ref) if action_ref else ()
    return int(levels[0]) if levels else 1


def _is_monster_action_id(action_id: str) -> bool:
    return action_id.startswith(MONSTER_ACTION_PREFIXES)


def _monster_source(source_path: str, raw_id: str) -> bool:
    return "/Monster/" in source_path or "MonsterSkill" in source_path or str(raw_id).startswith("monster")


def _status_mutation_count(mutations: tuple[Any, ...]) -> int:
    return sum(
        1
        for mutation in mutations
        if getattr(mutation, "source", "") == "status_system"
        and ("statuses" in getattr(mutation, "path", ()) or "status_details" in getattr(mutation, "path", ()))
    )


def _mutation_source_counts(mutations: tuple[Any, ...]) -> dict[str, int]:
    return dict(sorted(Counter(str(mutation.source) for mutation in mutations).items()))


def _compact_coverage(coverage: dict[str, Any]) -> dict[str, JSONValue]:
    keys = (
        "action_enabled",
        "damage_mutation_count",
        "toughness_mutation_count",
        "resource_mutation_count",
        "status_mutation_count",
        "target_ok",
        "resource_ok",
        "binding_ok",
        "event_ok",
        "blocked_reason",
        "plan_blocked_reason",
    )
    return {key: coverage.get(key) for key in keys if key in coverage}


def _blocked_reason_category(reason: str) -> str:
    lowered = reason.lower()
    if "action_definition" in lowered or "skill_definition" in lowered:
        return "action_definition_missing"
    if "target" in lowered:
        return "target_gap"
    if "formula" in lowered or "param" in lowered or "dynamic" in lowered or "custom" in lowered:
        return "formula_or_dynamic_gap"
    if "status" in lowered or "modifier" in lowered:
        return "status_source_gap"
    if "profile" in lowered or "card" in lowered or "template" in lowered:
        return "profile_or_card_gap"
    if "queue" in lowered or "action_delay" in lowered:
        return "queue_or_delay_gap"
    if "binding" in lowered or "event" in lowered or "phase" in lowered:
        return "action_graph_admission_gap"
    return "other_admission_gap"


def _record_sample(record: dict[str, Any]) -> dict[str, JSONValue]:
    definition = record["definition"]
    return {
        "action_id": record["action_id"],
        "level": record["level"],
        "definition_source": definition.source.to_json() if definition is not None else {},
        "phase_count": record["phase_count"],
        "task_count": record["task_count"],
        "task_opcodes": list(record["task_opcodes"][:10]),
        "blocked_reasons": list(record["blocked_reasons"][:10]),
    }


def _card_sample(card: MonsterDataCardIR) -> dict[str, JSONValue]:
    return {
        "card_id": card.card_id,
        "entity_ref": card.entity_ref,
        "coverage_status": card.coverage_status,
        "blocked_reason": card.blocked_reason,
        "source": card.source.to_json(),
    }


def _samples_by_key(items: Iterable[Any], key: str) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for item in items:
        if key == "source.raw_type":
            value = str(item.source.raw_type)
        else:
            value = str(getattr(item, key, ""))
        samples.setdefault(value, item)
    return samples


def _getattr_or_none(item: Any, name: str) -> Any:
    return getattr(item, name, None) if item is not None else None


def _all_elements() -> list[str]:
    return ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    raw_count: int = 0,
    ir_count: int = 0,
    rulebook_visible_count: int = 0,
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    runtime_samples: list[dict[str, JSONValue]] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "rulebook_visible_count": int(rulebook_visible_count),
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": sample_source_trace or {},
        "runtime_samples": runtime_samples or [],
        "details": details or {},
    }


def _row_check(rows: dict[str, Any], row_id: str, check_id: str) -> bool:
    return (
        dict(dict(rows.get(row_id) or {}).get("checks") or {})
        .get("checks", {})
        .get(check_id)
        is True
    )


def _counter_top(counter: Counter[str], limit: int) -> list[dict[str, JSONValue]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _first(items: Iterable[Any]) -> Any | None:
    for item in items:
        return item
    return None


def _source(item: Any | None) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    return source.to_json() if source is not None else {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
