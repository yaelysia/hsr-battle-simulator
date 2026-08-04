"""Focused production-contract validation for P9-S5A."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..core.model import BattleState, UnitState
from ..ir_types import IRSource
from ..rules.ir import ConditionIR, TargetExpressionIR, TargetExpressionNodeIR
from ..systems.status_callbacks import _condition_context
from ..systems.target import TargetExpressionResult, TargetSystem
from ..tbgd.character_ability_scope import build_character_ability_raw_snapshot
from ..tbgd.lowering import TBGDLowering, _target_expression_from_raw
from ..tbgd.target_source import (
    TargetSourceProjectionCatalog,
    _target_language_cycle_ids,
    _propagate_target_language_link_reasons,
    _target_language_reference_names,
    _target_record_route,
    _unique_json_object,
    _value_at_json_path,
    build_target_source_projection,
)


def _write_json(output_dir: Path, name: str, value: object) -> None:
    (output_dir / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expect_error(callback: Any) -> bool:
    try:
        callback()
    except (AttributeError, TypeError, ValueError):
        return True
    return False


def _source_for(path: str) -> IRSource:
    return IRSource(
        source_path="validation/target_source.json",
        raw_type="TargetExpression",
        raw_id="fixture",
        evidence={"json_path": path},
    )


def _expressions(catalog: TargetSourceProjectionCatalog) -> tuple[TargetExpressionIR, ...]:
    return tuple(
        record.expression
        for record in catalog.records
        if record.expression is not None
    ) + tuple(definition.expression for definition in catalog.language_definitions)


def _walk_nodes(node: TargetExpressionNodeIR) -> Iterable[TargetExpressionNodeIR]:
    yield node
    for child in node.children:
        yield from _walk_nodes(child)
    for child in (node.candidate, node.target, node.query_target, node.query_compare):
        if child is not None:
            yield from _walk_nodes(child)
    if node.predicate is not None:
        yield from _walk_payload_nodes(node.predicate.payload)


def _walk_payload_nodes(value: object) -> Iterable[TargetExpressionNodeIR]:
    if type(value) is TargetExpressionNodeIR:
        yield from _walk_nodes(value)
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_payload_nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload_nodes(child)


def _walk_conditions(value: object) -> Iterable[ConditionIR]:
    if type(value) is ConditionIR:
        yield value
        yield from _walk_conditions(value.payload)
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_conditions(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_conditions(child)


def _node_contract_cases() -> dict[str, bool]:
    source = _source_for("$.fixture.Target")

    def alias(path: str, raw_id: str) -> TargetExpressionNodeIR:
        return TargetExpressionNodeIR.build(
            "TargetAlias",
            IRSource(source.source_path, "TargetExpression", raw_id, {"json_path": path}),
            {"alias": "Caster"},
        )

    def condition(identity: str, path: str, raw_id: str, payload: Mapping[str, Any] | None = None) -> ConditionIR:
        return ConditionIR(
            condition_id=identity, opcode="AlwaysTrue", payload=dict(payload or {}),
            source=IRSource(source.source_path, "Condition", raw_id, {"json_path": path}),
            coverage_status="executable", expression_schema_version="hsr.condition_expression_node.v1",
        )

    lowered = _target_expression_from_raw(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
        field_name="$self", expression_id="validation:target", source=source,
    )
    _check(lowered is not None and lowered.node is not None, "fixture target did not lower")
    node = lowered.node
    predicate = condition(
        "validation:predicate", "$.fixture.Predicate", "fixture:Predicate",
        {"TargetType": alias("$.fixture.Predicate.TargetType", "fixture:Predicate:TargetType")},
    )
    filter_predicate = condition("validation:filter", "$.fixture.Target.Predicate", "fixture:Predicate")
    canonical_child = alias("$.fixture.Target.TargetType", "fixture:TargetType")
    forged_child = alias("$.fixture.Target.TargetTypeFake", "fixture:TargetTypeFake")
    forged_predicate = condition("validation:fake", "$.fixture.Target.PredicateFake", "fixture:PredicateFake")
    unsupported = TargetExpressionNodeIR.build(
        "TargetUnsupported", source, {"original_kind": "TargetFilter", "blocked_reason": "fixture"}
    )
    unsupported_numeric = {
        "schema_version": "hsr.numeric_expression.v1", "kind": "unsupported", "supported": False, "reason": "fixture",
    }
    fixed_numeric = {"schema_version": "hsr.numeric_expression.v1", "kind": "fixed", "value": 0, "supported": True}
    query_source = _source_for("$.fixture.Query")
    query_payload = {"entity_type_mask": "Servant", "alive_state_mask": "Alive", "target": None, "compare": None}
    deferred_query = TargetExpressionNodeIR.build("TargetQuery", query_source, query_payload)
    nested_query = TargetExpressionNodeIR.build(
        "TargetQuery",
        IRSource(source.source_path, "TargetExpression", "fixture:Predicate:TargetType", {"json_path": "$.fixture.Target.Predicate.TargetType"}),
        query_payload,
    )

    def raw_blocked(raw: dict[str, Any], expected_reason: str = "") -> bool:
        expression = _target_expression_from_raw(
            raw, field_name="$self", expression_id="validation:malformed", source=source
        )
        return expression is not None and expression.coverage_status == "blocked" and (not expected_reason or expression.blocked_reason == expected_reason)

    build_error_cases = (
        ("filter_requires_predicate", "TargetFilter", {"candidate": None, "predicate": None}),
        ("retarget_requires_target", "Retarget", {"target": None, "predicate": None, "by_random": False, "max_number_expr": {}, "include_limbo": False}),
        ("retarget_rejects_unsupported_max_number", "Retarget", {"target": canonical_child, "predicate": filter_predicate, "by_random": False, "max_number_expr": unsupported_numeric, "include_limbo": False}),
        ("query_requires_both_sides", "TargetQuery", {"entity_type_mask": "Servant", "alive_state_mask": "", "target": node, "compare": None}),
        ("index_type_restricted", "TargetIndex", {"index_type": "Invalid", "index_expr": {}}),
        ("unique_fetch_requires_name", "TargetFetchUniqueNameEntity", {"name": "", "unique_name": ""}),
        ("adjacent_side_restricted", "TargetMapAdjoinEntity", {"side": "Diagonal", "counting_option": ""}),
        ("take_requires_count", "TargetTake", {"count_expr": {}}),
        ("take_rejects_unsupported_count", "TargetTake", {"count_expr": unsupported_numeric}),
        ("strict_index_rejects_unsupported_value", "TargetIndex", {"index_type": "IndexStrict", "index_expr": unsupported_numeric}),
        ("first_index_rejects_unused_value", "TargetIndex", {"index_type": "First", "index_expr": fixed_numeric}),
    )
    build_cases = {
        name: _expect_error(lambda kind=kind, payload=payload: TargetExpressionNodeIR.build(kind, source, payload))
        for name, kind, payload in build_error_cases
    }
    invalid_sorts = (
        ("TargetSortByProperty", {"sort_key": "", "highest_first": False}),
        ("TargetSortByProperty", {"sort_key": "Unknown", "highest_first": False}),
        ("TargetSortByFormation", {"sort_key": "CurrentHP", "highest_first": False}),
    )
    invalid_query_payload = {
        "entity_type_mask": "Invalid", "alive_state_mask": "",
        "target": alias("$.fixture.Query.Predicate.TargetType", "fixture:Query:Predicate:TargetType"),
        "compare": alias("$.fixture.Query.Predicate.CompareType", "fixture:Query:Predicate:CompareType"),
    }
    fetch_unused_payloads = (
        ("TargetFetchCaster", {"name": "ignored", "unique_name": ""}),
        ("TargetFetchPartner", {"name": "", "unique_name": "ignored"}),
        ("TargetFetchUniqueNameEntity", {"name": "ignored", "unique_name": "unit"}),
    )
    foreign_target = TargetExpressionNodeIR.build("TargetAlias", IRSource("validation/other.json", "TargetExpression", "fixture:Predicate:TargetType", {"json_path": "$.fixture.Predicate.TargetType"}), {"alias": "Caster"})
    malformed_raws = (
        {"$type": "RPG.GameCore.Retarget", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "ByRandom": "false"},
        {"$type": "RPG.GameCore.TargetSortByProperty", "PropertyType": "CurrentHP", "HighestFirst": "false"},
        {"$type": "RPG.GameCore.TargetQuery", "EntityTypeMask": {"name": "Servant"}},
        {"$type": {"name": "RPG.GameCore.TargetAlias"}, "Alias": "Caster"},
    )
    deferred_condition_raw = {"$type": "RPG.GameCore.TargetFilter", "Predicate": {"$type": "RPG.GameCore.ByTargetAliveState", "TargetType": {"$type": "RPG.GameCore.TargetMapSummoner", "Recursive": True}, "AliveStateMask": "Mask_AliveOrRevivable"}}

    def executable_target(identity: str, kind: str, root: IRSource, target: TargetExpressionNodeIR) -> TargetExpressionIR:
        return TargetExpressionIR(target_expression_id=identity, expression_kind=kind, alias="", source=root, node=target, coverage_status="executable")

    extra_cases = {
        "query_entity_type_restricted": _expect_error(lambda: TargetExpressionNodeIR.build("TargetQuery", query_source, invalid_query_payload)),
        "fetch_rejects_unused_fields": all(_expect_error(lambda kind=kind, payload=payload: TargetExpressionNodeIR.build(kind, source, payload)) for kind, payload in fetch_unused_payloads),
        "condition_target_cross_file_rejected": _expect_error(lambda: condition("validation:cross", "$.fixture.Predicate", "fixture:Predicate", {"TargetType": foreign_target})),
        "condition_target_field_forgery_rejected": _expect_error(lambda: condition("validation:field", "$.fixture.Predicate", "fixture:Predicate", {"TargetType": alias("$.fixture.Predicate.TargetTypeFake", "fixture:Predicate:TargetTypeFake")})),
        "executable_condition_rejects_deferred_target": _expect_error(lambda: condition("validation:deferred", "$.fixture.Target.Predicate", "fixture:Predicate", {"TargetType": nested_query})),
        "blocked_condition_reason_cannot_be_rewritten": _expect_error(lambda: ConditionIR(condition_id="validation:condition-reason", opcode="AlwaysTrue", payload={"TargetType": nested_query}, source=filter_predicate.source, coverage_status="blocked", expression_schema_version="hsr.condition_expression_node.v1", blocked_reason="condition_not_admitted:AlwaysTrue")),
        "deferred_query_cannot_be_executable": _expect_error(lambda: executable_target("validation:query", "TargetQuery", query_source, deferred_query)) and TargetSystem().resolve_expression_node(BattleState(), deferred_query, caster_id="unit:caster").blocked,
        "blocked_target_reason_cannot_be_rewritten": _expect_error(lambda: TargetExpressionIR(target_expression_id="validation:reason", expression_kind="TargetQuery", alias="", source=query_source, node=deferred_query, coverage_status="blocked", blocked_reason="target_expression_not_admitted:TargetQuery")),
        "malformed_raw_target_fields_blocked": all(raw_blocked(raw) for raw in malformed_raws),
        "lowered_deferred_condition_closes": raw_blocked(deferred_condition_raw, "target_summoner_recursive_deferred_s5b"),
        "empty_source_rejected": _expect_error(lambda: TargetExpressionNodeIR.build("TargetAlias", IRSource("validation.json", "TargetExpression", "fixture", {"json_path": ""}), {"alias": "Caster"})),
        "blocked_node_cannot_be_executable": _expect_error(lambda: executable_target("validation:blocked", "TargetFilter", source, unsupported)),
        "root_node_source_must_close": _expect_error(lambda: executable_target("validation:mismatch", "TargetAlias", source, TargetExpressionNodeIR.build("TargetAlias", _source_for("$.fixture.other"), {"alias": "Caster"}))),
        "unrelated_child_source_rejected": _expect_error(lambda: TargetExpressionNodeIR.build("TargetFilter", source, {"candidate": TargetExpressionNodeIR.build("TargetAlias", _source_for("$.other.Target"), {"alias": "Caster"}), "predicate": filter_predicate})),
        "predicate_cannot_copy_parent_source": _expect_error(lambda: TargetExpressionNodeIR.build("TargetFilter", source, {"candidate": None, "predicate": condition("validation:copied", "$.fixture.Target", "fixture")})),
        "target_child_field_prefix_forgery_rejected": _expect_error(lambda: TargetExpressionNodeIR.build("TargetFilter", source, {"candidate": forged_child, "predicate": filter_predicate})),
        "predicate_field_prefix_forgery_rejected": _expect_error(lambda: TargetExpressionNodeIR.build("TargetFilter", source, {"candidate": canonical_child, "predicate": forged_predicate})),
        "sort_schema_restricted": all(_expect_error(lambda kind=kind, payload=payload: TargetExpressionNodeIR.build(kind, source, payload)) for kind, payload in invalid_sorts),
        "executable_predicate_block_reason_rejected": _expect_error(lambda: ConditionIR(condition_id="validation:contradiction", opcode="AlwaysTrue", payload={}, source=filter_predicate.source, coverage_status="executable", blocked_reason="forged")),
    }
    return {
        "round_trip_node_exact": TargetExpressionNodeIR.from_json(node.to_json()).to_json() == node.to_json(),
        "nested_predicate_node_round_trip_typed": (
            type(ConditionIR.from_json(predicate.to_json()).payload["TargetType"])
            is TargetExpressionNodeIR
        ),
        **build_cases,
        **extra_cases,
    }


def _result_contract_cases() -> dict[str, bool]:
    input_ids = ["unit:1"]
    input_metadata = {"nested": {"ids": ["unit:1"]}}
    result = TargetExpressionResult(
        status="resolved", target_ids=input_ids, metadata=input_metadata
    )
    input_ids.append("unit:2")
    input_metadata["nested"]["ids"].append("unit:2")
    nested = result.metadata["nested"]
    return {
        "input_containers_detached": result.target_ids == ("unit:1",) and nested["ids"] == ["unit:1"],
        "metadata_recursively_immutable": _expect_error(lambda: nested.__setitem__("x", 1)),
        "compatibility_ok_removed": not hasattr(result, "ok"),
        "resolved_empty_valid": TargetExpressionResult(status="resolved").resolved,
        "resolved_with_reason_rejected": _expect_error(
            lambda: TargetExpressionResult(status="resolved", blocked_reason="bad")
        ),
        "blocked_with_targets_rejected": _expect_error(
            lambda: TargetExpressionResult(status="blocked", target_ids=("unit",), blocked_reason="bad")
        ),
        "blocked_with_rng_rejected": _expect_error(
            lambda: TargetExpressionResult(status="blocked", blocked_reason="bad", rng_events=("rng",))
        ),
        "resolved_non_rng_rejected": _expect_error(
            lambda: TargetExpressionResult(status="resolved", rng_events=("rng",))
        ),
    }


def _retarget_runtime_case() -> bool:
    """A Retarget evaluates its predicate directly; it must not forge Filter."""

    root = IRSource(
        "validation/target_source.json",
        "TargetExpression",
        "retarget",
        {"json_path": "$.fixture.Retarget"},
    )
    target = TargetExpressionNodeIR.build(
        "TargetAlias",
        IRSource(root.source_path, "TargetExpression", "retarget:TargetType", {"json_path": "$.fixture.Retarget.TargetType"}),
        {"alias": "Caster"},
    )
    predicate = ConditionIR(
        condition_id="validation:retarget-predicate",
        opcode="AlwaysTrue",
        payload={},
        source=IRSource(root.source_path, "Condition", "retarget:Predicate", {"json_path": "$.fixture.Retarget.Predicate"}),
        coverage_status="executable",
        expression_schema_version="hsr.condition_expression_node.v1",
    )
    retarget = TargetExpressionNodeIR.build(
        "Retarget",
        root,
        {"target": target, "predicate": predicate, "by_random": False, "max_number_expr": {}, "include_limbo": False},
    )
    original_descriptor = TargetExpressionNodeIR.__dict__["build"]
    original_build = TargetExpressionNodeIR.build

    def reject_synthetic_filter(
        cls: type[TargetExpressionNodeIR],
        expression_kind: str,
        source: IRSource,
        payload: Mapping[str, Any],
    ) -> TargetExpressionNodeIR:
        if expression_kind == "TargetFilter":
            raise AssertionError("Retarget constructed a synthetic TargetFilter")
        return original_build(expression_kind, source, payload)

    TargetExpressionNodeIR.build = classmethod(reject_synthetic_filter)
    try:
        state = BattleState(units={"unit:caster": UnitState("unit:caster", "ally", "validation:caster")})
        result = TargetSystem().resolve_expression_node(
            state,
            retarget,
            caster_id="unit:caster",
        )
    finally:
        TargetExpressionNodeIR.build = original_descriptor
    return result.resolved and result.target_ids == ("unit:caster",)


def _raw_document(
    tbgd_root: Path,
    snapshot_documents: Mapping[str, Mapping[str, Any]],
    cache: dict[str, Mapping[str, Any]],
    source_path: str,
) -> Mapping[str, Any]:
    if source_path in snapshot_documents:
        return snapshot_documents[source_path]
    if source_path not in cache:
        value = json.loads((tbgd_root / source_path).read_bytes())
        _check(isinstance(value, Mapping), f"target source root not object:{source_path}")
        cache[source_path] = value
    return cache[source_path]


def _source_closure(
    tbgd_root: Path,
    snapshot_documents: Mapping[str, Mapping[str, Any]],
    records: Iterable[Any],
    expressions: tuple[TargetExpressionIR, ...],
) -> dict[str, Any]:
    cache: dict[str, Mapping[str, Any]] = {}
    record_items = tuple(records)
    rows: list[str] = []
    checked_nodes = 0
    checked_conditions = 0
    semantic_shape_sources = {"recursive_summoner": set(), "adjacent_ignore_servant": set(), "retarget_include_limbo": set(), "query_alive_state": set()}
    for record in record_items:
        path = record.source.evidence.get("json_path")
        raw = _value_at_json_path(_raw_document(tbgd_root, snapshot_documents, cache, record.source.source_path), str(path))
        _check(isinstance(raw, Mapping), f"record source cannot reverse to raw:{record.record_id}")
        rows.append(f"record\0{record.record_id}\0{record.source.source_path}\0{path}")
    for expression in expressions:
        _check("audit_raw" not in expression.to_json(), "target IR retained audit_raw")
        if expression.node is None:
            continue
        for node in _walk_nodes(expression.node):
            path = node.source.evidence.get("json_path")
            raw = _value_at_json_path(_raw_document(tbgd_root, snapshot_documents, cache, node.source.source_path), str(path))
            _check(isinstance(raw, Mapping), f"node source cannot reverse to raw:{node.node_id}")
            expected_kind = node.expression_kind
            if expected_kind == "TargetUnsupported":
                expected_kind = str(node.payload["original_kind"])
            actual_kind = str(raw.get("$type") or "").removeprefix("RPG.GameCore.")
            _check(actual_kind == expected_kind, f"node source kind mismatch:{node.node_id}:{actual_kind}:{expected_kind}")
            if actual_kind == "TargetMapSummoner" and raw.get("Recursive") is True:
                semantic_shape_sources["recursive_summoner"].add(f"{node.source.source_path}\0{path}")
                _check(node.recursive_summoner and expression.coverage_status == "blocked" and expression.blocked_reason == node.runtime_blocked_reason, "recursive summoner escaped or lost its S5B block")
            if actual_kind == "TargetMapAdjoinEntity" and raw.get("CountingOption") == "IgnoreServant":
                semantic_shape_sources["adjacent_ignore_servant"].add(f"{node.source.source_path}\0{path}")
                _check(node.adjacent_counting_option == "IgnoreServant" and expression.coverage_status == "blocked" and expression.blocked_reason == node.runtime_blocked_reason, "adjacent counting option escaped or lost its S5B block")
            if actual_kind == "Retarget" and raw.get("IncludeLimbo") is True:
                semantic_shape_sources["retarget_include_limbo"].add(f"{node.source.source_path}\0{path}")
                _check(node.include_limbo and expression.coverage_status == "blocked" and expression.blocked_reason == node.runtime_blocked_reason, "retarget limbo escaped or lost its S5B block")
            if actual_kind == "TargetQuery" and node.expression_kind == "TargetQuery" and raw.get("AliveStateMask"):
                semantic_shape_sources["query_alive_state"].add(f"{node.source.source_path}\0{path}")
                _check(isinstance(raw.get("AliveStateMask"), str) and node.query_alive_state_mask == raw["AliveStateMask"] and node.runtime_blocked_reason == f"target_query_alive_state_mask_deferred_s5b:{raw['AliveStateMask']}" and expression.coverage_status == "blocked" and expression.blocked_reason == node.runtime_blocked_reason, "target query alive state escaped or lost its S5B block")
            rows.append(f"node\0{node.node_id}\0{node.source.source_path}\0{path}")
            checked_nodes += 1
            for condition in _walk_conditions(node.predicate):
                condition_path = condition.source.evidence.get("json_path")
                condition_raw = _value_at_json_path(
                    _raw_document(tbgd_root, snapshot_documents, cache, condition.source.source_path),
                    str(condition_path),
                )
                _check(isinstance(condition_raw, Mapping), f"predicate source cannot reverse to raw:{condition.condition_id}")
                rows.append(f"condition\0{condition.condition_id}\0{condition.source.source_path}\0{condition_path}")
                checked_conditions += 1
    digest = sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()
    return {
        "record_reverse_check_count": len(record_items),
        "node_reverse_check_count": checked_nodes,
        "predicate_reverse_check_count": checked_conditions,
        "semantic_source_shape_counts": {name: len(paths) for name, paths in semantic_shape_sources.items()},
        "source_paths_read_for_reverse_check": sorted(cache),
        "closure_digest": digest,
    }


def _blocked_gap_ledger(catalog: TargetSourceProjectionCatalog) -> dict[str, Any]:
    grouped: dict[str, Any] = {"s5a_effect_target": {}, "global_target_definition": {}}
    for phase, items, owner_of in (
        ("s5a_effect_target", (item for item in catalog.records if item.responsibility == "s5a_effect_target" and item.coverage_status == "blocked"), lambda item: f"{item.effective_scope}:{item.family}"),
        ("global_target_definition", (item for item in catalog.language_definitions if item.coverage_status == "blocked"), lambda item: item.definition_kind),
    ):
        for item in items:
            owners = grouped[phase].setdefault(item.blocked_reason, {})
            owner = owner_of(item)
            entry = owners.setdefault(owner, {"count": 0, "representative_source": {"source_path": item.source.source_path, "record_identity": item.source.raw_id, "json_path": item.source.evidence["json_path"]}})
            entry["count"] += 1
    return {phase: {"total": sum(sum(entry["count"] for entry in owners.values()) for owners in reasons.values()), "by_reason": {reason: {"count": sum(entry["count"] for entry in owners.values()), "owners": dict(sorted(owners.items()))} for reason, owners in sorted(reasons.items())}} for phase, reasons in grouped.items()}


def _formal_source_shapes(value: object) -> frozenset[str]:
    shapes: set[str] = set()

    def has_target_node(item: object) -> bool:
        if isinstance(item, Mapping):
            raw_type = item.get("$type")
            return (
                isinstance(raw_type, str)
                and (raw_type.startswith("RPG.GameCore.Target") or raw_type == "RPG.GameCore.Retarget")
            ) or any(has_target_node(child) for child in item.values())
        return isinstance(item, (list, tuple)) and any(has_target_node(child) for child in item)

    def visit(item: object, in_callback: bool = False) -> None:
        if isinstance(item, Mapping):
            kind = str(item.get("$type") or "").removeprefix("RPG.GameCore.")
            callback_list = isinstance(item.get("_CallbackList"), list)
            if callback_list: shapes.add("status_callback")
            if in_callback and has_target_node(item.get("Predicate")):
                shapes.add("status_callback_target_condition")
            if kind in {"RemoveSelfModifier", "AttachEntityDeparted"} and "TargetType" not in item:
                shapes.add(f"implicit_{kind}")
            if kind == "Retarget" and item.get("IncludeLimbo") is True: shapes.add("retarget_include_limbo")
            for key, child in item.items(): visit(child, in_callback or key == "_CallbackList")
        elif isinstance(item, (list, tuple)):
            for child in item: visit(child, in_callback)
    visit(value)
    return frozenset(shapes)


def _select_formal_sources(documents: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    source_shapes = {path: _formal_source_shapes(document) for path, document in documents.items()}
    required = frozenset({"status_callback", "status_callback_target_condition", "retarget_include_limbo"}) | frozenset(
        shape for shapes in source_shapes.values() for shape in shapes if shape.startswith("implicit_")
    )
    choices: dict[frozenset[str], tuple[str, ...]] = {frozenset(): ()}
    for path in sorted(source_shapes):
        shapes = source_shapes[path] & required
        for covered, selected in tuple(choices.items()):
            expanded, candidate = covered | shapes, (*selected, path)
            previous = choices.get(expanded)
            if shapes and (previous is None or len(candidate) < len(previous)):
                choices[expanded] = candidate
    selected = choices.get(required)
    _check(selected is not None, "formal lowering source shapes are missing")
    return selected


def _formal_lowering_closure(
    tbgd_root: Path,
    snapshot_documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Exercise existing formal lowering without invoking CanonicalIR.build."""

    lowerer = TBGDLowering(tbgd_root)
    global_expressions = tuple(lowerer._lower_global_target_expressions())
    _check(global_expressions, "formal global target lowering emitted no definitions")
    selected_sources = _select_formal_sources(snapshot_documents)
    status_expressions: list[TargetExpressionIR] = []
    ability_expressions: list[TargetExpressionIR] = []
    callback_conditions: list[ConditionIR] = []
    for source_path in selected_sources:
        document = snapshot_documents[source_path]
        lowered = lowerer._lower_ability_file(
            tbgd_root / source_path,
            {},
            ability_file_order=0,
            raw_document=document,
        )
        ability_expressions.extend(lowered.target_expressions)
        callback_condition_ids = {task.condition_id for task in lowered.status_callback_tasks if task.condition_id}
        callback_conditions.extend(
            condition for condition in lowered.conditions
            if condition.condition_id in callback_condition_ids and any(_walk_payload_nodes(condition.payload))
        )
        status_expressions.extend(
            expression
            for expression in lowered.target_expressions
            if "status_callback_task:" in expression.target_expression_id
        )
    _check(status_expressions, "formal status callback lowering emitted no target expression")
    _check(callback_conditions, "formal status callback lowering emitted no target condition")
    _check(not any(str(item.source.evidence.get("target_expression_field", "")).startswith("implicit:") for item in ability_expressions), "formal lowering emitted synthetic implicit target")
    callback_condition = callback_conditions[0]
    condition_raw = _value_at_json_path(
        snapshot_documents[callback_condition.source.source_path],
        str(callback_condition.source.evidence.get("json_path")),
    )
    _check(isinstance(condition_raw, Mapping), "formal status callback condition cannot reverse to raw")
    callback_context = _condition_context(
        BattleState(units={"unit:callback": UnitState("unit:callback", "ally", "validation:callback")}),
        {"owner_id": "unit:callback", "caster_id": "unit:callback", "instance_id": "validation:callback"},
        None,
        condition=callback_condition,
        targets=TargetSystem(),
    )
    callback_direct_count = len(callback_context.resolved_target_groups) + len(callback_context.target_resolution_errors)
    _check(callback_direct_count > 0, "formal status callback target condition was not resolved")

    formal_closure = _source_closure(
        tbgd_root, snapshot_documents, (), tuple((*global_expressions, *ability_expressions))
    )
    return {
        "formal_global_definition_count": len(global_expressions),
        "formal_status_callback_expression_count": len(status_expressions),
        "formal_status_callback_condition_count": len(callback_conditions),
        "formal_status_callback_direct_target_count": callback_direct_count,
        "formal_selected_sources": list(selected_sources),
        "formal_selected_source_shapes": {path: sorted(_formal_source_shapes(snapshot_documents[path])) for path in selected_sources},
        "formal_ability_expression_count": len(ability_expressions),
        "formal_synthetic_implicit_target_count": 0,
        "formal_node_reverse_check_count": formal_closure["node_reverse_check_count"],
        "formal_predicate_reverse_check_count": formal_closure["predicate_reverse_check_count"],
        "formal_source_closure_digest": formal_closure["closure_digest"],
    }


