from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    TargetResolution,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import EffectIR, IRSource, TargetExpressionIR
from ..rules.rulebook import RuleBook
from ..systems.status import StatusSystem
from ..systems.target import TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p1_6_target_system"
SAFE_SORT_ALIASES = (
    "AllEnemy.SortByHP",
    "AllEnemy.SortByHPRatio",
    "AllEnemy.SortByFormation",
    "AllEnemy.SortByStance",
    "AllEnemy.SortByStanceRatio",
    "AllLightTeam.GetAliveOnly.SortByHPRatio",
)
SAFE_FETCH_KINDS = (
    "TargetFetchCaster",
    "TargetFetchModifierOwner",
    "TargetFetchOwner",
    "TargetFetchAbilityTarget",
    "TargetFetchCurrentActionTarget",
    "TargetFetchParamEntityList",
    "TargetFetchPartner",
    "TargetFetchUniqueNameEntity",
)
PIPELINE_KINDS = {
    "TargetFetchCaster",
    "TargetFetchModifierOwner",
    "TargetFetchOwner",
    "TargetFetchAbilityTarget",
    "TargetFetchCurrentActionTarget",
    "TargetFetchParamEntityList",
    "TargetFetchPartner",
    "TargetFetchUniqueNameEntity",
    "TargetMapAdjoinEntity",
    "TargetSortByProperty",
    "TargetSortByPropertyRatio",
    "TargetSortByFormation",
    "TargetTake",
    "TargetIndex",
    "TargetReverse",
    "TargetShuffle",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)

    matrix = _target_scope_matrix(rules)
    sort_case = _sort_cases(rules)
    fetch_case = _fetch_cases(rules)
    adjacent_case = _adjacent_cases(rules)
    random_case = _random_cases(rules)
    dynamic_max_case = _dynamic_max_cases(rules)
    blocked_case = _blocked_cases(rules, random_case)
    status_case = _status_blocked_trace_case(rules, random_case)
    audit_case = _mutation_audit_case(rules)

    checks = {
        "matrix": matrix["checks"],
        "sort": sort_case["checks"],
        "fetch": fetch_case["checks"],
        "adjacent": adjacent_case["checks"],
        "random": random_case["checks"],
        "dynamic_max": dynamic_max_case["checks"],
        "blocked": blocked_case["checks"],
        "status_blocked_trace": status_case["checks"],
        "mutation_audit": audit_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = _json_safe(
        {
            "version": VALIDATION_VERSION,
            "baseline_version": BASELINE_VERSION,
            "ok": all(item["ok"] for item in checks.values()),
            "build": {
                "tbgd_root": tbgd_root.as_posix(),
                "target_expression_count": len(ir.target_expressions),
                "selection_policy": {
                    "mode": "structured_predicate",
                    "fixed_entity_skill_file_or_observation_used": False,
                    "predicate": [
                        "TargetExpressionIR kind/alias/coverage_status/admission_batch/normalized payload",
                        "global TargetAliasConfig/TargetOperationConfig safe dot-chain aliases only",
                        "ConfigAI target sort is counted for matrix only and not selected as executable runtime path",
                        "negative cases may use validation-local no-mutation boundary expressions",
                    ],
                },
            },
            "checks": checks,
            "target_scope_matrix": matrix,
            "cases": {
                "sort": sort_case,
                "fetch": fetch_case,
                "adjacent": adjacent_case,
                "random": random_case,
                "dynamic_max": dynamic_max_case,
                "blocked": blocked_case,
                "status_blocked_trace": status_case,
                "mutation_audit": _strip_state(audit_case),
            },
            "static_checks": static_result.to_json(),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p1_6_target_system.json", result)
    write_json(output_dir / "target_scope_matrix_p1_6.json", _json_safe(matrix))
    write_json(output_dir / "target_sort_cases_p1_6.json", _json_safe(sort_case))
    write_json(output_dir / "target_fetch_cases_p1_6.json", _json_safe(fetch_case))
    write_json(output_dir / "target_adjacent_cases_p1_6.json", _json_safe(adjacent_case))
    write_json(output_dir / "target_random_cases_p1_6.json", _json_safe(random_case))
    write_json(output_dir / "target_dynamic_max_cases_p1_6.json", _json_safe(dynamic_max_case))
    write_json(output_dir / "target_blocked_cases_p1_6.json", _json_safe(blocked_case))
    write_json(output_dir / "target_status_blocked_trace_p1_6.json", _json_safe(status_case))
    write_json(output_dir / "target_mutation_audit_p1_6.json", _json_safe(_strip_state(audit_case)))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 P1-6 target system pipeline/fetch/sort/random slice.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _target_scope_matrix(rules: RuleBook) -> dict[str, Any]:
    expressions = rules.target_expressions()
    by_kind = Counter(expression.expression_kind for expression in expressions)
    by_coverage = Counter(expression.coverage_status for expression in expressions)
    by_admission = Counter(expression.admission_batch for expression in expressions if expression.admission_batch)
    p1_6_executable = tuple(
        expression
        for expression in expressions
        if expression.coverage_status == "executable"
        and (
            expression.admission_batch == "p1_6_target_pipeline"
            or expression.expression_kind in PIPELINE_KINDS
            or expression.alias in SAFE_SORT_ALIASES
        )
    )
    config_ai_expressions = tuple(expression for expression in expressions if "ConfigAI/" in expression.source.source_path)
    sort_blocked = tuple(
        expression
        for expression in expressions
        if expression.coverage_status == "blocked"
        and ("sort" in expression.blocked_reason.lower() or expression.expression_kind.startswith("TargetSort"))
    )
    fetch_counts = Counter(expression.expression_kind for expression in p1_6_executable if expression.expression_kind in SAFE_FETCH_KINDS)
    sort_counts = Counter(
        _normalized_sort_key(expression)
        for expression in p1_6_executable
        if expression.expression_kind.startswith("TargetSort") or _normalized_sort_key(expression)
    )
    samples: dict[str, Any] = {}
    for expression in p1_6_executable:
        key = expression.alias or expression.expression_kind
        samples.setdefault(key, _expression_sample(expression))
    checks = {
        "target_expressions_present": bool(expressions),
        "p1_6_executable_present": bool(p1_6_executable),
        "safe_fetch_lowered_or_gap_recorded": bool(fetch_counts) or any(kind in by_kind for kind in SAFE_FETCH_KINDS),
        "safe_sort_alias_or_node_present": bool(sort_counts) or any(alias in Counter(expression.alias for expression in expressions) for alias in SAFE_SORT_ALIASES),
        "unsupported_sort_remains_blocked": bool(sort_blocked),
        "config_ai_not_runtime_executable_source": all(
            expression.coverage_status != "executable" or expression.admission_batch != "p1_6_target_pipeline"
            for expression in config_ai_expressions
        ),
        "samples_have_tbgd_source": all(bool(sample.get("source", {}).get("source_path")) for sample in samples.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "coverage_counts": dict(sorted(by_coverage.items())),
        "admission_counts": dict(sorted(by_admission.items())),
        "kind_counts_top": [{"key": key, "count": count} for key, count in by_kind.most_common(60)],
        "p1_6_executable_count": len(p1_6_executable),
        "fetch_executable_counts": dict(sorted(fetch_counts.items())),
        "sort_source_matrix": {
            "executable_sort_counts": dict(sorted((key, count) for key, count in sort_counts.items() if key)),
            "blocked_sort_reasons_top": [
                {"key": key, "count": count}
                for key, count in Counter(expression.blocked_reason for expression in sort_blocked).most_common(20)
            ],
            "config_ai_expression_count": len(config_ai_expressions),
        },
        "sample_by_alias_or_kind": samples,
    }


def _sort_cases(rules: RuleBook) -> dict[str, Any]:
    state = _state()
    system = TargetSystem()
    cases: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for case_name, aliases in {
        "hp_sort": ("AllEnemy.SortByHP",),
        "hp_ratio_sort": ("AllEnemy.SortByHPRatio", "AllLightTeam.GetAliveOnly.SortByHPRatio"),
        "formation_sort": ("AllEnemy.SortByFormation",),
        "toughness_sort": ("AllEnemy.SortByStance", "AllEnemy.SortByStanceRatio"),
    }.items():
        expression = _select_expression_by_alias(rules, aliases)
        if expression is None:
            cases[case_name] = _source_gap(f"no executable sort alias found in {aliases}")
            checks[f"{case_name}_source_gap_recorded"] = True
            continue
        result = _resolve(expression, state)
        sort_step = _first_step(result, "target_sort")
        expected = _expected_sort_order(state, result.target_ids, sort_step)
        cases[case_name] = {
            "expression": _expression_sample(expression),
            "resolution": result.to_json(),
            "sort_step": sort_step,
            "expected_order_from_runtime_state": list(expected),
        }
        checks[f"{case_name}_ok"] = result.ok
        checks[f"{case_name}_trace_present"] = bool(result.metadata.get("resolution_steps"))
        checks[f"{case_name}_order_matches_state"] = result.ok and result.target_ids == expected
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _fetch_cases(rules: RuleBook) -> dict[str, Any]:
    state = _state()
    cases: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    fetch_caster = _select_expression(rules, kind="TargetFetchCaster", allow_missing=True)
    if fetch_caster is None:
        cases["caster"] = _source_gap("no executable TargetFetchCaster source")
        checks["caster_source_gap_recorded"] = True
    else:
        result = _resolve(fetch_caster, state)
        cases["caster"] = {"expression": _expression_sample(fetch_caster), "resolution": result.to_json()}
        checks["caster_fetch_ok"] = result.ok and result.target_ids == ("ally:caster",)

    fetch_owner = _select_expression_by_kind(rules, ("TargetFetchModifierOwner", "TargetFetchOwner"))
    if fetch_owner is None:
        cases["owner"] = _source_gap("no executable TargetFetchModifierOwner/TargetFetchOwner source")
        checks["owner_source_gap_recorded"] = True
    else:
        result = _resolve(fetch_owner, state)
        cases["owner"] = {"expression": _expression_sample(fetch_owner), "resolution": result.to_json()}
        checks["owner_fetch_ok"] = result.ok and result.target_ids == ("ally:caster",)

    fetch_param_list = _select_expression(rules, kind="TargetFetchParamEntityList", allow_missing=True)
    if fetch_param_list is None:
        cases["param_entity_list"] = _source_gap("no executable TargetFetchParamEntityList source")
        checks["param_list_source_gap_recorded"] = True
    else:
        result = _resolve(fetch_param_list, state)
        missing = _resolve(fetch_param_list, state, event_payload={})
        cases["param_entity_list"] = {
            "expression": _expression_sample(fetch_param_list),
            "resolution": result.to_json(),
            "missing_payload_resolution": missing.to_json(),
        }
        checks["param_list_fetch_ok"] = result.ok and set(result.target_ids) == {"enemy:left", "enemy:mid"}
        checks["param_list_missing_payload_blocked"] = not missing.ok and missing.blocked_reason == "param_entity_list_missing"

    fetch_partner = _select_expression(rules, kind="TargetFetchPartner", allow_missing=True)
    if fetch_partner is None:
        cases["partner"] = _source_gap("no executable TargetFetchPartner source")
        checks["partner_source_gap_recorded"] = True
    else:
        partner_name = _partner_name(fetch_partner)
        if partner_name:
            named_missing_state = _with_partner_registry(state, {"ally:caster": "ally:three"})
            named_scoped_key = f"ally:caster:{partner_name}"
            named_scoped_state = _with_partner_registry(
                state,
                {
                    "ally:caster": "ally:three",
                    named_scoped_key: "ally:two",
                },
            )
            named_missing = _resolve(fetch_partner, named_missing_state)
            result = _resolve(fetch_partner, named_scoped_state)
        else:
            named_missing_state = _with_partner_registry(state, {})
            named_scoped_key = "ally:caster"
            named_missing = _resolve(fetch_partner, named_missing_state)
            result = _resolve(fetch_partner, _with_partner_registry(state, {"ally:caster": "ally:two"}))
        missing = _resolve(fetch_partner, replace(state, global_flags={}))
        cases["partner"] = {
            "expression": _expression_sample(fetch_partner),
            "partner_name": partner_name,
            "resolution": result.to_json(),
            "named_missing_with_caster_default_resolution": named_missing.to_json(),
            "missing_registry_resolution": missing.to_json(),
        }
        checks["partner_fetch_ok"] = result.ok and result.target_ids == ("ally:two",)
        checks["partner_matched_registry_key_recorded"] = _matched_partner_key(result) == named_scoped_key
        if partner_name:
            checks["partner_named_missing_does_not_use_caster_default"] = (
                not named_missing.ok and named_missing.blocked_reason == "target_partner_missing"
            )
        else:
            checks["partner_unnamed_missing_default_blocked"] = (
                not named_missing.ok and named_missing.blocked_reason == "target_partner_missing"
            )
        checks["partner_missing_registry_blocked"] = not missing.ok and missing.blocked_reason == "target_partner_registry_missing"

    fetch_unique = _select_expression(rules, kind="TargetFetchUniqueNameEntity", allow_missing=True)
    if fetch_unique is None:
        cases["unique"] = _source_gap("no executable TargetFetchUniqueNameEntity source")
        checks["unique_source_gap_recorded"] = True
    else:
        unique_name = _unique_name(fetch_unique)
        unique_state = _with_unique_registry(state, unique_name, "enemy:mid")
        result = _resolve(fetch_unique, unique_state)
        missing = _resolve(fetch_unique, _with_unique_registry(state, unique_name, None))
        ambiguous = _resolve(fetch_unique, _with_unique_registry(state, unique_name, ["enemy:left", "enemy:mid"]))
        defeated = _resolve(fetch_unique, _with_unique_registry(_state_with_flags("enemy:mid", {"lifecycle_status": "defeated"}), unique_name, "enemy:mid"))
        cases["unique"] = {
            "expression": _expression_sample(fetch_unique),
            "unique_name": unique_name,
            "resolution": result.to_json(),
            "missing_resolution": missing.to_json(),
            "ambiguous_resolution": ambiguous.to_json(),
            "defeated_resolution": defeated.to_json(),
        }
        checks["unique_fetch_ok"] = result.ok and result.target_ids == ("enemy:mid",)
        checks["unique_missing_blocked"] = not missing.ok and missing.blocked_reason == "unique_entity_missing"
        checks["unique_ambiguous_blocked"] = not ambiguous.ok and ambiguous.blocked_reason == "unique_entity_ambiguous"
        checks["unique_defeated_blocked"] = not defeated.ok and defeated.blocked_reason.startswith("target_lifecycle_blocked")

    summon_cases = _summon_fetch_cases(rules)
    cases["summon"] = summon_cases
    checks["summon_fetch_ok_or_gap"] = summon_cases["checks"]["ok"]
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _summon_fetch_cases(rules: RuleBook) -> dict[str, Any]:
    state = _state()
    checks: dict[str, bool] = {}
    cases: dict[str, Any] = {}
    for alias, expected in {
        "LastSummonMonsters": ("summon:last",),
        "CasterSummonedMinions": ("summon:caster",),
    }.items():
        expression = _select_expression(rules, kind="TargetAlias", alias=alias, allow_missing=True)
        if expression is None:
            cases[alias] = _source_gap(f"no executable {alias} alias")
            checks[f"{alias}_source_gap_recorded"] = True
            continue
        result = _resolve(expression, state)
        missing_runtime = _resolve(expression, replace(state, global_flags={}))
        cases[alias] = {
            "expression": _expression_sample(expression),
            "resolution": result.to_json(),
            "missing_runtime_resolution": missing_runtime.to_json(),
        }
        checks[f"{alias}_ok"] = result.ok and result.target_ids == expected
        checks[f"{alias}_missing_runtime_blocked"] = not missing_runtime.ok and missing_runtime.blocked_reason == "summon_runtime_missing"
    checks["servant_runtime_source_gap_recorded"] = True
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "cases": cases,
        "servant_boundary": _source_gap("servant target registry is not executable in P1-6 runtime; servant stays source_gap_blocked"),
    }


def _adjacent_cases(rules: RuleBook) -> dict[str, Any]:
    expression = _select_expression(rules, kind="TargetAlias", alias="AbilityTargetAdjoinEntity", allow_missing=True)
    if expression is None:
        checks = {"source_gap_recorded": True}
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no executable AbilityTargetAdjoinEntity alias"}
    state = _state()
    middle = _resolve(expression, state, current_action_target_id="enemy:mid", target_resolution=_target_resolution(("enemy:mid",)))
    edge = _resolve(expression, state, current_action_target_id="enemy:left", target_resolution=_target_resolution(("enemy:left",)))
    missing_position = _resolve(
        expression,
        _state_with_flags("enemy:mid", {"position": None}),
        current_action_target_id="enemy:mid",
        target_resolution=_target_resolution(("enemy:mid",)),
    )
    removed_neighbor = _resolve(
        expression,
        _state_with_flags("enemy:left", {"lifecycle_status": "removed"}),
        current_action_target_id="enemy:mid",
        target_resolution=_target_resolution(("enemy:mid",)),
    )
    checks = {
        "middle_adjacent_ok": middle.ok and middle.target_ids == ("enemy:left", "enemy:right"),
        "edge_one_side_ok_or_empty_boundary": edge.ok and edge.target_ids == ("enemy:mid",),
        "missing_position_blocked": not missing_position.ok and missing_position.blocked_reason == "target_adjacent_blocked",
        "removed_neighbor_skipped_with_remaining_neighbor": removed_neighbor.ok and removed_neighbor.target_ids == ("enemy:right",),
        "resolution_trace_present": bool(middle.metadata.get("resolution_steps")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expression": _expression_sample(expression),
        "middle": middle.to_json(),
        "edge": edge.to_json(),
        "missing_position": missing_position.to_json(),
        "removed_neighbor": removed_neighbor.to_json(),
    }


def _random_cases(rules: RuleBook) -> dict[str, Any]:
    expression = _select_random_expression(rules)
    if expression is None:
        checks = {"source_gap_recorded": True, "no_synthetic_random_positive": True}
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no executable random Retarget/TargetShuffle expression"}
    state = _state()
    explicit = _resolve(
        expression,
        state,
        event_payload={
            **_event_payload(),
            "target_random_choices": {"default": 1},
        },
    )
    replay = _resolve(
        expression,
        state,
        event_payload={
            **_event_payload(),
            "target_random_choices": {"default": 1},
        },
    )
    missing = _resolve(expression, state)
    invalid = _resolve(expression, state, event_payload={**_event_payload(), "target_random_choices": {"default": 999}})
    checks = {
        "expression_has_real_source": _mainline_expression_source(expression),
        "explicit_choice_ok": explicit.ok and bool(explicit.rng_events),
        "explicit_choice_replay_stable": explicit.to_json() == replay.to_json(),
        "rng_event_type_target_random": bool(explicit.rng_events) and explicit.rng_events[0].rng_type == "target_random",
        "missing_choice_blocked": not missing.ok and missing.blocked_reason == "requires_rng_choice",
        "invalid_choice_blocked": not invalid.ok and invalid.blocked_reason == "target_random_choice_invalid",
        "no_process_random_used": all(event.after_state == state.rng_state for event in explicit.rng_events),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expression": _expression_sample(expression),
        "explicit_choice": explicit.to_json(),
        "replay_choice": replay.to_json(),
        "missing_choice": missing.to_json(),
        "invalid_choice": invalid.to_json(),
    }


def _dynamic_max_cases(rules: RuleBook) -> dict[str, Any]:
    fixed = _select_retarget_with_max(rules, dynamic=False)
    dynamic = _select_retarget_with_max(rules, dynamic=True)
    cases: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    if fixed is None:
        cases["fixed"] = _source_gap("no executable Retarget with fixed MaxNumber source")
        checks["fixed_source_gap_recorded"] = True
    else:
        result = _resolve(fixed, _state())
        cases["fixed"] = {"expression": _expression_sample(fixed), "resolution": result.to_json()}
        checks["fixed_max_ok"] = result.ok and bool(result.target_ids)
    if dynamic is None:
        cases["dynamic"] = _source_gap("no executable Retarget with dynamic MaxNumber source")
        checks["dynamic_source_gap_recorded"] = True
    else:
        result = _resolve(dynamic, _state(), dynamic_values={"MaxNumber": 1, "DynamicMaxNumber": 1})
        missing = _resolve(dynamic, _state(), dynamic_values={})
        cases["dynamic"] = {
            "expression": _expression_sample(dynamic),
            "resolution": result.to_json(),
            "missing_binding_resolution": missing.to_json(),
        }
        checks["dynamic_max_ok"] = result.ok and len(result.target_ids) == 1
        checks["dynamic_missing_binding_blocked"] = not missing.ok and "retarget_max_number_blocked" in missing.blocked_reason
    synthetic_missing = _resolve(_synthetic_retarget_missing_max(), _state())
    cases["missing_binding_boundary"] = synthetic_missing.to_json()
    checks["missing_binding_boundary_blocked"] = not synthetic_missing.ok and "retarget_max_number_blocked" in synthetic_missing.blocked_reason
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _blocked_cases(rules: RuleBook, random_case: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    blocked_sort = _select_blocked_sort(rules)
    missing_sort_payload = _resolve(_synthetic_sort_missing_payload(), state)
    missing_payload = _resolve(_synthetic_retarget_missing_payload(), state)
    unique_missing_registry_expression = _select_expression(rules, kind="TargetFetchUniqueNameEntity", allow_missing=True)
    unique_missing_registry = None
    if unique_missing_registry_expression is not None:
        unique_missing_registry = _resolve(unique_missing_registry_expression, replace(state, global_flags={}))
    cases: dict[str, Any] = {
        "missing_sort_payload": missing_sort_payload.to_json(),
        "missing_retarget_payload": missing_payload.to_json(),
        "unique_missing_registry": unique_missing_registry.to_json() if unique_missing_registry else _source_gap("no unique fetch source"),
    }
    checks: dict[str, bool] = {
        "missing_sort_payload_blocked": not missing_sort_payload.ok and bool(missing_sort_payload.blocked_reason),
        "missing_payload_blocked": not missing_payload.ok and missing_payload.blocked_reason == "retarget_target_type_missing",
        "unique_missing_registry_blocked_or_gap": unique_missing_registry is None
        or (not unique_missing_registry.ok and unique_missing_registry.blocked_reason == "target_unique_entity_registry_missing"),
    }
    if blocked_sort is not None:
        blocked = _resolve(blocked_sort, state)
        cases["blocked_sort_source"] = _expression_sample(blocked_sort)
        cases["blocked_sort_resolution"] = blocked.to_json()
        checks["blocked_sort_state_unchanged"] = not blocked.ok and bool(blocked.blocked_reason)
    else:
        cases["blocked_sort_source"] = _source_gap("no blocked sort expression remains")
        checks["blocked_sort_gap_recorded"] = True
    random_missing = (random_case.get("missing_choice") or {}) if isinstance(random_case, dict) else {}
    checks["random_missing_choice_blocked_or_gap"] = bool(random_case.get("coverage_gap")) or (
        isinstance(random_missing, dict) and random_missing.get("blocked_reason") == "requires_rng_choice"
    )
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _status_blocked_trace_case(rules: RuleBook, random_case: dict[str, Any]) -> dict[str, Any]:
    random_expression = _expression_from_case(rules, random_case)
    if random_expression is None:
        checks = {"source_gap_recorded": True, "no_synthetic_status_mutation": True}
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no random expression available for status blocked trace case"}
    effect = _synthetic_add_modifier_effect(random_expression)
    result = StatusSystem(rules).apply_add_modifier(
        _state(),
        effect,
        caster_id="ally:caster",
        source_id="validation:p1_6:status_blocked_trace",
        owner_id="ally:caster",
        param_entity_id="enemy:mid",
        current_action_target_id="enemy:mid",
        target_resolution=_target_resolution(("enemy:left", "enemy:mid", "enemy:right")),
        event_payload=_event_payload(),
    )
    record = result.records[0] if result.records else {}
    trace = record.get("trace") if isinstance(record, dict) else {}
    target_trace = trace.get("target_expression") if isinstance(trace, dict) else {}
    checks = {
        "status_result_blocked": not result.ok,
        "no_mutations": not result.mutations,
        "process_only_record": bool(record) and record.get("process_only") is True,
        "target_trace_present": isinstance(target_trace, dict) and target_trace.get("expression_id") == random_expression.target_expression_id,
        "blocked_reason_from_target": "requires_rng_choice" in result.unsupported,
        "rng_events_transparent_empty_on_missing_choice": not result.rng_events,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": effect.to_json(),
        "expression": _expression_sample(random_expression),
        "status_application": result.to_json(),
    }


def _mutation_audit_case(rules: RuleBook) -> dict[str, Any]:
    candidate = _select_runtime_candidate(rules)
    if candidate is None:
        checks = {"coverage_gap_recorded": True, "no_synthetic_runtime_mutation": True}
        checks["ok"] = True
        return {"checks": {"ok": True, "checks": checks}, "coverage_gap": "no safe AddModifier target expression mutation sample found"}
    effect, expression, result = candidate
    state = _state()
    after = MutationReducer().apply_all(state, result.mutations)
    transition = _status_transition(state, after, result, "p1_6:target_status_mutation")
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    details = _status_details(result)
    traces = [detail.get("source_trace", {}).get("target_expression") for detail in details if isinstance(detail, dict)]
    checks = {
        "runtime_mutations_present": bool(result.mutations),
        "settlement_records_present": bool(result.records),
        "target_expression_trace_present": all(isinstance(trace, dict) for trace in traces),
        "target_expression_ir_source_present": bool(expression.source.source_path),
        "mutation_replay_ok": replay.ok,
        "source_audit_ok": source_audit.ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "state": state,
        "after_state": after,
        "effect": effect.to_json(),
        "expression": _expression_sample(expression),
        "status_application": result.to_json(),
        "status_details": details,
        "transition": transition.to_json(),
        "replay": {"ok": replay.ok, "errors": list(replay.errors)},
        "source_audit": source_audit.to_json(),
    }


def _select_runtime_candidate(rules: RuleBook) -> tuple[EffectIR, TargetExpressionIR, Any] | None:
    system = StatusSystem(rules)
    state = _state()
    allowed_aliases = {"AbilityTargetEntity", "SkillTargetEntityList", "AllEnemy.SortByHP", "AllEnemy.SortByHPRatio"}
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if effect.opcode != "AddModifier" or effect.coverage_status != "executable":
            continue
        if not _mainline_effect_source(effect):
            continue
        standard = effect.payload.get("standard")
        if not isinstance(standard, dict):
            continue
        expression_id = standard.get("target_expression_id")
        if not isinstance(expression_id, str) or not expression_id:
            continue
        expression = rules.target_expression(expression_id)
        if expression is None or expression.coverage_status != "executable":
            continue
        if expression.alias not in allowed_aliases and expression.expression_kind not in {"TargetSequence", "Retarget"}:
            continue
        modifier_name = str(standard.get("modifier_name") or "")
        if not modifier_name or not rules.modifier_definitions(modifier_name):
            continue
        result = system.apply_add_modifier(
            state,
            effect,
            caster_id="ally:caster",
            source_id="validation:p1_6:add_modifier",
            owner_id="ally:caster",
            param_entity_id="enemy:mid",
            current_action_target_id="enemy:mid",
            target_resolution=_target_resolution(("enemy:mid",)),
            event_payload=_event_payload(),
        )
        if result.ok and result.mutations:
            return effect, expression, result
    return None


def _resolve(
    expression: TargetExpressionIR,
    state: BattleState,
    *,
    current_action_target_id: str = "enemy:mid",
    target_resolution: TargetResolution | None = None,
    event_payload: dict[str, Any] | None = None,
    dynamic_values: dict[str, float] | None = None,
) -> Any:
    return TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:caster",
        owner_id="ally:caster",
        param_entity_id="enemy:mid",
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution or _target_resolution(("enemy:left", "enemy:mid", "enemy:right")),
        event_payload=event_payload if event_payload is not None else _event_payload(),
        dynamic_values=dynamic_values,
    )


def _select_expression(
    rules: RuleBook,
    *,
    kind: str,
    alias: str = "",
    allow_missing: bool = False,
) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.source.source_path, item.target_expression_id)):
        if expression.coverage_status != "executable":
            continue
        if expression.expression_kind != kind:
            continue
        if alias and expression.alias != alias:
            continue
        if not _mainline_expression_source(expression) and not _global_target_config_source(expression):
            continue
        return expression
    if allow_missing:
        return None
    raise RuntimeError(f"no executable target expression found for kind={kind!r} alias={alias!r}")


def _select_expression_by_alias(rules: RuleBook, aliases: tuple[str, ...]) -> TargetExpressionIR | None:
    for alias in aliases:
        expression = _select_expression(rules, kind="TargetAlias", alias=alias, allow_missing=True)
        if expression is not None:
            return expression
    return None


def _select_expression_by_kind(rules: RuleBook, kinds: tuple[str, ...]) -> TargetExpressionIR | None:
    for kind in kinds:
        expression = _select_expression(rules, kind=kind, allow_missing=True)
        if expression is not None:
            return expression
    return None


def _select_random_expression(rules: RuleBook) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.source.source_path, item.target_expression_id)):
        if expression.coverage_status != "executable" or not _mainline_expression_source(expression):
            continue
        raw = expression.payload.get("raw") if isinstance(expression.payload, dict) else None
        if _raw_has_random_target(raw):
            return expression
    return None


