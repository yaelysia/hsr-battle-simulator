from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..rules.rulebook import RuleBook
from ..systems.status import SUPPORTED_ADD_MODIFIER_ALIASES, SUPPORTED_EFFECT_TARGET_ALIASES
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_287"

STATUS_FILES = (
    "StatusConfig.json",
    "AvatarStatusConfig.json",
    "MonsterStatusConfig.json",
    "ILBattleStatusConfig.json",
)

MAINLINE_AREAS = {"Avatar", "Monster", "Equip"}
SPECIAL_OR_DEFERRED_AREAS = {"Level", "BattleEvent", "Activity", "GridFight", "ElationBattle", "Servant"}

CORE_TARGET_ALIASES = {
    "Caster",
    "ModifierOwnerEntity",
    "ParamEntity",
    "CurrentActionTarget",
    "AbilityTargetEntity",
}
GROUP_TARGET_ALIASES = {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllTeammate"}
COMMON_NEXT_TARGET_ALIASES = {
    "SkillTargetEntityList",
    "ParamEntityList",
    "InherentTargetEntity",
    "TeamFormation",
    "BattleAllEntity",
    "AllLightTeamMember",
    "AllDarkTeamMember",
}
SUMMON_TARGET_ALIASES = {"CasterSummonedMinions", "LastSummonMonsters", "FriendServantSelect"}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    status_catalog = _status_catalog_matrix(tbgd_root)
    ability_audit = _ability_audit(tbgd_root, rules)
    modifier_add_matrix = _modifier_add_matrix(ability_audit)
    target_expression_matrix = _target_expression_matrix(ability_audit)
    callback_task_matrix = _status_callback_task_matrix(ability_audit, rules)
    gap_matrix = _status_system_gap_matrix(
        status_catalog=status_catalog,
        modifier_add_matrix=modifier_add_matrix,
        target_expression_matrix=target_expression_matrix,
        callback_task_matrix=callback_task_matrix,
    )
    priority = _implementation_priority(
        modifier_add_matrix=modifier_add_matrix,
        target_expression_matrix=target_expression_matrix,
        callback_task_matrix=callback_task_matrix,
    )
    checks = _checks(
        status_catalog=status_catalog,
        modifier_add_matrix=modifier_add_matrix,
        target_expression_matrix=target_expression_matrix,
        callback_task_matrix=callback_task_matrix,
        gap_matrix=gap_matrix,
        priority=priority,
        static_ok=static_result.ok,
    )
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": checks["ok"],
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "status_event_family_count": len(ir.status_event_families),
            "status_callback_count": len(ir.status_callbacks),
            "selection_policy": {
                "mode": "raw_tbgd_audit_matrix_with_structured_predicates",
                "runtime_behavior_changed": False,
                "fixed_character_monster_skill_or_file_used_for_selection": False,
                "textmap_read": False,
            },
        },
        "checks": checks,
        "status_catalog_matrix": status_catalog,
        "modifier_add_matrix": modifier_add_matrix,
        "target_expression_matrix": target_expression_matrix,
        "status_callback_task_matrix": callback_task_matrix,
        "status_system_gap_matrix": gap_matrix,
        "implementation_priority": priority,
        "static_checks": static_result.to_json(),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_287.json", result)
    write_json(output_dir / "status_catalog_matrix_v0_287.json", status_catalog)
    write_json(output_dir / "modifier_add_matrix_v0_287.json", modifier_add_matrix)
    write_json(output_dir / "target_expression_matrix_v0_287.json", target_expression_matrix)
    write_json(output_dir / "status_callback_task_matrix_v0_287.json", callback_task_matrix)
    write_json(output_dir / "status_system_gap_matrix_v0_287.json", gap_matrix)
    write_json(output_dir / "implementation_priority_v0_287.json", priority)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_287 status/target/event database audit matrices.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _status_catalog_matrix(tbgd_root: Path) -> dict[str, Any]:
    excel_root = tbgd_root / "ExcelOutput"
    files: dict[str, Any] = {}
    aggregate_type_counts = Counter()
    aggregate_read_params = Counter()
    aggregate_tags = Counter()
    modifier_index: dict[str, dict[str, Any]] = {}
    for file_name in STATUS_FILES:
        rows = _load_json_rows(excel_root / file_name)
        status_type_counts = Counter()
        can_dispel_counts = Counter()
        can_dispel_by_type = Counter()
        read_param_counts = Counter()
        tag_counts = Counter()
        row_samples: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status_type = str(row.get("StatusType") or "Unknown")
            modifier_name = str(row.get("ModifierName") or "")
            status_id = row.get("StatusID", row.get("ID"))
            status_type_counts[status_type] += 1
            aggregate_type_counts[status_type] += 1
            if "CanDispel" in row:
                can_dispel = bool(row.get("CanDispel"))
                can_dispel_counts[str(can_dispel)] += 1
                can_dispel_by_type[f"{status_type}:{can_dispel}"] += 1
            for item in _string_list(row.get("ReadParamList")):
                read_param_counts[item] += 1
                aggregate_read_params[item] += 1
            for item in _string_list(row.get("TagList")):
                tag_counts[item] += 1
                aggregate_tags[item] += 1
            if modifier_name:
                modifier_index[modifier_name] = {
                    "status_id": status_id,
                    "status_type": status_type,
                    "can_dispel": row.get("CanDispel") if isinstance(row.get("CanDispel"), bool) else None,
                    "source_file": file_name,
                    "read_param_list": _string_list(row.get("ReadParamList")),
                    "tag_list": _string_list(row.get("TagList")),
                }
            if len(row_samples) < 5:
                row_samples.append(_status_sample(file_name, row))
        files[file_name] = {
            "row_count": len(rows),
            "status_type_counts": dict(sorted(status_type_counts.items())),
            "can_dispel_counts": dict(sorted(can_dispel_counts.items())),
            "can_dispel_by_status_type": dict(sorted(can_dispel_by_type.items())),
            "read_param_counts_top": _counter_top(read_param_counts, 40),
            "tag_counts_top": _counter_top(tag_counts, 40),
            "sample_rows": row_samples,
        }
    return {
        "schema_version": "status_catalog_matrix_v0_287",
        "files": files,
        "aggregate": {
            "file_count": len(files),
            "row_count": sum(int(item["row_count"]) for item in files.values()),
            "status_type_counts": dict(sorted(aggregate_type_counts.items())),
            "read_param_counts_top": _counter_top(aggregate_read_params, 80),
            "tag_counts_top": _counter_top(aggregate_tags, 80),
            "modifier_index_count": len(modifier_index),
            "modifier_index_sample": dict(list(sorted(modifier_index.items()))[:30]),
        },
        "rules_boundary": {
            "status_tables_are_display_and_metadata_sources": True,
            "status_tables_do_not_define_full_runtime_effects": True,
            "textmap_read": False,
        },
    }


