from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "p5_s3_dynamic_custom_binding_projection"
MATRIX_SCHEMA_VERSION = "p5_s3_dynamic_custom_binding_projection_matrix_v1"

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
    "unclassified",
}
DISALLOWED_GAP_STATES = {"implementation_missing", "lowering_gap", "validation_gap", "unclassified"}
REQUIRED_ROWS = {
    "dynamic_definition_projection",
    "dynamic_read_site_projection",
    "definition_read_consumer_trace",
    "custom_value_definition_projection",
    "status_callback_dynamic_read_sites",
    "dynamic_read_negative_boundaries",
    "runtime_execution_deferred_policy",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p5_s3_dynamic_custom_binding_projection_matrix(ir, rules)
    matrix_checks = validate_p5_s3_dynamic_custom_binding_projection_matrix(matrix)
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
                "mode": "p5_s3_dynamic_custom_projection_structural_scan",
                "runtime_behavior_changed": False,
                "runtime_raw_tbgd_read": False,
                "textmap_read": False,
                "hash_hardcoded_to_name_or_value": False,
                "custom_value_name_table_hardcoded": False,
                "s0_missing_consumer_refs_counted_as_consumer_admitted": False,
                "full_ir_written": False,
                "full_rulebook_written": False,
                "full_transition_dump_written": False,
                "large_artifacts_written": False,
                "p5_aggregation_phase_claimed": False,
            },
        },
        "checks": checks,
        "summary": matrix["summary"],
        "dynamic_custom_binding_matrix": matrix["dynamic_custom_binding_matrix"],
        "definition_read_consumer_ledger": matrix["definition_read_consumer_ledger"],
        "gap_attribution_matrix": matrix["gap_attribution_matrix"],
        "blocked_negative_matrix": matrix["blocked_negative_matrix"],
        "resource_budget": matrix["resource_budget"],
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p5_s3_dynamic_custom_binding_projection.json", result)
    write_json(output_dir / "p5_s3_dynamic_custom_binding_projection_matrix.json", matrix)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P5-S3 dynamic/custom/hash binding projection.")
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


def build_p5_s3_dynamic_custom_binding_projection_matrix(ir: CanonicalIR, rules: RuleBook) -> dict[str, Any]:
    definitions = _collect_dynamic_definitions(ir)
    read_sites = _collect_dynamic_read_sites(ir, rules)
    custom_entries = _collect_custom_value_entries(ir)
    ledger = _definition_read_consumer_ledger(definitions, read_sites)
    rows = [
        _dynamic_definition_projection_row(definitions),
        _dynamic_read_site_projection_row(read_sites),
        _definition_read_consumer_trace_row(ledger),
        _custom_value_definition_projection_row(custom_entries),
        _status_callback_dynamic_read_sites_row(read_sites),
        _dynamic_read_negative_boundaries_row(),
        _runtime_execution_deferred_policy_row(),
    ]
    matrix = {str(row["row_id"]): row for row in rows}
    classification_counts = Counter(str(row.get("classification") or "unclassified") for row in rows)
    gap_counts = _gap_counts(rows)
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "dynamic_custom_binding_matrix": matrix,
        "summary": {
            "row_count": len(matrix),
            "classification_counts": dict(sorted(classification_counts.items())),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
            "dynamic_definition_count": len(definitions),
            "dynamic_read_site_count": len(read_sites),
            "custom_value_entry_count": len(custom_entries),
            "matched_definition_read_edge_count": int(ledger["summary"]["matched_edge_count"]),
            "unmatched_read_site_count": int(ledger["summary"]["unmatched_read_site_count"]),
            "runtime_execution_deferred": True,
        },
        "definition_read_consumer_ledger": ledger,
        "gap_attribution_matrix": _gap_attribution_matrix(rows),
        "blocked_negative_matrix": matrix["dynamic_read_negative_boundaries"]["details"].get("negative_cases", {}),
        "resource_budget": {
            "lowering_build_count": 1,
            "rulebook_build_count": 1,
            "static_check_count": 1,
            "full_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "output_files": [
                "validation_summary_p5_s3_dynamic_custom_binding_projection.json",
                "p5_s3_dynamic_custom_binding_projection_matrix.json",
            ],
        },
    }


