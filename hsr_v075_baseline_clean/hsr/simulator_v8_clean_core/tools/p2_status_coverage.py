from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..rules.ir import CanonicalIR, EffectIR, RuleEntity
from ..rules.rulebook import RuleBook
from .validate_v0_287 import (
    _counter_top,
    _load_json_file,
    _numeric_expr_kind,
    _source_area,
    _status_catalog_matrix,
    _target_expression_info,
    _value_string,
    _walk_json,
)


P2_CLASSIFICATION_STATES = {
    "executable",
    "source_absent_not_required",
    "boundary_only",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}

STATUS_EFFECT_OPCODES = {
    "AddModifier",
    "RemoveModifier",
    "RemoveSelfModifier",
    "DispelStatus",
}

STATUS_SOURCE_ROOTS = (
    "Config/ConfigAbility",
    "Config/ConfigGlobalModifier",
)

MATRIX_SCHEMA_VERSION = "p2_status_coverage_matrix_v0"


def build_p2_status_coverage_matrix(tbgd_root: Path, ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    status_catalog = _status_catalog_matrix(tbgd_root)
    raw_sources = _raw_status_source_matrix(tbgd_root)
    ir_sources = _ir_status_source_matrix(ir, rules)
    family_matrix = _status_family_matrix(status_catalog, raw_sources, ir_sources)
    classification_counts = Counter(str(item["classification"]) for item in family_matrix.values())
    source_item_counts = {
        "raw_total": sum(int(item["raw_count"]) for item in family_matrix.values()),
        "ir_total": sum(int(item["ir_count"]) for item in family_matrix.values()),
        "executable_total": sum(int(item["executable_count"]) for item in family_matrix.values()),
        "blocked_total": sum(int(item["blocked_count"]) for item in family_matrix.values()),
    }
    unclassified = [
        family_id
        for family_id, item in family_matrix.items()
        if item.get("classification") not in P2_CLASSIFICATION_STATES
    ]
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": False,
            "raw_sources_allowed_only_in_tools": True,
            "full_ir_written": False,
            "full_transition_dump_written": False,
        },
        "status_catalog": {
            "schema_version": status_catalog["schema_version"],
            "status_definition_total": status_catalog["aggregate"]["row_count"],
            "modifier_index_count": status_catalog["aggregate"]["modifier_index_count"],
            "status_type_counts": status_catalog["aggregate"]["status_type_counts"],
            "read_param_counts_top": status_catalog["aggregate"]["read_param_counts_top"][:30],
            "tag_counts_top": status_catalog["aggregate"]["tag_counts_top"][:30],
            "files": {
                name: {
                    "row_count": item["row_count"],
                    "status_type_counts": item["status_type_counts"],
                    "can_dispel_counts": item["can_dispel_counts"],
                    "sample_rows": item["sample_rows"][:3],
                }
                for name, item in sorted(status_catalog["files"].items())
            },
        },
        "raw_status_sources": raw_sources,
        "ir_status_sources": ir_sources,
        "status_family_matrix": family_matrix,
        "classification_counts": dict(sorted(classification_counts.items())),
        "source_item_counts": source_item_counts,
        "unclassified_families": unclassified,
        "unclassified_count": len(unclassified),
    }


