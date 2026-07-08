from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.ir import CanonicalIR, IRSource
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_287 import _counter_top, _load_json_file, _source_area, _target_expression_info, _walk_json


VALIDATION_VERSION = "p3_s0_summon_source_inventory"
MATRIX_SCHEMA_VERSION = "p3_summon_source_inventory_matrix_s0"

P3_CLASSIFICATION_STATES = {
    "executable",
    "source_absent_not_required",
    "source_gap_blocked",
    "boundary_only",
    "out_of_scope",
    "lowering_gap",
    "admission_gap",
    "validation_gap",
    "implementation_missing",
}

P3_RELEVANT_OPCODES = {
    "SummonMonster",
    "SummonUnit",
    "TurnInsertAssistantAbility",
}

P3_TARGET_ALIASES = {
    "CasterServant",
    "CasterSummonedMinions",
    "LastSummonMonsters",
    "ServantEntityList",
}

ASSISTANT_AVATAR_TARGET_ALIASES = {
    "AssistantAvatar",
    "FriendServantSelect",
}

P3_TARGET_FETCH_KINDS = {
    "TargetFetchModifierOwner",
    "TargetFetchOwner",
    "TargetQuery",
}

P3_TARGET_OPERATIONS = {
    "GetServant",
    "GetSummoner",
    "RemoveServant",
}

P3_LIFECYCLE_EVENTS = {
    "OnBeforeDying",
    "OnDestroy",
    "OnEnterBattle",
    "OnListenAllowAction",
    "OnListenModifierRemove",
    "OnModifierRemove",
    "OnWaveMonster",
}