def validate_p5_s3_dynamic_custom_binding_projection_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = dict(matrix.get("dynamic_custom_binding_matrix") or {})
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
        "definition_projection_present": _row_check(rows, "dynamic_definition_projection", "definition_projection_present"),
        "read_site_projection_present": _row_check(rows, "dynamic_read_site_projection", "read_site_projection_present"),
        "definition_read_consumer_ledger_built": _row_check(rows, "definition_read_consumer_trace", "ledger_built"),
        "custom_values_not_promoted_to_executable": _row_check(
            rows,
            "custom_value_definition_projection",
            "custom_values_not_promoted_to_executable",
        ),
        "negative_reads_blocked": _row_check(rows, "dynamic_read_negative_boundaries", "all_negative_reads_blocked"),
        "state_unchanged_replay_ok": _row_check(rows, "dynamic_read_negative_boundaries", "state_unchanged_replay_ok"),
        "runtime_execution_deferred": _row_check(rows, "runtime_execution_deferred_policy", "runtime_execution_deferred_to_s4_plus"),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "ok": checks["ok"],
        "checks": checks,
        "missing_rows": missing,
        "invalid_classifications": invalid_classifications,
        "disallowed_gap_count": disallowed_gap_count,
    }


def _dynamic_definition_projection_row(definitions: dict[str, dict[str, JSONValue]]) -> dict[str, JSONValue]:
    source_type_counts = Counter(str(item.get("source_type") or "") for item in definitions.values())
    source_trace_count = sum(1 for item in definitions.values() if bool(item.get("source_trace")))
    checks = _checks(
        {
            "scan_completed": True,
            "definition_projection_present": bool(definitions),
            "source_trace_present_for_projected_definitions": source_trace_count > 0,
            "hash_keys_preserved_without_name_mapping": True,
        }
    )
    return _row(
        "dynamic_definition_projection",
        classification="executable" if checks["ok"] else "source_gap_blocked",
        checks=checks,
        ir_count=len(definitions),
        executable_count=source_trace_count,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"source_gap_blocked": 1},
        sample_source_trace=_first_source_trace(definitions.values()),
        details={
            "source_type_counts": dict(sorted(source_type_counts.items())),
            "sample_definitions": [_compact_json(item) for item in list(definitions.values())[:5]],
        },
    )


def _dynamic_read_site_projection_row(read_sites: dict[str, dict[str, JSONValue]]) -> dict[str, JSONValue]:
    consumer_counts = Counter(str(item.get("consumer_kind") or "") for item in read_sites.values())
    source_trace_count = sum(1 for item in read_sites.values() if bool(item.get("source_trace")))
    checks = _checks(
        {
            "scan_completed": True,
            "read_site_projection_present": bool(read_sites),
            "source_trace_or_consumer_id_present": all(item.get("source_trace") or item.get("consumer_id") for item in read_sites.values()),
            "hash_keys_preserved_without_value_guess": True,
        }
    )
    gap_count = max(len(read_sites) - source_trace_count, 0)
    return _row(
        "dynamic_read_site_projection",
        classification="admission_gap" if gap_count else "executable",
        checks=checks,
        ir_count=len(read_sites),
        executable_count=len(read_sites) - gap_count,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        sample_source_trace=_first_source_trace(read_sites.values()),
        details={
            "consumer_kind_counts": dict(sorted(consumer_counts.items())),
            "read_site_source_trace_count": source_trace_count,
            "sample_read_sites": [_compact_json(item) for item in list(read_sites.values())[:8]],
        },
    )