def _ability_audit(tbgd_root: Path, rules: RuleBook) -> dict[str, Any]:
    ability_root = tbgd_root / "Config" / "ConfigAbility"
    add_modifier_records: list[dict[str, Any]] = []
    target_records: list[dict[str, Any]] = []
    callback_records: list[dict[str, Any]] = []
    for path in sorted(ability_root.rglob("*.json")):
        data = _load_json_file(path)
        if data is None:
            continue
        relative_path = path.relative_to(tbgd_root).as_posix()
        source_area = _source_area(relative_path)
        for node_path, node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("$type") or "")
            if node_type == "RPG.GameCore.AddModifier":
                add_modifier_records.append(_add_modifier_record(relative_path, source_area, node_path, node))
            target_info = _target_expression_info(node)
            if target_info is not None:
                target_records.append(
                    {
                        "source_path": relative_path,
                        "source_area": source_area,
                        "json_path": "/".join(node_path),
                        **target_info,
                    }
                )
            event = node.get("Event")
            callback_config = node.get("CallbackConfig")
            if isinstance(event, str) and isinstance(callback_config, list):
                callback_records.append(_callback_record(relative_path, source_area, node_path, node, rules))
    return {
        "add_modifier_records": add_modifier_records,
        "target_records": target_records,
        "callback_records": callback_records,
    }


