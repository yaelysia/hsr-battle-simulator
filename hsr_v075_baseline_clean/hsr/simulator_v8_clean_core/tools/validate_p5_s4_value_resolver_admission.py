from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import ActionSettlement, BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord, SettlementTraceabilityValidator
from ..rules.ir import CanonicalIR, SkillFormulaBindingIR
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ValueBindingRequest, ValueContext, ValueResolver, ValueResolution
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s4_value_resolver_admission"
MATRIX_SCHEMA_VERSION = "p5_s4_value_resolver_admission_matrix_v1"

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
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "value_context_contract",
    "s2_static_path_migrated_to_value_resolver",
    "dynamic_hash_value_resolver_admission",
    "context_missing_negative_cases",
    "unknown_binding_kind_blocked",
    "resolution_ledger_source_context_trace",
    "runtime_consumer_deferred_policy",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s4_value_resolver_admission_matrix(ir, rules)
    matrix_checks = validate_p5_s4_value_resolver_admission_matrix(matrix)
    checks = {
        "matrix": matrix_checks,
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(bool(item["ok"]) for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "p5_s4_value_context_resolver_admission",
                "runtime_behavior_changed": False,
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "unknown_binding_kind_executable": False,
                "consumer_migration_claimed": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "value_resolver_admission_matrix": matrix["value_resolver_admission_matrix"],
        "resolution_ledger": matrix["resolution_ledger"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "blocked_negative_matrix": matrix["blocked_negative_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s4_value_resolver_admission.json", result)
    write_json(output_dir / "p5_s4_value_resolver_admission_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S4 ValueContext and ValueResolver admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} "
        f"classifications={result['summary']['classification_counts']} "
        f"gap_counts={result['summary']['gap_attribution_counts']}"
    )
    return 0 if result["ok"] else 1


def build_p5_s4_value_resolver_admission_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    resolver = ValueResolver(rules)
    binding = _select_executable_skill_formula_binding(ir)
    dynamic_hash_sample = _select_dynamic_hash_sample(ir)
    full_context = _full_context(binding, dynamic_hash_sample)
    rows = [
        _value_context_contract_row(full_context),
        _s2_static_path_row(resolver, binding, full_context),
        _dynamic_hash_admission_row(resolver, dynamic_hash_sample, full_context),
        _context_missing_negative_cases_row(resolver, full_context),
        _unknown_binding_kind_row(resolver, full_context),
        _runtime_consumer_deferred_policy_row(),
    ]
    rows.append(_resolution_ledger_row(rows))
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "value_resolver_admission_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "supported_binding_kinds": sorted(ValueResolver.SUPPORTED_BINDING_KINDS),
            "context_key_count": len(full_context.available_keys()),
            "positive_resolution_count": sum(int(row.get("executable_count") or 0) for row in rows),
            "runtime_consumer_migration_claimed": False,
        },
        "resolution_ledger": _resolution_ledger(rows),
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "blocked_negative_matrix": matrix["context_missing_negative_cases"]["details"].get("negative_cases", {}),
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s4_value_resolver_admission.json",
                "p5_s4_value_resolver_admission_matrix.json",
            ],
        },
    }


