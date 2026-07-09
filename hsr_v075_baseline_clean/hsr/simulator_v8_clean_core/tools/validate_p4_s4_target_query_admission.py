from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CanonicalIR, TargetExpressionIR
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem, ActionChoice
from ..systems.summon import SUMMON_RUNTIME_SCHEMA_VERSION
from ..systems.target import TargetPolicy, TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p4_s4_target_query_admission"
MATRIX_SCHEMA_VERSION = "p4_s4_target_backlog_matrix_v1"

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
    "action_target_policy_source_trace",
    "action_target_boundary_negative",
    "target_alias_character_domain",
    "target_alias_monster_domain",
    "target_alias_summon_servant_domain",
    "target_alias_global_operation_dot_alias",
    "target_query_subtypes",
    "target_fetch_registry_boundaries",
    "target_sort_filter_retarget_pipeline",
    "target_random_rng_ledger",
    "p3_summon_target_expression_backlog_split",
}

SUMMON_SERVANT_ALIASES = {
    "CasterServant",
    "CasterSummonedMinions",
    "FriendServantSelect",
    "LastSummonMonsters",
    "ServantEntityList",
}
P3_TARGET_ALIASES = (
    "CasterServant",
    "CasterSummonedMinions",
    "LastSummonMonsters",
    "ServantEntityList",
)
P3_TARGET_OPERATIONS = ("GetServant", "GetSummoner", "RemoveServant")
PIPELINE_KINDS = {
    "Retarget",
    "TargetConcat",
    "TargetFilter",
    "TargetIndex",
    "TargetMapAdjoinEntity",
    "TargetMapSummonedMinions",
    "TargetMapSummoner",
    "TargetReverse",
    "TargetSequence",
    "TargetShuffle",
    "TargetTake",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    global_config = _global_target_config(tbgd_root)
    matrix = build_p4_s4_target_backlog_matrix(ir, rules, global_config)
    matrix_checks = validate_p4_s4_target_backlog_matrix(matrix)
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
                "mode": "p4_s4_target_structural_predicates",
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
                "default_target_fallback_used": False,
                "default_random_used": False,
                "full_ir_written": False,
                "full_transition_dump_written": False,
                "aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "target_backlog_matrix": matrix["target_backlog_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p4_s4_target_query_admission.json", result)
    write_json(output_dir / "p4_s4_target_backlog_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P4-S4 target alias/query/fetch/sort admission.")
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


def build_p4_s4_target_backlog_matrix(
    ir: CanonicalIR,
    rules: RuleBook,
    global_config: dict[str, Any],
) -> dict[str, Any]:
    expressions = tuple(rules.target_expressions())
    rows = [
        _action_target_policy_source_trace_row(ir, rules),
        _action_target_boundary_negative_row(),
        _target_expression_bucket_row(
            rules,
            "target_alias_character_domain",
            [item for item in expressions if item.expression_kind == "TargetAlias" and _source_domain(item) == "character_ability"],
            required=True,
            details={"source_domain": "character_ability"},
        ),
        _target_expression_bucket_row(
            rules,
            "target_alias_monster_domain",
            [item for item in expressions if item.expression_kind == "TargetAlias" and _source_domain(item) == "monster_ability"],
            required=True,
            details={"source_domain": "monster_ability"},
        ),
        _target_expression_bucket_row(
            rules,
            "target_alias_summon_servant_domain",
            [item for item in expressions if _is_summon_servant_expression(item)],
            required=True,
            details={"tracked_aliases": sorted(SUMMON_SERVANT_ALIASES)},
        ),
        _target_expression_bucket_row(
            rules,
            "target_alias_global_operation_dot_alias",
            [item for item in expressions if _is_global_or_dot_alias_expression(item)],
            required=True,
            details={
                "global_alias_count": len(global_config["aliases"]),
                "global_operation_count": len(global_config["operations"]),
            },
        ),
        _target_query_subtypes_row(rules, expressions),
        _target_fetch_registry_boundaries_row(rules, expressions),
        _target_expression_bucket_row(
            rules,
            "target_sort_filter_retarget_pipeline",
            [item for item in expressions if _is_sort_filter_retarget_expression(item)],
            required=True,
            details={"pipeline_kinds": sorted(PIPELINE_KINDS)},
        ),
        _target_random_rng_ledger_row(rules, expressions),
        _p3_summon_target_expression_backlog_split_row(rules, expressions, global_config),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            gap_counts[str(key)] += int(value or 0)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "target_backlog_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "unclassified_count": int(classification_counts.get("unclassified", 0)),
            "target_expression_count": len(expressions),
            "target_expression_coverage_counts": dict(sorted(Counter(item.coverage_status for item in expressions).items())),
            "p3_summon_split_row_count": len(
                matrix["p3_summon_target_expression_backlog_split"]["details"].get("subrows", [])
            ),
        },
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "combat_executor_runtime_sample_count": 1,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p4_s4_target_query_admission.json",
                "p4_s4_target_backlog_matrix.json",
            ],
        },
    }