def _migration_slice(expressions: tuple[TargetExpressionIR, ...]) -> dict[str, Any]:
    expression = next(
        (item for item in expressions if item.coverage_status == "executable" and item.expression_kind == "TargetAlias" and item.alias == "Caster"),
        None,
    )
    _check(expression is not None, "current source has no admitted Caster target expression")
    state = BattleState(units={"ally:caster": UnitState("ally:caster", "ally", "validation:caster")})
    result = TargetSystem().resolve_target_expression(state, expression, caster_id="ally:caster")
    return {
        "source_expression_id": expression.target_expression_id,
        "status": result.status,
        "target_ids": list(result.target_ids),
        "stable_caster_result": result.resolved and result.target_ids == ("ally:caster",),
    }


def _run(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    snapshot = build_character_ability_raw_snapshot(tbgd_root)
    intercepted_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden_full_build(_self: TBGDLowering) -> object:
        nonlocal intercepted_build_calls
        intercepted_build_calls += 1
        raise AssertionError("P9-S5A target projection invoked full Canonical IR lowering")

    TBGDLowering.build = forbidden_full_build
    try:
        catalog = build_target_source_projection(tbgd_root, snapshot=snapshot)
        formal_lowering = _formal_lowering_closure(tbgd_root, snapshot.documents)
    finally:
        TBGDLowering.build = original_build
    expressions = _expressions(catalog)
    _check(expressions, "target source projection contains no typed expressions")
    source_closure = _source_closure(tbgd_root, snapshot.documents, catalog.records, expressions)
    gap_ledger = _blocked_gap_ledger(catalog)
    node_cases = _node_contract_cases()
    result_cases = _result_contract_cases()
    retarget_runtime_without_synthetic_filter = _retarget_runtime_case()
    migration = _migration_slice(expressions)
    definition_ids = {item.definition_id for item in catalog.language_definitions}
    random_gameplay_route = _target_record_route("RandomSelectInTargetList", "gameplay")
    random_non_gameplay_route = _target_record_route("RandomSelectInTargetList", "non_gameplay")
    delegated = next(item for item in catalog.records if item.coverage_status == "delegated")
    partial_catalog = replace(catalog, fingerprint_kind="partial", source_catalog_complete=False)
    definition = next(item for item in catalog.language_definitions)
    mutable_references = list(definition.reference_names)
    copied_definition = replace(definition, reference_names=mutable_references)
    mutable_references.append("forged:reference")
    alias_reference = next(
        (
            reference
            for item in catalog.language_definitions
            for reference in item.reference_names
            if reference.startswith("alias:")
        ),
        "",
    )
    alias_name = alias_reference.removeprefix("alias:")
    _check(alias_name, "current global target language has no alias dependency")
    _references_after_delete, missing_after_delete = _target_language_reference_names(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": alias_name},
        alias_names=set(),
        operation_names={item.name for item in catalog.language_definitions if item.definition_kind == "operation"},
    )
    _ambiguous_references, ambiguous_reason = _target_language_reference_names(
        {"$type": "RPG.GameCore.TargetAlias", "Alias": "Shared"},
        alias_names={"Shared"}, operation_names={"Shared"},
    )
    propagated_reasons = _propagate_target_language_link_reasons(
        {"definition:upstream": ("definition:missing",)},
        {"definition:missing": ambiguous_reason},
    )
    directory_cases = {
        "random_route_respects_scope": (
            random_gameplay_route[0] == "s5d_random_target_task"
            and random_non_gameplay_route[0] == "retired_non_gameplay"
            and all(
                record.responsibility != "s5a_effect_target"
                for record in catalog.records
                if record.family == "RandomSelectInTargetList"
            )
        ),
        "delegated_cannot_masquerade_executable": _expect_error(
            lambda: replace(delegated, coverage_status="executable")
        ),
        "language_fingerprints_immutable": _expect_error(
            lambda: catalog.language_fingerprints.__setitem__("x", "0" * 64)
        ),
        "definition_reference_lists_detached": (
            copied_definition.reference_names != tuple(mutable_references)
            and copied_definition.reference_names == definition.reference_names
        ),
        "partial_catalog_explicitly_marked": not partial_catalog.source_catalog_complete and partial_catalog.summary_json()["fingerprint_kind"] == "partial",
        "definition_reference_closure": all(
            len(item.reference_names) == len(item.reference_definition_ids)
            and set(item.reference_definition_ids).issubset(definition_ids)
            and not item.blocked_reason.startswith("target_language_")
            for item in catalog.language_definitions
        ),
        "missing_config_alias_blocks": missing_after_delete.startswith(
            "target_language_alias_definition_missing:"
        ),
        "ambiguous_config_name_blocks": ambiguous_reason.startswith("target_language_definition_name_ambiguous:"),
        "dependency_block_propagates": propagated_reasons.get("definition:upstream", "").startswith(
            "target_language_dependency_blocked:"
        ),
        "reference_cycles_detected": _target_language_cycle_ids(
            {"definition:left": ("definition:right",), "definition:right": ("definition:left",)}
        ) == {"definition:left", "definition:right"},
        "duplicate_definition_json_rejected": _expect_error(
            lambda: json.loads('{"x": 1, "x": 2}', object_pairs_hook=_unique_json_object)
        ),
    }
    checks = {
        "single_complete_snapshot_reused": catalog.snapshot_id == snapshot.snapshot_id and catalog.source_catalog_complete,
        "full_canonical_lowering_intercepted": intercepted_build_calls == 0 and catalog.build_counters["full_canonical_ir_build_count"] == 0,
        "gameplay_records_typed_or_blocked": all(
            record.expression is not None and record.expression.coverage_status in {"executable", "blocked"}
            for record in catalog.records if record.responsibility == "s5a_effect_target"
        ),
        "raw_reverse_source_closure": source_closure["record_reverse_check_count"] == len(catalog.records) and source_closure["node_reverse_check_count"] > 0,
        "blocked_gap_ledger_complete": gap_ledger["s5a_effect_target"]["total"] == sum(item.coverage_status == "blocked" and item.responsibility == "s5a_effect_target" for item in catalog.records) and gap_ledger["global_target_definition"]["total"] == sum(item.coverage_status == "blocked" for item in catalog.language_definitions) and all(entry["representative_source"]["source_path"] and entry["representative_source"]["record_identity"] and entry["representative_source"]["json_path"] for phase in gap_ledger.values() for reason in phase["by_reason"].values() for entry in reason["owners"].values()),
        "formal_lowering_source_closure": (
            formal_lowering["formal_global_definition_count"] > 0
            and formal_lowering["formal_status_callback_expression_count"] > 0
            and formal_lowering["formal_status_callback_condition_count"] > 0
            and formal_lowering["formal_status_callback_direct_target_count"] > 0
            and formal_lowering["formal_ability_expression_count"] > 0
            and formal_lowering["formal_node_reverse_check_count"] > 0
            and formal_lowering["formal_synthetic_implicit_target_count"] == 0
        ),
        "semantic_target_parameters_closed": all(source_closure["semantic_source_shape_counts"].values()) and source_closure["semantic_source_shape_counts"]["query_alive_state"] == 2,
        "strict_tagged_node_contract": all(node_cases.values()),
        "strict_result_contract": all(result_cases.values()),
        "retarget_runtime_has_no_synthetic_filter": retarget_runtime_without_synthetic_filter,
        "source_directory_contract": all(directory_cases.values()),
        "admitted_target_slice_stable": migration["stable_caster_result"],
    }
    ownership = {
        "candidate_records": len(catalog.records),
        "records_by_responsibility": catalog.summary_json()["records_by_responsibility"],
        "scope_routes": sorted({record.responsibility for record in catalog.records}),
        "blocked_gap_ledger": gap_ledger,
    }
    _write_json(output_dir, "source_ownership.json", ownership)
    _write_json(output_dir, "node_contract.json", node_cases)
    _write_json(output_dir, "source_closure.json", source_closure)
    _write_json(output_dir, "formal_lowering_closure.json", formal_lowering)
    _write_json(
        output_dir,
        "negative_cases.json",
        {
            **result_cases,
            **directory_cases,
            "retarget_runtime_has_no_synthetic_filter": retarget_runtime_without_synthetic_filter,
        },
    )
    _write_json(output_dir, "migration_slice.json", migration)
    summary = {
        "ok": all(checks.values()),
        "checks": checks,
        "catalog": catalog.summary_json(),
        "evidence_files": sorted(path.name for path in output_dir.iterdir() if path.is_file()),
    }
    _write_json(output_dir, "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True)
    try:
        summary = _run(args.tbgd_root.resolve(), args.output_dir)
    except Exception as exc:
        _write_json(args.output_dir, "summary.json", {"ok": False, "error": f"{type(exc).__name__}:{exc}"})
        raise
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
