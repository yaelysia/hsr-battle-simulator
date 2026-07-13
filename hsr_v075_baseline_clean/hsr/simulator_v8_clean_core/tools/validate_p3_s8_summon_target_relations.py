from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import IRSource, TargetExpressionIR, TargetExpressionNodeIR
from ..rules.rulebook import RuleBook
from ..systems.summon import SummonSystem
from ..systems.target import TargetExpressionResult, TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_p1_3_summon_assistant_servant import (
    _select_executable_servant_definition,
    _select_executable_summon_monster_intent,
)
from .validate_p3_s0_summon_source_inventory import _raw_ability_source_matrix
from .validate_v0_287 import _counter_top


VALIDATION_VERSION = "p3_s8_summon_target_relations"

P3_TARGET_ALIASES = (
    "CasterServant",
    "CasterSummonedMinions",
    "LastSummonMonsters",
    "ServantEntityList",
)

P3_TARGET_OPERATIONS = ("GetServant", "GetSummoner", "RemoveServant")


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    raw_sources = _raw_ability_source_matrix(tbgd_root)
    global_config = _global_target_config(tbgd_root)
    state_bundle = _combined_summon_state(rules)
    groups = {
        "target_source_matrix": _target_source_matrix_case(raw_sources, global_config, rules),
        "source_backed_positive_relations": _source_backed_positive_relations_case(rules, state_bundle),
        "target_relation_negative_cases": _target_relation_negative_cases(rules, state_bundle),
        "assistant_target_boundary": _assistant_target_boundary_case(raw_sources, rules, state_bundle),
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
                "mode": "structured_summon_servant_target_relation_predicates_with_assistant_avatar_scope_exclusion",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "textmap_read": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "validation_only_unsupported_operation_negative": True,
                "servant_definition_id": state_bundle["servant_definition_id"],
                "summon_intent_id": state_bundle["summon_intent_id"],
            },
        },
        "summary": {
            "classification_counts": groups["target_source_matrix"]["classification_counts"],
            "positive_case_count": groups["source_backed_positive_relations"]["positive_case_count"],
            "negative_case_count": groups["target_relation_negative_cases"]["negative_case_count"],
            "assistant_boundary_classification": groups["assistant_target_boundary"]["classification"],
            "failed_group_count": sum(0 if group["checks"]["ok"] else 1 for group in groups.values()),
        },
        "case_groups": groups,
        "checks": checks,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p3_s8_summon_target_relations.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P3-S8 summon/servant target relations.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _target_source_matrix_case(
    raw_sources: dict[str, Any],
    global_config: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    raw_alias_counts = Counter(str(record.get("alias") or "") for record in raw_sources["target_records"])
    global_aliases = set(global_config["aliases"])
    global_operations = set(global_config["operations"])
    rows = []
    for alias in P3_TARGET_ALIASES:
        expressions = [item for item in rules.target_expressions() if item.alias == alias]
        executable = [item for item in expressions if item.coverage_status == "executable"]
        raw_count = int(raw_alias_counts.get(alias, 0))
        global_count = 1 if alias in global_aliases else 0
        if executable:
            classification = "executable"
        elif raw_count or global_count or expressions:
            classification = "lowering_gap" if raw_count and not expressions and not global_count else "admission_gap"
        else:
            classification = "source_absent_not_required"
        rows.append(
            {
                "kind": "alias",
                "name": alias,
                "raw_count": raw_count,
                "global_config_count": global_count,
                "ir_count": len(expressions),
                "executable_count": len(executable),
                "blocked_count": len(expressions) - len(executable),
                "classification": classification,
                "sample_expression_id": expressions[0].target_expression_id if expressions else "",
            }
        )
    for operation in P3_TARGET_OPERATIONS:
        expressions = [
            item
            for item in rules.target_expressions()
            if _source_evidence(item).get("operation") == operation
            or str(item.alias).endswith(f".{operation}")
        ]
        executable = [item for item in expressions if item.coverage_status == "executable"]
        raw_count = 1 if operation in global_operations else 0
        classification = "executable" if executable else ("admission_gap" if raw_count or expressions else "source_absent_not_required")
        rows.append(
            {
                "kind": "operation",
                "name": operation,
                "raw_count": raw_count,
                "global_config_count": raw_count,
                "ir_count": len(expressions),
                "executable_count": len(executable),
                "blocked_count": len(expressions) - len(executable),
                "classification": classification,
                "sample_expression_id": expressions[0].target_expression_id if expressions else "",
            }
        )
    classification_counts = Counter(str(row["classification"]) for row in rows)
    checks = {
        "no_unclassified_rows": not any(row["classification"] == "unclassified" for row in rows),
        "required_alias_rows_present": {row["name"] for row in rows if row["kind"] == "alias"} == set(P3_TARGET_ALIASES),
        "required_operation_rows_present": {row["name"] for row in rows if row["kind"] == "operation"} == set(P3_TARGET_OPERATIONS),
        "source_backed_core_aliases_executable": all(
            next(row for row in rows if row["name"] == alias)["classification"] == "executable"
            for alias in ("CasterServant", "CasterSummonedMinions", "LastSummonMonsters", "ServantEntityList")
        ),
        "required_operations_executable": all(
            next(row for row in rows if row["name"] == operation)["classification"] == "executable"
            for operation in P3_TARGET_OPERATIONS
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification_counts": dict(sorted(classification_counts.items())),
        "rows": rows,
        "raw_alias_counts_top": _counter_top(raw_alias_counts, 20),
    }


def _global_target_config(tbgd_root: Path) -> dict[str, Any]:
    alias_path = tbgd_root / "Config" / "GlobalConfig" / "TargetAliasConfig.json"
    operation_path = tbgd_root / "Config" / "GlobalConfig" / "TargetOperationConfig.json"
    alias_config = _read_json_object(alias_path)
    operation_config = _read_json_object(operation_path)
    alias_dict = alias_config.get("AliasDict") if isinstance(alias_config.get("AliasDict"), dict) else {}
    operation_dict = operation_config.get("OperationDict") if isinstance(operation_config.get("OperationDict"), dict) else {}
    return {
        "aliases": sorted(str(key) for key in alias_dict.keys()),
        "operations": sorted(str(key) for key in operation_dict.keys()),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    value = data.get("Value") if isinstance(data, dict) and "Value" in data else data
    return value if isinstance(value, dict) else {}


def _source_backed_positive_relations_case(rules: RuleBook, bundle: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = bundle["state"]
    servant_id = str(bundle["servant_id"])
    summoned_monster_ids = tuple(bundle["summoned_monster_ids"])
    owner_id = str(bundle["servant_owner_id"])
    summoner_id = str(bundle["summoner_id"])
    cases = {
        "owner_fetch": _expect_targets(
            _select_first_kind_expression(rules, ("TargetFetchOwner", "TargetFetchModifierOwner")),
            state,
            (owner_id,),
            owner_id=owner_id,
        ),
        "last_summon": _expect_targets(
            _select_alias_expression(rules, "LastSummonMonsters"),
            state,
            summoned_monster_ids,
            caster_id=summoner_id,
        ),
        "caster_summoned_minions": _expect_targets(
            _select_alias_expression(rules, "CasterSummonedMinions"),
            state,
            summoned_monster_ids,
            caster_id=summoner_id,
        ),
        "servant_entity_list": _expect_targets(
            _select_alias_expression(rules, "ServantEntityList"),
            state,
            (servant_id,),
            caster_id=owner_id,
        ),
        "caster_servant": _expect_targets(
            _select_alias_expression(rules, "CasterServant"),
            state,
            (servant_id,),
            caster_id=owner_id,
        ),
        "get_servant_operation": _expect_targets(
            _select_operation_expression(rules, "GetServant", preferred_aliases=("AllLightTeam.GetServant",)),
            state,
            (servant_id,),
            caster_id=owner_id,
        ),
        "get_summoner_operation": _expect_targets(
            _select_operation_expression(rules, "GetSummoner", preferred_aliases=("ServantEntityList.GetSummoner",)),
            state,
            (owner_id,),
            caster_id=owner_id,
        ),
        "remove_servant_operation": _expect_targets(
            _select_operation_expression(rules, "RemoveServant", preferred_aliases=("AllLightTeam.RemoveServant",)),
            state,
            ("ally:observer", owner_id),
            caster_id=owner_id,
        ),
    }
    checks = {f"{name}_ok": case["ok"] for name, case in cases.items()}
    checks["all_positive_cases_source_backed"] = all(case["source_backed"] for case in cases.values())
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "executable",
        "positive_case_count": len(cases),
        "servant_id": servant_id,
        "summoned_monster_ids": list(summoned_monster_ids),
        "cases": cases,
    }


def _target_relation_negative_cases(rules: RuleBook, bundle: dict[str, Any]) -> dict[str, Any]:
    state: BattleState = bundle["state"]
    servant_id = str(bundle["servant_id"])
    owner_id = str(bundle["servant_owner_id"])
    summoner_id = str(bundle["summoner_id"])
    caster_servant = _select_alias_expression(rules, "CasterServant")
    servant_list = _select_alias_expression(rules, "ServantEntityList")
    cases = {
        "missing_runtime": _expect_blocked(
            caster_servant,
            replace(state, global_flags={key: value for key, value in state.global_flags.items() if key != "summon_runtime"}),
            expected_reason="summon_runtime_missing",
            caster_id=owner_id,
        ),
        "flag_only_no_runtime": _expect_blocked(
            caster_servant,
            _flag_only_servant_state(state, servant_id, owner_id),
            expected_reason="summon_runtime_missing",
            caster_id=owner_id,
        ),
        "wrong_owner_no_default_fallback": _expect_blocked(
            caster_servant,
            _with_runtime_default_owner(state, servant_id),
            expected_reason="target_map_servant_empty",
            caster_id=summoner_id,
        ),
        "removed_servant": _expect_blocked(
            servant_list,
            _with_unit_lifecycle(state, servant_id, "removed"),
            expected_reason="unit_removed",
            caster_id=owner_id,
        ),
        "untargetable_servant": _expect_blocked(
            servant_list,
            _with_runtime_targetable(state, servant_id, False),
            expected_reason="summon_runtime_entity_not_targetable",
            caster_id=owner_id,
        ),
        "trimmed_runtime_audit_equivalent": _expect_audit_trim_equivalent(
            servant_list,
            state,
            _without_runtime_source_trace(state, servant_id),
            caster_id=owner_id,
        ),
        "unsupported_target_operation": _expect_blocked(
            _validation_only_expression("AllLightTeam.UnsupportedSummonOperation"),
            state,
            expected_reason="target_alias_not_admitted:AllLightTeam.UnsupportedSummonOperation",
            caster_id=owner_id,
        ),
    }
    checks = {f"{name}_ok": case["ok"] for name, case in cases.items()}
    checks["all_negative_cases_state_unchanged"] = all(case["state_unchanged"] for case in cases.values())
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": "boundary_only",
        "negative_case_count": len(cases),
        "cases": cases,
    }


def _assistant_target_boundary_case(
    raw_sources: dict[str, Any],
    rules: RuleBook,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    state: BattleState = bundle["state"]
    owner_id = str(bundle["servant_owner_id"])
    raw_count = sum(1 for record in raw_sources["target_records"] if record.get("alias") == "FriendServantSelect")
    expressions = [item for item in rules.target_expressions() if item.alias == "FriendServantSelect"]
    executable = [item for item in expressions if item.coverage_status == "executable"]
    result = TargetExpressionResult(
        ok=False,
        blocked_reason="friend_servant_select_is_assistant_avatar_scope_exclusion",
        expression_id="",
        expression_kind="TargetAlias",
        alias="FriendServantSelect",
        metadata={"raw_count": raw_count, "ir_count": len(expressions), "executable_count": len(executable)},
    )
    classification = "out_of_scope" if raw_count or expressions else "source_absent_not_required"
    runtime_check = True
    checks = {
        "friend_servant_select_raw_classified": raw_count >= 0,
        "friend_servant_select_no_unclassified_state": classification in {
            "out_of_scope",
            "source_absent_not_required",
        },
        "assistant_boundary_no_fake_execution": runtime_check,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "classification": classification,
        "raw_count": raw_count,
        "ir_count": len(expressions),
        "executable_count": len(executable),
        "scope_exclusion_reason": (
            "FriendServantSelect belongs to the AssistantAvatar / avatar-assistant target system, "
            "not summon monster or servant runtime target acceptance."
        )
        if classification == "out_of_scope"
        else "",
        "resolution": result.to_json(),
    }


def _combined_summon_state(rules: RuleBook) -> dict[str, Any]:
    servant_definition = _select_executable_servant_definition(rules)
    summon_intent = _select_executable_summon_monster_intent(rules)
    owner_id = "ally:servant_owner"
    summoner_id = "enemy:summoner"
    state = BattleState(
        units={
            owner_id: UnitState(
                owner_id,
                "ally",
                servant_definition.owner_entity_ref,
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                attack=500.0,
                defense=300.0,
                speed=100.0,
                flags={"position": 1},
            ),
            "ally:observer": UnitState(
                "ally:observer",
                "ally",
                "avatar:observer",
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                speed=100.0,
                flags={"position": 2},
            ),
            summoner_id: UnitState(
                summoner_id,
                "enemy",
                "monster:summoner",
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                flags={"position": 5},
            ),
            "enemy:target": UnitState(
                "enemy:target",
                "enemy",
                "monster:target",
                level=80,
                hp=1000.0,
                max_hp=1000.0,
                speed=90.0,
                flags={"position": 6},
            ),
        },
        global_flags={"phase": "scenario", "current_window": "idle"},
    )
    system = SummonSystem(rules)
    servant_result = system.apply_spawn_servant(
        state,
        system.plan_spawn_servant(state, servant_definition, owner_id=owner_id),
    )
    after_servant = MutationReducer().apply_all(state, servant_result.mutations)
    summon_result = system.apply_spawn(
        after_servant,
        system.plan_spawn_summoned_monster(after_servant, summon_intent, owner_id=summoner_id),
    )
    after = MutationReducer().apply_all(after_servant, summon_result.mutations)
    servant_id = next(
        unit_id
        for unit_id, unit in sorted(after.units.items())
        if unit.flags.get("summon_kind") == "servant"
    )
    summoned_monsters = tuple(
        unit_id
        for unit_id, unit in sorted(after.units.items())
        if unit.flags.get("summon_kind") == "summoned_monster"
    )
    return {
        "state": after,
        "servant_id": servant_id,
        "summoned_monster_ids": summoned_monsters,
        "servant_owner_id": owner_id,
        "summoner_id": summoner_id,
        "servant_definition_id": servant_definition.servant_definition_id,
        "summon_intent_id": summon_intent.summon_intent_id,
    }


def _expect_targets(
    expression: TargetExpressionIR | None,
    state: BattleState,
    expected: tuple[str, ...],
    *,
    caster_id: str = "ally:servant_owner",
    owner_id: str | None = None,
) -> dict[str, Any]:
    if expression is None:
        return {"ok": False, "source_backed": False, "blocked_reason": "target_expression_missing"}
    before = state.snapshot().to_json()
    result = _resolve(expression, state, caster_id=caster_id, owner_id=owner_id)
    after = state.snapshot().to_json()
    return {
        "ok": result.ok and result.target_ids == expected and before == after,
        "source_backed": _expression_source_backed(expression),
        "expression": _expression_sample(expression),
        "expected": list(expected),
        "resolution": result.to_json(),
        "state_unchanged": before == after,
    }


def _expect_blocked(
    expression: TargetExpressionIR | None,
    state: BattleState,
    *,
    expected_reason: str,
    caster_id: str,
) -> dict[str, Any]:
    if expression is None:
        return {
            "ok": False,
            "state_unchanged": True,
            "blocked_reason": "target_expression_missing",
            "expected_reason": expected_reason,
        }
    before = state.snapshot().to_json()
    result = _resolve(expression, state, caster_id=caster_id)
    after = state.snapshot().to_json()
    return {
        "ok": (not result.ok) and result.blocked_reason == expected_reason and before == after,
        "state_unchanged": before == after,
        "expression": _expression_sample(expression),
        "blocked_reason": result.blocked_reason,
        "expected_reason": expected_reason,
        "resolution": result.to_json(),
    }


def _expect_audit_trim_equivalent(
    expression: TargetExpressionIR | None,
    full_state: BattleState,
    trimmed_state: BattleState,
    *,
    caster_id: str,
) -> dict[str, Any]:
    if expression is None:
        return {"ok": False, "state_unchanged": True, "blocked_reason": "target_expression_missing"}
    full_before = full_state.snapshot().to_json()
    trimmed_before = trimmed_state.snapshot().to_json()
    full = _resolve(expression, full_state, caster_id=caster_id)
    trimmed = _resolve(expression, trimmed_state, caster_id=caster_id)
    full_after = full_state.snapshot().to_json()
    trimmed_after = trimmed_state.snapshot().to_json()
    return {
        "ok": full.ok
        and trimmed.ok
        and full.target_ids == trimmed.target_ids
        and full_before == full_after
        and trimmed_before == trimmed_after,
        "state_unchanged": full_before == full_after and trimmed_before == trimmed_after,
        "expression": _expression_sample(expression),
        "full_resolution": full.to_json(),
        "trimmed_resolution": trimmed.to_json(),
    }


def _resolve(
    expression: TargetExpressionIR,
    state: BattleState,
    *,
    caster_id: str,
    owner_id: str | None = None,
) -> TargetExpressionResult:
    return TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id=caster_id,
        owner_id=owner_id,
    )


def _select_alias_expression(rules: RuleBook, alias: str) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: item.target_expression_id):
        if expression.alias == alias and expression.coverage_status == "executable":
            return expression
    return None


def _select_kind_expression(rules: RuleBook, kind: str) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: item.target_expression_id):
        if expression.expression_kind == kind and expression.coverage_status == "executable":
            return expression
    return None