def validate_p4_s4_target_backlog_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("target_backlog_matrix") or {})
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
        "action_policy_source_trace_executable": rows.get("action_target_policy_source_trace", {}).get("classification")
        == "executable",
        "action_boundary_state_unchanged": _row_check(rows, "action_target_boundary_negative", "state_unchanged"),
        "fetch_registry_negative_boundaries": _row_check(
            rows,
            "target_fetch_registry_boundaries",
            "wrong_key_or_missing_registry_blocked",
        ),
        "random_target_uses_rng_ledger": _row_check(rows, "target_random_rng_ledger", "rng_ledger_checked"),
        "p3_backlog_split": int(matrix.get("summary", {}).get("p3_summon_split_row_count") or 0)
        == len(P3_TARGET_ALIASES) + len(P3_TARGET_OPERATIONS),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
    }


def _action_target_policy_source_trace_row(ir: CanonicalIR, rules: RuleBook) -> dict[str, JSONValue]:
    case = _select_and_execute_action_target_policy_case(ir, rules)
    checks = dict(case["checks"])
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "action_target_policy_source_trace",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        raw_count=1,
        ir_count=1,
        rulebook_visible_count=1,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=case["source_trace"],
        runtime_samples=[case["runtime_sample"]],
        details={
            "selection_predicate": "availability choice with action target policy source_trace and executor target resolution policy source_trace",
            "target_policy": case["target_policy"],
            "transition_target_policy": case["transition_target_policy"],
        },
    )