def _modifier_add_matrix(ability_audit: dict[str, Any]) -> dict[str, Any]:
    records = list(ability_audit["add_modifier_records"])
    by_area = Counter(str(record["source_area"]) for record in records)
    by_target_kind = Counter(str(record["target_expression_kind"]) for record in records)
    by_target_alias = Counter(str(record["target_alias"]) for record in records if record.get("target_alias"))
    field_presence = Counter()
    life_expr_kind = Counter()
    max_layer_expr_kind = Counter()
    layer_add_expr_kind = Counter()
    chance_expr_kind = Counter()
    task_list_fields = Counter()
    admission = Counter()
    examples: dict[str, dict[str, Any]] = {}
    for record in records:
        for field in record["present_fields"]:
            field_presence[field] += 1
        for key, counter in (
            ("life_time_expr_kind", life_expr_kind),
            ("max_layer_expr_kind", max_layer_expr_kind),
            ("layer_add_expr_kind", layer_add_expr_kind),
            ("chance_expr_kind", chance_expr_kind),
        ):
            value = str(record.get(key) or "missing")
            counter[value] += 1
        for field in ("SuccessTaskList", "FailTaskList", "FailedTaskList", "ResistedTaskList"):
            if record.get("task_list_fields", {}).get(field):
                task_list_fields[field] += 1
        admission[record["current_admission_bucket"]] += 1
        _set_example(examples, record["current_admission_bucket"], record)
        _set_example(examples, f"target:{record['target_expression_kind']}", record)
    return {
        "schema_version": "modifier_add_matrix_v0_287",
        "total_add_modifier": len(records),
        "source_area_counts": dict(sorted(by_area.items())),
        "mainline_add_modifier_count": sum(by_area[area] for area in MAINLINE_AREAS),
        "deferred_or_special_area_count": sum(by_area[area] for area in SPECIAL_OR_DEFERRED_AREAS),
        "target_expression_kind_counts": dict(sorted(by_target_kind.items())),
        "target_alias_counts_top": _counter_top(by_target_alias, 80),
        "field_presence_counts": dict(sorted(field_presence.items())),
        "life_time_expr_kind_counts": dict(sorted(life_expr_kind.items())),
        "max_layer_expr_kind_counts": dict(sorted(max_layer_expr_kind.items())),
        "layer_add_when_stack_expr_kind_counts": dict(sorted(layer_add_expr_kind.items())),
        "chance_expr_kind_counts": dict(sorted(chance_expr_kind.items())),
        "task_list_field_counts": dict(sorted(task_list_fields.items())),
        "current_admission_bucket_counts": dict(sorted(admission.items())),
        "examples_by_bucket": examples,
        "coverage_notes": {
            "status_system_supported_aliases": sorted(SUPPORTED_ADD_MODIFIER_ALIASES),
            "effect_system_supported_aliases": sorted(SUPPORTED_EFFECT_TARGET_ALIASES),
            "runtime_behavior_changed": False,
        },
    }


def _target_expression_matrix(ability_audit: dict[str, Any]) -> dict[str, Any]:
    records = list(ability_audit["target_records"])
    by_area = Counter(str(record["source_area"]) for record in records)
    by_kind = Counter(str(record["target_expression_kind"]) for record in records)
    by_alias = Counter(str(record["alias"]) for record in records if record.get("alias"))
    by_admission = Counter(str(record["current_admission_bucket"]) for record in records)
    examples: dict[str, dict[str, Any]] = {}
    for record in records:
        _set_example(examples, record["target_expression_kind"], record)
        _set_example(examples, record["current_admission_bucket"], record)
        if record.get("alias"):
            _set_example(examples, f"alias:{record['alias']}", record)
    return {
        "schema_version": "target_expression_matrix_v0_287",
        "total_target_expression_nodes": len(records),
        "source_area_counts": dict(sorted(by_area.items())),
        "target_expression_kind_counts": dict(sorted(by_kind.items())),
        "target_alias_counts_top": _counter_top(by_alias, 120),
        "current_admission_bucket_counts": dict(sorted(by_admission.items())),
        "suggested_admission_batches": _target_admission_batches(records),
        "examples_by_kind_or_bucket": examples,
        "coverage_notes": {
            "current_action_target_system_scope": "action-level single/blast/bounce/aoe/self_or_team only",
            "ability_target_expression_layer_missing": True,
            "runtime_behavior_changed": False,
        },
    }


def _status_callback_task_matrix(ability_audit: dict[str, Any], rules: RuleBook) -> dict[str, Any]:
    records = list(ability_audit["callback_records"])
    by_area = Counter(str(record["source_area"]) for record in records)
    by_event = Counter(str(record["event"]) for record in records)
    event_matrix: dict[str, Any] = {}
    examples: dict[str, dict[str, Any]] = {}
    for record in records:
        event = str(record["event"])
        item = event_matrix.setdefault(
            event,
            {
                "callback_count": 0,
                "source_area_counts": Counter(),
                "task_opcode_counts": Counter(),
                "samples": [],
            },
        )
        item["callback_count"] += 1
        item["source_area_counts"][record["source_area"]] += 1
        item["task_opcode_counts"].update(record["task_opcode_counts"])
        if len(item["samples"]) < 3:
            item["samples"].append(_sample_record(record))
        _set_example(examples, event, record)
    serial_event_matrix: dict[str, Any] = {}
    for event, item in sorted(event_matrix.items()):
        family = rules.status_event_family(event)
        serial_event_matrix[event] = {
            "callback_count": item["callback_count"],
            "source_area_counts": dict(sorted(item["source_area_counts"].items())),
            "task_opcode_counts_top": _counter_top(item["task_opcode_counts"], 40),
            "status_event_family": family.to_json() if family else None,
            "current_runtime_event_sources": list(family.runtime_event_sources) if family else [],
            "current_coverage_status": family.coverage_status if family else "missing",
            "current_blocked_reason": (family.blocked_reason or family.blocking_dependency) if family else "status_event_family_missing",
            "samples": item["samples"],
        }
    return {
        "schema_version": "status_callback_task_matrix_v0_287",
        "total_callbacks": len(records),
        "callback_event_kind_count": len(by_event),
        "source_area_counts": dict(sorted(by_area.items())),
        "callback_event_counts_top": _counter_top(by_event, 120),
        "event_matrix": serial_event_matrix,
        "examples_by_event": examples,
        "coverage_notes": {
            "event_family_matrix_source": "CanonicalIR.status_event_families",
            "callback_task_source": "raw TBGD CallbackConfig audit only",
            "runtime_behavior_changed": False,
        },
    }