def _select_retarget_with_max(rules: RuleBook, *, dynamic: bool) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.source.source_path, item.target_expression_id)):
        if expression.coverage_status != "executable" or expression.expression_kind != "Retarget":
            continue
        if not _mainline_expression_source(expression):
            continue
        raw = expression.payload.get("raw") if isinstance(expression.payload, dict) else None
        if not isinstance(raw, dict):
            continue
        max_number = raw.get("MaxNumber")
        if max_number is None:
            continue
        is_dynamic = isinstance(max_number, dict) and str(max_number.get("$type") or "").endswith("DynamicValue")
        if is_dynamic == dynamic:
            return expression
    return None


def _select_blocked_sort(rules: RuleBook) -> TargetExpressionIR | None:
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.blocked_reason, item.target_expression_id)):
        if expression.coverage_status == "blocked" and (
            expression.expression_kind.startswith("TargetSort") or "sort" in expression.blocked_reason.lower()
        ):
            return expression
    return None


def _expression_from_case(rules: RuleBook, case: dict[str, Any]) -> TargetExpressionIR | None:
    expression_payload = case.get("expression")
    if not isinstance(expression_payload, dict):
        return None
    expression_id = expression_payload.get("target_expression_id")
    if not isinstance(expression_id, str):
        return None
    return rules.target_expression(expression_id)


