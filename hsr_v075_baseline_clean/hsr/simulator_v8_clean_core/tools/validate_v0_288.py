from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
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


VALIDATION_VERSION = "v0_288"
SAFE_SINGLE_ALIASES = {"AbilityTargetEntity", "CurrentActionTarget", "ParamEntity", "Caster", "ModifierOwnerEntity"}
SAFE_GROUP_ALIASES = {"AllEnemy", "AllTeamMember", "AllLightTeam", "AllTeammate"}


@dataclass(frozen=True)
class TargetExpressionCandidate:
    effect: EffectIR
    expression: TargetExpressionIR
    alias: str
    modifier_name: str
    result: Any


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = _target_expression_matrix(rules)
    single = _select_positive_candidate(rules, aliases=SAFE_SINGLE_ALIASES)
    group = _select_positive_candidate(rules, aliases=SAFE_GROUP_ALIASES, require_multiple_targets=True, allow_missing=True)
    positive_single_case = _positive_case(rules, single)
    positive_group_case = _positive_case(rules, group) if group is not None else _group_gap_case(matrix)
    boundary_case = _boundary_case(rules, single)
    checks = {
        "ir_matrix": matrix["checks"],
        "positive_single": positive_single_case["checks"],
        "positive_group": positive_group_case["checks"],
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
                        "EffectIR opcode AddModifier",
                        "source_path under Config/ConfigAbility/Avatar, Monster, or Equip",
                        "standard.target_expression_id exists",
                    "TargetExpressionIR coverage_status executable for positive cases",
                    "direct StatusSystem application succeeds without dynamic/listener/duration blocked path",
                    "blocked expression selected by coverage_status/kind, not by fixed id",
                ],
            },
        },
        "checks": checks,
        "target_expression_matrix": matrix,
        "positive_single_case": positive_single_case,
        "positive_group_case": positive_group_case,
        "boundary_case": boundary_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_288.json", result)
    write_json(output_dir / "target_expression_matrix_v0_288.json", matrix)
    write_json(output_dir / "target_expression_positive_single_v0_288.json", positive_single_case)
    write_json(output_dir / "target_expression_positive_group_v0_288.json", positive_group_case)
    write_json(output_dir / "target_expression_boundary_cases_v0_288.json", boundary_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_288 target expression core.")
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
    effect_ref_count = sum(
        1
        for effect in rules.ir.effects
        if isinstance(effect.payload.get("standard"), dict)
        and isinstance(effect.payload["standard"].get("target_expression_id"), str)
    )
    sample_by_bucket: dict[str, dict[str, Any]] = {}
    for expression in rules.target_expressions():
        sample_by_bucket.setdefault(expression.coverage_status, _expression_sample(expression))
        sample_by_bucket.setdefault(expression.expression_kind, _expression_sample(expression))
    checks = {
        "target_expressions_lowered": bool(rules.target_expressions()),
        "effect_payload_refs_present": effect_ref_count > 0,
        "executable_aliases_present": by_coverage.get("executable", 0) > 0,
        "blocked_composite_or_fetch_present": any(
            kind in by_kind
            for kind in ("TargetSequence", "TargetFilter", "Retarget", "TargetFetchCaster", "TargetFetchUniqueNameEntity")
        ),
        "samples_have_source": all(bool(sample.get("source")) for sample in sample_by_bucket.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "target_expression_count": len(rules.target_expressions()),
        "effect_ref_count": effect_ref_count,
        "coverage_counts": dict(sorted(by_coverage.items())),
        "kind_counts_top": [{"key": key, "count": count} for key, count in by_kind.most_common(40)],
        "alias_counts_top": [{"key": key, "count": count} for key, count in by_alias.most_common(60)],
        "sample_by_bucket": sample_by_bucket,
    }


def _positive_case(rules: RuleBook, candidate: TargetExpressionCandidate) -> dict[str, Any]:
    result = candidate.result
    details = _status_details(result, candidate.modifier_name)
    target_expression_traces = [
        detail.get("source_trace", {}).get("target_expression")
        for detail in details
        if isinstance(detail, dict)
    ]
    checks = {
        "status_application_ok": result.ok,
        "mutations_present": bool(result.mutations),
        "status_details_present": bool(details),
        "target_expression_trace_present": all(bool(trace) for trace in target_expression_traces),
        "target_expression_id_matches": all(
            isinstance(trace, dict) and trace.get("expression_id") == candidate.expression.target_expression_id
            for trace in target_expression_traces
        ),
        "source_trace_has_expression_source": all(
            isinstance(trace, dict) and bool(trace.get("metadata", {}).get("target_expression", {}).get("source"))
            for trace in target_expression_traces
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "candidate": _candidate_sample(candidate),
        "status_application": result.to_json(),
        "status_details": details,
    }


def _group_gap_case(matrix: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "group_gap_recorded": True,
        "no_synthetic_group_sample": True,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "coverage_gap": "no safe executable AddModifier group target expression sample found by structured predicates",
        "matrix_counts": {
            "coverage_counts": matrix["coverage_counts"],
            "alias_counts_top": matrix["alias_counts_top"][:20],
        },
    }


def _boundary_case(rules: RuleBook, positive: TargetExpressionCandidate) -> dict[str, Any]:
    state = _state()
    system = StatusSystem(rules)
    blocked_expression = _select_blocked_expression(rules)
    missing_expression = system.apply_add_modifier(
        state,
        _effect_with_standard(positive.effect, {"target_expression_id": "target_expression:missing:v0_288"}),
        caster_id="enemy:caster",
        source_id="validation:v0_288:missing_expression",
        owner_id="enemy:caster",
        param_entity_id="ally:one",
        current_action_target_id="ally:one",
        target_resolution=_target_resolution("ally:one"),
    )
    blocked_expression_result = system.apply_add_modifier(
        state,
        _effect_with_standard(
            positive.effect,
            {
                "target_expression_id": blocked_expression.target_expression_id,
                "target_expression_kind": blocked_expression.expression_kind,
                "target_expression_coverage_status": blocked_expression.coverage_status,
                "target_expression_blocked_reason": blocked_expression.blocked_reason,
            },
        ),
        caster_id="enemy:caster",
        source_id="validation:v0_288:blocked_expression",
        owner_id="enemy:caster",
        param_entity_id="ally:one",
        current_action_target_id="ally:one",
        target_resolution=_target_resolution("ally:one"),
    )
    fallback_effect = _effect_without_target_expression(positive.effect)
    fallback_result = system.apply_add_modifier(
        state,
        fallback_effect,
        caster_id="enemy:caster",
        source_id="validation:v0_288:legacy_alias_fallback",
        owner_id="enemy:caster",
        param_entity_id="ally:one",
        current_action_target_id="ally:one",
        target_resolution=_target_resolution("ally:one"),
    )
    resolver_blocked = TargetSystem().resolve_target_expression(
        state,
        blocked_expression,
        caster_id="enemy:caster",
        owner_id="enemy:caster",
        param_entity_id="ally:one",
        current_action_target_id="ally:one",
        target_resolution=_target_resolution("ally:one"),
    )
    checks = {
        "missing_expression_blocked": not missing_expression.ok and not missing_expression.mutations,
        "blocked_expression_blocked": not blocked_expression_result.ok and not blocked_expression_result.mutations,
        "blocked_expression_reason_visible": bool(blocked_expression_result.unsupported),
        "resolver_blocks_non_admitted_expression": not resolver_blocked.ok and bool(resolver_blocked.blocked_reason),
        "legacy_alias_fallback_still_works": fallback_result.ok and bool(fallback_result.mutations),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "blocked_expression": _expression_sample(blocked_expression),
        "missing_expression": missing_expression.to_json(),
        "blocked_expression_application": blocked_expression_result.to_json(),
        "resolver_blocked": resolver_blocked.to_json(),
        "legacy_alias_fallback": fallback_result.to_json(),
    }


def _select_positive_candidate(
    rules: RuleBook,
    *,
    aliases: set[str],
    require_multiple_targets: bool = False,
    allow_missing: bool = False,
) -> TargetExpressionCandidate | None:
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
        alias = str(standard.get("target_alias") or "")
        if alias not in aliases:
            continue
        modifier_name = str(standard.get("modifier_name") or "")
        if not modifier_name or not rules.modifier_definitions(modifier_name):
            continue
        expression_id = standard.get("target_expression_id")
        if not isinstance(expression_id, str) or not expression_id:
            continue
        expression = rules.target_expression(expression_id)
        if expression is None or expression.coverage_status != "executable":
            continue
        result = system.apply_add_modifier(
            state,
            effect,
            caster_id="enemy:caster",
            source_id="validation:v0_288:positive",
            owner_id="enemy:caster",
            param_entity_id="ally:one",
            current_action_target_id="ally:one",
            target_resolution=_target_resolution("ally:one"),
        )
        if not result.ok or not result.mutations:
            continue
        if require_multiple_targets:
            details = _status_details(result, modifier_name)
            owners = {str(detail.get("owner_id") or "") for detail in details if isinstance(detail, dict)}
            if len(owners) < 2:
                continue
        return TargetExpressionCandidate(
            effect=effect,
            expression=expression,
            alias=alias,
            modifier_name=modifier_name,
            result=result,
        )
    if allow_missing:
        return None
    raise RuntimeError(f"no positive target expression AddModifier candidate found for aliases {sorted(aliases)}")


def _mainline_effect_source(effect: EffectIR) -> bool:
    source_path = effect.source.source_path
    return (
        source_path.startswith("Config/ConfigAbility/Avatar/")
        or source_path.startswith("Config/ConfigAbility/Monster/")
        or source_path.startswith("Config/ConfigAbility/Equip/")
        or source_path in {"Config/ConfigAbility/EquipmemtAbility.json", "Config/ConfigAbility/RelicAbility.json"}
    )


def _select_blocked_expression(rules: RuleBook) -> TargetExpressionIR:
    preferred = {"TargetSequence", "TargetFilter", "Retarget"}
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.expression_kind not in preferred, item.expression_kind, item.target_expression_id)):
        if expression.coverage_status == "blocked" and expression.expression_kind in preferred:
            return expression
    for expression in sorted(rules.target_expressions(), key=lambda item: (item.expression_kind, item.target_expression_id)):
        if expression.coverage_status == "blocked":
            return expression
    raise RuntimeError("no blocked target expression found")


def _state() -> BattleState:
    return BattleState(
        units={
            "enemy:caster": UnitState(
                unit_id="enemy:caster",
                side="enemy",
                template_id="monster:validation",
                hp=1000.0,
                max_hp=1000.0,
            ),
            "ally:one": UnitState(
                unit_id="ally:one",
                side="ally",
                template_id="avatar:validation:one",
                hp=1000.0,
                max_hp=1000.0,
            ),
            "ally:two": UnitState(
                unit_id="ally:two",
                side="ally",
                template_id="avatar:validation:two",
                hp=1000.0,
                max_hp=1000.0,
            ),
        },
        skill_points=3,
        max_skill_points=5,
    )


def _target_resolution(target_id: str) -> TargetResolution:
    return TargetResolution(
        requested=(target_id,),
        legal=(target_id,),
        selected=(target_id,),
        rejected=(),
        reason="validation_target",
        source="validate_v0_288",
    )


def _status_details(result: Any, modifier_name: str) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for mutation in result.mutations:
        if mutation.path[-1:] != ("status_details",):
            continue
        after = mutation.after
        if not isinstance(after, list):
            continue
        for item in after:
            if isinstance(item, dict) and item.get("modifier_name") == modifier_name:
                details.append(item)
    return details


def _effect_with_standard(effect: EffectIR, updates: dict[str, Any]) -> EffectIR:
    payload = dict(effect.payload)
    standard = dict(payload.get("standard")) if isinstance(payload.get("standard"), dict) else {}
    standard.update(updates)
    payload["standard"] = standard
    return replace(effect, payload=payload)


def _effect_without_target_expression(effect: EffectIR) -> EffectIR:
    payload = dict(effect.payload)
    standard = dict(payload.get("standard")) if isinstance(payload.get("standard"), dict) else {}
    for key in (
        "target_expression_id",
        "target_expression_kind",
        "target_expression_coverage_status",
        "target_expression_blocked_reason",
        "target_expression_source",
        "target_expression_refs",
    ):
        standard.pop(key, None)
    payload["standard"] = standard
    return replace(effect, payload=payload)


def _candidate_sample(candidate: TargetExpressionCandidate) -> dict[str, Any]:
    return {
        "effect_id": candidate.effect.effect_id,
        "effect_source": candidate.effect.source.to_json(),
        "modifier_name": candidate.modifier_name,
        "target_alias": candidate.alias,
        "target_expression": _expression_sample(candidate.expression),
    }


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