def _status_system_gap_matrix(
    *,
    status_catalog: dict[str, Any],
    modifier_add_matrix: dict[str, Any],
    target_expression_matrix: dict[str, Any],
    callback_task_matrix: dict[str, Any],
) -> dict[str, Any]:
    event_matrix = callback_task_matrix["event_matrix"]
    gaps = [
        _gap(
            "ability_target_expression_layer",
            "blocked",
            "目标表达式层缺失，TargetSequence/TargetFilter/Retarget/ParamEntityList 等不能通用解析。",
            evidence={
                "target_expression_bucket_counts": target_expression_matrix["current_admission_bucket_counts"],
                "top_target_aliases": target_expression_matrix["target_alias_counts_top"][:20],
            },
            next_step="v0_288 优先建立只读 TargetExpressionIR 与 resolver，先支持 TargetAlias + TargetSequence + TargetFilter + Retarget 的安全子集。",
        ),
        _gap(
            "status_stack_refresh_semantics",
            "partial",
            "AddModifier 中 MaxLayer、LayerAddWhenStack、Chance、Success/Fail/ResistedTaskList 分布较大，当前 stack/refresh 多为 partial。",
            evidence={
                "max_layer": modifier_add_matrix["max_layer_expr_kind_counts"],
                "layer_add_when_stack": modifier_add_matrix["layer_add_when_stack_expr_kind_counts"],
                "chance": modifier_add_matrix["chance_expr_kind_counts"],
                "task_list_fields": modifier_add_matrix["task_list_field_counts"],
            },
            next_step="目标表达式之后补 stack/refresh/chance/失败分支 admission，缺绑定时继续 blocked。",
        ),
        _gap(
            "duration_tick_expire",
            "partial",
            "状态生命周期已有 duration admission，但完整 tick/expire 触发窗口和各 LifeStep 语义未全量接入。",
            evidence={"life_time": modifier_add_matrix["life_time_expr_kind_counts"]},
            next_step="按 LifeTime/LifeStepMoment 实际字段补 duration trigger，不造默认时机。",
        ),
        _gap(
            "dot_tick",
            "blocked_or_partial",
            "DoT 添加可由状态元数据证明后发 OnModifierDotAdd，但 DoT tick 仍依赖状态伤害 emission 与生命周期窗口。",
            evidence={"OnModifierDotAdd": _event_summary(event_matrix, "OnModifierDotAdd")},
            next_step="基于状态伤害 emission 和 duration tick admission 补 DoT tick。",
        ),
        _gap(
            "control_resist_immunity",
            "blocked",
            "控制、抵抗、免疫仍缺完整命中/抵抗判定与状态抗性来源。",
            evidence={
                "status_resistance_table": "MonsterStatusResistanceType.json",
                "resist_events": {
                    "OnResistModifier": _event_summary(event_matrix, "OnResistModifier"),
                    "OnListenModifierResist": _event_summary(event_matrix, "OnListenModifierResist"),
                },
            },
            next_step="先审计控制类 StatusType/Modifier 与抗性来源，再接抵抗判定和 ResistedTaskList。",
        ),
        _gap(
            "dispel",
            "blocked",
            "状态表有 CanDispel，但驱散目标选择、驱散数量/优先级/事件 payload 未 admission。",
            evidence={
                "can_dispel_status_counts": status_catalog["aggregate"]["status_type_counts"],
                "dispel_events": {
                    "OnDispel": _event_summary(event_matrix, "OnDispel"),
                    "OnListenModifierDispel": _event_summary(event_matrix, "OnListenModifierDispel"),
                },
            },
            next_step="在状态生命周期和目标表达式后补驱散操作、source audit 和 OnDispel 事件源。",
        ),
        _gap(
            "lock_hp_threshold",
            "blocked",
            "锁血阈值需要 HP pending mutation 改写和重算 ledger，目前 before 类同路径改写仍安全 blocked。",
            evidence={"OnLockHPThresholdReached": _event_summary(event_matrix, "OnLockHPThresholdReached")},
            next_step="建立 HP pending mutation 重算 ledger 后再 admission 锁血阈值。",
        ),
        _gap(
            "break_end_and_leave_enter_battle",
            "blocked_or_missing",
            "破韧结束、进入/离开战斗事件在怪物中高频，但对应真实事件源和生命周期时机还未接。",
            evidence={
                "OnEndBreak": _event_summary(event_matrix, "OnEndBreak"),
                "OnEnterBattle": _event_summary(event_matrix, "OnEnterBattle"),
                "OnLeaveBattle": _event_summary(event_matrix, "OnLeaveBattle"),
            },
            next_step="先补 break duration/end lifecycle，再考虑 battle enter/leave 初始化和清理窗口。",
        ),
    ]
    return {
        "schema_version": "status_system_gap_matrix_v0_287",
        "gaps": gaps,
        "coverage_boundary": {
            "runtime_behavior_changed": False,
            "blocked_or_partial_is_not_executable": True,
        },
    }


