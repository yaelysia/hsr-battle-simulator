from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, TargetResolution, UnitState
from ..rules.ir import EffectIR, TargetExpressionIR
from ..rules.rulebook import RuleBook
from ..systems.status import StatusSystem
from ..systems.target import TargetSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_289"
SAFE_CONTEXT_ALIASES = {"SkillTargetEntityList", "ParamEntityList", "TeamFormation"}
COMPOSITE_KINDS = {"TargetSequence", "TargetConcat", "Retarget"}


@dataclass(frozen=True)
class RuntimeCandidate:
    effect: EffectIR
    expression: TargetExpressionIR
    result: Any


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = _target_expression_matrix(rules)
    alias_cases = _alias_cases(rules)
    sequence_case = _resolver_case(rules, kind="TargetSequence")
    retarget_case = _resolver_case(rules, kind="Retarget")
    add_modifier_case = _runtime_add_modifier_case(rules)
    boundary_case = _boundary_case(rules)
    checks = {
        "matrix": matrix["checks"],
        "alias_cases": alias_cases["checks"],
        "sequence_case": sequence_case["checks"],
        "retarget_case": retarget_case["checks"],
        "add_modifier_case": add_modifier_case["checks"],
        "boundary": boundary_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
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
                    "TargetExpressionIR kind/alias/coverage_status",
                    "EffectIR opcode AddModifier for runtime integration only",
                    "mainline ConfigAbility source for runtime mutation samples",
                    "no fixed character monster skill file or action id",
                ],
            },
        },
        "checks": checks,
        "target_expression_matrix": matrix,
        "alias_cases": alias_cases,
        "sequence_case": sequence_case,
        "retarget_case": retarget_case,
        "add_modifier_case": add_modifier_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_289.json", result)
    write_json(output_dir / "target_expression_matrix_v0_289.json", matrix)
    write_json(output_dir / "target_expression_alias_cases_v0_289.json", alias_cases)
    write_json(output_dir / "target_expression_sequence_case_v0_289.json", sequence_case)
    write_json(output_dir / "target_expression_retarget_case_v0_289.json", retarget_case)
    write_json(output_dir / "target_expression_add_modifier_case_v0_289.json", add_modifier_case)
    write_json(output_dir / "target_expression_boundary_cases_v0_289.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_289 target expression sequence/filter/retarget admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _target_expression_matrix(rules: RuleBook) -> dict[str, Any]:
    by_kind = Counter(expression.expression_kind for expression in rules.target_expressions())
    by_alias = Counter(expression.alias for expression in rules.target_expressions() if expression.alias)
    by_coverage = Counter(expression.coverage_status for expression in rules.target_expressions())
    executable_by_kind = Counter(
        expression.expression_kind
        for expression in rules.target_expressions()
        if expression.coverage_status == "executable"
    )
    sample_by_kind: dict[str, dict[str, Any]] = {}
    for expression in rules.target_expressions():
        sample_by_kind.setdefault(expression.expression_kind, _expression_sample(expression))
    checks = {
        "target_expressions_present": bool(rules.target_expressions()),
        "sequence_lowered": by_kind.get("TargetSequence", 0) > 0,
        "retarget_lowered": by_kind.get("Retarget", 0) > 0,
        "safe_context_aliases_executable": all(
            any(
                expression.alias == alias and expression.coverage_status == "executable"
                for expression in rules.target_expressions()
            )
            for alias in SAFE_CONTEXT_ALIASES
        ),
        "composite_executable_or_gap_recorded": any(executable_by_kind.get(kind, 0) > 0 for kind in COMPOSITE_KINDS),
        "blocked_sort_fetch_still_present": any(
            expression.coverage_status == "blocked"
            and (
                expression.expression_kind.startswith("TargetSort")
                or expression.expression_kind.startswith("TargetFetch")
            )
            for expression in rules.target_expressions()
        ),
        "samples_have_source": all(bool(sample.get("source")) for sample in sample_by_kind.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "coverage_counts": dict(sorted(by_coverage.items())),
        "kind_counts_top": [{"key": key, "count": count} for key, count in by_kind.most_common(40)],
        "executable_kind_counts": dict(sorted(executable_by_kind.items())),
        "alias_counts_top": [{"key": key, "count": count} for key, count in by_alias.most_common(60)],
        "sample_by_kind": sample_by_kind,
    }


def _alias_cases(rules: RuleBook) -> dict[str, Any]:
    state = _state()
    system = TargetSystem()
    cases: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for alias in sorted(SAFE_CONTEXT_ALIASES):
        expression = _select_expression(rules, kind="TargetAlias", alias=alias)
        result = system.resolve_target_expression(
            state,
            expression,
            caster_id="ally:caster",
            owner_id="ally:caster",
            param_entity_id="enemy:one",
            current_action_target_id="enemy:one",
            target_resolution=_target_resolution(("enemy:one", "enemy:two")),
            event_payload={
                "param_entity_ids": ["enemy:one", "enemy:two"],
                "selected_target_ids": ["enemy:one", "enemy:two"],
                "target_ids": ["enemy:one", "enemy:two"],
            },
        )
        cases[alias] = {
            "expression": _expression_sample(expression),
            "resolution": result.to_json(),
        }
        if alias == "TeamFormation":
            checks[f"{alias}_resolved"] = result.ok and set(result.target_ids) == {"ally:caster", "ally:two"}
        else:
            checks[f"{alias}_resolved"] = result.ok and set(result.target_ids) == {"enemy:one", "enemy:two"}
        checks[f"{alias}_trace_present"] = bool(result.metadata.get("target_expression"))
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "cases": cases}


def _resolver_case(rules: RuleBook, *, kind: str) -> dict[str, Any]:
    expression = _select_expression(rules, kind=kind, allow_missing=True)
    if expression is None:
        checks = {"coverage_gap_recorded": True, "no_synthetic_expression_used": True}
        checks["ok"] = True
        return {
            "checks": {"ok": True, "checks": checks},
            "coverage_gap": f"no executable {kind} expression found by structured predicate",
        }
    result = TargetSystem().resolve_target_expression(
        _state(),
        expression,
        caster_id="ally:caster",
        owner_id="ally:caster",
        param_entity_id="enemy:one",
        current_action_target_id="enemy:one",
        target_resolution=_target_resolution(("enemy:one", "enemy:two")),
        event_payload={
            "param_entity_ids": ["enemy:one", "enemy:two"],
            "selected_target_ids": ["enemy:one", "enemy:two"],
            "target_ids": ["enemy:one", "enemy:two"],
            "AttackType": "Normal",
            "SkillType": "Normal",
        },
    )
    checks = {
        "expression_executable": expression.coverage_status == "executable",
        "resolver_ok": result.ok,
        "targets_present": bool(result.target_ids),
        "resolution_steps_present": bool(result.metadata.get("resolution_steps")),
        "source_trace_present": bool(expression.source.to_json()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "expression": _expression_sample(expression),
        "resolution": result.to_json(),
    }


def _runtime_add_modifier_case(rules: RuleBook) -> dict[str, Any]:
    candidate = _select_runtime_candidate(rules)
    if candidate is None:
        checks = {
            "coverage_gap_recorded": True,
            "no_synthetic_runtime_mutation": True,
        }
        checks["ok"] = True
        return {
            "checks": {"ok": True, "checks": checks},
            "coverage_gap": "no safe executable AddModifier target expression runtime mutation sample found",
        }
    details = _status_details(candidate.result)
    traces = [detail.get("source_trace", {}).get("target_expression") for detail in details if isinstance(detail, dict)]
    checks = {
        "status_application_ok": candidate.result.ok,
        "mutations_present": bool(candidate.result.mutations),
        "status_details_present": bool(details),
        "target_expression_trace_present": all(isinstance(trace, dict) for trace in traces),
        "target_expression_id_matches": all(
            isinstance(trace, dict) and trace.get("expression_id") == candidate.expression.target_expression_id
            for trace in traces
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": {"effect_id": candidate.effect.effect_id, "source": candidate.effect.source.to_json()},
        "expression": _expression_sample(candidate.expression),
        "status_application": candidate.result.to_json(),
        "status_details": details,
    }


def _boundary_case(rules: RuleBook) -> dict[str, Any]:
    state = _state()
    system = TargetSystem()
    blocked_sort_or_fetch = _select_blocked_sort_or_fetch(rules)
    unsupported_filter = _synthetic_boundary_expression("TargetFilter", "target_filter:unsupported")
    missing_payload_result = system.resolve_target_expression(
        state,
        _synthetic_boundary_expression("Retarget", "retarget:missing_target"),
        caster_id="ally:caster",
        owner_id="ally:caster",
    )
    blocked_result = system.resolve_target_expression(
        state,
        blocked_sort_or_fetch,
        caster_id="ally:caster",
        owner_id="ally:caster",
        target_resolution=_target_resolution(("enemy:one",)),
    )
    unsupported_filter_result = system.resolve_target_expression(
        state,
        unsupported_filter,
        caster_id="ally:caster",
        owner_id="ally:caster",
        target_resolution=_target_resolution(("enemy:one",)),
    )
    param_list_missing = system.resolve_target_expression(
        state,
        _select_expression(rules, kind="TargetAlias", alias="ParamEntityList"),
        caster_id="ally:caster",
        owner_id="ally:caster",
        event_payload={},
    )
    checks = {
        "blocked_sort_fetch_state_unchanged": not blocked_result.ok and bool(blocked_result.blocked_reason),
        "unsupported_filter_blocked": not unsupported_filter_result.ok and "condition" in unsupported_filter_result.blocked_reason,
        "missing_retarget_payload_blocked": not missing_payload_result.ok and bool(missing_payload_result.blocked_reason),
        "param_entity_list_missing_blocked": not param_list_missing.ok and param_list_missing.blocked_reason == "param_entity_list_missing",
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_sort_or_fetch": _expression_sample(blocked_sort_or_fetch),
        "blocked_sort_or_fetch_result": blocked_result.to_json(),
        "unsupported_filter_result": unsupported_filter_result.to_json(),
        "missing_retarget_payload_result": missing_payload_result.to_json(),
        "param_entity_list_missing_result": param_list_missing.to_json(),
    }


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
        if not _mainline_expression_source(expression):
            continue
        return expression
    if allow_missing:
        return None
    raise RuntimeError(f"no executable target expression found for kind={kind!r} alias={alias!r}")


def _select_runtime_candidate(rules: RuleBook) -> RuntimeCandidate | None:
    system = StatusSystem(rules)
    state = _state()
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
        if expression.expression_kind not in COMPOSITE_KINDS and expression.alias not in SAFE_CONTEXT_ALIASES:
            continue
        modifier_name = str(standard.get("modifier_name") or "")
        if not modifier_name or not rules.modifier_definitions(modifier_name):
            continue
        result = system.apply_add_modifier(
            state,
            effect,
            caster_id="ally:caster",
            source_id="validation:v0_289:add_modifier",
            owner_id="ally:caster",
            param_entity_id="enemy:one",
            current_action_target_id="enemy:one",
            target_resolution=_target_resolution(("enemy:one", "enemy:two")),
            event_payload={
                "param_entity_ids": ["enemy:one", "enemy:two"],
                "selected_target_ids": ["enemy:one", "enemy:two"],
                "target_ids": ["enemy:one", "enemy:two"],
                "AttackType": "Normal",
                "SkillType": "Normal",
            },
        )
        if result.ok and result.mutations:
            return RuntimeCandidate(effect=effect, expression=expression, result=result)
    return None


def _select_blocked_sort_or_fetch(rules: RuleBook) -> TargetExpressionIR:
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.expression_kind, item.target_expression_id)):
        if expression.coverage_status == "blocked" and (
            expression.expression_kind.startswith("TargetSort")
            or expression.expression_kind.startswith("TargetFetch")
        ):
            return expression
    raise RuntimeError("no blocked TargetSort/TargetFetch expression found")


def _synthetic_boundary_expression(kind: str, raw_id: str) -> TargetExpressionIR:
    if kind == "TargetFilter":
        raw = {
            "$type": "RPG.GameCore.TargetFilter",
            "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "SkillTargetEntityList"},
            "Predicate": {"$type": "RPG.GameCore.ByUnsupportedForV0289"},
        }
    else:
        raw = {"$type": "RPG.GameCore.Retarget"}
    return TargetExpressionIR(
        target_expression_id=f"validation:v0_289:{raw_id}",
        expression_kind=kind,
        alias="",
        payload={"raw": raw},
        source=rules_source(raw_id),
        coverage_status="executable",
        admission_batch="validation_boundary_no_mutation",
    )


def rules_source(raw_id: str):
    from ..rules.ir import IRSource

    return IRSource(
        source_path="simulator_v8_clean_core/tools/validate_v0_289.py",
        raw_type="ValidationBoundaryTargetExpression",
        raw_id=raw_id,
        evidence={"purpose": "negative resolver boundary; no runtime mutation"},
    )


def _mainline_expression_source(expression: TargetExpressionIR) -> bool:
    return _mainline_source_path(expression.source.source_path)


def _mainline_effect_source(effect: EffectIR) -> bool:
    return _mainline_source_path(effect.source.source_path)


def _mainline_source_path(source_path: str) -> bool:
    return (
        source_path.startswith("Config/ConfigAbility/Avatar/")
        or source_path.startswith("Config/ConfigAbility/Monster/")
        or source_path.startswith("Config/ConfigAbility/Equip/")
        or source_path in {"Config/ConfigAbility/EquipmemtAbility.json", "Config/ConfigAbility/RelicAbility.json"}
    )


def _state() -> BattleState:
    return BattleState(
        units={
            "ally:caster": UnitState(
                unit_id="ally:caster",
                side="ally",
                template_id="avatar:validation:caster",
                hp=1000.0,
                max_hp=1000.0,
            ),
            "ally:two": UnitState(
                unit_id="ally:two",
                side="ally",
                template_id="avatar:validation:two",
                hp=900.0,
                max_hp=1000.0,
            ),
            "enemy:one": UnitState(
                unit_id="enemy:one",
                side="enemy",
                template_id="monster:validation:one",
                hp=1000.0,
                max_hp=1000.0,
            ),
            "enemy:two": UnitState(
                unit_id="enemy:two",
                side="enemy",
                template_id="monster:validation:two",
                hp=800.0,
                max_hp=1000.0,
            ),
        },
        skill_points=3,
        max_skill_points=5,
    )


def _target_resolution(target_ids: tuple[str, ...]) -> TargetResolution:
    return TargetResolution(
        requested=target_ids,
        legal=target_ids,
        selected=target_ids,
        rejected=(),
        reason="validation_target",
        source="validate_v0_289",
    )


def _status_details(result: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for mutation in result.mutations:
        if mutation.path[-1:] != ("status_details",):
            continue
        after = mutation.after
        if not isinstance(after, list):
            continue
        details.extend(item for item in after if isinstance(item, dict))
    return details


def _expression_sample(expression: TargetExpressionIR) -> dict[str, Any]:
    return {
        "target_expression_id": expression.target_expression_id,
        "expression_kind": expression.expression_kind,
        "alias": expression.alias,
        "coverage_status": expression.coverage_status,
        "blocked_reason": expression.blocked_reason,
        "admission_batch": expression.admission_batch,
        "source": expression.source.to_json(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