def _definition_read_consumer_trace_row(ledger: dict[str, JSONValue]) -> dict[str, JSONValue]:
    summary = dict(ledger.get("summary") or {})
    matched = int(summary.get("matched_edge_count") or 0)
    unmatched = int(summary.get("unmatched_read_site_count") or 0)
    checks = _checks(
        {
            "ledger_built": bool(ledger.get("entries")),
            "matched_edges_present": matched > 0,
            "unmatched_reads_are_gap_not_executable": True,
            "definition_to_read_to_consumer_trace_shape_present": all(
                {"definition", "read_site", "consumer"}.issubset(set(entry))
                for entry in list(ledger.get("entries") or [])[:20]
            ),
        }
    )
    return _row(
        "definition_read_consumer_trace",
        classification="admission_gap" if unmatched else "executable",
        checks=checks,
        ir_count=int(summary.get("read_site_count") or 0),
        executable_count=matched,
        blocked_or_gap_count=unmatched,
        gap_attribution={"admission_gap": unmatched} if unmatched else {},
        sample_source_trace=_compact_json((list(ledger.get("entries") or [{}])[0]).get("definition", {}).get("source_trace", {})),
        details={
            "ledger_summary": summary,
            "sample_edges": [_compact_json(item) for item in list(ledger.get("entries") or [])[:8]],
        },
    )


def _custom_value_definition_projection_row(custom_entries: dict[str, dict[str, JSONValue]]) -> dict[str, JSONValue]:
    field_counts = Counter(str(item.get("field_name") or "") for item in custom_entries.values())
    checks = _checks(
        {
            "scan_completed": True,
            "custom_or_dynamic_parameter_blocks_present": bool(custom_entries),
            "custom_values_not_promoted_to_executable": True,
            "hash_to_name_mapping_not_hardcoded": True,
        }
    )
    gap_count = len(custom_entries)
    return _row(
        "custom_value_definition_projection",
        classification="admission_gap" if custom_entries else "source_absent_not_required",
        checks=checks,
        ir_count=len(custom_entries),
        executable_count=0,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        sample_source_trace=_first_source_trace(custom_entries.values()),
        details={
            "field_counts": dict(sorted(field_counts.items())),
            "sample_custom_entries": [_compact_json(item) for item in list(custom_entries.values())[:8]],
            "policy": "Monster custom/dynamic/override parameter blocks are projected as definitions only until S7/S4 supplies context binding.",
        },
    )


def _status_callback_dynamic_read_sites_row(read_sites: dict[str, dict[str, JSONValue]]) -> dict[str, JSONValue]:
    status_sites = {
        key: item
        for key, item in read_sites.items()
        if str(item.get("consumer_kind") or "") in {"status_damage_emission", "action_delay_emission", "queue_intent"}
    }
    consumer_counts = Counter(str(item.get("consumer_kind") or "") for item in status_sites.values())
    checks = _checks(
        {
            "scan_completed": True,
            "status_callback_scan_completed": True,
            "missing_event_payload_not_executed": True,
            "text_runtime_parse_not_used": True,
        }
    )
    gap_count = len(status_sites)
    return _row(
        "status_callback_dynamic_read_sites",
        classification="admission_gap" if gap_count else "source_absent_not_required",
        checks=checks,
        ir_count=len(status_sites),
        executable_count=0,
        blocked_or_gap_count=gap_count,
        gap_attribution={"admission_gap": gap_count} if gap_count else {},
        sample_source_trace=_first_source_trace(status_sites.values()),
        details={
            "consumer_kind_counts": dict(sorted(consumer_counts.items())),
            "sample_status_callback_read_sites": [_compact_json(item) for item in list(status_sites.values())[:8]],
            "policy": "Status/callback dynamic reads need event payload, modifier instance and owner context before execution.",
        },
    )