P3_LIFECYCLE_OPCODES = {
    "AddModifier",
    "ForceKill",
    "RemoveModifier",
    "RemoveSelfModifier",
    "SummonMonster",
    "SummonUnit",
    "TurnInsertAction",
    "TurnInsertAssistantAbility",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p3_summon_source_inventory_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p3_summon_source_inventory_matrix(matrix)
    checks = {
        "inventory": inventory_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p3_s0_full_summon_source_inventory_structured_predicates",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
            },
        },
        "checks": checks,
        "summary": {
            "domain_count": len(matrix["domain_matrix"]),
            "classification_counts": matrix["classification_counts"],
            "source_item_counts": matrix["source_item_counts"],
            "unclassified_count": matrix["unclassified_count"],
            "summon_monster_raw_count": matrix["raw_ability_sources"]["opcode_counts"].get("SummonMonster", 0),
            "summon_monster_ir_count": matrix["summon_monster_intents"]["ir_count"],
            "summon_unit_raw_count": matrix["summon_unit_definitions"]["raw_count"],
            "summon_unit_ir_count": matrix["summon_unit_definitions"]["ir_count"],
            "servant_raw_count": matrix["servant_sources"]["raw_servant_config_count"],
            "servant_ir_count": matrix["servant_sources"]["servant_definition_ir_count"],
            "assistant_raw_count": matrix["raw_ability_sources"]["opcode_counts"].get("TurnInsertAssistantAbility", 0),
            "assistant_resolution_ir_count": matrix["assistant_sources"]["assistant_resolution_ir_count"],
            "p3_target_raw_count": matrix["target_relation_sources"]["raw_count"],
            "p3_target_ir_count": matrix["target_relation_sources"]["ir_count"],
            "lifecycle_raw_count": matrix["lifecycle_sources"]["raw_count"],
            "lifecycle_ir_count": matrix["lifecycle_sources"]["ir_count"],
        },
        "domain_matrix": matrix["domain_matrix"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s0_summon_source_inventory.json", result)
    write_json(output_dir / "p3_summon_source_inventory_matrix_s0.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate P3-S0 summon/servant source inventory with AssistantAvatar scope exclusion."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def build_p3_summon_source_inventory_matrix(tbgd_root: Path, ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    raw_ability_sources = _raw_ability_source_matrix(tbgd_root)
    summon_unit_sources = _summon_unit_source_matrix(tbgd_root, ir)
    monster_catalog_sources = _monster_catalog_ref_matrix(tbgd_root, ir)
    summon_monster_sources = _summon_monster_intent_matrix(raw_ability_sources, ir, rules)
    servant_sources = _servant_source_matrix(tbgd_root, ir, rules)
    assistant_sources = _assistant_source_matrix(raw_ability_sources, ir, rules)
    target_relation_sources = _target_relation_source_matrix(tbgd_root, raw_ability_sources, ir)
    lifecycle_sources = _lifecycle_source_matrix(raw_ability_sources, ir, rules)

    domain_matrix = {
        "summoned_monster_intent": _domain_row(
            source_domain="summoned_monster_intent",
            raw_count=summon_monster_sources["raw_count"],
            ir_count=summon_monster_sources["ir_count"],
            executable_count=summon_monster_sources["coverage_status_counts"].get("executable", 0),
            blocked_count=summon_monster_sources["coverage_status_counts"].get("blocked", 0),
            classification=(
                "executable"
                if summon_monster_sources["coverage_status_counts"].get("executable", 0) > 0
                else _missing_or_gap_classification(summon_monster_sources["raw_count"], summon_monster_sources["ir_count"])
            ),
            sample_source_trace=summon_monster_sources["sample_source_trace"],
            gap_attribution=summon_monster_sources["gap_attribution"],
            notes="SummonMonster ability task lower to SummonMonsterIntentIR; unsupported subsets remain blocked by reason.",
            gap_reason_token_counts=summon_monster_sources["gap_reason_token_counts"],
            gap_reason_layer_counts=summon_monster_sources["gap_reason_layer_counts"],
        ),
        "summon_unit_config_catalog": _domain_row(
            source_domain="summon_unit_config_catalog",
            raw_count=summon_unit_sources["raw_count"],
            ir_count=summon_unit_sources["ir_count"],
            executable_count=summon_unit_sources["coverage_status_counts"].get("executable", 0),
            blocked_count=summon_unit_sources["coverage_status_counts"].get("blocked", 0),
            classification="boundary_only",
            sample_source_trace=summon_unit_sources["sample_source_trace"],
            gap_attribution=summon_unit_sources["gap_attribution"],
            notes="SummonUnitData/ConfigSummonUnit is a definition/catalog source; spawn requires a separate runtime intent.",
        ),
        "battle_unit_summon_candidate": _domain_row(
            source_domain="battle_unit_summon_candidate",
            raw_count=summon_unit_sources["battle_admission_candidate_count"],
            ir_count=summon_unit_sources["battle_admission_candidate_count"],
            executable_count=0,
            blocked_count=summon_unit_sources["battle_admission_candidate_count"],
            classification=(
                "admission_gap"
                if summon_unit_sources["battle_admission_candidate_count"] > 0
                else "source_absent_not_required"
            ),
            sample_source_trace=summon_unit_sources["battle_candidate_sample_source_trace"],
            gap_attribution=(
                {"admission_gap": summon_unit_sources["battle_admission_candidate_count"]}
                if summon_unit_sources["battle_admission_candidate_count"] > 0
                else {}
            ),
            notes="SummonUnit battle candidates require explicit battle runtime triggers; the current database has none admitted.",
        ),
        "client_scene_adventure_summon": _domain_row(
            source_domain="client_scene_adventure_summon",
            raw_count=summon_unit_sources["non_battle_kind_count"],
            ir_count=summon_unit_sources["non_battle_kind_count"],
            executable_count=0,
            blocked_count=summon_unit_sources["non_battle_kind_count"],
            classification="source_absent_not_required",
            sample_source_trace=summon_unit_sources["non_battle_sample_source_trace"],
            gap_attribution={},
            notes="Client, visual, adventure, or follow-unit summon definitions are not combat runtime spawn sources.",
        ),
        "monster_summon_catalog_ref": _domain_row(
            source_domain="monster_summon_catalog_ref",
            raw_count=monster_catalog_sources["raw_monster_config_with_summon_refs"],
            ir_count=monster_catalog_sources["monster_data_card_with_summon_refs"],
            executable_count=0,
            blocked_count=monster_catalog_sources["monster_data_card_with_summon_refs"],
            classification="boundary_only",
            sample_source_trace=monster_catalog_sources["sample_source_trace"],
            gap_attribution={},
            notes="MonsterConfig.SummonIDList is retained as catalog evidence, not a runtime trigger.",
        ),
        "servant_definition": _domain_row(
            source_domain="servant_definition",
            raw_count=servant_sources["raw_servant_config_count"],
            ir_count=servant_sources["servant_definition_ir_count"],
            executable_count=servant_sources["coverage_status_counts"].get("executable", 0),
            blocked_count=servant_sources["coverage_status_counts"].get("blocked", 0),
            classification=(
                "executable"
                if servant_sources["coverage_status_counts"].get("executable", 0) > 0
                else _missing_or_gap_classification(
                    servant_sources["raw_servant_config_count"],
                    servant_sources["servant_definition_ir_count"],
                )
            ),
            sample_source_trace=servant_sources["sample_source_trace"],
            gap_attribution=servant_sources["gap_attribution"],
            notes="AvatarServantConfig lowers to owner-bound ServantDefinitionIR with stat, timeline, lifecycle, and action admission evidence.",
        ),
        "servant_skill_and_ability_files": _domain_row(
            source_domain="servant_skill_and_ability_files",
            raw_count=servant_sources["raw_servant_skill_count"],
            ir_count=servant_sources["servant_action_definition_count"],
            executable_count=servant_sources["servant_action_definition_executable_count"],
            blocked_count=servant_sources["servant_action_definition_blocked_count"],
            classification=(
                "executable"
                if servant_sources["servant_action_definition_executable_count"] > 0
                else _missing_or_gap_classification(
                    servant_sources["raw_servant_skill_count"],
                    servant_sources["servant_action_definition_count"],
                )
            ),
            sample_source_trace=servant_sources["servant_skill_sample_source_trace"],
            gap_attribution=servant_sources["servant_skill_gap_attribution"],
            notes="AvatarServantSkillConfig and servant ability files provide servant action graph sources.",
        ),
        "assistant_ability_queue": _domain_row(
            source_domain="assistant_ability_queue",
            raw_count=assistant_sources["raw_count"],
            ir_count=assistant_sources["assistant_resolution_ir_count"],
            executable_count=assistant_sources["resolution_coverage_status_counts"].get("executable", 0),
            blocked_count=assistant_sources["resolution_coverage_status_counts"].get("blocked", 0),
            classification="out_of_scope",
            sample_source_trace=assistant_sources["sample_source_trace"],
            gap_attribution={},
            notes=(
                "TurnInsertAssistantAbility belongs to the AssistantAvatar / avatar assistant ability system, "
                "not summon monster or servant runtime. It is inventoried here as a P3 scope exclusion."
            ),
            gap_reason_token_counts=assistant_sources["gap_reason_token_counts"],
            gap_reason_layer_counts=assistant_sources["gap_reason_layer_counts"],
        ),
        "summon_target_expression": _domain_row(
            source_domain="summon_target_expression",
            raw_count=target_relation_sources["raw_count"],
            ir_count=target_relation_sources["ir_count"],
            executable_count=target_relation_sources["coverage_status_counts"].get("executable", 0),
            blocked_count=target_relation_sources["coverage_status_counts"].get("blocked", 0),
            classification=(
                "executable"
                if target_relation_sources["coverage_status_counts"].get("executable", 0) > 0
                else _missing_or_gap_classification(target_relation_sources["raw_count"], target_relation_sources["ir_count"])
            ),
            sample_source_trace=target_relation_sources["sample_source_trace"],
            gap_attribution=target_relation_sources["gap_attribution"],
            notes="Summon/servant target aliases and operations are inventoried from raw ability usage, global target config, and TargetExpressionIR.",
            gap_reason_token_counts=target_relation_sources["gap_reason_token_counts"],
            gap_reason_layer_counts=target_relation_sources["gap_reason_layer_counts"],
        ),
        "lifecycle_cleanup_and_actionability_sources": _domain_row(
            source_domain="lifecycle_cleanup_and_actionability_sources",
            raw_count=lifecycle_sources["raw_count"],
            ir_count=lifecycle_sources["ir_count"],
            executable_count=lifecycle_sources["executable_count"],
            blocked_count=lifecycle_sources["blocked_count"],
            classification="boundary_only",
            sample_source_trace=lifecycle_sources["sample_source_trace"],
            gap_attribution=lifecycle_sources["gap_attribution"],
            notes="Owner death, remove, expire, wave clear, targetability, and actionability are inventoried as lifecycle candidates for later P3 steps.",
        ),
    }
    classification_counts = Counter(str(item["classification"]) for item in domain_matrix.values())
    source_item_counts = {
        "raw_total": sum(int(item["raw_count"]) for item in domain_matrix.values()),
        "ir_total": sum(int(item["ir_count"]) for item in domain_matrix.values()),
        "executable_total": sum(int(item["executable_count"]) for item in domain_matrix.values()),
        "blocked_total": sum(int(item["blocked_count"]) for item in domain_matrix.values()),
        "gap_total": sum(int(item["gap_count"]) for item in domain_matrix.values()),
    }
    unclassified = [
        domain_id
        for domain_id, item in sorted(domain_matrix.items())
        if item.get("classification") not in P3_CLASSIFICATION_STATES
    ]
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "coverage_scope": {
            "runtime_behavior_changed": False,
            "raw_sources_allowed_only_in_tools": True,
            "textmap_read": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "samples_per_bucket": 3,
        },
        "raw_ability_sources": raw_ability_sources["summary"],
        "summon_monster_intents": summon_monster_sources,
        "summon_unit_definitions": summon_unit_sources,
        "monster_catalog_refs": monster_catalog_sources,
        "servant_sources": servant_sources,
        "assistant_sources": assistant_sources,
        "target_relation_sources": target_relation_sources,
        "lifecycle_sources": lifecycle_sources,
        "domain_matrix": domain_matrix,
        "classification_counts": dict(sorted(classification_counts.items())),
        "source_item_counts": source_item_counts,
        "unclassified_domains": unclassified,
        "unclassified_count": len(unclassified),
    }


def validate_p3_summon_source_inventory_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    domains = matrix["domain_matrix"]
    raw_ability = matrix["raw_ability_sources"]
    summon_units = matrix["summon_unit_definitions"]
    servants = matrix["servant_sources"]
    assistants = matrix["assistant_sources"]
    targets = matrix["target_relation_sources"]
    lifecycle = matrix["lifecycle_sources"]
    required_domains = {
        "assistant_ability_queue",
        "battle_unit_summon_candidate",
        "client_scene_adventure_summon",
        "lifecycle_cleanup_and_actionability_sources",
        "monster_summon_catalog_ref",
        "servant_definition",
        "servant_skill_and_ability_files",
        "summon_target_expression",
        "summon_unit_config_catalog",
        "summoned_monster_intent",
    }
    checks = {
        "summon_monster_raw_seen": raw_ability["opcode_counts"].get("SummonMonster", 0) > 0,
        "summon_monster_raw_ir_linked": (
            raw_ability["opcode_counts"].get("SummonMonster", 0) > 0
            and matrix["summon_monster_intents"]["ir_count"] > 0
            and matrix["summon_monster_intents"]["rulebook_visible_count"]
            == matrix["summon_monster_intents"]["ir_count"]
        ),
        "summon_unit_raw_ir_linked": summon_units["raw_count"] == summon_units["ir_count"],
        "summon_unit_subclasses_present": bool(summon_units["summon_kind_counts"]),
        "monster_catalog_refs_classified_boundary": (
            domains["monster_summon_catalog_ref"]["classification"] == "boundary_only"
        ),
        "servant_raw_ir_linked": (
            servants["raw_servant_config_count"] == servants["servant_definition_ir_count"]
        ),
        "servant_skill_sources_seen": servants["raw_servant_skill_count"] > 0,
        "assistant_raw_ir_linked": (
            assistants["raw_count"] > 0
            and assistants["queue_intent_ir_count"] > 0
            and assistants["queue_intent_ir_count"] == assistants["assistant_resolution_ir_count"]
            and assistants["rulebook_visible_count"] == assistants["assistant_resolution_ir_count"]
        ),
        "assistant_avatar_scope_excluded": domains["assistant_ability_queue"]["classification"] == "out_of_scope",
        "target_relation_sources_seen": targets["raw_count"] > 0 and targets["ir_count"] > 0,
        "lifecycle_sources_seen": lifecycle["raw_count"] > 0 and lifecycle["ir_count"] > 0,
        "required_domains_present": required_domains.issubset(set(domains)),
        "all_domains_classified": matrix["unclassified_count"] == 0,
        "gap_domains_have_attribution": all(
            item["classification"] not in {"lowering_gap", "admission_gap", "validation_gap", "implementation_missing"}
            or bool(item["gap_attribution"])
            for item in domains.values()
        ),
        "matrix_is_summary_only": (
            matrix["coverage_scope"]["full_ir_written"] is False
            and matrix["coverage_scope"]["full_transition_dump_written"] is False
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _raw_ability_source_matrix(tbgd_root: Path) -> dict[str, Any]:
    task_records: list[dict[str, Any]] = []
    target_records: list[dict[str, Any]] = []
    lifecycle_records: list[dict[str, Any]] = []
    scanned_files = 0
    for path in _ability_source_files(tbgd_root):
        data = _load_json_file(path)
        if data is None:
            continue
        scanned_files += 1
        relative_path = path.relative_to(tbgd_root).as_posix()
        source_area = _p3_source_area(relative_path)
        for node_path, node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            opcode = _gamecore_opcode(node)
            if opcode in P3_RELEVANT_OPCODES:
                task_records.append(_raw_task_record(relative_path, source_area, node_path, node, opcode))
            target_info = _target_expression_info(node)
            if target_info is not None and _is_p3_target_info(target_info):
                target_records.append(_raw_target_record(relative_path, source_area, node_path, target_info))
            lifecycle = _raw_lifecycle_record(relative_path, source_area, node_path, node)
            if lifecycle is not None:
                lifecycle_records.append(lifecycle)
    opcode_counts = Counter(str(record["opcode"]) for record in task_records)
    source_area_counts = Counter(str(record["source_area"]) for record in task_records)
    return {
        "task_records": task_records,
        "target_records": target_records,
        "lifecycle_records": lifecycle_records,
        "summary": {
            "schema_version": "p3_raw_ability_sources_s0",
            "scanned_file_count": scanned_files,
            "total_relevant_task_count": len(task_records),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "source_area_counts": dict(sorted(source_area_counts.items())),
            "target_relation_record_count": len(target_records),
            "lifecycle_record_count": len(lifecycle_records),
            "examples_by_opcode": _examples_by_key(task_records, "opcode"),
            "target_examples": target_records[:3],
            "lifecycle_examples": lifecycle_records[:3],
        },
    }


def _summon_monster_intent_matrix(raw_ability_sources: dict[str, Any], ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    intents = tuple(sorted(ir.summon_monster_intents, key=lambda item: item.summon_intent_id))
    status_counts = Counter(intent.coverage_status for intent in intents)
    blocked_reason_counts = Counter(intent.blocked_reason for intent in intents if intent.blocked_reason)
    entry_status_counts = Counter(entry.coverage_status for intent in intents for entry in intent.entries)
    entry_blocked_reason_counts = Counter(
        entry.blocked_reason for intent in intents for entry in intent.entries if entry.blocked_reason
    )
    all_reason_counts = blocked_reason_counts + entry_blocked_reason_counts
    first = _first_with_status(intents, "executable") or (intents[0] if intents else None)
    rulebook_visible = sum(1 for intent in intents if rules.summon_monster_intent(intent.summon_intent_id) == intent)
    return {
        "schema_version": "p3_summon_monster_intents_s0",
        "raw_count": raw_ability_sources["summary"]["opcode_counts"].get("SummonMonster", 0),
        "ir_count": len(intents),
        "raw_to_ir_projection": {
            "raw_occurrence_count": raw_ability_sources["summary"]["opcode_counts"].get("SummonMonster", 0),
            "ir_intent_count": len(intents),
            "ir_may_exceed_raw": True,
            "reason": "AbilityTaskIR is expanded through action/level/source binding; S0 requires traceability, not one-to-one raw occurrence equality.",
        },
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts_top": _counter_top(blocked_reason_counts, 40),
        "entry_coverage_status_counts": dict(sorted(entry_status_counts.items())),
        "entry_blocked_reason_counts_top": _counter_top(entry_blocked_reason_counts, 40),
        "gap_reason_token_counts": _reason_token_counts(all_reason_counts),
        "gap_reason_layer_counts": _reason_layer_counts(all_reason_counts),
        "rulebook_visible_count": rulebook_visible,
        "sample_source_trace": _source_trace_sample(first.source if first is not None else None),
        "sample_intent": _sample_item(first),
        "gap_attribution": _gap_attribution_from_reasons(all_reason_counts),
    }


def _summon_unit_source_matrix(tbgd_root: Path, ir: CanonicalIR) -> dict[str, Any]:
    raw_rows = _load_json_rows(tbgd_root / "ExcelOutput" / "SummonUnitData.json")
    definitions = tuple(sorted(ir.summon_unit_definitions, key=lambda item: item.summon_definition_id))
    status_counts = Counter(definition.coverage_status for definition in definitions)
    kind_counts = Counter(definition.summon_kind for definition in definitions)
    reason_counts = Counter(definition.blocked_reason for definition in definitions if definition.blocked_reason)
    battle_candidates = tuple(
        item
        for item in definitions
        if item.summon_kind == "battle_candidate"
        or item.blocked_reason == "summon_unit_battle_admission_source_missing"
    )
    non_battle = tuple(item for item in definitions if item not in battle_candidates)
    config_exists = sum(
        1
        for definition in definitions
        if definition.source.evidence.get("config_source_exists") is True
    )
    battle_candidate = battle_candidates[0] if battle_candidates else None
    non_battle_sample = non_battle[0] if non_battle else None
    return {
        "schema_version": "p3_summon_unit_definitions_s0",
        "raw_count": len(raw_rows),
        "ir_count": len(definitions),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "summon_kind_counts": dict(sorted(kind_counts.items())),
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "config_source_exists_count": config_exists,
        "battle_admission_candidate_count": len(battle_candidates),
        "non_battle_kind_count": len(non_battle),
        "sample_source_trace": _source_trace_sample(definitions[0].source if definitions else None),
        "battle_candidate_sample_source_trace": _source_trace_sample(battle_candidate.source if battle_candidate else None),
        "non_battle_sample_source_trace": _source_trace_sample(non_battle_sample.source if non_battle_sample else None),
        "sample_definition": _sample_item(definitions[0] if definitions else None),
        "gap_attribution": _gap_attribution_from_reasons(reason_counts),
    }


def _monster_catalog_ref_matrix(tbgd_root: Path, ir: CanonicalIR) -> dict[str, Any]:
    raw_rows = _load_json_rows(tbgd_root / "ExcelOutput" / "MonsterConfig.json")
    rows_with_refs = [
        row
        for row in raw_rows
        if isinstance(row, dict)
        and isinstance(row.get("SummonIDList"), list)
        and bool(row.get("SummonIDList"))
    ]
    cards = tuple(card for card in ir.monster_data_cards if card.summon_refs)
    total_refs = sum(len(row.get("SummonIDList") or []) for row in rows_with_refs if isinstance(row, dict))
    first = cards[0] if cards else None
    return {
        "schema_version": "p3_monster_summon_catalog_refs_s0",
        "raw_monster_config_with_summon_refs": len(rows_with_refs),
        "raw_summon_ref_count": total_refs,
        "monster_data_card_with_summon_refs": len(cards),
        "monster_data_card_ref_count": sum(len(card.summon_refs) for card in cards),
        "sample_source_trace": _source_trace_sample(first.source if first is not None else None),
        "sample_catalog_card": _sample_item(first),
        "classification_note": "catalog_ref_not_runtime_trigger",
    }


def _servant_source_matrix(tbgd_root: Path, ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    servant_rows = _load_json_rows(tbgd_root / "ExcelOutput" / "AvatarServantConfig.json")
    servant_skill_rows = _load_json_rows(tbgd_root / "ExcelOutput" / "AvatarServantSkillConfig.json")
    definitions = tuple(sorted(ir.servant_definitions, key=lambda item: item.servant_definition_id))
    status_counts = Counter(definition.coverage_status for definition in definitions)
    reason_counts = Counter(definition.blocked_reason for definition in definitions if definition.blocked_reason)
    first = _first_with_status(definitions, "executable") or (definitions[0] if definitions else None)
    rulebook_visible = sum(1 for definition in definitions if rules.servant_definition(definition.servant_definition_id) == definition)
    ability_paths = [
        str(definition.source.evidence.get("ability_path") or "")
        for definition in definitions
        if isinstance(definition.source.evidence, dict)
    ]
    readable_ability_paths = sum(1 for path in ability_paths if path and (tbgd_root / path).exists())
    servant_action_definitions = tuple(
        definition
        for definition in ir.action_definitions
        if definition.action_id.startswith("servant_skill:")
        or definition.source.source_path == "ExcelOutput/AvatarServantSkillConfig.json"
    )
    action_status_counts = Counter(definition.coverage_status for definition in servant_action_definitions)
    action_reason_counts = Counter(
        getattr(definition, "blocked_reason", "")
        for definition in servant_action_definitions
        if getattr(definition, "blocked_reason", "")
    )
    first_action = _first_with_status(servant_action_definitions, "executable") or (
        servant_action_definitions[0] if servant_action_definitions else None
    )
    return {
        "schema_version": "p3_servant_sources_s0",
        "raw_servant_config_count": len(servant_rows),
        "raw_servant_skill_count": len(servant_skill_rows),
        "servant_definition_ir_count": len(definitions),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "rulebook_visible_count": rulebook_visible,
        "servant_ability_file_ref_count": len([path for path in ability_paths if path]),
        "servant_ability_file_readable_count": readable_ability_paths,
        "servant_action_definition_count": len(servant_action_definitions),
        "servant_action_definition_executable_count": action_status_counts.get("executable", 0),
        "servant_action_definition_blocked_count": action_status_counts.get("blocked", 0),
        "servant_action_definition_status_counts": dict(sorted(action_status_counts.items())),
        "sample_source_trace": _source_trace_sample(first.source if first is not None else None),
        "servant_skill_sample_source_trace": _source_trace_sample(first_action.source if first_action is not None else None),
        "sample_definition": _sample_item(first),
        "sample_action_definition": _sample_item(first_action),
        "gap_attribution": _gap_attribution_from_reasons(reason_counts),
        "servant_skill_gap_attribution": _gap_attribution_from_reasons(action_reason_counts),
    }


def _assistant_source_matrix(raw_ability_sources: dict[str, Any], ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    queue_intents = tuple(intent for intent in ir.queue_intents if intent.opcode == "TurnInsertAssistantAbility")
    resolutions = tuple(sorted(ir.assistant_ability_resolutions, key=lambda item: item.assistant_resolution_id))
    windows = tuple(window for window in ir.queue_windows if window.window_family == "assistant")
    intent_status_counts = Counter(intent.coverage_status for intent in queue_intents)
    resolution_status_counts = Counter(resolution.coverage_status for resolution in resolutions)
    window_status_counts = Counter(window.coverage_status for window in windows)
    reason_counts = Counter()
    reason_counts.update(intent.blocked_reason for intent in queue_intents if intent.blocked_reason)
    reason_counts.update(resolution.blocked_reason for resolution in resolutions if resolution.blocked_reason)
    reason_counts.update(window.blocked_reason for window in windows if window.blocked_reason)
    first = resolutions[0] if resolutions else None
    rulebook_visible = sum(
        1
        for resolution in resolutions
        if rules.assistant_ability_resolution(resolution.assistant_resolution_id) == resolution
    )
    raw_count = raw_ability_sources["summary"]["opcode_counts"].get("TurnInsertAssistantAbility", 0)
    gap_attribution = Counter(_gap_attribution_from_reasons(reason_counts))
    if raw_count > len(resolutions):
        gap_attribution["lowering_gap"] += raw_count - len(resolutions)
    return {
        "schema_version": "p3_assistant_sources_s0",
        "raw_count": raw_count,
        "queue_intent_ir_count": len(queue_intents),
        "assistant_resolution_ir_count": len(resolutions),
        "assistant_queue_window_ir_count": len(windows),
        "raw_to_ir_projection": {
            "raw_occurrence_count": raw_count,
            "queue_intent_ir_count": len(queue_intents),
            "assistant_resolution_ir_count": len(resolutions),
            "raw_minus_resolution_count": max(0, raw_count - len(resolutions)),
            "classification_if_positive": "lowering_gap",
        },
        "queue_intent_coverage_status_counts": dict(sorted(intent_status_counts.items())),
        "resolution_coverage_status_counts": dict(sorted(resolution_status_counts.items())),
        "queue_window_coverage_status_counts": dict(sorted(window_status_counts.items())),
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "gap_reason_token_counts": _reason_token_counts(reason_counts),
        "gap_reason_layer_counts": _reason_layer_counts(reason_counts),
        "rulebook_visible_count": rulebook_visible,
        "sample_source_trace": _source_trace_sample(first.source if first is not None else None),
        "sample_resolution": _sample_item(first),
        "gap_attribution": dict(sorted(gap_attribution.items())),
    }


def _target_relation_source_matrix(tbgd_root: Path, raw_ability_sources: dict[str, Any], ir: CanonicalIR) -> dict[str, Any]:
    raw_target_records = [
        record
        for record in raw_ability_sources["target_records"]
        if not _is_assistant_avatar_target_alias(str(record.get("alias") or ""))
    ]
    global_target_config = _global_target_config_matrix(tbgd_root)
    ir_targets = tuple(sorted((item for item in ir.target_expressions if _is_p3_ir_target_expression(item)), key=lambda item: item.target_expression_id))
    status_counts = Counter(item.coverage_status for item in ir_targets)
    reason_counts = Counter(item.blocked_reason for item in ir_targets if item.blocked_reason)
    alias_counts = Counter(item.alias for item in ir_targets if item.alias)
    kind_counts = Counter(item.expression_kind for item in ir_targets)
    raw_count = len(raw_target_records) + global_target_config["p3_alias_count"] + global_target_config["p3_operation_count"]
    first = _first_with_status(ir_targets, "executable") or (ir_targets[0] if ir_targets else None)
    return {
        "schema_version": "p3_target_relation_sources_s0",
        "raw_count": raw_count,
        "raw_ability_target_record_count": len(raw_target_records),
        "global_target_config": global_target_config,
        "ir_count": len(ir_targets),
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "gap_reason_token_counts": _reason_token_counts(reason_counts),
        "gap_reason_layer_counts": _reason_layer_counts(reason_counts),
        "target_alias_counts_top": _counter_top(alias_counts, 40),
        "target_expression_kind_counts": dict(sorted(kind_counts.items())),
        "sample_source_trace": _source_trace_sample(first.source if first is not None else None),
        "raw_sample": raw_target_records[:3],
        "sample_target_expression": _sample_item(first),
        "gap_attribution": _gap_attribution_from_reasons(reason_counts),
    }


def _lifecycle_source_matrix(raw_ability_sources: dict[str, Any], ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    raw_records = list(raw_ability_sources["lifecycle_records"])
    event_families = tuple(
        family
        for event in sorted(P3_LIFECYCLE_EVENTS)
        for family in (rules.status_event_family(event),)
        if family is not None
    )
    servant_lifecycle_count = sum(1 for definition in ir.servant_definitions if definition.lifecycle_source)
    summon_entry_count = sum(len(intent.entries) for intent in ir.summon_monster_intents)
    executable_wave_clear_count = sum(
        1
        for intent in ir.summon_monster_intents
        for entry in intent.entries
        if entry.wave_clear_policy == "counts"
    )
    summon_unit_lifecycle_flag_count = sum(
        1
        for definition in ir.summon_unit_definitions
        if definition.destroy_on_enter_battle is not None or definition.remove_maze_buff_on_destroy is not None
    )
    assistant_lifecycle_policy_count = sum(1 for policy in ir.queue_lifecycle_policies if policy.window_family == "assistant")
    event_status_counts = Counter(family.coverage_status for family in event_families)
    reason_counts = Counter(family.blocked_reason or family.blocking_dependency for family in event_families if family.blocked_reason or family.blocking_dependency)
    raw_event_counts = Counter(str(record.get("event") or "missing") for record in raw_records)
    ir_count = (
        len(event_families)
        + servant_lifecycle_count
        + summon_entry_count
        + summon_unit_lifecycle_flag_count
        + assistant_lifecycle_policy_count
    )
    return {
        "schema_version": "p3_lifecycle_sources_s0",
        "raw_count": len(raw_records),
        "raw_event_counts_top": _counter_top(raw_event_counts, 40),
        "ir_count": ir_count,
        "event_family_count": len(event_families),
        "event_family_coverage_status_counts": dict(sorted(event_status_counts.items())),
        "servant_lifecycle_source_count": servant_lifecycle_count,
        "summon_monster_entry_wave_policy_count": summon_entry_count,
        "summon_monster_wave_clear_counts_policy_count": executable_wave_clear_count,
        "summon_unit_lifecycle_flag_count": summon_unit_lifecycle_flag_count,
        "assistant_queue_lifecycle_policy_count": assistant_lifecycle_policy_count,
        "executable_count": event_status_counts.get("executable", 0) + executable_wave_clear_count + servant_lifecycle_count,
        "blocked_count": event_status_counts.get("blocked", 0) + max(0, summon_entry_count - executable_wave_clear_count),
        "blocked_reason_counts_top": _counter_top(reason_counts, 40),
        "sample_source_trace": raw_records[0].get("source", {}) if raw_records else {},
        "raw_sample": raw_records[:3],
        "gap_attribution": _gap_attribution_from_reasons(reason_counts),
    }


def _domain_row(
    *,
    source_domain: str,
    raw_count: int,
    ir_count: int,
    executable_count: int,
    blocked_count: int,
    classification: str,
    sample_source_trace: dict[str, Any],
    gap_attribution: dict[str, int],
    notes: str,
    gap_reason_token_counts: list[dict[str, Any]] | None = None,
    gap_reason_layer_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "source_domain": source_domain,
        "raw_count": int(raw_count),
        "ir_count": int(ir_count),
        "executable_count": int(executable_count),
        "blocked_count": int(blocked_count),
        "gap_count": sum(
            int(count)
            for key, count in gap_attribution.items()
            if key in {"source_gap_blocked", "lowering_gap", "admission_gap", "validation_gap", "implementation_missing"}
        ),
        "classification": classification,
        "gap_attribution": dict(sorted(gap_attribution.items())),
        "gap_reason_layer_counts": dict(sorted((gap_reason_layer_counts or {}).items())),
        "gap_reason_token_counts": gap_reason_token_counts or [],
        "sample_source_trace": sample_source_trace,
        "notes": notes,
    }


def _ability_source_files(tbgd_root: Path) -> tuple[Path, ...]:
    roots = (
        tbgd_root / "Config" / "ConfigAbility",
        tbgd_root / "Config" / "ConfigGlobalModifier",
    )
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.json") if not path.name.endswith(".layout.json"))
    return tuple(sorted(files))


def _raw_task_record(
    relative_path: str,
    source_area: str,
    node_path: list[str],
    node: dict[str, Any],
    opcode: str,
) -> dict[str, Any]:
    return {
        "opcode": opcode,
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "present_fields": sorted(str(key) for key in node.keys() if key != "$type")[:40],
        "source": {
            "source_path": relative_path,
            "raw_type": f"RPG.GameCore.{opcode}",
            "raw_id": "/".join(node_path),
            "evidence": {
                "opcode": opcode,
                "source_area": source_area,
                "field_keys": sorted(str(key) for key in node.keys() if key != "$type")[:40],
            },
        },
    }


def _raw_target_record(
    relative_path: str,
    source_area: str,
    node_path: list[str],
    target_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "target_expression_kind": target_info.get("target_expression_kind"),
        "alias": target_info.get("alias"),
        "current_admission_bucket": target_info.get("current_admission_bucket"),
        "suggested_admission_batch": target_info.get("suggested_admission_batch"),
        "source": {
            "source_path": relative_path,
            "raw_type": "TargetExpression",
            "raw_id": "/".join(node_path),
            "evidence": {
                "target_expression_kind": target_info.get("target_expression_kind"),
                "alias": target_info.get("alias"),
            },
        },
    }


def _raw_lifecycle_record(
    relative_path: str,
    source_area: str,
    node_path: list[str],
    node: dict[str, Any],
) -> dict[str, Any] | None:
    event = node.get("Event")
    callback_config = node.get("CallbackConfig")
    if not isinstance(event, str) or not isinstance(callback_config, list):
        return None
    task_opcodes = Counter()
    target_aliases = Counter()
    for _, child in _walk_json(callback_config):
        if not isinstance(child, dict):
            continue
        opcode = _gamecore_opcode(child)
        if opcode:
            task_opcodes[opcode] += 1
        target_info = _target_expression_info(child)
        if target_info is not None and target_info.get("alias"):
            target_aliases[str(target_info["alias"])] += 1
    relevant = (
        event in P3_LIFECYCLE_EVENTS
        or bool(set(task_opcodes) & P3_LIFECYCLE_OPCODES)
        or bool(set(target_aliases) & P3_TARGET_ALIASES)
    )
    if not relevant:
        return None
    return {
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "event": event,
        "task_opcode_counts_top": _counter_top(task_opcodes, 20),
        "target_alias_counts_top": _counter_top(target_aliases, 20),
        "source": {
            "source_path": relative_path,
            "raw_type": "StatusCallback",
            "raw_id": "/".join(node_path),
            "evidence": {
                "event": event,
                "source_area": source_area,
                "p3_lifecycle_candidate": True,
            },
        },
    }


def _global_target_config_matrix(tbgd_root: Path) -> dict[str, Any]:
    alias_path = tbgd_root / "Config" / "GlobalConfig" / "TargetAliasConfig.json"
    operation_path = tbgd_root / "Config" / "GlobalConfig" / "TargetOperationConfig.json"
    alias_config = _load_json_file(alias_path)
    operation_config = _load_json_file(operation_path)
    alias_dict = alias_config.get("AliasDict") if isinstance(alias_config, dict) and isinstance(alias_config.get("AliasDict"), dict) else {}
    operation_dict = (
        operation_config.get("OperationDict")
        if isinstance(operation_config, dict) and isinstance(operation_config.get("OperationDict"), dict)
        else {}
    )
    p3_aliases: list[dict[str, Any]] = []
    for alias, raw in sorted(alias_dict.items()):
        alias_text = str(alias)
        operations = alias_text.split(".")[1:] if "." in alias_text else []
        if (
            not _is_assistant_avatar_target_alias(alias_text)
            and (
                alias_text in P3_TARGET_ALIASES
                or any(term in alias_text.lower() for term in ("servant", "summon", "summoner"))
                or bool(set(operations) & P3_TARGET_OPERATIONS)
            )
        ):
            p3_aliases.append(
                {
                    "alias": alias_text,
                    "operations": operations,
                    "raw_type": _short_gamecore_type(raw.get("$type") if isinstance(raw, dict) else ""),
                    "source": {
                        "source_path": "Config/GlobalConfig/TargetAliasConfig.json",
                        "raw_type": "TargetAliasConfig.AliasDict",
                        "raw_id": alias_text,
                    },
                }
            )
    p3_operations = [
        {
            "operation": str(operation),
            "raw_type": _short_gamecore_type(raw.get("$type") if isinstance(raw, dict) else ""),
            "source": {
                "source_path": "Config/GlobalConfig/TargetOperationConfig.json",
                "raw_type": "TargetOperationConfig.OperationDict",
                "raw_id": str(operation),
            },
        }
        for operation, raw in sorted(operation_dict.items())
        if str(operation) in P3_TARGET_OPERATIONS
        or any(term in str(operation).lower() for term in ("servant", "summon", "summoner"))
    ]
    return {
        "p3_alias_count": len(p3_aliases),
        "p3_operation_count": len(p3_operations),
        "p3_alias_samples": p3_aliases[:10],
        "p3_operation_samples": p3_operations[:10],
    }


def _is_p3_target_info(target_info: dict[str, Any]) -> bool:
    alias = str(target_info.get("alias") or "")
    kind = str(target_info.get("target_expression_kind") or "").removeprefix("Embedded:")
    if _is_assistant_avatar_target_alias(alias):
        return True
    return (
        alias in P3_TARGET_ALIASES
        or any(term in alias.lower() for term in ("servant", "summon", "summoner"))
        or kind in P3_TARGET_FETCH_KINDS
    )


def _is_p3_ir_target_expression(expression: Any) -> bool:
    alias = str(getattr(expression, "alias", "") or "")
    kind = str(getattr(expression, "expression_kind", "") or "")
    source = getattr(expression, "source", None)
    evidence = source.evidence if isinstance(source, IRSource) and isinstance(source.evidence, dict) else {}
    operation = str(evidence.get("operation") or "")
    base_alias = str(evidence.get("base_alias") or "")
    if _is_assistant_avatar_target_alias(alias) or _is_assistant_avatar_target_alias(base_alias):
        return False
    return (
        alias in P3_TARGET_ALIASES
        or any(term in alias.lower() for term in ("servant", "summon", "summoner"))
        or kind in P3_TARGET_FETCH_KINDS
        or operation in P3_TARGET_OPERATIONS
        or base_alias in P3_TARGET_ALIASES
        or any(term in operation.lower() for term in ("servant", "summon", "summoner"))
    )


def _is_assistant_avatar_target_alias(alias: str) -> bool:
    return alias in ASSISTANT_AVATAR_TARGET_ALIASES


def _gap_attribution_from_reasons(reason_counts: Counter[str]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for reason, count in reason_counts.items():
        if not reason:
            continue
        result[_gap_layer_from_reason(str(reason))] += int(count)
    return dict(sorted(result.items()))


def _reason_token_counts(reason_counts: Counter[str]) -> list[dict[str, Any]]:
    token_counts: Counter[str] = Counter()
    for reason, count in reason_counts.items():
        if not reason:
            continue
        parts = tuple(part for part in (item.strip() for item in str(reason).split(";")) if part)
        for token in parts or (str(reason),):
            token_counts[token] += int(count)
    return [
        {"key": token, "count": int(count), "classification": _gap_layer_from_reason(token)}
        for token, count in sorted(token_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    ]


def _reason_layer_counts(reason_counts: Counter[str]) -> dict[str, int]:
    layers: Counter[str] = Counter()
    for row in _reason_token_counts(reason_counts):
        layers[str(row["classification"])] += int(row["count"])
    return dict(sorted(layers.items()))


def _gap_layer_from_reason(reason: str) -> str:
    parts = tuple(part for part in (item.strip() for item in reason.split(";")) if part)
    if len(parts) > 1:
        layers = tuple(_gap_layer_from_reason(part) for part in parts)
        for layer in (
            "source_gap_blocked",
            "lowering_gap",
            "implementation_missing",
            "admission_gap",
            "validation_gap",
            "boundary_only",
        ):
            if layer in layers:
                return layer
        return "admission_gap"
    lowered = reason.lower()
    if (
        "client_only" in lowered
        or "destroy_on_enter_battle" in lowered
        or "adventure_or_maze" in lowered
        or "not_combat_runtime" in lowered
        or "catalog" in lowered
        or "source_mode" in lowered
    ):
        return "boundary_only"
    if "validation" in lowered:
        return "validation_gap"
    if (
        "profile_source_missing" in lowered
        or "profile_source_blocked" in lowered
        or "data_card_source_missing" in lowered
        or "data_card_source_blocked" in lowered
        or "monster_template_base_stat_missing" in lowered
        or "monster_template_missing" in lowered
    ):
        return "source_gap_blocked"
    if "profile_missing" in lowered or "data_card_missing" in lowered or "missing_or_unreadable" in lowered:
        return "lowering_gap"
    if "delay_ratio" in lowered or "runtime" in lowered or "not_executable" in lowered:
        return "implementation_missing"
    if "not_admitted" in lowered or "missing" in lowered or "blocked" in lowered or "unresolved" in lowered:
        return "admission_gap"
    return "admission_gap"


def _missing_or_gap_classification(raw_count: int, ir_count: int) -> str:
    if raw_count <= 0 and ir_count <= 0:
        return "source_absent_not_required"
    if raw_count > 0 and ir_count <= 0:
        return "lowering_gap"
    return "implementation_missing"


def _examples_by_key(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    examples: dict[str, Any] = {}
    for record in records:
        value = str(record.get(key) or "")
        if not value or value in examples:
            continue
        examples[value] = record
    return examples


def _first_with_status(items: tuple[Any, ...], status: str) -> Any | None:
    return next((item for item in items if getattr(item, "coverage_status", "") == status), None)


def _sample_item(item: Any | None) -> dict[str, Any]:
    if item is None:
        return {}
    data = item.to_json()
    data.pop("source", None)
    return _json_safe(data)


def _source_trace_sample(source: IRSource | None) -> dict[str, Any]:
    if source is None:
        return {}
    evidence = source.evidence if isinstance(source.evidence, dict) else {}
    return {
        "source_path": source.source_path,
        "raw_type": source.raw_type,
        "raw_id": source.raw_id,
        "evidence_keys": sorted(str(key) for key in evidence.keys())[:30],
        "row_index": evidence.get("row_index"),
        "raw_paths": _json_safe(evidence.get("raw_paths")) if isinstance(evidence.get("raw_paths"), dict) else {},
        "admission_policy": evidence.get("admission_policy"),
        "source_boundary": evidence.get("source_boundary"),
    }


def _p3_source_area(relative_path: str) -> str:
    area = _source_area(relative_path)
    if area != "Other":
        return area
    if relative_path.startswith("Config/ConfigGlobalModifier/"):
        return "GlobalModifier"
    if relative_path.startswith("Config/GlobalConfig/"):
        return "GlobalConfig"
    if relative_path.startswith("ExcelOutput/"):
        return "ExcelOutput"
    if relative_path.startswith("Stages/"):
        return "Stage"
    return area


def _gamecore_opcode(node: dict[str, Any]) -> str:
    node_type = str(node.get("$type") or "")
    if not node_type.startswith("RPG.GameCore."):
        return ""
    return node_type.rsplit(".", 1)[-1]


def _short_gamecore_type(value: Any) -> str:
    text = str(value or "")
    return text.rsplit(".", 1)[-1] if text else ""


def _load_json_rows(path: Path) -> list[Any]:
    data = _load_json_file(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