def _implementation_priority(
    *,
    modifier_add_matrix: dict[str, Any],
    target_expression_matrix: dict[str, Any],
    callback_task_matrix: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "implementation_priority_v0_287",
        "ranking_policy": {
            "criteria": [
                "通用性",
                "来源清楚",
                "对怪物和角色收益大",
                "低风险",
                "不需要伪造事件源",
            ],
            "fixed_entity_or_file_selection": False,
        },
        "priorities": [
            {
                "rank": 1,
                "item": "target_expression_core",
                "reason": "状态、回调、怪物技能都依赖 TargetAlias/TargetSequence/TargetFilter/Retarget；当前缺口最大且可先做只读解析。",
                "suggested_scope": "只 admission 主线 Avatar/Monster/Equip 的安全目标表达式子集，不接召唤物和特殊玩法目标。",
                "evidence": target_expression_matrix["current_admission_bucket_counts"],
            },
            {
                "rank": 2,
                "item": "status_stack_refresh_chance",
                "reason": "AddModifier 中 MaxLayer、LayerAddWhenStack、Chance 出现频繁，当前状态生命周期仍 partial。",
                "suggested_scope": "固定/已绑定数值先 admission，缺动态值或失败分支继续 blocked。",
                "evidence": {
                    "max_layer": modifier_add_matrix["max_layer_expr_kind_counts"],
                    "layer_add_when_stack": modifier_add_matrix["layer_add_when_stack_expr_kind_counts"],
                    "chance": modifier_add_matrix["chance_expr_kind_counts"],
                },
            },
            {
                "rank": 3,
                "item": "duration_tick_expire_and_dot_tick",
                "reason": "持续时间、tick、DoT 是状态正确性的主干，且依赖状态生命周期与目标表达式。",
                "suggested_scope": "先接主线单位状态的 duration tick/expire，再接 DoT tick。",
                "evidence": {"life_time": modifier_add_matrix["life_time_expr_kind_counts"]},
            },
            {
                "rank": 4,
                "item": "break_end_and_common_event_sources",
                "reason": "怪物中 OnBeingBreak/OnEndBreak 高频，破韧结束是可明确建模的战斗生命周期。",
                "suggested_scope": "补 break duration/end event source；Enter/LeaveBattle 作为初始化/清理窗口单独审计。",
                "evidence": {
                    "OnBeingBreak": _event_summary(callback_task_matrix["event_matrix"], "OnBeingBreak"),
                    "OnEndBreak": _event_summary(callback_task_matrix["event_matrix"], "OnEndBreak"),
                },
            },
            {
                "rank": 5,
                "item": "control_resist_dispel_immunity",
                "reason": "影响面大但依赖命中/抵抗/驱散选择/优先级等多条来源，风险高于前几项。",
                "suggested_scope": "先审计控制类 modifier 与抵抗来源，再实现状态抵抗和驱散。",
                "evidence": {
                    "OnResistModifier": _event_summary(callback_task_matrix["event_matrix"], "OnResistModifier"),
                    "OnDispel": _event_summary(callback_task_matrix["event_matrix"], "OnDispel"),
                },
            },
        ],
    }