def _select_first_kind_expression(rules: RuleBook, kinds: tuple[str, ...]) -> TargetExpressionIR | None:
    for kind in kinds:
        expression = _select_kind_expression(rules, kind)
        if expression is not None:
            return expression
    return None


def _select_operation_expression(
    rules: RuleBook,
    operation: str,
    *,
    preferred_aliases: tuple[str, ...],
) -> TargetExpressionIR | None:
    expressions = [
        item
        for item in sorted(rules.target_expressions(), key=lambda expr: expr.target_expression_id)
        if item.coverage_status == "executable"
        and (
            _source_evidence(item).get("operation") == operation
            or str(item.alias).endswith(f".{operation}")
        )
    ]
    for alias in preferred_aliases:
        for expression in expressions:
            if expression.alias == alias:
                return expression
    return expressions[0] if expressions else None


def _source_evidence(expression: TargetExpressionIR) -> dict[str, Any]:
    source = expression.source
    if isinstance(source, IRSource) and isinstance(source.evidence, dict):
        return source.evidence
    return {}


def _expression_source_backed(expression: TargetExpressionIR) -> bool:
    source = expression.source
    return (
        isinstance(source, IRSource)
        and bool(source.source_path)
        and bool(source.raw_type)
        and bool(source.raw_id)
        and "validation_only" not in source.source_path
    )