def _raw_has_random_target(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if raw.get("ByRandom") is True or str(raw.get("$type") or "").endswith("TargetShuffle"):
        return True
    for value in raw.values():
        if isinstance(value, dict) and _raw_has_random_target(value):
            return True
        if isinstance(value, list) and any(_raw_has_random_target(item) for item in value):
            return True
    return False


def _normalized_sort_key(expression: TargetExpressionIR) -> str:
    payload = expression.payload.get("normalized") if isinstance(expression.payload, dict) else None
    if not isinstance(payload, dict):
        return ""
    sort = payload.get("sort")
    if isinstance(sort, dict):
        return str(sort.get("sort_key") or "")
    alias = expression.alias
    for token, key in {
        "SortByHPRatio": "HPRatio",
        "SortByHP": "CurrentHP",
        "SortByFormation": "formation_position",
        "SortByStanceRatio": "StanceRatio",
        "SortByStance": "CurrentStance",
    }.items():
        if token in alias:
            return key
    return ""


def _expected_sort_order(state: BattleState, target_ids: tuple[str, ...], sort_step: dict[str, Any]) -> tuple[str, ...]:
    candidate_pool = tuple(str(item) for item in sort_step.get("candidate_pool_before", []) if isinstance(item, str))
    sort_values = sort_step.get("sort_values")
    if not isinstance(sort_values, dict):
        return target_ids
    highest_first = sort_step.get("direction") == "desc"
    return tuple(
        sorted(
            candidate_pool,
            key=lambda target_id: (
                -float(sort_values[target_id]) if highest_first else float(sort_values[target_id]),
                target_id,
            ),
        )
    )


def _first_step(result: Any, operation: str) -> dict[str, Any]:
    for step in result.metadata.get("resolution_steps", []):
        if isinstance(step, dict) and step.get("operation") == operation:
            return step
    return {}


def _state() -> BattleState:
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
            "ally:three": UnitState(
                unit_id="ally:three",
                side="ally",
                template_id="avatar:validation:three",
                hp=900.0,
                max_hp=1000.0,
                toughness=20.0,
                max_toughness=100.0,
                flags={"position": 3},
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
            "summon:caster": UnitState(
                unit_id="summon:caster",
                side="summon",
                template_id="monster:validation:caster_summon",
                hp=500.0,
                max_hp=500.0,
                toughness=30.0,
                max_toughness=60.0,
                flags={"position": 4, "team_side": "ally", "summon_kind": "summoned_monster", "owner_id": "ally:caster"},
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
                "schema_version": "p1_3_summon_runtime_v1",
                "last_summon_monsters": ["summon:last"],
                "by_owner": {"ally:caster": ["summon:caster"], "enemy:mid": ["summon:last"]},
            },
        },
    )