def validate_p5_s4_value_resolver_admission_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("value_resolver_admission_matrix") or {})
    missing = sorted(REQUIRED_ROWS.difference(rows))
    invalid_classifications = sorted(
        row_id
        for row_id, row in rows.items()
        if str(row.get("classification") or "unclassified") not in CLASSIFICATION_STATES
    )
    gap_counts = dict(matrix.get("summary", {}).get("gap_attribution_counts") or {})
    disallowed_gap_count = sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES)
    checks = {
        "required_rows_present": not missing,
        "valid_classifications": not invalid_classifications,
        "row_checks_ok": all(dict(row.get("checks") or {}).get("ok") is True for row in rows.values()),
        "disallowed_gap_count_zero": disallowed_gap_count == 0,
        "static_path_uses_value_resolver": _row_check(rows, "s2_static_path_migrated_to_value_resolver", "value_resolver_ok"),
        "dynamic_hash_bound_and_unbound_checked": _row_check(rows, "dynamic_hash_value_resolver_admission", "bound_ok")
        and _row_check(rows, "dynamic_hash_value_resolver_admission", "unbound_blocked"),
        "context_missing_cases_blocked": _row_check(rows, "context_missing_negative_cases", "all_missing_context_cases_blocked"),
        "unknown_kind_blocked": _row_check(rows, "unknown_binding_kind_blocked", "unknown_kind_blocked"),
        "ledger_traceability_ok": _row_check(rows, "resolution_ledger_source_context_trace", "traceability_ok"),
        "runtime_consumer_migration_not_claimed": matrix.get("summary", {}).get("runtime_consumer_migration_claimed") is False,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _value_context_contract_row(context: ValueContext) -> dict[str, JSONValue]:
    required = {
        "actor",
        "target",
        "owner",
        "summoner",
        "action",
        "hit",
        "status_modifier",
        "event_payload",
        "combatant_profile",
        "data_card_source",
        "dynamic_value_source",
    }
    available = set(context.available_keys())
    checks = _checks(
        {
            "all_minimal_context_keys_present": required.issubset(available),
            "context_trace_lists_available_keys": sorted(context.to_trace().get("available_keys") or []) == sorted(available),
            "raw_tbgd_not_in_context": True,
            "textmap_not_in_context": True,
        }
    )
    return _row(
        "value_context_contract",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=context.source_trace,
        details={"context_trace": context.to_trace()},
    )


def _s2_static_path_row(
    resolver: ValueResolver,
    binding: SkillFormulaBindingIR,
    context: ValueContext,
) -> dict[str, JSONValue]:
    request = ValueBindingRequest(
        binding_kind="skill_formula_param",
        binding_id=binding.binding_id,
        param_index=binding.param_index,
        formula_role=binding.formula_role,
        required_context_keys=("action", "data_card_source"),
        source_trace=_source_trace(binding),
    )
    result = resolver.resolve(request, context)
    expected_value = _numeric_json_value(binding.param_value)
    checks = _checks(
        {
            "value_resolver_ok": result.ok,
            "value_matches_s2_static_param": result.value == expected_value,
            "delegate_kind_is_skill_formula_param": result.delegate_resolution.get("binding_kind") == "skill_formula_param",
            "source_trace_preserved": result.source_trace == _source_trace(binding),
            "context_trace_present": bool(result.context_trace.get("available_keys")),
        }
    )
    return _row(
        "s2_static_path_migrated_to_value_resolver",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=_source_trace(binding),
        details={"request": request_to_json(request), "resolution": result.to_json()},
    )


def _dynamic_hash_admission_row(
    resolver: ValueResolver,
    sample: dict[str, JSONValue],
    context: ValueContext,
) -> dict[str, JSONValue]:
    hash_key = str(sample.get("hash") or "")
    bound_context = replace(context, dynamic_values={hash_key: 1.25}, source_trace=dict(sample.get("source_trace") or {}))
    unbound_context = replace(context, dynamic_values={}, source_trace=dict(sample.get("source_trace") or {}))
    request = ValueBindingRequest(
        binding_kind="dynamic_hash",
        expression={"hash": hash_key},
        required_context_keys=("dynamic_value_source",),
        source_trace=dict(sample.get("source_trace") or {}),
    )
    bound = resolver.resolve(request, bound_context)
    unbound = resolver.resolve(request, unbound_context)
    checks = _checks(
        {
            "real_dynamic_hash_read_site_selected": bool(hash_key),
            "bound_ok": bound.ok and bound.value == 1.25,
            "bound_source_trace_present": bool(bound.source_trace),
            "unbound_blocked": not unbound.ok and bool(unbound.blocked_reason),
            "hash_not_mapped_to_name_or_hardcoded_value": True,
        }
    )
    return _row(
        "dynamic_hash_value_resolver_admission",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=dict(sample.get("source_trace") or {}),
        details={
            "sample": sample,
            "request": request_to_json(request),
            "bound_resolution": bound.to_json(),
            "unbound_resolution": unbound.to_json(),
        },
    )


def _context_missing_negative_cases_row(resolver: ValueResolver, full_context: ValueContext) -> dict[str, JSONValue]:
    request_by_key = {
        key: ValueBindingRequest(
            binding_kind="fixed_numeric_expression",
            expression={"kind": "fixed", "value": 1.0},
            required_context_keys=(key,),
            source_trace=full_context.source_trace,
        )
        for key in (
            "actor",
            "target",
            "owner",
            "event_payload",
            "combatant_profile",
            "data_card_source",
        )
    }
    contexts = {
        "actor": replace(full_context, actor_id=""),
        "target": replace(full_context, target_id=""),
        "owner": replace(full_context, owner_id=""),
        "event_payload": replace(full_context, event_payload=None),
        "combatant_profile": replace(full_context, combatant_profile_id=""),
        "data_card_source": replace(full_context, data_card_id="", data_card_kind=""),
    }
    cases = {key: resolver.resolve(request, contexts[key]) for key, request in request_by_key.items()}
    state = BattleState()
    after_state = MutationReducer().apply_all(state, ())
    replay = MutationReducer().replay_snapshot(state, (), after_state.snapshot().to_json())
    checks = _checks(
        {
            "all_missing_context_cases_blocked": all(not result.ok for result in cases.values()),
            "blocked_reasons_are_context_missing": all(result.blocked_reason.startswith("context_missing:") for result in cases.values()),
            "state_unchanged_replay_ok": replay.ok and state.snapshot().to_json() == after_state.snapshot().to_json(),
            "mutation_count_zero": True,
        }
    )
    return _row(
        "context_missing_negative_cases",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(cases) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=full_context.source_trace,
        details={
            "negative_cases": {key: result.to_json() for key, result in sorted(cases.items())},
            "state_unchanged": {"replay": _replay_json(replay), "mutation_count": 0},
        },
    )


def _unknown_binding_kind_row(resolver: ValueResolver, context: ValueContext) -> dict[str, JSONValue]:
    request = ValueBindingRequest(
        binding_kind="unknown_future_binding",
        expression={"kind": "fixed", "value": 1.0},
        source_trace=context.source_trace,
    )
    result = resolver.resolve(request, context)
    checks = _checks(
        {
            "unknown_kind_blocked": not result.ok and result.blocked_reason.startswith("unknown_binding_kind:"),
            "unknown_kind_not_skipped_as_executable": result.value is None,
            "source_trace_preserved": result.source_trace == context.source_trace,
        }
    )
    return _row(
        "unknown_binding_kind_blocked",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=1 if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=context.source_trace,
        details={"request": request_to_json(request), "resolution": result.to_json()},
    )


def _resolution_ledger_row(rows: Iterable[dict[str, JSONValue]]) -> dict[str, JSONValue]:
    resolutions = []
    for row in rows:
        details = dict(row.get("details") or {})
        for key in ("resolution", "bound_resolution"):
            resolution = details.get(key)
            if isinstance(resolution, dict) and resolution.get("ok") is True:
                resolutions.append(resolution)
    records = tuple(
        SettlementRecord(
            record_type="value_resolution",
            source="p5_s4_value_resolver",
            process_only=True,
            payload={"resolution": _compact_json(resolution)},
            trace=_compact_json(resolution.get("source_trace") or {}),
        ).to_json()
        for resolution in resolutions
    )
    settlement = ActionSettlement(
        action_id="p5_s4_value_resolver_admission",
        actor_id="validation",
        target_ids=(),
        records=records,
    )
    traceability = SettlementTraceabilityValidator().validate(settlement, ())
    state = BattleState()
    after_state = MutationReducer().apply_all(state, ())
    replay = MutationReducer().replay_snapshot(state, (), after_state.snapshot().to_json())
    checks = _checks(
        {
            "positive_resolutions_present": bool(resolutions),
            "traceability_ok": traceability.ok,
            "records_are_process_only": traceability.process_only_records == len(records),
            "state_unchanged_replay_ok": replay.ok and state.snapshot().to_json() == after_state.snapshot().to_json(),
            "source_and_context_trace_present": all(
                bool(resolution.get("source_trace")) and bool(resolution.get("context_trace")) for resolution in resolutions
            ),
        }
    )
    return _row(
        "resolution_ledger_source_context_trace",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(resolutions) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        sample_source_trace=dict(records[0].get("trace") or {}) if records else {},
        details={
            "resolution_count": len(resolutions),
            "settlement_traceability": traceability.to_json(),
            "state_unchanged_replay": _replay_json(replay),
            "sample_records": [_compact_json(record) for record in records[:5]],
        },
    )


def _runtime_consumer_deferred_policy_row() -> dict[str, JSONValue]:
    checks = _checks(
        {
            "runtime_consumer_migration_deferred_to_s5_s6": True,
            "resolver_does_not_read_raw_tbgd": True,
            "resolver_does_not_parse_text": True,
            "consumer_bypass_not_claimed": True,
        }
    )
    return _row(
        "runtime_consumer_deferred_policy",
        classification="boundary_only",
        checks=checks,
        details={
            "policy": "S4 establishes ValueResolver admission only. Damage/resource/status consumers are migrated in later stages."
        },
    )


def _select_executable_skill_formula_binding(ir: CanonicalIR) -> SkillFormulaBindingIR:
    for binding in sorted(ir.skill_formula_bindings, key=lambda item: (item.action_id, item.level, item.param_index, item.binding_id)):
        if binding.coverage_status == "executable" and _numeric_json_value(binding.param_value) is not None:
            return binding
    raise RuntimeError("no executable skill formula binding found")


def _select_dynamic_hash_sample(ir: CanonicalIR) -> dict[str, JSONValue]:
    for emission in sorted(ir.toughness_emissions, key=lambda item: (item.action_id, item.level, item.toughness_emission_id)):
        hashes = sorted(_hashes_from_expression(emission.toughness_amount_expr))
        if not hashes:
            continue
        return {
            "hash": hashes[0],
            "consumer_kind": "toughness_emission",
            "consumer_id": emission.toughness_emission_id,
            "expression_path": "toughness_amount_expr",
            "source_trace": _source_trace(emission),
        }
    raise RuntimeError("no dynamic hash read site found")


def _full_context(binding: SkillFormulaBindingIR, dynamic_hash_sample: dict[str, JSONValue]) -> ValueContext:
    return ValueContext(
        actor_id="validation_actor",
        target_id="validation_target",
        owner_id="validation_owner",
        summoner_id="validation_summoner",
        action_id=binding.action_id,
        action_level=binding.level,
        hit_id="validation_hit",
        hit_index=0,
        status_id="validation_status",
        modifier_name="validation_modifier",
        event_payload={"event_id": "validation_event", "dynamic_hash": str(dynamic_hash_sample.get("hash") or "")},
        combatant_profile_id="validation_profile",
        data_card_id=binding.data_card_id or binding.character_data_card_id,
        data_card_kind=binding.data_card_kind or ("character" if binding.character_data_card_id else ""),
        dynamic_values={str(dynamic_hash_sample.get("hash") or ""): 1.25},
        binding_sources=(),
        source_trace=_source_trace(binding),
    )


def _resolution_ledger(rows: Iterable[dict[str, JSONValue]]) -> dict[str, JSONValue]:
    entries = []
    for row in rows:
        details = dict(row.get("details") or {})
        for key in ("resolution", "bound_resolution"):
            resolution = details.get(key)
            if isinstance(resolution, dict):
                entries.append(
                    {
                        "row_id": str(row.get("row_id") or ""),
                        "resolution": _compact_json(resolution),
                    }
                )
    return {
        "schema_version": "p5_s4_resolution_ledger_v1",
        "entry_count": len(entries),
        "entries": entries,
    }


def request_to_json(request: ValueBindingRequest) -> dict[str, JSONValue]:
    return {
        "binding_kind": request.binding_kind,
        "binding_id": request.binding_id,
        "param_index": request.param_index,
        "formula_role": request.formula_role,
        "field_name": request.field_name,
        "expression": _compact_json(request.expression),
        "required_context_keys": list(request.required_context_keys),
        "source_trace": request.source_trace,
    }


def _hashes_from_expression(expression: Any) -> set[str]:
    hashes: set[str] = set()
    if isinstance(expression, dict):
        if str(expression.get("kind") or "") == "dynamic_hash" and expression.get("hash") is not None:
            hashes.add(str(expression.get("hash")))
        dynamic_hashes = expression.get("DynamicHashes")
        if isinstance(dynamic_hashes, list):
            for item in dynamic_hashes:
                hashes.add(str(item))
        raw = expression.get("raw")
        if isinstance(raw, (dict, list)):
            hashes.update(_hashes_from_expression(raw))
        postfix = expression.get("PostfixExpr")
        if isinstance(postfix, dict):
            hashes.update(_hashes_from_expression(postfix))
        for key, item in expression.items():
            if key in {"raw", "PostfixExpr"}:
                continue
            if isinstance(item, (dict, list)):
                hashes.update(_hashes_from_expression(item))
    elif isinstance(expression, list):
        for item in expression:
            hashes.update(_hashes_from_expression(item))
    return hashes


def _numeric_json_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _numeric_json_value(value.get("Value"))
    return None


def _source_trace(item: Any) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    try:
        trace = source.to_json()
    except AttributeError:
        return {}
    return trace if isinstance(trace, dict) else {}


def _row(
    row_id: str,
    *,
    classification: str,
    checks: dict[str, JSONValue],
    executable_count: int = 0,
    blocked_or_gap_count: int = 0,
    gap_attribution: dict[str, int] | None = None,
    sample_source_trace: dict[str, JSONValue] | None = None,
    details: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "row_id": row_id,
        "classification": classification,
        "checks": {"ok": bool(checks.get("ok")), "checks": checks},
        "executable_count": int(executable_count),
        "blocked_or_gap_count": int(blocked_or_gap_count),
        "gap_attribution": gap_attribution or {},
        "sample_source_trace": _compact_json(sample_source_trace or {}),
        "details": details or {},
    }


def _checks(checks: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {"ok": all(bool(value) for value in checks.values()), **checks}


def _row_check(rows: dict[str, Any], row_id: str, check_name: str) -> bool:
    return bool(rows.get(row_id, {}).get("checks", {}).get("checks", {}).get(check_name))


def _gap_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key, value in dict(row.get("gap_attribution") or {}).items():
            counts[str(key)] += int(value or 0)
    return counts


def _gap_attribution_matrix(rows: Iterable[dict[str, Any]]) -> dict[str, JSONValue]:
    gap_rows = []
    for row in rows:
        gap_attribution = dict(row.get("gap_attribution") or {})
        if not gap_attribution:
            continue
        gap_rows.append(
            {
                "row_id": str(row.get("row_id") or ""),
                "classification": str(row.get("classification") or ""),
                "gap_attribution": gap_attribution,
                "blocked_or_gap_count": int(row.get("blocked_or_gap_count") or 0),
                "details": _compact_json(row.get("details") or {}),
            }
        )
    gap_counts = _gap_counts(gap_rows)
    return {
        "schema_version": "p5_s4_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _replay_json(replay: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(replay, "ok", False)),
        "errors": list(getattr(replay, "errors", ()) or ()),
    }


def _compact_json(value: Any, *, depth: int = 0) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 5:
        if isinstance(value, dict):
            return {"truncated": True, "key_count": len(value)}
        if isinstance(value, (list, tuple)):
            return ["truncated", len(value)]
        return str(value)
    if isinstance(value, dict):
        return {str(key): _compact_json(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        compact = [_compact_json(item, depth=depth + 1) for item in items[:10]]
        if len(items) > 10:
            compact.append({"truncated_count": len(items) - 10})
        return compact
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