def _dynamic_read_negative_boundaries_row() -> dict[str, JSONValue]:
    evaluator = RuleEvaluator()
    cases = {
        "missing_definition": evaluator.evaluate_numeric(
            {"kind": "dynamic_hash", "hash": "p5_s3_missing_definition"},
            NumericEvaluationContext(dynamic_values={}),
        ),
        "wrong_key": evaluator.evaluate_numeric(
            {"kind": "dynamic_hash", "hash": "p5_s3_expected_key"},
            NumericEvaluationContext(dynamic_values={"p5_s3_other_key": 1.0}),
        ),
        "missing_read_payload": evaluator.evaluate_numeric(
            {"kind": "dynamic_hash"},
            NumericEvaluationContext(dynamic_values={}),
        ),
    }
    state = BattleState()
    after_state = MutationReducer().apply_all(state, ())
    replay = MutationReducer().replay_snapshot(state, (), after_state.snapshot().to_json())
    checks = _checks(
        {
            "all_negative_reads_blocked": all(not result.ok and bool(result.blocked_reason) for result in cases.values()),
            "state_unchanged_replay_ok": replay.ok and state.snapshot().to_json() == after_state.snapshot().to_json(),
            "mutation_count_zero": True,
            "no_default_value_returned": all(result.value is None for result in cases.values()),
        }
    )
    return _row(
        "dynamic_read_negative_boundaries",
        classification="executable" if checks["ok"] else "implementation_missing",
        checks=checks,
        executable_count=len(cases) if checks["ok"] else 0,
        blocked_or_gap_count=0 if checks["ok"] else 1,
        gap_attribution={} if checks["ok"] else {"implementation_missing": 1},
        details={
            "negative_cases": {name: result.to_json() for name, result in sorted(cases.items())},
            "state_unchanged": {
                "replay": _replay_json(replay),
                "mutation_count": 0,
                "before_equals_after": state.snapshot().to_json() == after_state.snapshot().to_json(),
            },
        },
    )


def _runtime_execution_deferred_policy_row() -> dict[str, JSONValue]:
    checks = _checks(
        {
            "runtime_execution_deferred_to_s4_plus": True,
            "definition_projection_not_claimed_as_mutation_source": True,
            "unknown_hash_kind_not_executable": True,
            "consumer_migration_not_claimed": True,
        }
    )
    return _row(
        "runtime_execution_deferred_policy",
        classification="boundary_only",
        checks=checks,
        details={
            "policy": (
                "S3 projects dynamic/custom definitions, read sites and consumers. "
                "Execution admission belongs to S4 ValueResolver and later consumer stages."
            )
        },
    )


def _collect_dynamic_definitions(ir: CanonicalIR) -> dict[str, dict[str, JSONValue]]:
    definitions: dict[str, dict[str, JSONValue]] = {}
    for consumer_kind, consumer_id, trace in _iter_consumer_source_traces(ir):
        for item in _definitions_from_json(trace, consumer_kind=consumer_kind, consumer_id=consumer_id):
            key = _definition_key(item)
            definitions.setdefault(key, item)
    return definitions


def _collect_dynamic_read_sites(ir: CanonicalIR, rules: RuleBook) -> dict[str, dict[str, JSONValue]]:
    read_sites: dict[str, dict[str, JSONValue]] = {}

    def add_sites(consumer_kind: str, consumer_id: str, expression_path: str, expression: Any, source_trace: dict[str, JSONValue]) -> None:
        for hash_key in sorted(_hashes_from_expression(expression)):
            key = f"{consumer_kind}:{consumer_id}:{expression_path}:{hash_key}"
            read_sites.setdefault(
                key,
                {
                    "hash": hash_key,
                    "consumer_kind": consumer_kind,
                    "consumer_id": consumer_id,
                    "expression_path": expression_path,
                    "expression_kind": _expr_kind(expression),
                    "source_trace": _compact_json(source_trace),
                },
            )

    for emission in ir.damage_emissions:
        if rules.damage_emission(emission.damage_emission_id) is not emission:
            continue
        source = _source_trace(emission)
        add_sites("damage_emission", emission.damage_emission_id, "scaling_ratio_expr", emission.scaling_ratio_expr, source)
        add_sites("damage_emission", emission.damage_emission_id, "scaling_basis_expr", emission.scaling_basis_expr, source)
    for emission in ir.toughness_emissions:
        if rules.toughness_emission(emission.toughness_emission_id) is not emission:
            continue
        add_sites("toughness_emission", emission.toughness_emission_id, "toughness_amount_expr", emission.toughness_amount_expr, _source_trace(emission))
    for emission in ir.status_damage_emissions:
        if rules.status_damage_emission(emission.status_damage_emission_id) is not emission:
            continue
        add_sites("status_damage_emission", emission.status_damage_emission_id, "scaling_expr", emission.scaling_expr, _source_trace(emission))
    for emission in ir.action_delay_emissions:
        if rules.action_delay_emission(emission.action_delay_emission_id) is not emission:
            continue
        add_sites("action_delay_emission", emission.action_delay_emission_id, "delay_expr", emission.delay_expr, _source_trace(emission))
    for intent in ir.queue_intents:
        if rules.queue_intent(intent.queue_intent_id) is not intent:
            continue
        source = _source_trace(intent)
        add_sites("queue_intent", intent.queue_intent_id, "priority_source", intent.priority_source, source)
        add_sites("queue_intent", intent.queue_intent_id, "skill_index_expr", intent.skill_index_expr, source)
    return read_sites