def _checks(
    *,
    status_catalog: dict[str, Any],
    modifier_add_matrix: dict[str, Any],
    target_expression_matrix: dict[str, Any],
    callback_task_matrix: dict[str, Any],
    gap_matrix: dict[str, Any],
    priority: dict[str, Any],
    static_ok: bool,
) -> dict[str, Any]:
    status_files = status_catalog["files"]
    add_total = int(modifier_add_matrix["total_add_modifier"])
    target_total = int(target_expression_matrix["total_target_expression_nodes"])
    callback_total = int(callback_task_matrix["total_callbacks"])
    checks = {
        "status_files_all_loaded": all(file_name in status_files and status_files[file_name]["row_count"] > 0 for file_name in STATUS_FILES),
        "status_modifier_index_present": status_catalog["aggregate"]["modifier_index_count"] > 0,
        "add_modifier_all_classified_by_area": sum(modifier_add_matrix["source_area_counts"].values()) == add_total,
        "add_modifier_all_classified_by_target": sum(modifier_add_matrix["target_expression_kind_counts"].values()) == add_total,
        "add_modifier_has_structured_samples": _examples_have_source(modifier_add_matrix["examples_by_bucket"]),
        "target_expression_all_classified": sum(target_expression_matrix["target_expression_kind_counts"].values()) == target_total,
        "target_expression_has_structured_samples": _examples_have_source(target_expression_matrix["examples_by_kind_or_bucket"]),
        "callback_events_all_classified": sum(callback_task_matrix["source_area_counts"].values()) == callback_total,
        "callback_event_matrix_has_family_status": all(
            bool(item.get("current_coverage_status"))
            for item in callback_task_matrix["event_matrix"].values()
        ),
        "callback_samples_have_source": _examples_have_source(callback_task_matrix["examples_by_event"]),
        "blocked_or_missing_items_have_reason": all(
            bool(item.get("current_blocked_reason") or item.get("current_runtime_event_sources"))
            for item in callback_task_matrix["event_matrix"].values()
        ),
        "gap_matrix_has_prioritized_gaps": bool(gap_matrix["gaps"]),
        "implementation_priority_target_expression_first": priority["priorities"][0]["item"] == "target_expression_core",
        "static_checks": static_ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"ok": checks["ok"], "checks": checks}


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_json_rows(path: Path) -> list[Any]:
    data = _load_json_file(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


def _walk_json(value: Any, path: list[str] | None = None):
    path = path or []
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_json(item, [*path, str(key)])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json(item, [*path, str(index)])


def _source_area(relative_path: str) -> str:
    marker = "Config/ConfigAbility/"
    if marker not in relative_path:
        return "Other"
    suffix = relative_path.split(marker, 1)[1]
    first = suffix.split("/", 1)[0]
    if first in {"Avatar", "Monster", "Equip", "Level", "BattleEvent", "Servant", "Activity", "GridFight", "ElationBattle", "Story", "SpecialAvatar"}:
        return first
    if first in {"EquipmemtAbility.json", "RelicAbility.json"}:
        return "Equip"
    if first.startswith("BattleEventAbility"):
        return "BattleEvent"
    return "Other"


def _add_modifier_record(relative_path: str, source_area: str, node_path: list[str], node: dict[str, Any]) -> dict[str, Any]:
    target_info = _target_expression_info(node.get("TargetType")) or _target_expression_info(node)
    target_kind = target_info["target_expression_kind"] if target_info else "target_missing"
    target_alias = str(target_info.get("alias") or "") if target_info else ""
    record = {
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "modifier_name": _value_string(node.get("ModifierName")),
        "target_expression_kind": target_kind,
        "target_alias": target_alias,
        "present_fields": sorted(str(key) for key in node.keys()),
        "life_time_expr_kind": _numeric_expr_kind(node.get("LifeTime")),
        "max_layer_expr_kind": _numeric_expr_kind(node.get("MaxLayer")),
        "layer_add_expr_kind": _numeric_expr_kind(node.get("LayerAddWhenStack")),
        "chance_expr_kind": _numeric_expr_kind(node.get("Chance", node.get("Probability"))),
        "dynamic_value_count": len(node.get("DynamicValues")) if isinstance(node.get("DynamicValues"), dict) else 0,
        "inherit_caster": str(node.get("InheritCaster") or ""),
        "task_list_fields": {
            key: len(node.get(key)) if isinstance(node.get(key), list) else 0
            for key in ("SuccessTaskList", "FailTaskList", "FailedTaskList", "ResistedTaskList")
        },
        "source": {
            "source_path": relative_path,
            "raw_type": "RPG.GameCore.AddModifier",
            "raw_id": "/".join(node_path),
            "evidence": {
                "modifier_name": _value_string(node.get("ModifierName")),
                "target_expression_kind": target_kind,
                "target_alias": target_alias,
            },
        },
    }
    record["current_admission_bucket"] = _add_modifier_admission_bucket(record)
    return record


def _target_expression_info(node: Any) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    node_type = str(node.get("$type") or "")
    alias = ""
    kind = ""
    if node_type == "RPG.GameCore.TargetAlias":
        alias = str(node.get("Alias") or "")
        kind = "TargetAlias"
    elif node_type.startswith("RPG.GameCore.Target"):
        kind = node_type.removeprefix("RPG.GameCore.")
        alias = str(node.get("Alias") or node.get("UniqueName") or "")
    elif node_type == "RPG.GameCore.Retarget":
        kind = "Retarget"
    elif "TargetType" in node:
        target_type = node.get("TargetType")
        if isinstance(target_type, dict):
            nested = _target_expression_info(target_type)
            if nested is None:
                kind = "TargetTypeObject"
            else:
                return {
                    **nested,
                    "target_expression_kind": f"Embedded:{nested['target_expression_kind']}",
                    "current_admission_bucket": _target_admission_bucket(nested["target_expression_kind"], str(nested.get("alias") or "")),
                }
        elif isinstance(target_type, str):
            kind = "TargetTypeString"
            alias = target_type
    if not kind:
        return None
    bucket = _target_admission_bucket(kind, alias)
    return {
        "target_expression_kind": kind,
        "alias": alias,
        "node_type": node_type,
        "current_admission_bucket": bucket,
        "suggested_admission_batch": _target_suggested_batch(kind, alias, bucket),
    }


def _callback_record(
    relative_path: str,
    source_area: str,
    node_path: list[str],
    node: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    event = str(node.get("Event") or "")
    callback_config = node.get("CallbackConfig")
    task_opcodes = Counter()
    target_kinds = Counter()
    if isinstance(callback_config, list):
        for _, child in _walk_json(callback_config):
            if not isinstance(child, dict):
                continue
            node_type = str(child.get("$type") or "")
            if node_type.startswith("RPG.GameCore.") and not node_type.startswith("RPG.GameCore.Target"):
                task_opcodes[node_type] += 1
            target_info = _target_expression_info(child)
            if target_info is not None:
                target_kinds[target_info["target_expression_kind"]] += 1
    family = rules.status_event_family(event)
    return {
        "source_path": relative_path,
        "source_area": source_area,
        "json_path": "/".join(node_path),
        "event": event,
        "callback_config_task_count": sum(task_opcodes.values()),
        "task_opcode_counts": dict(sorted(task_opcodes.items())),
        "target_expression_kind_counts": dict(sorted(target_kinds.items())),
        "status_event_family_status": family.coverage_status if family else "missing",
        "runtime_event_sources": list(family.runtime_event_sources) if family else [],
        "blocked_reason": (family.blocked_reason or family.blocking_dependency) if family else "status_event_family_missing",
        "source": {
            "source_path": relative_path,
            "raw_type": "StatusCallback",
            "raw_id": "/".join(node_path),
            "evidence": {"event": event, "task_opcode_count": sum(task_opcodes.values())},
        },
    }


def _add_modifier_admission_bucket(record: dict[str, Any]) -> str:
    alias = str(record.get("target_alias") or "")
    target_kind = str(record.get("target_expression_kind") or "")
    if alias in CORE_TARGET_ALIASES:
        return "currently_supported_single_alias"
    if alias in GROUP_TARGET_ALIASES:
        return "currently_supported_group_alias_for_add_modifier"
    if target_kind in {"TargetSequence", "TargetFilter", "Retarget"} or target_kind.startswith("Embedded:TargetSequence"):
        return "blocked_needs_target_expression_layer"
    if alias in COMMON_NEXT_TARGET_ALIASES:
        return "blocked_common_alias_needs_target_expression_layer"
    if alias in SUMMON_TARGET_ALIASES:
        return "blocked_summon_or_servant_target"
    if not alias and target_kind == "target_missing":
        return "blocked_missing_target"
    return "blocked_target_not_admitted"


def _target_admission_bucket(kind: str, alias: str) -> str:
    normalized_kind = kind.removeprefix("Embedded:")
    if normalized_kind == "TargetAlias" and alias in CORE_TARGET_ALIASES:
        return "currently_supported_single_alias"
    if normalized_kind == "TargetAlias" and alias in GROUP_TARGET_ALIASES:
        return "currently_supported_group_alias_for_add_modifier"
    if normalized_kind in {"TargetSequence", "TargetFilter", "Retarget"}:
        return "blocked_needs_target_expression_layer"
    if normalized_kind == "TargetAlias" and alias in COMMON_NEXT_TARGET_ALIASES:
        return "blocked_common_alias_needs_target_expression_layer"
    if normalized_kind == "TargetAlias" and alias in SUMMON_TARGET_ALIASES:
        return "blocked_summon_or_servant_target"
    if normalized_kind.startswith("TargetSort"):
        return "blocked_target_sort_not_admitted"
    if normalized_kind.startswith("TargetFetch"):
        return "blocked_target_fetch_not_admitted"
    return "blocked_target_not_admitted"


def _target_suggested_batch(kind: str, alias: str, bucket: str) -> str:
    normalized_kind = kind.removeprefix("Embedded:")
    if bucket.startswith("currently_supported"):
        return "already_supported_in_limited_context"
    if normalized_kind in {"TargetSequence", "TargetFilter", "Retarget"}:
        return "v0_288_target_expression_core"
    if alias in COMMON_NEXT_TARGET_ALIASES:
        return "v0_288_target_expression_core_aliases"
    if normalized_kind.startswith("TargetSort"):
        return "after_target_sequence_sorting"
    if normalized_kind.startswith("TargetFetch") or alias in SUMMON_TARGET_ALIASES:
        return "after_summon_or_unique_entity_system"
    return "later_target_expression_admission"


def _target_admission_batches(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(record["suggested_admission_batch"]) for record in records)
    return {
        "counts": dict(sorted(counts.items())),
        "recommended_first_batch": "v0_288_target_expression_core",
        "first_batch_includes": [
            "TargetAlias core/common aliases",
            "TargetSequence",
            "TargetFilter with already-admitted predicates",
            "Retarget process-only planning",
        ],
        "first_batch_excludes": [
            "summon/servant targets",
            "unique-name entity fetch without entity registry",
            "special gameplay targets",
        ],
    }


def _numeric_expr_kind(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, (int, float)):
        return "literal_number"
    if isinstance(value, dict):
        if value.get("IsDynamic") is False and isinstance(value.get("FixedValue"), dict):
            return "fixed_value"
        if value.get("IsDynamic") is True and isinstance(value.get("PostfixExpr"), dict):
            return "dynamic_postfix"
        if "DynamicHashes" in value or "PostfixExpr" in value:
            return "dynamic_expr"
        return "dict_other"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _value_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        nested = value.get("Value")
        if isinstance(nested, str):
            return nested
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _status_sample(file_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file": file_name,
        "status_id": row.get("StatusID", row.get("ID")),
        "modifier_name": row.get("ModifierName"),
        "status_type": row.get("StatusType"),
        "can_dispel": row.get("CanDispel") if isinstance(row.get("CanDispel"), bool) else None,
        "read_param_list": _string_list(row.get("ReadParamList")),
        "tag_list": _string_list(row.get("TagList")),
    }


def _counter_top(counter: Counter, limit: int) -> list[dict[str, Any]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _set_example(examples: dict[str, dict[str, Any]], key: str, record: dict[str, Any]) -> None:
    if key in examples:
        return
    examples[key] = _sample_record(record)


def _sample_record(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_path",
        "source_area",
        "json_path",
        "event",
        "modifier_name",
        "target_expression_kind",
        "target_alias",
        "alias",
        "current_admission_bucket",
        "suggested_admission_batch",
        "status_event_family_status",
        "runtime_event_sources",
        "blocked_reason",
    )
    sample = {key: record[key] for key in keys if key in record}
    if "source" in record:
        sample["source"] = record["source"]
    return sample


def _examples_have_source(examples: dict[str, dict[str, Any]]) -> bool:
    if not examples:
        return False
    for sample in examples.values():
        if not sample.get("source_path") and not isinstance(sample.get("source"), dict):
            return False
    return True


def _event_summary(event_matrix: dict[str, Any], event: str) -> dict[str, Any]:
    item = event_matrix.get(event)
    if not isinstance(item, dict):
        return {"callback_count": 0, "current_coverage_status": "missing"}
    return {
        "callback_count": item.get("callback_count", 0),
        "current_coverage_status": item.get("current_coverage_status", ""),
        "runtime_event_sources": item.get("current_runtime_event_sources", []),
        "blocked_reason": item.get("current_blocked_reason", ""),
        "source_area_counts": item.get("source_area_counts", {}),
        "task_opcode_counts_top": item.get("task_opcode_counts_top", [])[:10],
    }


def _gap(
    gap_id: str,
    status: str,
    summary: str,
    *,
    evidence: dict[str, Any],
    next_step: str,
) -> dict[str, Any]:
    return {
        "gap_id": gap_id,
        "status": status,
        "summary": summary,
        "evidence": evidence,
        "next_step": next_step,
    }


if __name__ == "__main__":
    raise SystemExit(main())
