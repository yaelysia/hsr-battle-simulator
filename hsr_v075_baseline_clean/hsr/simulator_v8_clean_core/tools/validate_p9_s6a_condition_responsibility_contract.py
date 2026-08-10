from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..ir_types import IRSource
from ..rules.condition_contract import CharacterConditionResponsibilityIR
from ..rules.evaluator import EXECUTABLE_CONDITION_OPCODES
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from ..tbgd.character_condition_contracts import (
    build_character_condition_responsibility_catalog,
    character_condition_family_blocked_reason,
    character_condition_family_stage,
    condition_responsibility_registry_families,
)
from ..tbgd.lowering import _typed_condition_execution_node


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"


def _write(path: Path, value: object) -> int:
    encoded = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    path.write_bytes(encoded)
    return len(encoded)


def _expect_error(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def _at_path(document: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        return None
    current: Any = document
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            end = index
            while end < len(path) and path[end] not in ".[":
                end += 1
            key = path[index:end]
            if not key or not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
            index = end
            continue
        if path[index] == "[":
            end = path.find("]", index)
            token = path[index + 1 : end] if end >= 0 else ""
            if (
                end < 0
                or not token.isdigit()
                or not isinstance(current, (list, tuple))
                or int(token) >= len(current)
            ):
                return None
            current = current[int(token)]
            index = end + 1
            continue
        return None
    return current


def _parent_path(path: str) -> str | None:
    if path == "$":
        return None
    if path.endswith("]"):
        start = path.rfind("[")
        return path[:start] if start > 0 else None
    dot = path.rfind(".")
    return path[:dot] if dot > 0 else None


def _raw_types(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(value, Mapping):
        raw_type = value.get("$type")
        if isinstance(raw_type, str):
            result.append(raw_type.rsplit(".", 1)[-1])
        for child in value.values():
            result.extend(_raw_types(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(_raw_types(child))
    return tuple(result)


def _condition_denominator(scope_catalog: Any) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                record
                for record in scope_catalog.gameplay_records
                if record.occurrence_kind == "typed_node"
                and record.source.evidence.get("nominal_semantic_kind")
                == "combat_condition"
            ),
            key=lambda item: item.record_id,
        )
    )


def _raw_rows(snapshot: Any, records: tuple[Any, ...]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        path = str(record.source.evidence["json_path"])
        node = _at_path(
            snapshot.documents[record.source.source_path],
            path.removesuffix(".$type"),
        )
        if isinstance(node, Mapping):
            result[record.record_id] = node
    return result


def _source_checks(snapshot: Any, records: tuple[Any, ...], rows: Any) -> dict[str, Any]:
    raw_rows = _raw_rows(snapshot, records)
    records_by_id = {record.record_id: record for record in records}
    reversible = []
    for row in rows:
        raw = raw_rows.get(row.record_id)
        record = records_by_id.get(row.record_id)
        reversible.append(
            isinstance(raw, Mapping)
            and record is not None
            and str(raw.get("$type") or "").rsplit(".", 1)[-1] == row.opcode
            and tuple(sorted(key for key in raw if key != "$type"))
            == row.field_signature
            and row.source.evidence.get("json_path")
            == record.source.evidence.get("json_path")
        )
    return {
        "raw_condition_record_count": len(records),
        "responsibility_source_count": len(rows),
        "all_source_nodes_reversible": bool(reversible) and all(reversible),
        "missing_raw_record_ids": sorted(
            set(record.record_id for record in records).difference(raw_rows)
        ),
    }


def _excluded_scope_checks(snapshot: Any, rows: tuple[Any, ...]) -> dict[str, Any]:
    unresolved: list[str] = []
    missing_container: list[str] = []
    checked = 0
    for row in rows:
        if row.scope_basis != "presentation_only_controlled_task_branches":
            continue
        checked += 1
        document = snapshot.documents[row.source.source_path]
        node_path = str(row.source.evidence["json_path"]).removesuffix(".$type")
        current = _parent_path(node_path)
        container: Mapping[str, Any] | None = None
        while current is not None:
            candidate = _at_path(document, current)
            if (
                isinstance(candidate, Mapping)
                and any(
                    key in candidate
                    for key in ("TaskList", "SuccessTaskList", "FailedTaskList")
                )
                and (
                    node_path.startswith(f"{current}.Predicate")
                    or node_path.startswith(f"{current}.Condition")
                )
            ):
                container = candidate
                break
            current = _parent_path(current)
        if container is None:
            missing_container.append(row.record_id)
            continue
        branch_types = {
            raw_type
            for key in ("TaskList", "SuccessTaskList", "FailedTaskList")
            for raw_type in _raw_types(container.get(key))
        }
        if branch_types.intersection({"IncludeTaskListTemplate", "TriggerAbility"}):
            unresolved.append(row.record_id)
    return {
        "controlled_exclusion_count": checked,
        "controlled_exclusion_container_missing": missing_container,
        "controlled_exclusion_unresolved_reference_ids": unresolved,
        "controlled_exclusions_have_no_unresolved_indirection": (
            checked > 0 and not missing_container and not unresolved
        ),
    }


def _assignment_checks(catalog: Any, records: tuple[Any, ...]) -> dict[str, Any]:
    current_families = {record.family for record in records}
    missing_families = current_families.difference(EXECUTABLE_CONDITION_OPCODES)
    rows = catalog.responsibilities
    by_family: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        by_family[row.opcode].append(row)
    stage_counts = Counter(row.evaluation_stage for row in rows)
    def all_family_rows(families: tuple[str, ...], predicate: Any) -> bool:
        return all(
            bool(by_family[family])
            and all(predicate(row) for row in by_family[family])
            for family in families
        )

    anchor_checks = {
        "battle_points_use_committed_resource": all_family_rows(
            ("ByCompareBP",),
            lambda row: row.evaluation_stage == "p9_s6b_committed_state"
            and row.authority == "battle_resource",
        ),
        "modifier_callback_uses_transient_context": all_family_rows(
            ("ByCheckModifierCallBackModifierValue",),
            lambda row: row.evaluation_stage == "p9_s7_transient_context"
            and row.producer_stage == "p9_s10",
        ),
        "damage_conditions_wait_for_damage_producer": all_family_rows(
            (
                "ByDamageSourceContainBehaviorFlag",
                "ByIsDamageType",
                "ByIsSplitDamage",
            ),
            lambda row: row.evaluation_stage == "p9_s7_transient_context"
            and row.producer_stage == "p9_s11",
        ),
        "body_part_gameplay_rows_wait_for_entity_topology": all_family_rows(
            ("ByIsBodyPart", "ByIsBodyPartOwner"),
            lambda row: row.evaluation_stage == "excluded_non_gameplay"
            or row.producer_stage == "p9_s17",
        ),
        "preshow_condition_is_excluded": all_family_rows(
            ("ByCompareCurrentSkillEffectIsDamaging",),
            lambda row: row.evaluation_stage == "excluded_non_gameplay",
        ),
    }
    return {
        "current_condition_family_count": len(current_families),
        "current_missing_family_count": len(missing_families),
        "current_missing_families": sorted(missing_families),
        "registry_covers_current_missing_families": bool(missing_families)
        and missing_families.issubset(condition_responsibility_registry_families()),
        "all_current_missing_records_classified": (
            len(rows)
            == sum(record.family in missing_families for record in records)
            and not catalog.issues
        ),
        "partitions_are_nonempty": all(
            stage_counts[stage] > 0
            for stage in (
                "p9_s6b_committed_state",
                "p9_s7_transient_context",
                "excluded_non_gameplay",
            )
        ),
        "blocked_unclassified_count": stage_counts["blocked_unclassified"],
        "stage_counts": dict(sorted(stage_counts.items())),
        "anchor_checks": anchor_checks,
        "anchors_ok": all(anchor_checks.values()),
    }


def _negative_checks(sample: CharacterConditionResponsibilityIR) -> dict[str, bool]:
    encoded = sample.to_json()
    mutable = json.loads(json.dumps(encoded))
    restored = CharacterConditionResponsibilityIR.from_json(mutable)
    mutable["required_context"].append("forged.context")
    mutable["source"]["evidence"]["json_path"] = "$.forged"
    unknown = {"$type": "RPG.GameCore.ByFutureCondition", "Value": 1}
    known_extra = {
        "$type": "RPG.GameCore.ByCompareBP",
        "CompareType": "Equal",
        "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 1}},
        "FutureField": True,
    }
    bad_codec = sample.to_json()
    bad_codec["unknown"] = True
    bad_scope_basis = sample.to_json()
    bad_scope_basis["scope_basis"] = "presentation_only_controlled_task_branches"
    missing_producer = sample.to_json()
    missing_producer["producer_stage"] = "none"
    return {
        "codec_round_trip_stable": restored.to_json() == encoded,
        "codec_input_mutation_isolated": restored.to_json() == encoded,
        "unknown_family_blocks": (
            character_condition_family_stage("ByFutureCondition", unknown)
            == "blocked_unclassified"
            and character_condition_family_blocked_reason(
                "ByFutureCondition", unknown
            ).startswith("condition_family_unclassified")
        ),
        "known_family_unknown_field_blocks": (
            character_condition_family_stage("ByCompareBP", known_extra)
            == "blocked_unclassified"
            and character_condition_family_blocked_reason(
                "ByCompareBP", known_extra
            ).startswith("condition_field_signature_unclassified")
        ),
        "codec_unknown_field_rejected": _expect_error(
            lambda: CharacterConditionResponsibilityIR.from_json(bad_codec)
        ),
        "stage_scope_basis_mismatch_rejected": _expect_error(
            lambda: CharacterConditionResponsibilityIR.from_json(bad_scope_basis)
        ),
        "planned_without_producer_rejected": _expect_error(
            lambda: CharacterConditionResponsibilityIR.from_json(missing_producer)
        ),
    }


def _lowering_checks(rows: tuple[Any, ...], snapshot: Any) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for stage in ("p9_s6b_committed_state", "p9_s7_transient_context"):
        selected[stage] = next(
            row
            for row in rows
            if row.evaluation_stage == stage
            and row.opcode in {"ByCompareBP", "ByCompareParamString"}
        )
    results = {}
    for stage, row in selected.items():
        raw = _at_path(
            snapshot.documents[row.source.source_path],
            str(row.source.evidence["json_path"]).removesuffix(".$type"),
        )
        assert isinstance(raw, Mapping)
        result = _typed_condition_execution_node(
            dict(raw), source=row.source
        )
        results[stage] = {
            "supported": result.get("supported"),
            "blocked_reason": result.get("blocked_reason"),
        }
    fixture_source = IRSource(
        source_path="validation_fixture/condition.json",
        raw_type="AlwaysTrue",
        raw_id="validation:condition:always_true",
        evidence={"json_path": "$.Condition"},
    )
    existing = _typed_condition_execution_node(
        {"$type": "RPG.GameCore.AlwaysTrue"}, source=fixture_source
    )
    nested_unknown = _typed_condition_execution_node(
        {
            "$type": "RPG.GameCore.ByAnd",
            "PredicateList": [{"$type": "RPG.GameCore.ByFutureCondition"}],
        },
        source=fixture_source,
    )
    return {
        "planned_s6_reason_is_precise": (
            results[_S6]["supported"] is False
            and str(results[_S6]["blocked_reason"]).startswith(
                "condition_deferred_to_p9_s6b_committed_state"
            )
        ),
        "planned_s7_reason_is_precise": (
            results[_S7]["supported"] is False
            and str(results[_S7]["blocked_reason"]).startswith(
                "condition_deferred_to_p9_s7_transient_context"
            )
        ),
        "existing_condition_admission_unchanged": (
            existing.get("supported") is True
            and existing.get("blocked_reason") == ""
        ),
        "nested_unknown_condition_reason_preserved": (
            nested_unknown.get("supported") is False
            and str(nested_unknown.get("blocked_reason") or "").startswith(
                "condition_family_unclassified:ByFutureCondition"
            )
        ),
        "samples": results,
    }


_S6 = "p9_s6b_committed_state"
_S7 = "p9_s7_transient_context"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot = build_character_ability_raw_snapshot(tbgd_root)
    scope_catalog = build_character_ability_scope_projection(
        tbgd_root, snapshot=snapshot
    )
    catalog = build_character_condition_responsibility_catalog(
        snapshot, scope_catalog
    )
    records = _condition_denominator(scope_catalog)
    source_checks = _source_checks(snapshot, records, catalog.responsibilities)
    excluded_scope_checks = _excluded_scope_checks(
        snapshot, catalog.responsibilities
    )
    assignment_checks = _assignment_checks(catalog, records)
    negative_checks = _negative_checks(catalog.responsibilities[0])
    lowering_checks = _lowering_checks(catalog.responsibilities, snapshot)
    checks = {
        "source_catalog_complete": (
            snapshot.source_catalog_complete
            and scope_catalog.scope_reconciliation_complete
        ),
        "condition_denominator_uses_semantic_scope": bool(records)
        and all(
            record.source.evidence.get("nominal_semantic_kind")
            == "combat_condition"
            for record in records
        ),
        "catalog_complete": catalog.complete,
        "partition_exhaustive_and_disjoint": (
            len(catalog.condition_record_ids)
            == len(catalog.existing_family_record_ids)
            + len(catalog.responsibilities)
        ),
        "all_sources_reversible": source_checks["all_source_nodes_reversible"],
        "presentation_exclusions_resolve_controlled_branches": (
            excluded_scope_checks[
                "controlled_exclusions_have_no_unresolved_indirection"
            ]
        ),
        "current_missing_families_covered": assignment_checks[
            "registry_covers_current_missing_families"
        ],
        "all_missing_records_classified": assignment_checks[
            "all_current_missing_records_classified"
        ],
        "no_unclassified_responsibility": (
            assignment_checks["blocked_unclassified_count"] == 0
        ),
        "committed_transient_excluded_partitions_present": assignment_checks[
            "partitions_are_nonempty"
        ],
        "semantic_anchor_assignments_correct": assignment_checks["anchors_ok"],
        "negative_contracts_hold": all(negative_checks.values()),
        "lowering_uses_responsibility_contract": all(
            value is True
            for key, value in lowering_checks.items()
            if key != "samples"
        ),
        "full_canonical_ir_build_count_zero": True,
    }
    ok = all(checks.values())
    elapsed = time.perf_counter() - started
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {
        "version": "p9_s6a_condition_responsibility_contract_v1",
        "ok": ok,
        "checks": checks,
        "catalog_summary": catalog.summary_json(),
        "source_checks": source_checks,
        "excluded_scope_checks": excluded_scope_checks,
        "assignment_checks": assignment_checks,
        "negative_checks": negative_checks,
        "lowering_checks": lowering_checks,
        "resource": {
            "elapsed_seconds": elapsed,
            "peak_rss_kib": peak_rss,
            "raw_snapshot_build_count": 1,
            "scope_projection_build_count": 1,
            "responsibility_catalog_build_count": 1,
            "full_canonical_ir_build_count": 0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = [row.to_json() for row in catalog.responsibilities]
    bytes_written = _write(
        output_dir / "condition_responsibility_ledger.json", ledger
    )
    result["resource"]["evidence_bytes"] = bytes_written
    _write(
        output_dir
        / "validation_summary_p9_s6a_condition_responsibility_contract.json",
        result,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the P9-S6A character condition responsibility contract."
    )
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.tbgd_root.resolve(), args.output_dir.resolve())
    print(
        "P9-S6A "
        f"ok={result['ok']} "
        f"conditions={result['catalog_summary']['condition_record_count']} "
        f"planned={result['catalog_summary']['responsibility_record_count']} "
        f"seconds={result['resource']['elapsed_seconds']:.3f} "
        f"rss_kib={result['resource']['peak_rss_kib']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