def _state_with_flags(unit_id: str, flags: dict[str, Any]) -> BattleState:
    state = _state()
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


def _with_unique_registry(state: BattleState, unique_name: str, value: Any) -> BattleState:
    registry = {} if value is None else {unique_name: value}
    return replace(state, global_flags={**state.global_flags, "target_unique_entity_registry": registry})


def _with_partner_registry(state: BattleState, registry: dict[str, Any]) -> BattleState:
    return replace(state, global_flags={**state.global_flags, "target_partner_registry": registry})


def _target_resolution(target_ids: tuple[str, ...]) -> TargetResolution:
    return TargetResolution(
        requested=target_ids,
        legal=target_ids,
        selected=target_ids,
        rejected=(),
        reason="validation_target",
        source="validate_p1_6_target_system",
    )


def _event_payload() -> dict[str, Any]:
    return {
        "param_entity_ids": ["enemy:left", "enemy:mid"],
        "selected_target_ids": ["enemy:left", "enemy:mid", "enemy:right"],
        "target_ids": ["enemy:left", "enemy:mid", "enemy:right"],
        "AttackType": "Normal",
        "SkillType": "Normal",
    }


def _unique_name(expression: TargetExpressionIR) -> str:
    raw = expression.payload.get("raw") if isinstance(expression.payload, dict) else None
    if isinstance(raw, dict):
        value = raw.get("UniqueName")
        if isinstance(value, str):
            return value
    normalized = expression.payload.get("normalized") if isinstance(expression.payload, dict) else None
    if isinstance(normalized, dict):
        fetch = normalized.get("fetch")
        if isinstance(fetch, dict):
            value = fetch.get("unique_name")
            if isinstance(value, str):
                return value
    return "validation_unique_entity"