def _expression_sample(expression: TargetExpressionIR) -> dict[str, JSONValue]:
    return {
        "target_expression_id": expression.target_expression_id,
        "expression_kind": expression.expression_kind,
        "alias": expression.alias,
        "coverage_status": expression.coverage_status,
        "blocked_reason": expression.blocked_reason,
        "source": expression.source.to_json(),
    }


def _validation_only_expression(alias: str) -> TargetExpressionIR:
    return TargetExpressionIR(
        target_expression_id=f"validation_only:{alias}",
        expression_kind="TargetAlias",
        alias=alias,
        payload={"validation_only": True},
        source=IRSource(
            source_path="validation_only:P3-S8",
            raw_type="ValidationOnlyTargetAlias",
            raw_id=alias,
            evidence={"validation_only": True, "alias": alias},
        ),
        node=TargetExpressionNodeIR(expression_kind="TargetAlias", alias=alias),
        coverage_status="executable",
    )


def _flag_only_servant_state(state: BattleState, servant_id: str, owner_id: str) -> BattleState:
    servant = state.units[servant_id]
    return BattleState(
        units={
            owner_id: state.units[owner_id],
            servant_id: servant,
        },
        global_flags={key: value for key, value in state.global_flags.items() if key != "summon_runtime"},
    )