def validate_p2_status_inventory_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    raw_sources = matrix["raw_status_sources"]
    ir_sources = matrix["ir_status_sources"]
    family_matrix = matrix["status_family_matrix"]
    required_families = {
        "status_definitions",
        "status_add_sources",
        "status_remove_sources",
        "status_dispel_sources",
        "status_lifecycle_sources",
        "status_stack_refresh_sources",
        "status_chance_resist_immunity_sources",
        "status_callback_event_families",
        "status_numeric_binding_sources",
        "status_damage_sources",
    }
    checks = {
        "status_definitions_seen": matrix["status_catalog"]["status_definition_total"] > 0,
        "raw_add_modifier_sources_seen": raw_sources["opcode_counts"].get("AddModifier", 0) > 0,
        "raw_remove_sources_seen": (
            raw_sources["opcode_counts"].get("RemoveModifier", 0)
            + raw_sources["opcode_counts"].get("RemoveSelfModifier", 0)
        ) > 0,
        "raw_dispel_sources_seen": raw_sources["opcode_counts"].get("DispelStatus", 0) > 0,
        "raw_callbacks_seen": raw_sources["callback_summary"]["total_callbacks"] > 0,
        "ir_status_effects_seen": ir_sources["status_effects"]["total"] > 0,
        "ir_status_callbacks_seen": ir_sources["callbacks"]["total_callbacks"] > 0,
        "ir_status_event_families_seen": ir_sources["callbacks"]["total_event_families"] > 0,
        "required_families_present": required_families.issubset(set(family_matrix)),
        "all_families_classified": matrix["unclassified_count"] == 0,
        "matrix_is_summary_only": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def validate_p2_ir_rulebook_integrity_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    definitions = matrix["ir_status_sources"]["definitions"]
    effects = matrix["ir_status_sources"]["status_effects"]
    callbacks = matrix["ir_status_sources"]["callbacks"]
    numeric = matrix["ir_status_sources"]["status_damage_and_numeric"]
    status_entity_count = definitions["status_entity_count"]
    modifier_definition_count = definitions["modifier_definition_count"]
    modifier_fields = definitions["modifier_definition_required_field_counts"]
    status_fields = definitions["status_entity_field_counts"]
    family_matrix = matrix["status_family_matrix"]
    checks = {
        "status_entity_count_covers_raw_catalog": status_entity_count >= matrix["status_catalog"]["status_definition_total"],
        "modifier_definitions_rulebook_visible": (
            definitions["modifier_definitions_rulebook_visible"] == modifier_definition_count
        ),
        "status_entities_rulebook_visible": definitions["status_entities_rulebook_visible"] == status_entity_count,
        "modifier_definition_source_trace_complete": (
            definitions["modifier_definition_source_trace_complete"] == modifier_definition_count
        ),
        "status_entity_source_trace_complete": definitions["status_entity_source_trace_complete"] == status_entity_count,
        "modifier_definition_core_fields_present": all(
            modifier_fields.get(key, 0) == modifier_definition_count
            for key in (
                "modifier_name",
                "stacking",
                "lifetime_expr",
                "duration_admission",
                "behavior_flags",
                "dynamic_value_bindings",
                "callback_events",
                "stack_properties",
            )
        ),
        "status_entity_modifier_name_present": status_fields.get("ModifierName", 0) == status_entity_count,
        "status_entity_status_type_present": status_fields.get("StatusType", 0) == status_entity_count,
        "status_entity_can_dispel_counted": "CanDispel" in status_fields,
        "status_effect_source_trace_complete": effects["source_trace_complete"] == effects["total"],
        "callbacks_rulebook_visible": callbacks["callbacks_rulebook_visible"] == callbacks["total_callbacks"],
        "event_families_rulebook_visible": (
            callbacks["event_families_rulebook_visible"] == callbacks["total_event_families"]
        ),
        "callback_tasks_source_trace_complete": (
            callbacks["callback_task_source_trace_complete"] == callbacks["total_callback_tasks"]
        ),
        "status_damage_source_trace_complete": (
            numeric["status_damage_source_trace_complete"] == numeric["status_damage_emission_count"]
        ),
        "action_delay_source_trace_complete": (
            numeric["action_delay_source_trace_complete"] == numeric["action_delay_emission_count"]
        ),
        "no_family_lowering_or_admission_gap": not any(
            item["classification"] in {"lowering_gap", "admission_gap"}
            for item in family_matrix.values()
        ),
        "all_families_classified": matrix["unclassified_count"] == 0,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _raw_status_source_matrix(tbgd_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    callback_events = Counter()
    callback_areas = Counter()
    callback_task_opcodes = Counter()
    callback_examples: dict[str, dict[str, Any]] = {}
    for path in _status_source_files(tbgd_root):
        data = _load_json_file(path)
        if data is None:
            continue
        relative_path = path.relative_to(tbgd_root).as_posix()
        source_area = _p2_source_area(relative_path)
        for node_path, node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            opcode = _gamecore_opcode(node)
            if opcode in STATUS_EFFECT_OPCODES:
                records.append(_raw_status_effect_record(relative_path, source_area, node_path, node, opcode))
            event = node.get("Event")
            callback_config = node.get("CallbackConfig")
            if isinstance(event, str) and isinstance(callback_config, list):
                callback_events[event] += 1
                callback_areas[source_area] += 1
                for _, child in _walk_json(callback_config):
                    if not isinstance(child, dict):
                        continue
                    child_opcode = _gamecore_opcode(child)
                    if child_opcode:
                        callback_task_opcodes[child_opcode] += 1
                callback_examples.setdefault(
                    event,
                    {
                        "source_path": relative_path,
                        "source_area": source_area,
                        "json_path": "/".join(node_path),
                        "event": event,
                        "source": {
                            "source_path": relative_path,
                            "raw_type": "StatusCallback",
                            "raw_id": "/".join(node_path),
                            "evidence": {"event": event},
                        },
                    },
                )

    opcode_counts = Counter(str(record["opcode"]) for record in records)
    source_area_counts = Counter(str(record["source_area"]) for record in records)
    opcode_area_counts: dict[str, Counter] = defaultdict(Counter)
    add_field_counts = Counter()
    add_life_time_kind = Counter()
    add_max_layer_kind = Counter()
    add_layer_add_kind = Counter()
    add_chance_kind = Counter()
    examples_by_opcode: dict[str, dict[str, Any]] = {}
    examples_by_classification_key: dict[str, dict[str, Any]] = {}
    for record in records:
        opcode = str(record["opcode"])
        opcode_area_counts[opcode][str(record["source_area"])] += 1
        examples_by_opcode.setdefault(opcode, _sample_status_effect_record(record))
        if opcode == "AddModifier":
            for field in record["present_fields"]:
                add_field_counts[str(field)] += 1
            add_life_time_kind[str(record["life_time_expr_kind"])] += 1
            add_max_layer_kind[str(record["max_layer_expr_kind"])] += 1
            add_layer_add_kind[str(record["layer_add_expr_kind"])] += 1
            add_chance_kind[str(record["chance_expr_kind"])] += 1
            examples_by_classification_key.setdefault(
                f"target:{record['target_expression_kind']}",
                _sample_status_effect_record(record),
            )
    return {
        "schema_version": "p2_raw_status_source_matrix_v0",
        "source_roots": list(STATUS_SOURCE_ROOTS),
        "total_status_effect_nodes": len(records),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "source_area_counts": dict(sorted(source_area_counts.items())),
        "opcode_source_area_counts": {
            opcode: dict(sorted(counter.items()))
            for opcode, counter in sorted(opcode_area_counts.items())
        },
        "add_modifier_field_presence_counts": dict(sorted(add_field_counts.items())),
        "add_modifier_life_time_expr_kind_counts": dict(sorted(add_life_time_kind.items())),
        "add_modifier_max_layer_expr_kind_counts": dict(sorted(add_max_layer_kind.items())),
        "add_modifier_layer_add_when_stack_expr_kind_counts": dict(sorted(add_layer_add_kind.items())),
        "add_modifier_chance_expr_kind_counts": dict(sorted(add_chance_kind.items())),
        "examples_by_opcode": examples_by_opcode,
        "examples_by_classification_key": dict(list(sorted(examples_by_classification_key.items()))[:20]),
        "callback_summary": {
            "total_callbacks": sum(callback_events.values()),
            "event_kind_count": len(callback_events),
            "event_counts_top": _counter_top(callback_events, 80),
            "source_area_counts": dict(sorted(callback_areas.items())),
            "task_opcode_counts_top": _counter_top(callback_task_opcodes, 80),
            "examples_by_event": dict(list(sorted(callback_examples.items()))[:30]),
        },
    }


def _ir_status_source_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    modifier_definitions = [entity for entity in ir.entities if entity.entity_type == "modifier_definition"]
    status_entities = [entity for entity in ir.entities if entity.entity_type == "status"]
    status_effects = [effect for effect in ir.effects if effect.opcode in STATUS_EFFECT_OPCODES]
    effects_by_opcode = Counter(effect.opcode for effect in status_effects)
    coverage_by_opcode: dict[str, Counter] = defaultdict(Counter)
    area_by_opcode: dict[str, Counter] = defaultdict(Counter)
    examples_by_opcode: dict[str, dict[str, Any]] = {}
    for effect in status_effects:
        coverage_by_opcode[effect.opcode][effect.coverage_status] += 1
        area_by_opcode[effect.opcode][_p2_source_area(effect.source.source_path)] += 1
        examples_by_opcode.setdefault(effect.opcode, _sample_effect(effect))

    callbacks_by_coverage = Counter(callback.coverage_status for callback in ir.status_callbacks)
    callbacks_by_admission = Counter(callback.admission_status for callback in ir.status_callbacks)
    families_by_coverage = Counter(family.coverage_status for family in ir.status_event_families)
    families_by_admission = Counter(family.admission_status for family in ir.status_event_families)
    callback_tasks_by_coverage = Counter(task.coverage_status for task in ir.status_callback_tasks)
    callback_tasks_by_opcode = Counter(task.opcode for task in ir.status_callback_tasks)
    status_damage_by_coverage = Counter(emission.coverage_status for emission in ir.status_damage_emissions)
    action_delay_by_coverage = Counter(emission.coverage_status for emission in ir.action_delay_emissions)
    damage_modifier_by_coverage = Counter(modifier.coverage_status for modifier in ir.damage_modifiers)
    queue_intent_by_coverage = Counter(intent.coverage_status for intent in ir.queue_intents)

    return {
        "schema_version": "p2_ir_status_source_matrix_v0",
        "definitions": {
            "modifier_definition_count": len(modifier_definitions),
            "status_entity_count": len(status_entities),
            "modifier_definitions_rulebook_visible": _modifier_definition_visibility(rules, modifier_definitions),
            "status_entities_rulebook_visible": _status_entity_visibility(rules, status_entities),
            "modifier_definition_source_trace_complete": _source_trace_complete_count(modifier_definitions),
            "status_entity_source_trace_complete": _source_trace_complete_count(status_entities),
            "modifier_definition_coverage_counts": _entity_coverage_counts(modifier_definitions),
            "status_entity_coverage_counts": _entity_coverage_counts(status_entities),
            "modifier_definition_required_field_counts": _field_presence_counts(
                modifier_definitions,
                (
                    "modifier_name",
                    "stacking",
                    "lifetime",
                    "lifetime_expr",
                    "life_step_moment",
                    "duration_admission",
                    "behavior_flags",
                    "dynamic_values",
                    "dynamic_value_bindings",
                    "callback_dynamic_hashes",
                    "callback_events",
                    "stack_properties",
                ),
            ),
            "status_entity_field_counts": _field_presence_counts(
                status_entities,
                ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList", "DisplayPriority"),
            ),
            "samples": {
                "modifier_definition": _sample_entity(modifier_definitions[0]) if modifier_definitions else None,
                "status_entity": _sample_entity(status_entities[0]) if status_entities else None,
            },
        },
        "status_effects": {
            "total": len(status_effects),
            "opcode_counts": dict(sorted(effects_by_opcode.items())),
            "source_trace_complete": _source_trace_complete_count(status_effects),
            "coverage_by_opcode": {
                opcode: dict(sorted(counter.items()))
                for opcode, counter in sorted(coverage_by_opcode.items())
            },
            "source_area_by_opcode": {
                opcode: dict(sorted(counter.items()))
                for opcode, counter in sorted(area_by_opcode.items())
            },
            "examples_by_opcode": examples_by_opcode,
        },
        "callbacks": {
            "total_callbacks": len(ir.status_callbacks),
            "total_callback_tasks": len(ir.status_callback_tasks),
            "total_event_families": len(ir.status_event_families),
            "callback_coverage_counts": dict(sorted(callbacks_by_coverage.items())),
            "callback_admission_counts": dict(sorted(callbacks_by_admission.items())),
            "event_family_coverage_counts": dict(sorted(families_by_coverage.items())),
            "event_family_admission_counts": dict(sorted(families_by_admission.items())),
            "callback_task_coverage_counts": dict(sorted(callback_tasks_by_coverage.items())),
            "callback_task_opcode_counts_top": _counter_top(callback_tasks_by_opcode, 80),
            "callbacks_rulebook_visible": sum(
                1 for callback in ir.status_callbacks if rules.status_callback(callback.callback_id) is not None
            ),
            "event_families_rulebook_visible": sum(
                1 for family in ir.status_event_families if rules.status_event_family(family.callback_event) is not None
            ),
            "callback_source_trace_complete": _source_trace_complete_count(ir.status_callbacks),
            "callback_task_source_trace_complete": _source_trace_complete_count(ir.status_callback_tasks),
            "event_family_source_trace_complete": _source_trace_complete_count(ir.status_event_families),
            "samples": {
                "event_family": ir.status_event_families[0].to_json() if ir.status_event_families else None,
                "callback": ir.status_callbacks[0].to_json() if ir.status_callbacks else None,
                "callback_task": ir.status_callback_tasks[0].to_json() if ir.status_callback_tasks else None,
            },
        },
        "status_damage_and_numeric": {
            "status_damage_emission_count": len(ir.status_damage_emissions),
            "status_damage_source_trace_complete": _source_trace_complete_count(ir.status_damage_emissions),
            "status_damage_coverage_counts": dict(sorted(status_damage_by_coverage.items())),
            "damage_modifier_count": len(ir.damage_modifiers),
            "damage_modifier_source_trace_complete": _source_trace_complete_count(ir.damage_modifiers),
            "damage_modifier_coverage_counts": dict(sorted(damage_modifier_by_coverage.items())),
            "action_delay_emission_count": len(ir.action_delay_emissions),
            "action_delay_source_trace_complete": _source_trace_complete_count(ir.action_delay_emissions),
            "action_delay_coverage_counts": dict(sorted(action_delay_by_coverage.items())),
            "queue_intent_count": len(ir.queue_intents),
            "queue_intent_source_trace_complete": _source_trace_complete_count(ir.queue_intents),
            "queue_intent_coverage_counts": dict(sorted(queue_intent_by_coverage.items())),
            "dynamic_value_definition_count": _dynamic_value_definition_count(modifier_definitions),
            "formula_binding_add_modifier_count": _status_formula_binding_effect_count(status_effects),
            "samples": {
                "status_damage_emission": ir.status_damage_emissions[0].to_json()
                if ir.status_damage_emissions
                else None,
                "damage_modifier": ir.damage_modifiers[0].to_json() if ir.damage_modifiers else None,
            },
        },
    }


def _status_family_matrix(
    status_catalog: dict[str, Any],
    raw_sources: dict[str, Any],
    ir_sources: dict[str, Any],
) -> dict[str, Any]:
    raw_opcode_counts = raw_sources["opcode_counts"]
    ir_effects = ir_sources["status_effects"]
    callback_ir = ir_sources["callbacks"]
    numeric_ir = ir_sources["status_damage_and_numeric"]
    add_fields = raw_sources["add_modifier_field_presence_counts"]
    duration_source_count = _non_missing_expr_count(raw_sources["add_modifier_life_time_expr_kind_counts"])
    families = {
        "status_definitions": _family_entry(
            "executable",
            "状态定义已从状态表和 modifier definition 投影为 RuleBook 可见事实。",
            raw_count=status_catalog["aggregate"]["row_count"],
            ir_count=ir_sources["definitions"]["modifier_definition_count"],
            executable_count=ir_sources["definitions"]["modifier_definitions_rulebook_visible"],
            evidence={
                "status_type_counts": status_catalog["aggregate"]["status_type_counts"],
                "modifier_definition_coverage_counts": ir_sources["definitions"]["modifier_definition_coverage_counts"],
            },
        ),
        "status_add_sources": _effect_family_entry("AddModifier", raw_opcode_counts, ir_effects),
        "status_remove_sources": _combined_effect_family_entry(
            ("RemoveModifier", "RemoveSelfModifier"),
            raw_opcode_counts,
            ir_effects,
            "状态移除来源已分类，RemoveModifier 与 RemoveSelfModifier 分开计数。",
        ),
        "status_dispel_sources": _effect_family_entry("DispelStatus", raw_opcode_counts, ir_effects),
        "status_lifecycle_sources": _family_entry(
            _classify_source_presence(
                raw_count=duration_source_count,
                ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
                executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            ),
            "持续时间、tick、过期来源按 LifeTime/LifeStepMoment 字段和 AddModifier admission 分类。",
            raw_count=duration_source_count,
            ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
            executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            evidence={"life_time_expr_kind_counts": raw_sources["add_modifier_life_time_expr_kind_counts"]},
        ),
        "status_stack_refresh_sources": _family_entry(
            _classify_source_presence(
                raw_count=(
                    add_fields.get("MaxLayer", 0)
                    + add_fields.get("LayerAddWhenStack", 0)
                    + add_fields.get("StackingFlag", 0)
                ),
                ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
                executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            ),
            "叠层、刷新、减少层数、替换和共存来源按 AddModifier 字段分布分类。",
            raw_count=add_fields.get("MaxLayer", 0) + add_fields.get("LayerAddWhenStack", 0) + add_fields.get("StackingFlag", 0),
            ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
            executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            evidence={
                "max_layer_expr_kind_counts": raw_sources["add_modifier_max_layer_expr_kind_counts"],
                "layer_add_when_stack_expr_kind_counts": raw_sources["add_modifier_layer_add_when_stack_expr_kind_counts"],
                "stacking_flag_count": add_fields.get("StackingFlag", 0),
            },
        ),
        "status_chance_resist_immunity_sources": _family_entry(
            _classify_source_presence(
                raw_count=add_fields.get("Chance", 0) + add_fields.get("ResistedTaskList", 0),
                ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
                executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            ),
            "状态概率、抵抗、免疫来源按 Chance / ResistedTaskList / 状态分类来源分类。",
            raw_count=add_fields.get("Chance", 0) + add_fields.get("ResistedTaskList", 0),
            ir_count=ir_effects["opcode_counts"].get("AddModifier", 0),
            executable_count=ir_effects["coverage_by_opcode"].get("AddModifier", {}).get("executable", 0),
            evidence={
                "chance_expr_kind_counts": raw_sources["add_modifier_chance_expr_kind_counts"],
                "resisted_task_list_count": add_fields.get("ResistedTaskList", 0),
            },
        ),
        "status_callback_event_families": _family_entry(
            _classify_source_presence(
                raw_count=raw_sources["callback_summary"]["total_callbacks"],
                ir_count=callback_ir["total_event_families"],
                executable_count=callback_ir["event_family_coverage_counts"].get("executable", 0),
            ),
            "状态回调事件族、callback task 和 runtime event source 已进入 Canonical IR 矩阵。",
            raw_count=raw_sources["callback_summary"]["total_callbacks"],
            ir_count=callback_ir["total_event_families"],
            executable_count=callback_ir["event_family_coverage_counts"].get("executable", 0),
            blocked_count=callback_ir["event_family_coverage_counts"].get("blocked", 0),
            evidence={
                "event_family_coverage_counts": callback_ir["event_family_coverage_counts"],
                "callback_task_opcode_counts_top": callback_ir["callback_task_opcode_counts_top"][:20],
            },
        ),
        "status_numeric_binding_sources": _family_entry(
            _classify_source_presence(
                raw_count=add_fields.get("DynamicValues", 0),
                ir_count=numeric_ir["dynamic_value_definition_count"] + numeric_ir["damage_modifier_count"],
                executable_count=numeric_ir["dynamic_value_definition_count"] + numeric_ir["damage_modifier_coverage_counts"].get("executable", 0),
            ),
            "状态动态值、状态层数读取、damage modifier 和公式绑定来源已分类。",
            raw_count=add_fields.get("DynamicValues", 0),
            ir_count=numeric_ir["dynamic_value_definition_count"] + numeric_ir["damage_modifier_count"],
            executable_count=numeric_ir["dynamic_value_definition_count"] + numeric_ir["damage_modifier_coverage_counts"].get("executable", 0),
            blocked_count=numeric_ir["damage_modifier_coverage_counts"].get("blocked", 0),
            evidence={
                "dynamic_value_definition_count": numeric_ir["dynamic_value_definition_count"],
                "damage_modifier_coverage_counts": numeric_ir["damage_modifier_coverage_counts"],
                "formula_binding_add_modifier_count": numeric_ir["formula_binding_add_modifier_count"],
            },
        ),
        "status_damage_sources": _family_entry(
            _classify_source_presence(
                raw_count=raw_sources["callback_summary"]["task_opcode_counts_top"][0]["count"]
                if raw_sources["callback_summary"]["task_opcode_counts_top"]
                else 0,
                ir_count=numeric_ir["status_damage_emission_count"],
                executable_count=numeric_ir["status_damage_coverage_counts"].get("executable", 0),
            ),
            "DoT、状态触发伤害和状态伤害 emission 已按 StatusDamageEmissionIR 分类。",
            raw_count=numeric_ir["status_damage_emission_count"],
            ir_count=numeric_ir["status_damage_emission_count"],
            executable_count=numeric_ir["status_damage_coverage_counts"].get("executable", 0),
            blocked_count=numeric_ir["status_damage_coverage_counts"].get("blocked", 0),
            evidence={"status_damage_coverage_counts": numeric_ir["status_damage_coverage_counts"]},
        ),
    }
    return {key: families[key] for key in sorted(families)}


def _status_source_files(tbgd_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative_root in STATUS_SOURCE_ROOTS:
        root = tbgd_root / relative_root
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.json") if not path.name.endswith(".layout.json"))
    return tuple(sorted(files))


def _raw_status_effect_record(
    relative_path: str,
    source_area: str,
    node_path: list[str],
    node: dict[str, Any],
    opcode: str,
) -> dict[str, Any]:
    target_info = _target_expression_info(node.get("TargetType")) or _target_expression_info(node)
    target_kind = target_info["target_expression_kind"] if target_info else "target_missing"
    target_alias = str(target_info.get("alias") or "") if target_info else ""
    modifier_name = _value_string(node.get("ModifierName"))
    if not modifier_name and isinstance(node.get("ModifierNames"), list):
        modifier_name = ",".join(str(item) for item in node["ModifierNames"] if isinstance(item, str))[:120]
    return {
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "opcode": opcode,
        "modifier_name": modifier_name,
        "target_expression_kind": target_kind,
        "target_alias": target_alias,
        "present_fields": sorted(str(key) for key in node.keys()),
        "life_time_expr_kind": _numeric_expr_kind(node.get("LifeTime")),
        "max_layer_expr_kind": _numeric_expr_kind(node.get("MaxLayer")),
        "layer_add_expr_kind": _numeric_expr_kind(node.get("LayerAddWhenStack")),
        "chance_expr_kind": _numeric_expr_kind(node.get("Chance", node.get("Probability"))),
        "source": {
            "source_path": relative_path,
            "raw_type": f"RPG.GameCore.{opcode}",
            "raw_id": "/".join(node_path),
            "evidence": {
                "modifier_name": modifier_name,
                "target_expression_kind": target_kind,
                "target_alias": target_alias,
            },
        },
    }


def _effect_family_entry(opcode: str, raw_opcode_counts: dict[str, int], ir_effects: dict[str, Any]) -> dict[str, Any]:
    coverage = ir_effects["coverage_by_opcode"].get(opcode, {})
    return _family_entry(
        _classify_source_presence(
            raw_count=raw_opcode_counts.get(opcode, 0),
            ir_count=ir_effects["opcode_counts"].get(opcode, 0),
            executable_count=coverage.get("executable", 0),
        ),
        f"{opcode} 来源已按 raw / IR / RuleBook admission 分类。",
        raw_count=raw_opcode_counts.get(opcode, 0),
        ir_count=ir_effects["opcode_counts"].get(opcode, 0),
        executable_count=coverage.get("executable", 0),
        blocked_count=coverage.get("blocked", 0),
        evidence={"coverage_counts": coverage, "source_area_counts": ir_effects["source_area_by_opcode"].get(opcode, {})},
    )


def _combined_effect_family_entry(
    opcodes: tuple[str, ...],
    raw_opcode_counts: dict[str, int],
    ir_effects: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    raw_count = sum(raw_opcode_counts.get(opcode, 0) for opcode in opcodes)
    ir_count = sum(ir_effects["opcode_counts"].get(opcode, 0) for opcode in opcodes)
    executable_count = sum(ir_effects["coverage_by_opcode"].get(opcode, {}).get("executable", 0) for opcode in opcodes)
    blocked_count = sum(ir_effects["coverage_by_opcode"].get(opcode, {}).get("blocked", 0) for opcode in opcodes)
    return _family_entry(
        _classify_source_presence(raw_count=raw_count, ir_count=ir_count, executable_count=executable_count),
        summary,
        raw_count=raw_count,
        ir_count=ir_count,
        executable_count=executable_count,
        blocked_count=blocked_count,
        evidence={
            opcode: {
                "coverage_counts": ir_effects["coverage_by_opcode"].get(opcode, {}),
                "source_area_counts": ir_effects["source_area_by_opcode"].get(opcode, {}),
            }
            for opcode in opcodes
        },
    )


def _family_entry(
    classification: str,
    summary: str,
    *,
    raw_count: int,
    ir_count: int,
    executable_count: int,
    blocked_count: int = 0,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "summary": summary,
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "executable_count": int(executable_count),
        "blocked_count": int(blocked_count),
        "evidence": evidence or {},
    }


def _classify_source_presence(*, raw_count: int, ir_count: int, executable_count: int) -> str:
    if raw_count <= 0 and ir_count <= 0:
        return "source_absent_not_required"
    if raw_count > 0 and ir_count <= 0:
        return "lowering_gap"
    if ir_count > 0 and executable_count <= 0:
        return "boundary_only"
    return "executable"


def _non_missing_expr_count(counter: dict[str, int]) -> int:
    return sum(count for key, count in counter.items() if key != "missing")


def _sample_status_effect_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": record["source_path"],
        "source_area": record["source_area"],
        "json_path": record["json_path"],
        "opcode": record["opcode"],
        "modifier_name": record.get("modifier_name", ""),
        "target_expression_kind": record.get("target_expression_kind", ""),
        "target_alias": record.get("target_alias", ""),
        "source": record["source"],
    }


def _sample_effect(effect: EffectIR) -> dict[str, Any]:
    standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
    return {
        "effect_id": effect.effect_id,
        "opcode": effect.opcode,
        "coverage_status": effect.coverage_status,
        "modifier_name": standard.get("modifier_name") if isinstance(standard, dict) else "",
        "target_alias": standard.get("target_alias") if isinstance(standard, dict) else "",
        "source": effect.source.to_json(),
    }


def _sample_entity(entity: RuleEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "modifier_name": entity.fields.get("modifier_name") or entity.fields.get("ModifierName"),
        "coverage_status": entity.coverage_status,
        "source": entity.source.to_json(),
    }


def _entity_coverage_counts(entities: list[RuleEntity]) -> dict[str, int]:
    return dict(sorted(Counter(entity.coverage_status for entity in entities).items()))


def _field_presence_counts(entities: list[RuleEntity], field_names: tuple[str, ...]) -> dict[str, int]:
    return {
        field_name: sum(1 for entity in entities if field_name in entity.fields)
        for field_name in field_names
    }


def _source_trace_complete_count(items: Any) -> int:
    count = 0
    for item in items:
        source = getattr(item, "source", None)
        if source is None:
            continue
        if source.source_path and source.raw_type and source.raw_id:
            count += 1
    return count


def _modifier_definition_visibility(rules: RuleBook, definitions: list[RuleEntity]) -> int:
    count = 0
    for entity in definitions:
        modifier_name = entity.fields.get("modifier_name") or entity.fields.get("ModifierName")
        if isinstance(modifier_name, str) and rules.modifier_definition(modifier_name) is not None:
            count += 1
    return count


def _status_entity_visibility(rules: RuleBook, entities: list[RuleEntity]) -> int:
    count = 0
    for entity in entities:
        modifier_name = entity.fields.get("modifier_name") or entity.fields.get("ModifierName")
        if isinstance(modifier_name, str) and rules.status_entity_for_modifier(modifier_name) is not None:
            count += 1
    return count


def _dynamic_value_definition_count(definitions: list[RuleEntity]) -> int:
    count = 0
    for entity in definitions:
        fields = entity.fields
        if isinstance(fields.get("dynamic_value_bindings"), dict) and fields["dynamic_value_bindings"]:
            count += 1
        if isinstance(fields.get("callback_dynamic_hashes"), dict) and fields["callback_dynamic_hashes"]:
            count += 1
    return count


def _status_formula_binding_effect_count(effects: list[EffectIR]) -> int:
    count = 0
    for effect in effects:
        if effect.opcode != "AddModifier":
            continue
        standard = effect.payload.get("standard")
        if isinstance(standard, dict) and standard.get("status_formula_bindings"):
            count += 1
    return count


def _gamecore_opcode(node: dict[str, Any]) -> str:
    node_type = str(node.get("$type") or "")
    if not node_type.startswith("RPG.GameCore."):
        return ""
    return node_type.removeprefix("RPG.GameCore.")


def _p2_source_area(relative_path: str) -> str:
    if relative_path.startswith("Config/ConfigGlobalModifier/"):
        return "GlobalModifier"
    if relative_path.startswith("Config/ConfigGlobalTaskListTemplate/"):
        return "GlobalModifier"
    if relative_path == "Config/ConfigAbility/StageBattleEventAbility.json":
        return "BattleEvent"
    if relative_path == "Config/ConfigAbility/TrialPlayerPassiveAbility.json":
        return "Avatar"
    if relative_path == "Config/ConfigAbility/Common_Additional_Ability.json":
        return "GlobalModifier"
    return _source_area(relative_path)