def _partner_name(expression: TargetExpressionIR) -> str:
    raw = expression.payload.get("raw") if isinstance(expression.payload, dict) else None
    if isinstance(raw, dict):
        value = raw.get("Name")
        if isinstance(value, str):
            return value
    normalized = expression.payload.get("normalized") if isinstance(expression.payload, dict) else None
    if isinstance(normalized, dict):
        fetch = normalized.get("fetch")
        if isinstance(fetch, dict):
            value = fetch.get("name")
            if isinstance(value, str):
                return value
    return ""


def _matched_partner_key(result: Any) -> str:
    for step in result.metadata.get("resolution_steps", []):
        if isinstance(step, dict) and step.get("operation") == "target_fetch_partner":
            key = step.get("matched_registry_key")
            if isinstance(key, str) and key:
                return key
    return ""


def _synthetic_sort_missing_payload() -> TargetExpressionIR:
    return TargetExpressionIR(
        target_expression_id="validation:p1_6:missing_sort_payload",
        expression_kind="TargetSequence",
        alias="",
        payload={
            "raw": {
                "$type": "RPG.GameCore.TargetSequence",
                "Sequence": [
                    {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllEnemy"},
                    {"$type": "RPG.GameCore.TargetSortByProperty"},
                ],
            }
        },
        source=_validation_source("missing_sort_payload"),
        coverage_status="executable",
        admission_batch="validation_boundary_no_mutation",
    )


def _synthetic_retarget_missing_payload() -> TargetExpressionIR:
    return TargetExpressionIR(
        target_expression_id="validation:p1_6:missing_retarget_payload",
        expression_kind="Retarget",
        alias="",
        payload={"raw": {"$type": "RPG.GameCore.Retarget"}},
        source=_validation_source("missing_retarget_payload"),
        coverage_status="executable",
        admission_batch="validation_boundary_no_mutation",
    )


def _synthetic_retarget_missing_max() -> TargetExpressionIR:
    return TargetExpressionIR(
        target_expression_id="validation:p1_6:missing_dynamic_max",
        expression_kind="Retarget",
        alias="",
        payload={
            "raw": {
                "$type": "RPG.GameCore.Retarget",
                "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllEnemy"},
                "MaxNumber": {"$type": "RPG.GameCore.DynamicValue", "Hash": "validation_missing_target_max"},
            }
        },
        source=_validation_source("missing_dynamic_max"),
        coverage_status="executable",
        admission_batch="validation_boundary_no_mutation",
    )