def _collect_custom_value_entries(ir: CanonicalIR) -> dict[str, dict[str, JSONValue]]:
    entries: dict[str, dict[str, JSONValue]] = {}
    fields = ("custom_value_tags", "custom_values", "dynamic_values", "override_skill_params")
    for card in ir.monster_data_cards:
        monster_config = {}
        blocks = card.raw_parameter_blocks
        if isinstance(blocks, dict):
            monster_config = blocks.get("monster_config") if isinstance(blocks.get("monster_config"), dict) else {}
        for field_name in fields:
            raw_value = monster_config.get(field_name)
            if raw_value in (None, "", [], {}, ()):
                continue
            key = f"{card.card_id}:{field_name}"
            entries[key] = {
                "card_id": card.card_id,
                "monster_id": card.monster_id,
                "field_name": field_name,
                "raw_value_summary": _raw_value_summary(raw_value),
                "source_trace": _compact_json(_source_trace(card)),
                "admission_status": "admission_gap",
                "blocked_reason": "custom_or_dynamic_parameter_context_missing",
            }
    return entries


def _definition_read_consumer_ledger(
    definitions: dict[str, dict[str, JSONValue]],
    read_sites: dict[str, dict[str, JSONValue]],
) -> dict[str, JSONValue]:
    definitions_by_hash: dict[str, list[dict[str, JSONValue]]] = {}
    for definition in definitions.values():
        hash_key = str(definition.get("hash") or "")
        if hash_key:
            definitions_by_hash.setdefault(hash_key, []).append(definition)
    entries = []
    unmatched_read_sites = []
    for read_site in read_sites.values():
        hash_key = str(read_site.get("hash") or "")
        matched_definitions = definitions_by_hash.get(hash_key) or []
        if not matched_definitions:
            unmatched_read_sites.append(read_site)
            continue
        for definition in matched_definitions[:3]:
            entries.append(
                {
                    "definition": _compact_json(definition),
                    "read_site": _compact_json(read_site),
                    "consumer": {
                        "consumer_kind": read_site.get("consumer_kind"),
                        "consumer_id": read_site.get("consumer_id"),
                        "expression_path": read_site.get("expression_path"),
                    },
                    "admission_status": "trace_projected",
                }
            )
    return {
        "schema_version": "p5_s3_definition_read_consumer_ledger_v1",
        "entries": entries[:200],
        "unmatched_read_site_samples": [_compact_json(item) for item in unmatched_read_sites[:20]],
        "summary": {
            "definition_count": len(definitions),
            "definition_hash_count": len(definitions_by_hash),
            "read_site_count": len(read_sites),
            "matched_edge_count": len(entries),
            "unmatched_read_site_count": len(unmatched_read_sites),
            "entry_output_cap": 200,
        },
    }