def _select_and_execute_action_target_policy_case(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    availability = ActionAvailabilitySystem(rules)
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        if rules.combatant_action_set(card.entity_ref) is None:
            continue
        state = _action_state(card.entity_ref)
        view = availability.view(state)
        for choice in view.choices:
            target_ids = tuple(choice.auto_target_ids or choice.selectable_target_ids[:1])
            if not target_ids:
                continue
            choice_policy_source = dict(choice.target_policy.get("source_trace") or {})
            if not choice_policy_source.get("action_definition") or not choice_policy_source.get("action_event"):
                continue
            command = _command_from_choice(choice, target_ids)
            after, transition = CombatExecutor(rules).execute(command, state)
            replay = MutationReducer().replay_snapshot(state, transition.transaction.mutations, transition.after.to_json())
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            transition_policy = dict(transition.target_resolution.metadata.get("policy") or {})
            transition_policy_source = dict(transition_policy.get("source_trace") or {})
            checks = {
                "choice_target_policy_has_source_trace": bool(choice_policy_source.get("action_definition"))
                and bool(choice_policy_source.get("action_event")),
                "choice_target_enumeration_policy_has_source_trace": bool(
                    dict(
                        dict(dict(choice.metadata.get("target_enumeration") or {}).get("policy") or {}).get("source_trace")
                        or {}
                    ).get("action_definition")
                ),
                "transition_policy_has_source_trace": bool(transition_policy_source.get("action_definition"))
                and bool(transition_policy_source.get("action_event")),
                "action_enabled": transition.coverage.get("action_enabled") is True,
                "target_resolution_selected": bool(transition.target_resolution.selected),
                "after_matches_transition": after.snapshot().to_json() == transition.after.to_json(),
                "replay_ok": replay.ok,
                "source_audit_ok": audit.ok,
            }
            if all(checks.values()):
                return {
                    "checks": checks,
                    "source_trace": {
                        "choice": choice.source_trace,
                        "target_policy": choice_policy_source,
                        "transition_target_policy": transition_policy_source,
                    },
                    "target_policy": choice.target_policy,
                    "transition_target_policy": transition_policy,
                    "runtime_sample": {
                        "actor_data_card_id": card.card_id,
                        "action_id": choice.action_id,
                        "action_level": choice.action_level,
                        "choice_kind": choice.choice_kind,
                        "target_ids": list(target_ids),
                        "target_policy_id": choice.target_policy.get("policy_id"),
                        "target_mode": choice.target_policy.get("target_mode"),
                        "transition_reason": transition.target_resolution.reason,
                    },
                }
    raise RuntimeError("no executable action target policy source trace sample selected by structured predicate")


def _action_target_boundary_negative_row() -> dict[str, JSONValue]:
    system = TargetSystem()
    state = _target_validation_state()
    before = state.snapshot().to_json()
    no_target_state = BattleState(
        units={
            "ally:caster": UnitState(
                unit_id="ally:caster",
                side="ally",
                template_id="avatar:validation:caster",
                hp=1000.0,
                max_hp=1000.0,
            )
        }
    )
    empty = system.enumerate_action_targets(no_target_state, "ally:caster", TargetPolicy(policy_id="enemy_damage"))
    unknown = system.resolve_action_targets(state, "ally:caster", ("enemy:missing",), TargetPolicy(policy_id="enemy_damage"))
    defeated = system.resolve_action_targets(
        _with_unit_flags(state, "enemy:left", {"lifecycle_status": "defeated"}),
        "ally:caster",
        ("enemy:left",),
        TargetPolicy(policy_id="enemy_damage"),
    )
    removed = system.resolve_action_targets(
        _with_unit_flags(state, "enemy:left", {"lifecycle_status": "removed"}),
        "ally:caster",
        ("enemy:left",),
        TargetPolicy(policy_id="enemy_damage"),
    )
    checks = {
        "empty_candidates_blocked": not empty.ok and empty.blocked_reason == "target_candidates_empty",
        "unknown_target_blocked": not unknown.ok and any("unknown:enemy:missing" in item for item in unknown.errors),
        "defeated_target_blocked": not defeated.ok and any("unit_defeated:enemy:left" in item for item in defeated.errors),
        "removed_target_blocked": not removed.ok and any("unit_removed:enemy:left" in item for item in removed.errors),
        "state_unchanged": state.snapshot().to_json() == before,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "action_target_boundary_negative",
        classification="boundary_only",
        checks=checks,
        raw_count=4,
        ir_count=4,
        executable_count=0,
        blocked_or_gap_count=4,
        details={
            "empty_candidates": empty.to_json(),
            "unknown_target": unknown.resolution.to_json(),
            "defeated_target": defeated.resolution.to_json(),
            "removed_target": removed.resolution.to_json(),
        },
    )


def _target_query_subtypes_row(rules: RuleBook, expressions: tuple[TargetExpressionIR, ...]) -> dict[str, JSONValue]:
    query_expressions = tuple(item for item in expressions if item.expression_kind == "TargetQuery")
    positive = _first_successful_resolution(
        query_expressions,
        owner_id="ally:caster",
        state=_target_validation_state(),
    )
    base = _target_expression_bucket_row(
        rules,
        "target_query_subtypes",
        query_expressions,
        required=True,
        details={"entity_type_counts": _raw_field_counts(query_expressions, "EntityTypeMask")},
    )
    checks = dict(base["checks"]["checks"])
    checks["servant_query_positive_or_gap_recorded"] = bool(positive) or base["classification"] in GAP_STATES
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    base["checks"] = {"ok": checks["ok"], "checks": checks}
    base["runtime_samples"] = [positive] if positive else []
    return base


def _target_fetch_registry_boundaries_row(
    rules: RuleBook,
    expressions: tuple[TargetExpressionIR, ...],
) -> dict[str, JSONValue]:
    fetch_expressions = tuple(item for item in expressions if item.expression_kind.startswith("TargetFetch"))
    positive = _registry_fetch_positive(fetch_expressions)
    negative = _registry_fetch_negative(fetch_expressions)
    base = _target_expression_bucket_row(
        rules,
        "target_fetch_registry_boundaries",
        fetch_expressions,
        required=True,
        details={"fetch_kind_counts": _kind_counts(fetch_expressions)},
    )
    checks = dict(base["checks"]["checks"])
    checks["registry_fetch_positive_or_gap_recorded"] = bool(positive) or base["classification"] in GAP_STATES
    checks["wrong_key_or_missing_registry_blocked"] = bool(negative) and negative.get("blocked") is True
    checks["default_registry_does_not_satisfy_named_source"] = bool(negative) and negative.get("blocked") is True
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    base["checks"] = {"ok": checks["ok"], "checks": checks}
    base["runtime_samples"] = [item for item in (positive, negative) if item]
    return base


def _target_random_rng_ledger_row(rules: RuleBook, expressions: tuple[TargetExpressionIR, ...]) -> dict[str, JSONValue]:
    random_expressions = tuple(item for item in expressions if _expression_has_random(item))
    explicit = _random_resolution(random_expressions, event_payload={**_event_payload(), "target_random_choices": {"default": 1}})
    missing = _random_resolution(random_expressions, event_payload=_event_payload())
    invalid = _random_resolution(random_expressions, event_payload={**_event_payload(), "target_random_choices": {"default": 999}})
    base = _target_expression_bucket_row(
        rules,
        "target_random_rng_ledger",
        random_expressions,
        required=False,
        details={"random_expression_count": len(random_expressions)},
    )
    checks = dict(base["checks"]["checks"])
    if random_expressions:
        checks["explicit_choice_ok"] = bool(explicit) and explicit.get("ok") is True and bool(explicit.get("rng_events"))
        checks["missing_choice_blocked"] = bool(missing) and missing.get("blocked_reason") == "requires_rng_choice"
        checks["invalid_choice_blocked"] = bool(invalid) and invalid.get("blocked_reason") == "target_random_choice_invalid"
        checks["rng_ledger_checked"] = (
            checks["explicit_choice_ok"] and checks["missing_choice_blocked"] and checks["invalid_choice_blocked"]
        )
    else:
        checks["rng_ledger_checked"] = True
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    base["checks"] = {"ok": checks["ok"], "checks": checks}
    base["runtime_samples"] = [item for item in (explicit, missing, invalid) if item]
    return base


def _p3_summon_target_expression_backlog_split_row(
    rules: RuleBook,
    expressions: tuple[TargetExpressionIR, ...],
    global_config: dict[str, Any],
) -> dict[str, JSONValue]:
    subrows: list[dict[str, JSONValue]] = []
    global_aliases = set(global_config["aliases"])
    global_operations = set(global_config["operations"])
    for alias in P3_TARGET_ALIASES:
        exprs = tuple(item for item in expressions if item.alias == alias)
        subrows.append(_subrow_for_expressions("alias", alias, exprs, 1 if alias in global_aliases else 0))
    for operation in P3_TARGET_OPERATIONS:
        exprs = tuple(item for item in expressions if _source_operation(item) == operation or item.alias.endswith(f".{operation}"))
        subrows.append(_subrow_for_expressions("operation", operation, exprs, 1 if operation in global_operations else 0))
    classification_counts = Counter(str(row["classification"]) for row in subrows)
    blocked_count = sum(int(row["blocked_count"]) for row in subrows)
    classification = "admission_gap" if blocked_count else "executable"
    checks = {
        "required_alias_subrows_present": {
            str(row["name"]) for row in subrows if row["kind"] == "alias"
        }
        == set(P3_TARGET_ALIASES),
        "required_operation_subrows_present": {
            str(row["name"]) for row in subrows if row["kind"] == "operation"
        }
        == set(P3_TARGET_OPERATIONS),
        "no_unclassified_subrows": not any(row["classification"] == "unclassified" for row in subrows),
        "split_not_single_bucket": len(subrows) == len(P3_TARGET_ALIASES) + len(P3_TARGET_OPERATIONS),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        "p3_summon_target_expression_backlog_split",
        classification=classification,
        checks=checks,
        raw_count=sum(int(row["raw_count"]) for row in subrows),
        ir_count=sum(int(row["ir_count"]) for row in subrows),
        rulebook_visible_count=sum(int(row["rulebook_visible_count"]) for row in subrows),
        executable_count=sum(int(row["executable_count"]) for row in subrows),
        blocked_or_gap_count=blocked_count,
        gap_attribution={"admission_gap": blocked_count} if blocked_count else {},
        details={
            "subrows": subrows,
            "classification_counts": dict(sorted(classification_counts.items())),
        },
    )


def _target_expression_bucket_row(
    rules: RuleBook,
    row_id: str,
    expressions: Iterable[TargetExpressionIR],
    *,
    required: bool,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    exprs = tuple(expressions)
    coverage_counts = Counter(item.coverage_status for item in exprs)
    executable_count = int(coverage_counts.get("executable", 0))
    blocked_count = len(exprs) - executable_count
    if not exprs:
        classification = "validation_gap" if required else "source_absent_not_required"
    elif blocked_count:
        classification = "admission_gap"
    else:
        classification = "executable"
    visible = sum(1 for item in exprs if rules.target_expression(item.target_expression_id) is item)
    checks = {
        "expressions_present_or_not_required": bool(exprs) or not required,
        "rulebook_visible": visible == len(exprs),
        "sample_sources_present": all(bool(_source(item)) for item in _samples_by_coverage(exprs).values()),
        "classification_has_gap_when_blocked": blocked_count == 0 or classification in GAP_STATES,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return _row(
        row_id,
        classification=classification,
        checks=checks,
        raw_count=len(exprs),
        ir_count=len(exprs),
        rulebook_visible_count=visible,
        executable_count=executable_count,
        blocked_or_gap_count=blocked_count if classification in GAP_STATES else 0,
        gap_attribution={classification: blocked_count} if classification in GAP_STATES and blocked_count else {},
        sample_source_trace=_source(_first(exprs)),
        details={
            **(details or {}),
            "coverage_counts": dict(sorted(coverage_counts.items())),
            "kind_counts": _kind_counts(exprs),
            "alias_counts_top": _counter_top(Counter(item.alias for item in exprs if item.alias), 20),
            "blocked_reason_counts_top": _counter_top(Counter(item.blocked_reason for item in exprs if item.blocked_reason), 20),
            "sample_by_coverage": {
                key: _expression_sample(value) for key, value in sorted(_samples_by_coverage(exprs).items())
            },
        },
    )


def _subrow_for_expressions(kind: str, name: str, expressions: tuple[TargetExpressionIR, ...], raw_count: int) -> dict[str, JSONValue]:
    coverage_counts = Counter(item.coverage_status for item in expressions)
    executable = int(coverage_counts.get("executable", 0))
    blocked = len(expressions) - executable
    if expressions and not blocked:
        classification = "executable"
    elif expressions or raw_count:
        classification = "admission_gap"
    else:
        classification = "source_absent_not_required"
    return {
        "kind": kind,
        "name": name,
        "raw_count": raw_count,
        "ir_count": len(expressions),
        "rulebook_visible_count": len(expressions),
        "executable_count": executable,
        "blocked_count": blocked,
        "classification": classification,
        "coverage_counts": dict(sorted(coverage_counts.items())),
        "sample_expression_id": expressions[0].target_expression_id if expressions else "",
        "sample_blocked_reason": next((item.blocked_reason for item in expressions if item.blocked_reason), ""),
    }


def _global_target_config(tbgd_root: Path) -> dict[str, Any]:
    alias_config = _read_json_object(tbgd_root / "Config" / "GlobalConfig" / "TargetAliasConfig.json")
    operation_config = _read_json_object(tbgd_root / "Config" / "GlobalConfig" / "TargetOperationConfig.json")
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


def _registry_fetch_positive(expressions: tuple[TargetExpressionIR, ...]) -> dict[str, JSONValue]:
    state = _target_validation_state()
    for expression in expressions:
        if expression.coverage_status != "executable":
            continue
        raw = _raw_payload(expression)
        if expression.expression_kind == "TargetFetchPartner":
            name = str(raw.get("Name") or "")
            registry = {"ally:caster": "ally:two"}
            if name:
                registry[name] = "ally:two"
                registry[f"ally:caster:{name}"] = "ally:two"
            result = _resolve_expression(
                expression,
                replace(state, global_flags={**state.global_flags, "target_partner_registry": registry}),
            )
        elif expression.expression_kind == "TargetFetchUniqueNameEntity":
            unique_name = str(raw.get("UniqueName") or "")
            if not unique_name:
                continue
            result = _resolve_expression(
                expression,
                replace(state, global_flags={**state.global_flags, "target_unique_entity_registry": {unique_name: "enemy:mid"}}),
            )
        else:
            continue
        if result.ok:
            return {
                "case": "registry_fetch_positive",
                "expression": _expression_sample(expression),
                "resolution": result.to_json(),
            }
    return {}


def _registry_fetch_negative(expressions: tuple[TargetExpressionIR, ...]) -> dict[str, JSONValue]:
    state = _target_validation_state()
    for expression in expressions:
        if expression.coverage_status != "executable":
            continue
        raw = _raw_payload(expression)
        if expression.expression_kind == "TargetFetchPartner":
            result = _resolve_expression(
                expression,
                replace(state, global_flags={**state.global_flags, "target_partner_registry": {"default": "ally:two"}}),
            )
        elif expression.expression_kind == "TargetFetchUniqueNameEntity":
            if not str(raw.get("UniqueName") or ""):
                continue
            result = _resolve_expression(
                expression,
                replace(state, global_flags={**state.global_flags, "target_unique_entity_registry": {"default": "enemy:mid"}}),
            )
        else:
            continue
        if not result.ok:
            return {
                "case": "registry_fetch_wrong_key_negative",
                "expression": _expression_sample(expression),
                "blocked": True,
                "resolution": result.to_json(),
            }
    return {}


def _first_successful_resolution(
    expressions: tuple[TargetExpressionIR, ...],
    *,
    state: BattleState,
    owner_id: str = "ally:caster",
) -> dict[str, JSONValue]:
    for expression in expressions:
        if expression.coverage_status != "executable":
            continue
        result = _resolve_expression(expression, state, owner_id=owner_id)
        if result.ok:
            return {
                "expression": _expression_sample(expression),
                "resolution": result.to_json(),
            }
    return {}


def _random_resolution(
    expressions: tuple[TargetExpressionIR, ...],
    *,
    event_payload: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    for expression in expressions:
        if expression.coverage_status != "executable":
            continue
        result = _resolve_expression(expression, _target_validation_state(), event_payload=event_payload)
        if result.ok or result.blocked_reason in {"requires_rng_choice", "target_random_choice_invalid"}:
            payload = result.to_json()
            return {
                "expression": _expression_sample(expression),
                "ok": result.ok,
                "blocked_reason": result.blocked_reason,
                "rng_events": payload.get("rng_events", []),
                "resolution": payload,
            }
    return {}


def _resolve_expression(
    expression: TargetExpressionIR,
    state: BattleState,
    *,
    owner_id: str = "ally:caster",
    event_payload: dict[str, JSONValue] | None = None,
):
    return TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:caster",
        owner_id=owner_id,
        param_entity_id="enemy:left",
        current_action_target_id="enemy:left",
        target_resolution=_target_resolution(("enemy:left",)),
        event_payload=event_payload or _event_payload(),
        dynamic_values={"MaxNumber": 1.0, "DynamicMaxNumber": 1.0},
    )


def _action_state(actor_template_id: str) -> BattleState:
    return BattleState(
        units={
            "ally:target_actor": UnitState(
                unit_id="ally:target_actor",
                side="ally",
                template_id=actor_template_id,
                level=80,
                max_hp=3000.0,
                hp=3000.0,
                attack=1000.0,
                defense=500.0,
                speed=100.0,
                energy=100.0,
                max_energy=100.0,
            ),
            "enemy:target_probe": UnitState(
                unit_id="enemy:target_probe",
                side="enemy",
                template_id="validation:target_probe",
                level=80,
                max_hp=100000.0,
                hp=100000.0,
                attack=100.0,
                defense=100.0,
                speed=100.0,
                toughness=120.0,
                max_toughness=120.0,
                flags={"weaknesses": ["Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"]},
            ),
        },
        skill_points=5,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle", "turn_owner_id": "ally:target_actor"},
    )


def _target_validation_state() -> BattleState:
    return BattleState(
        units={
            "ally:caster": UnitState(
                unit_id="ally:caster",
                side="ally",
                template_id="avatar:validation:caster",
                hp=1000.0,
                max_hp=1000.0,
                toughness=80.0,
                max_toughness=100.0,
                flags={"position": 1},
            ),
            "ally:two": UnitState(
                unit_id="ally:two",
                side="ally",
                template_id="avatar:validation:two",
                hp=600.0,
                max_hp=1000.0,
                toughness=40.0,
                max_toughness=100.0,
                flags={"position": 2},
            ),
            "enemy:left": UnitState(
                unit_id="enemy:left",
                side="enemy",
                template_id="monster:validation:left",
                hp=300.0,
                max_hp=1000.0,
                toughness=20.0,
                max_toughness=100.0,
                flags={"position": 1},
            ),
            "enemy:mid": UnitState(
                unit_id="enemy:mid",
                side="enemy",
                template_id="monster:validation:mid",
                hp=800.0,
                max_hp=1000.0,
                toughness=50.0,
                max_toughness=100.0,
                flags={"position": 2},
            ),
            "enemy:right": UnitState(
                unit_id="enemy:right",
                side="enemy",
                template_id="monster:validation:right",
                hp=100.0,
                max_hp=1000.0,
                toughness=10.0,
                max_toughness=100.0,
                flags={"position": 3},
            ),
            "summon:servant": UnitState(
                unit_id="summon:servant",
                side="summon",
                template_id="servant:validation",
                hp=500.0,
                max_hp=500.0,
                speed=100.0,
                flags={
                    "position": 2,
                    "team_side": "ally",
                    "summon_kind": "servant",
                    "owner_id": "ally:caster",
                    "servant_definition_id": "servant_definition:validation",
                },
            ),
            "summon:last": UnitState(
                unit_id="summon:last",
                side="summon",
                template_id="monster:validation:last_summon",
                hp=500.0,
                max_hp=500.0,
                toughness=30.0,
                max_toughness=60.0,
                flags={"position": 4, "team_side": "enemy", "summon_kind": "summoned_monster", "owner_id": "enemy:mid"},
            ),
        },
        skill_points=3,
        max_skill_points=5,
        global_flags={
            "target_partner_registry": {
                "ally:caster": "ally:two",
                "validation_partner": "ally:two",
                "ally:caster:validation_partner": "ally:two",
            },
            "summon_runtime": {
                "schema_version": SUMMON_RUNTIME_SCHEMA_VERSION,
                "last_summon_monsters": ["summon:last"],
                "by_owner": {"ally:caster": ["summon:servant"], "enemy:mid": ["summon:last"]},
                "entities": {
                    "summon:servant": {
                        "summon_kind": "servant",
                        "owner_id": "ally:caster",
                        "source_intent_id": "servant_definition:validation",
                        "source_trace": {"source_path": "validation", "raw_type": "ServantDefinitionIR", "raw_id": "validation"},
                        "removed_event_index": None,
                    },
                    "summon:last": {
                        "summon_kind": "summoned_monster",
                        "owner_id": "enemy:mid",
                        "source_intent_id": "summon_intent:validation:last",
                        "source_trace": {"source_path": "validation", "raw_type": "SummonMonsterIntent", "raw_id": "last"},
                        "removed_event_index": None,
                    },
                },
                "servants": {
                    "summon:servant": {
                        "unit_id": "summon:servant",
                        "servant_definition_id": "servant_definition:validation",
                        "servant_ref": "servant:validation",
                        "owner_id": "ally:caster",
                        "source_trace": {"source_path": "validation", "raw_type": "ServantDefinitionIR", "raw_id": "validation"},
                        "removed_event_index": None,
                    }
                },
                "last_servants": ["summon:servant"],
            },
        },
    )


def _with_unit_flags(state: BattleState, unit_id: str, flags: dict[str, Any]) -> BattleState:
    unit = state.units[unit_id]
    merged = dict(unit.flags)
    for key, value in flags.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    units = dict(state.units)
    units[unit_id] = replace(unit, flags=merged)
    return replace(state, units=units)


def _target_resolution(target_ids: tuple[str, ...]) -> TargetResolution:
    return TargetResolution(
        requested=target_ids,
        legal=target_ids,
        selected=target_ids,
        rejected=(),
        reason="validation_target",
        source="validate_p4_s4_target_query_admission",
    )


def _event_payload() -> dict[str, JSONValue]:
    return {
        "param_entity_ids": ["enemy:left", "enemy:mid"],
        "param_entity_list": ["enemy:left", "enemy:mid"],
        "target_id": "enemy:left",
    }


def _command_from_choice(choice: ActionChoice, target_ids: tuple[str, ...]) -> ActionCommand:
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=target_ids,
        source="manual",
        metadata={"p4_s4_selected_from_availability": True},
    )


def _source_domain(expression: TargetExpressionIR) -> str:
    path = expression.source.source_path
    if path.startswith("Config/ConfigAbility/Avatar/"):
        return "character_ability"
    if path.startswith("Config/ConfigAbility/Monster/"):
        return "monster_ability"
    if path.startswith("Config/GlobalConfig/"):
        return "global_config"
    return "other"


def _is_summon_servant_expression(expression: TargetExpressionIR) -> bool:
    alias = expression.alias
    kind = expression.expression_kind
    if alias in SUMMON_SERVANT_ALIASES:
        return True
    lowered = f"{alias} {kind} {expression.target_expression_id}".lower()
    return "servant" in lowered or "summon" in lowered


def _is_global_or_dot_alias_expression(expression: TargetExpressionIR) -> bool:
    if _source_domain(expression) == "global_config":
        return True
    if expression.alias and "." in expression.alias:
        return True
    return bool(_source_operation(expression))


def _is_sort_filter_retarget_expression(expression: TargetExpressionIR) -> bool:
    kind = expression.expression_kind
    return kind in PIPELINE_KINDS or kind.startswith("TargetSort")


def _expression_has_random(expression: TargetExpressionIR) -> bool:
    if expression.expression_kind == "TargetShuffle":
        return True
    return _raw_has_key_value(_raw_payload(expression), "ByRandom", True)


def _raw_has_key_value(value: Any, key: str, expected: Any) -> bool:
    if isinstance(value, dict):
        if value.get(key) == expected:
            return True
        return any(_raw_has_key_value(child, key, expected) for child in value.values())
    if isinstance(value, list):
        return any(_raw_has_key_value(child, key, expected) for child in value)
    return False


def _raw_payload(expression: TargetExpressionIR) -> dict[str, JSONValue]:
    raw = expression.payload.get("raw") if isinstance(expression.payload, dict) else None
    return raw if isinstance(raw, dict) else {}


def _source_operation(expression: TargetExpressionIR) -> str:
    evidence = expression.source.evidence
    return str(evidence.get("operation") or evidence.get("target_operation") or "")


def _raw_field_counts(expressions: tuple[TargetExpressionIR, ...], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(_raw_payload(item).get(field) or "") for item in expressions).items()))


def _kind_counts(expressions: Iterable[TargetExpressionIR]) -> dict[str, int]:
    return dict(sorted(Counter(item.expression_kind for item in expressions).items()))


def _samples_by_coverage(expressions: Iterable[TargetExpressionIR]) -> dict[str, TargetExpressionIR]:
    samples: dict[str, TargetExpressionIR] = {}
    for expression in expressions:
        samples.setdefault(expression.coverage_status, expression)
    return samples


def _expression_sample(expression: TargetExpressionIR | None) -> dict[str, JSONValue]:
    if expression is None:
        return {}
    return {
        "target_expression_id": expression.target_expression_id,
        "expression_kind": expression.expression_kind,
        "alias": expression.alias,
        "coverage_status": expression.coverage_status,
        "blocked_reason": expression.blocked_reason,
        "source": expression.source.to_json(),
    }


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