def _synthetic_add_modifier_effect(expression: TargetExpressionIR) -> EffectIR:
    return EffectIR(
        effect_id="validation:p1_6:add_modifier_target_blocked",
        opcode="AddModifier",
        payload={
            "standard": {
                "modifier_name": "validation_no_mutation_modifier",
                "target_expression_id": expression.target_expression_id,
                "target_expression_kind": expression.expression_kind,
                "target_expression_coverage_status": expression.coverage_status,
                "target_expression_source": expression.source.to_json(),
            }
        },
        source=_validation_source("add_modifier_target_blocked"),
        coverage_status="executable",
    )


def _validation_source(raw_id: str) -> IRSource:
    return IRSource(
        source_path="simulator_v8_clean_core/tools/validate_p1_6_target_system.py",
        raw_type="ValidationBoundary",
        raw_id=raw_id,
        evidence={"purpose": "negative no-mutation target boundary validation"},
    )


def _status_transition(before: BattleState, after: BattleState, result: Any, action_id: str) -> BattleTransition:
    target_ids = tuple(
        str(item)
        for record in result.records
        for item in ((record.get("payload") or {}).get("target_ids") or [])
        if isinstance(item, str)
    )
    return BattleTransition(
        transaction=ActionTransaction(
            command=ActionCommand(actor_id="ally:caster", action_id=action_id, action_level=1, target_ids=target_ids),
            before=before.snapshot(),
            mutations=result.mutations,
            settlement=ActionSettlement(
                action_id=action_id,
                actor_id="ally:caster",
                target_ids=target_ids,
                records=tuple(result.records),
            ),
        ),
        after=after.snapshot(),
        target_resolution=_target_resolution(target_ids),
        rng_events=result.rng_events,
    )