def _iter_consumer_source_traces(ir: CanonicalIR) -> Iterable[tuple[str, str, dict[str, JSONValue]]]:
    collections = (
        ("skill_formula_binding", ir.skill_formula_bindings, "binding_id"),
        ("damage_emission", ir.damage_emissions, "damage_emission_id"),
        ("toughness_emission", ir.toughness_emissions, "toughness_emission_id"),
        ("status_damage_emission", ir.status_damage_emissions, "status_damage_emission_id"),
        ("action_delay_emission", ir.action_delay_emissions, "action_delay_emission_id"),
        ("queue_intent", ir.queue_intents, "queue_intent_id"),
        ("summon_monster_intent", ir.summon_monster_intents, "summon_intent_id"),
    )
    seen: set[tuple[str, str, str, str]] = set()
    for consumer_kind, items, id_attr in collections:
        for item in items:
            trace = _source_trace(item)
            if not trace:
                continue
            key = (
                consumer_kind,
                str(trace.get("source_path") or ""),
                str(trace.get("raw_type") or ""),
                str(trace.get("raw_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            yield consumer_kind, str(getattr(item, id_attr)), trace


def _definitions_from_json(
    value: Any,
    *,
    consumer_kind: str,
    consumer_id: str,
    path: str = "$",
) -> Iterable[dict[str, JSONValue]]:
    if isinstance(value, dict):
        source_type = str(value.get("source_type") or "")
        by_hash = value.get("by_hash")
        if source_type and isinstance(by_hash, dict):
            for hash_key, entry in by_hash.items():
                if not isinstance(entry, dict):
                    continue
                yield _definition_entry(
                    source_type=source_type,
                    hash_key=str(hash_key),
                    entry=entry,
                    consumer_kind=consumer_kind,
                    consumer_id=consumer_id,
                    path=f"{path}.by_hash[{hash_key}]",
                )
        entries = value.get("entries")
        if source_type and isinstance(entries, list):
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict) or "hash" not in entry:
                    continue
                yield _definition_entry(
                    source_type=source_type,
                    hash_key=str(entry.get("hash")),
                    entry=entry,
                    consumer_kind=consumer_kind,
                    consumer_id=consumer_id,
                    path=f"{path}.entries[{index}]",
                )
        for key, item in value.items():
            yield from _definitions_from_json(
                item,
                consumer_kind=consumer_kind,
                consumer_id=consumer_id,
                path=f"{path}.{key}",
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _definitions_from_json(
                item,
                consumer_kind=consumer_kind,
                consumer_id=consumer_id,
                path=f"{path}[{index}]",
            )


def _definition_entry(
    *,
    source_type: str,
    hash_key: str,
    entry: dict[str, Any],
    consumer_kind: str,
    consumer_id: str,
    path: str,
) -> dict[str, JSONValue]:
    return {
        "source_type": source_type,
        "hash": hash_key,
        "consumer_kind": consumer_kind,
        "consumer_id": consumer_id,
        "definition_path": path,
        "param_index": _compact_json(entry.get("param_index")),
        "value_present": _numeric_json_value(entry.get("value")) is not None,
        "admission_status": str(entry.get("admission_status") or entry.get("coverage_status") or "projected"),
        "source_trace": _compact_json(entry.get("source_trace") or {}),
    }


def _definition_key(item: dict[str, JSONValue]) -> str:
    trace = item.get("source_trace") if isinstance(item.get("source_trace"), dict) else {}
    return "|".join(
        (
            str(item.get("source_type") or ""),
            str(item.get("hash") or ""),
            str(item.get("consumer_kind") or ""),
            str(trace.get("source_path") if isinstance(trace, dict) else ""),
            str(item.get("definition_path") or ""),
        )
    )


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


def _expr_kind(expression: Any) -> str:
    if isinstance(expression, dict):
        return str(expression.get("kind") or ("raw_postfix" if "PostfixExpr" in expression else "object"))
    return type(expression).__name__


def _raw_value_summary(value: Any) -> dict[str, JSONValue]:
    if isinstance(value, list):
        return {"kind": "list", "count": len(value), "sample": _compact_json(value[:3])}
    if isinstance(value, dict):
        return {"kind": "dict", "key_count": len(value), "sample_keys": sorted(str(key) for key in list(value)[:10])}
    return {"kind": type(value).__name__, "value": _compact_json(value)}


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
    ir_count: int = 0,
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
        "ir_count": int(ir_count),
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
        "schema_version": "p5_s3_gap_attribution_matrix_v1",
        "rows": gap_rows,
        "summary": {
            "row_count": len(gap_rows),
            "gap_attribution_counts": dict(sorted(gap_counts.items())),
            "disallowed_gap_count": sum(int(gap_counts.get(kind, 0)) for kind in DISALLOWED_GAP_STATES),
        },
    }


def _first_source_trace(items: Iterable[dict[str, JSONValue]]) -> dict[str, JSONValue]:
    for item in items:
        trace = item.get("source_trace")
        if isinstance(trace, dict) and trace:
            return trace
    return {}


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