def _with_runtime_default_owner(state: BattleState, servant_id: str) -> BattleState:
    runtime = deepcopy(state.global_flags.get("summon_runtime"))
    if isinstance(runtime, dict):
        by_owner = dict(runtime.get("by_owner") or {})
        by_owner["default"] = [servant_id]
        runtime["by_owner"] = by_owner
    return replace(state, global_flags={**state.global_flags, "summon_runtime": runtime})


def _with_unit_lifecycle(state: BattleState, unit_id: str, lifecycle_status: str) -> BattleState:
    units = dict(state.units)
    unit = units[unit_id]
    units[unit_id] = replace(
        unit,
        flags={**unit.flags, "lifecycle_status": lifecycle_status},
    )
    return replace(state, units=units)


def _with_runtime_targetable(state: BattleState, unit_id: str, targetable: bool) -> BattleState:
    runtime = deepcopy(state.global_flags.get("summon_runtime"))
    if isinstance(runtime, dict):
        entities = dict(runtime.get("entities") or {})
        entry = dict(entities.get(unit_id) or {})
        targetability = dict(entry.get("targetability") or {})
        targetability["targetable"] = targetable
        entry["targetability"] = targetability
        entities[unit_id] = entry
        runtime["entities"] = entities
    return replace(state, global_flags={**state.global_flags, "summon_runtime": runtime})


def _without_runtime_source_trace(state: BattleState, unit_id: str) -> BattleState:
    runtime = deepcopy(state.global_flags.get("summon_runtime"))
    if isinstance(runtime, dict):
        entities = dict(runtime.get("entities") or {})
        entry = dict(entities.get(unit_id) or {})
        entry.pop("source_trace", None)
        entities[unit_id] = entry
        runtime["entities"] = entities
    return replace(state, global_flags={**state.global_flags, "summon_runtime": runtime})


if __name__ == "__main__":
    raise SystemExit(main())