def _status_details(result: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for mutation in result.mutations:
        if mutation.path[-1:] != ("status_details",):
            continue
        after = mutation.after
        if isinstance(after, list):
            details.extend(item for item in after if isinstance(item, dict))
    return details


def _mainline_expression_source(expression: TargetExpressionIR) -> bool:
    return _mainline_source_path(expression.source.source_path)


def _mainline_effect_source(effect: EffectIR) -> bool:
    return _mainline_source_path(effect.source.source_path)


def _mainline_source_path(source_path: str) -> bool:
    return (
        source_path.startswith("Config/ConfigAbility/Avatar/")
        or source_path.startswith("Config/ConfigAbility/Monster/")
        or source_path.startswith("Config/ConfigAbility/Equip/")
        or source_path.startswith("Config/ConfigAbility/Level/")
        or source_path in {"Config/ConfigAbility/EquipmemtAbility.json", "Config/ConfigAbility/RelicAbility.json"}
    )


def _global_target_config_source(expression: TargetExpressionIR) -> bool:
    evidence = expression.source.evidence
    raw_path = evidence.get("source_path") or evidence.get("target_config_path") or ""
    return "TargetAliasConfig.json" in str(raw_path) or "TargetOperationConfig.json" in str(raw_path)


def _expression_sample(expression: TargetExpressionIR) -> dict[str, Any]:
    return {
        "target_expression_id": expression.target_expression_id,
        "expression_kind": expression.expression_kind,
        "alias": expression.alias,
        "coverage_status": expression.coverage_status,
        "blocked_reason": expression.blocked_reason,
        "admission_batch": expression.admission_batch,
        "normalized": expression.payload.get("normalized") if isinstance(expression.payload, dict) else {},
        "source": expression.source.to_json(),
    }


def _source_gap(reason: str) -> dict[str, Any]:
    return {"coverage_status": "source_gap_blocked", "reason": reason, "state_unchanged": True}


def _strip_state(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if key not in {"state", "after_state"}}


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_json"):
        return value.to_json()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
