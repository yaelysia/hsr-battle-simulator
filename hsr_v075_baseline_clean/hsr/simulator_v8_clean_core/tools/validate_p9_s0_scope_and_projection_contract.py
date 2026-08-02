from __future__ import annotations

import argparse
import json
import random
import resource
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from ..ir_types import IRSource, JSONValue
from ..rules.ir import CharacterAbilityProjectionIR, CharacterAbilitySourceIR
from ..tbgd.character_ability_scope import (
    CharacterAbilityRawSnapshot, CharacterAbilityScopeProjectionCatalog,
    _CharacterAbilityInventoryManifest, _SourceCandidate, _compute_source_fingerprint, _normalize_inventory_avatar_id,
    build_character_ability_raw_snapshot, build_character_ability_scope_projection,
    character_ability_snapshot_fingerprint, classify_character_ability_document,
)
from ..tbgd.lowering import TBGDLowering

WALL_CLOCK_BUDGET_SECONDS = 8 * 60
RSS_BUDGET_BYTES = 1024 * 1024 * 1024
EVIDENCE_BUDGET_BYTES = 5 * 1024 * 1024
VALIDATION_CODE_BUDGET_LINES = 900

_ORACLE_INVENTORY_PATHS = ("ExcelOutput/AvatarConfig.json", "ExcelOutput/AvatarConfigLD.json", "ExcelOutput/AvatarConfigEnhanced.json")
_ORACLE_SHARED_SOURCE = "Config/ConfigAbility/Avatar/Avatar_Common_Ability.json"
_ORACLE_DEFERRED_BASE_TYPES = {"Memory", "Elation"}
_ORACLE_RESOURCE_FIELDS = set("Active ActiveCount BarType CD CurrentCount CurrentState MaxCount TargetType".split())
_ORACLE_RESOURCE_CLIENT_FIELDS = {"EnergyDotPrefabPaths", "IconPath", "PrefabPath"}

class _UncheckedProjection(CharacterAbilityProjectionIR): __post_init__ = lambda self: None
class _UncheckedInventoryManifest(_CharacterAbilityInventoryManifest): __post_init__ = lambda self: None

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the P9-S0 character ability scope contract.")
    parser.add_argument("--tbgd-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--family", action="append", default=[])
    parser.add_argument("--source-path", action="append", default=[])
    return parser.parse_args()

def _expect_rejected(operation: Callable[[], object]) -> bool:
    try:
        operation()
    except (TypeError, ValueError):
        return True
    return False
def _mutation_rejected(operation: Callable[[], None]) -> bool:
    try:
        operation()
    except (AttributeError, TypeError):
        return True
    return False
def _cases(**conditions: bool) -> dict[str, JSONValue]: return {name: {"ok": bool(condition)} for name, condition in conditions.items()}
def _resource_payload(value: object) -> dict[str, Any]:
    return {"operation": "resource_state", "resource_fields": {"CurrentCount": {"IsDynamic": False, "FixedValue": {"Value": value}}}}

def _write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    text = json.dumps(value, ensure_ascii=True, indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")
def _synthetic_source() -> CharacterAbilitySourceIR:
    content = b"p9-s0-scope-contract-probe"
    source_id = "character_ability_source:shared:contract_probe"
    return CharacterAbilitySourceIR(
        source_id=source_id, source_kind="character_shared", avatar_id="",
        base_type="contract_probe", content_sha256=sha256(content).hexdigest(), byte_size=len(content),
        source=IRSource(
            source_path="validation/p9_s0_scope_contract_probe.json", raw_type="character_ability_source", raw_id=source_id,
            evidence={"purpose": "scope_contract_negative_matrix"},
        ),
    )
def _branch_matrix() -> dict[str, JSONValue]:
    source = _synthetic_source()
    document = {
        "SameObject": {
            "Event": "OnAimAtTargetsRefresh_CL", "$type": "RPG.GameCore.AddModifier",
            "TaskList": [{"$type": "RPG.GameCore.AddModifier"}],
        },
        "Presentation": {
            "$type": "RPG.GameCore.TriggerEffect",
            "TaskList": [{"$type": "RPG.GameCore.AddModifier"}, {"$type": "RPG.GameCore.RandomConfig"}],
        },
        "ReverseObject": {
            "Event": "OnAfterAttack", "$type": "RPG.GameCore.TriggerEffect",
            "TaskList": [{"$type": "RPG.GameCore.AddModifier"}],
        },
        "ConflictingObject": {
            "Event": "OnAimAtTargetsRefresh_CL",
            "$type": "RPG.GameCore.SetDeathDragonSkillButtonState",
        },
        "Structural": {"OnProjectileHitClientOnly": {"$type": "RPG.GameCore.AddModifier"}},
        "GameplayName": {"Event": "OnBreakExtendAnim", "$type": "RPG.GameCore.AddModifier"},
        "EmptyResource": {"$type": "RPG.GameCore.SetEnergyBarState"},
        "ClientResource": {"$type": "RPG.GameCore.SetEnergyBarState", "IconPath": "ui/icon.png"},
        "KnownResource": {
            "$type": "RPG.GameCore.SetEnergyBarState", "CurrentState": "Normal",
            "Active": "True", "BarType": 1, "CD": {"IsDynamic": False, "FixedValue": {"Value": 0}},
        },
    }
    rng_before = random.getstate()
    result = classify_character_ability_document(source, document)
    rng_after = random.getstate()
    by_path = {str(record.source.evidence["json_path"]): record for record in result.scope_records}
    same_paths = ("$.SameObject.Event", "$.SameObject.$type", "$.SameObject.TaskList[0].$type")
    presentation_paths = (
        "$.Presentation.$type", "$.Presentation.TaskList[0].$type", "$.Presentation.TaskList[1].$type",
        "$.Structural.OnProjectileHitClientOnly", "$.Structural.OnProjectileHitClientOnly.$type",
    )
    gameplay_paths = ("$.GameplayName.Event", "$.GameplayName.$type")
    reverse_paths = ("$.ReverseObject.Event", "$.ReverseObject.$type", "$.ReverseObject.TaskList[0].$type")
    conflict_paths = ("$.ConflictingObject.Event", "$.ConflictingObject.$type")
    empty = by_path["$.EmptyResource.$type"]
    client_resource = by_path["$.ClientResource.$type"]
    known_resource = by_path["$.KnownResource.$type"]
    known_projection = next(item for item in result.projections if item.scope_record_id == known_resource.record_id)
    malformed_projection = classify_character_ability_document(source, {"$type": "RPG.GameCore.SetTeamLockTarget", "Team": "TeamLight"})
    unknown = classify_character_ability_document(source, {"$type": "RPG.GameCore.FutureUnknownScopeNode", "Value": 1})
    filtered = classify_character_ability_document(source, document["Presentation"], families=["AddModifier"])
    return _cases(
        same_object_terminal_dominates=all(by_path[path].effective_scope == "non_gameplay" for path in same_paths),
        nested_terminal_dominates=all(by_path[path].effective_scope == "non_gameplay" for path in presentation_paths),
        reverse_object_terminal_dominates=all(by_path[path].effective_scope == "non_gameplay" for path in reverse_paths),
        conflicting_object_scopes_blocked=(all(by_path[path].effective_scope == "decode_required" for path in conflict_paths)
                                           and any(issue.code == "scope_decision_required" and "conflicting same-object" in issue.detail for issue in result.issues)),
        on_break_extend_anim_remains_gameplay=all(by_path[path].effective_scope == "gameplay" for path in gameplay_paths),
        non_gameplay_rng_unchanged=rng_before == rng_after,
        family_filter_preserves_trigger_ancestor=any(record.family == "TriggerEffect" and record.materialization_role == "ancestor_context" for record in filtered.scope_records),
        empty_resource_not_lowered=(
            empty.effective_scope == "decode_required"
            and empty.coverage_status == "blocked"
            and bool(empty.raw_fields)
            and not any(projection.scope_record_id == empty.record_id for projection in result.projections)
        ),
        client_only_resource_retired=(client_resource.effective_scope == "non_gameplay" and client_resource.admission_status == "retired"),
        known_resource_fields_preserved=(
            known_resource.effective_scope == "battle_data_projection"
            and known_projection.payload["resource_fields"]["Active"] == "True"
            and known_projection.payload["resource_fields"]["CurrentState"] == "Normal"
            and known_projection.payload["resource_fields"]["BarType"] == 1
            and known_projection.payload["resource_fields"]["CD"]["FixedValue"]["Value"] == 0
        ),
        malformed_projection_fail_closed=(not malformed_projection.projections and any(issue.code == "projection_blocked" for issue in malformed_projection.issues)),
        unknown_scope_preserved=(
            len(unknown.scope_records) == 1
            and unknown.scope_records[0].effective_scope == "decode_required"
            and bool(unknown.scope_records[0].raw_fields)
            and any(issue.code == "scope_decision_required" for issue in unknown.issues)
        ),
    )
def _projection_construction_matrix() -> dict[str, JSONValue]:
    scope_id = "character_ability_scope:projection_contract_probe"
    evidence_input: dict[str, Any] = {"nested": {"value": 1}}
    payload_input = _resource_payload(1.0)
    projection = CharacterAbilityProjectionIR(
        projection_id="character_ability_projection:contract_probe",
        scope_record_id=scope_id,
        projection_scope="battle_data_projection",
        projection_kind="special_resource_state_fragment",
        source_opcode="SetEnergyBarState",
        payload=payload_input,
        raw_field_names=("CurrentCount",),
        ignored_client_fields=(),
        source=IRSource(
            source_path="validation/projection.json",
            raw_type="SetEnergyBarState",
            raw_id=scope_id,
            evidence=evidence_input,
        ),
    )
    payload_input["resource_fields"]["CurrentCount"]["FixedValue"]["Value"] = 9.0
    evidence_input["nested"]["value"] = 9
    detached = projection.to_json()
    detached_payload = detached["payload"]
    assert isinstance(detached_payload, dict)
    detached_payload["forged"] = 1
    frozen_source = _synthetic_source()
    def reject_projection(**changes: Any) -> bool:
        return _expect_rejected(lambda: replace(projection, **changes))
    def reject_resource_fields(fields: dict[str, Any]) -> bool:
        return reject_projection(
            payload={"operation": "resource_state", "resource_fields": fields},
            raw_field_names=tuple(sorted(fields)),
        )
    return _cases(
        payload_copied_and_frozen=(
            projection.payload["resource_fields"]["CurrentCount"]["FixedValue"]["Value"]
            == 1.0
            and _mutation_rejected(
                lambda: projection.payload.__setitem__("forged", 1)  # type: ignore[attr-defined]
            )
        ),
        projection_json_detached="forged" not in projection.payload,
        source_evidence_copied_and_frozen=(
            projection.source.evidence["nested"]["value"] == 1
            and _mutation_rejected(
                lambda: projection.source.evidence.__setitem__("forged", 1)  # type: ignore[attr-defined]
            )
        ),
        fake_source_kind_rejected=_expect_rejected(lambda: replace(frozen_source, source_kind="forged")),
        fake_digest_rejected=_expect_rejected(lambda: replace(frozen_source, content_sha256="not-sha256")),
        empty_projection_rejected=reject_projection(payload={"operation": "resource_state", "resource_fields": {}}),
        fake_projection_kind_rejected=reject_projection(projection_kind="forged"),
        wrong_projection_opcode_rejected=reject_projection(source_opcode="AddModifier"),
        forged_raw_lineage_rejected=reject_projection(raw_field_names=("MaxCount",)),
        wrong_projection_field_type_rejected=reject_projection(
            payload={"operation": "resource_state", "resource_fields": {"CurrentCount": "1"}}
        ),
        known_resource_field_types_enforced=all((
            reject_resource_fields({"CurrentState": ""}),
            reject_resource_fields({"Active": True}),
            reject_resource_fields({"BarType": True}),
            reject_resource_fields({"CD": 0}),
            reject_resource_fields({"FutureState": "unknown"}),
        )),
        nonfinite_projection_rejected=reject_projection(payload=_resource_payload(float("nan"))),
        fake_projection_coverage_rejected=reject_projection(coverage_status="validated"),
    )

def _oracle_ability_path(character_path: str) -> str:
    path = PurePosixPath(character_path)
    name = path.name.removesuffix("_Config.json") + "_Ability.json" if path.name.endswith("_Config.json") else path.stem + "_Ability.json"
    root = "Config/ConfigAbility/Avatar/Advanced" if "Advanced" in path.parts else "Config/ConfigAbility/Avatar"
    return f"{root}/{name}"

def _oracle_avatar_id(value: object, context: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int): raise ValueError(f"oracle avatar identity is not an integer:{context}")
    return str(value)

def _oracle_source_inventory(snapshot: CharacterAbilityRawSnapshot) -> dict[str, dict[str, JSONValue]]:
    rows: dict[str, list[Any]] = {}
    for path in _ORACLE_INVENTORY_PATHS:
        value = json.loads(snapshot.inventory_bytes[path])
        if not isinstance(value, list):
            raise ValueError(f"oracle inventory is not a list:{path}")
        rows[path] = value
    base: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for path in _ORACLE_INVENTORY_PATHS[:2]:
        for index, row in enumerate(rows[path]):
            if not isinstance(row, dict) or not isinstance(row.get("Release"), bool):
                raise ValueError(f"oracle avatar row invalid:{path}:{index}")
            if not row["Release"]:
                continue
            avatar_id = _oracle_avatar_id(row.get("AvatarID"), f"{path}:{index}")
            if avatar_id in base:
                raise ValueError(f"oracle avatar identity invalid:{avatar_id}")
            base[avatar_id] = (path, index, row)
    enhanced: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, row in enumerate(rows[_ORACLE_INVENTORY_PATHS[2]]):
        if not isinstance(row, dict):
            raise ValueError("oracle enhanced avatar row invalid")
        avatar_id = _oracle_avatar_id(row.get("AvatarID"), f"enhanced:{index}")
        if avatar_id in enhanced:
            raise ValueError(f"oracle enhanced avatar identity invalid:{avatar_id}")
        enhanced[avatar_id] = (index, row)
    if set(enhanced) - set(base):
        raise ValueError("oracle enhanced inventory references unreleased avatars")
    result: dict[str, dict[str, JSONValue]] = {}
    for avatar_id, (base_path, base_index, base_row) in base.items():
        base_type = base_row.get("AvatarBaseType")
        if not isinstance(base_type, str) or not base_type:
            raise ValueError(f"oracle avatar base type invalid:{avatar_id}")
        if base_type in _ORACLE_DEFERRED_BASE_TYPES:
            continue
        selected = enhanced.get(avatar_id)
        row = selected[1] if selected else base_row
        json_path = row.get("JsonPath")
        if not isinstance(json_path, str) or not json_path:
            raise ValueError(f"oracle avatar JsonPath missing:{avatar_id}")
        ability_path = _oracle_ability_path(json_path)
        if ability_path in result:
            raise ValueError(f"oracle duplicate ability path:{ability_path}")
        result[ability_path] = {
            "source_kind": "character_main", "avatar_id": avatar_id, "base_type": base_type,
            "config_source_path": _ORACLE_INVENTORY_PATHS[2] if selected else base_path,
            "config_row_index": selected[0] if selected else base_index,
            "selected_version": "enhanced" if selected else "base",
        }
    result[_ORACLE_SHARED_SOURCE] = {
        "source_kind": "character_shared", "avatar_id": "", "base_type": "shared_character_runtime",
        "config_source_path": _ORACLE_SHARED_SOURCE, "config_row_index": 0, "selected_version": "shared",
    }
    return result

def _oracle_child_path(path: str, key: object) -> str:
    text = str(key)
    if text and all(character.isalnum() or character == "_" for character in text):
        return f"{path}.{text}"
    return f"{path}[{json.dumps(text, ensure_ascii=True)}]"

def _oracle_occurrences(
    snapshot: CharacterAbilityRawSnapshot,
) -> tuple[tuple[tuple[str, str, str, str], ...], tuple[tuple[str, str, str, str], ...]]:
    result: list[tuple[str, str, str, str]] = []
    resources: list[tuple[str, str, str, str]] = []
    def walk(source_path: str, value: object, path: str) -> None:
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(source_path, item, f"{path}[{index}]")
            return
        if not isinstance(value, Mapping):
            return
        event = value.get("Event")
        if isinstance(event, str):
            result.append((source_path, f"{path}.Event", "event", event))
        raw_type = value.get("$type")
        if isinstance(raw_type, str):
            opcode = raw_type.rsplit(".", 1)[-1]
            result.append((source_path, f"{path}.$type", "typed_node", opcode))
            if opcode in {"SetEnergyBarState", "SetSummonerEnergyBarState"}:
                fields = set(value) - {"$type"}
                unknown = fields - _ORACLE_RESOURCE_FIELDS - _ORACLE_RESOURCE_CLIENT_FIELDS
                shape = "unclassified" if unknown else (
                    "known" if fields & _ORACLE_RESOURCE_FIELDS else
                    "client_only" if fields and fields <= _ORACLE_RESOURCE_CLIENT_FIELDS else
                    "unclassified"
                )
                resources.append((source_path, f"{path}.$type", opcode, shape))
        for key, child in value.items():
            child_path = _oracle_child_path(path, key)
            if str(key).startswith("On") and isinstance(child, (Mapping, list, tuple)):
                result.append((source_path, child_path, "structural_entry", str(key)))
            walk(source_path, child, child_path)
    for source_path, document in snapshot.documents.items():
        walk(source_path, document, "$")
    return tuple(result), tuple(resources)

def _source_oracle_checks(snapshot: CharacterAbilityRawSnapshot) -> dict[str, JSONValue]:
    oracle = _oracle_source_inventory(snapshot)
    selected_paths = set(snapshot.source_filter) if snapshot.source_filter else set(oracle)
    sources_by_path = {source.source.source_path: source for source in snapshot.sources}
    candidates_by_path = {candidate.relative_path: candidate for candidate in snapshot.candidates}
    candidate_ok = set(candidates_by_path) == set(oracle) and all(
        candidate.manifest_fields() == (expected["source_kind"], expected["avatar_id"], expected["base_type"], path,
                                        expected["config_source_path"], str(expected["config_row_index"]), expected["selected_version"])
        for path, expected in oracle.items() for candidate in (candidates_by_path[path],)
    )
    metadata_ok = True
    digest_ok = True
    for path in selected_paths:
        source = sources_by_path.get(path)
        expected = oracle[path]
        if source is None:
            metadata_ok = False
            continue
        metadata_ok = metadata_ok and (
            source.source_kind == expected["source_kind"]
            and source.avatar_id == expected["avatar_id"]
            and source.base_type == expected["base_type"]
            and all(source.source.evidence.get(key) == value for key, value in expected.items() if key != "source_kind")
        )
        raw_bytes = snapshot.source_bytes[path]
        digest_ok = digest_ok and source.content_sha256 == sha256(raw_bytes).hexdigest()
    return {
        "ok": set(sources_by_path) == selected_paths
        and set(snapshot.documents) == selected_paths
        and set(snapshot.source_bytes) == selected_paths
        and candidate_ok
        and metadata_ok
        and digest_ok,
        "oracle_available_source_count": len(oracle),
        "selected_source_count": len(selected_paths),
        "metadata_closed": metadata_ok,
        "candidate_manifest_closed": candidate_ok,
        "content_digests_closed": digest_ok,
    }

def _occurrence_oracle_checks(snapshot: CharacterAbilityRawSnapshot, catalog: CharacterAbilityScopeProjectionCatalog) -> dict[str, JSONValue]:
    oracle_rows, resource_rows = _oracle_occurrences(snapshot)
    requested = set(catalog.family_filter)
    expected = {
        row for row in oracle_rows if not requested or row[3] in requested
    }
    actual_rows = [
        (
            record.source.source_path,
            str(record.source.evidence.get("json_path") or ""),
            record.occurrence_kind,
            record.family,
        )
        for record in catalog.scope_records
        if record.materialization_role == "selected"
    ]
    actual = set(actual_rows)
    records_by_identity = {
        (
            record.source.source_path,
            str(record.source.evidence.get("json_path") or ""),
            record.occurrence_kind,
            record.family,
        ): record
        for record in catalog.scope_records
        if record.materialization_role == "selected"
    }
    projection_roots = {projection.scope_record_id for projection in catalog.projections}
    resource_ok = True
    for source_path, json_path, opcode, shape in resource_rows:
        if requested and opcode not in requested:
            continue
        record = records_by_identity.get((source_path, json_path, "typed_node", opcode))
        if record is None:
            resource_ok = False
        elif record.effective_scope == "non_gameplay":
            continue
        elif shape == "known":
            resource_ok &= record.effective_scope == "battle_data_projection" and record.record_id in projection_roots
        else:
            resource_ok &= shape == "unclassified" and record.effective_scope == "decode_required"
    parent_ids = {source.source_id for source in catalog.sources} | {
        record.record_id for record in catalog.scope_records
    }
    family_counts = Counter()
    for family in catalog.families:
        family_counts[family.occurrence_kind] += family.occurrence_count
    actual_counts = Counter(row[2] for row in actual_rows)
    return {
        "ok": expected == actual
        and len(actual_rows) == len(actual)
        and resource_ok
        and all(
            record.parent_record_id in parent_ids
            for record in catalog.scope_records
        )
        and family_counts == actual_counts,
        "oracle_occurrence_count": len(oracle_rows),
        "expected_selected_count": len(expected),
        "actual_selected_count": len(actual_rows),
        "oracle_counts_by_kind": dict(sorted(Counter(row[2] for row in oracle_rows).items())),
        "actual_counts_by_kind": dict(sorted(actual_counts.items())),
        "unit_topology_producer_count": sum(
            row[2] == "typed_node" and row[3] == "SetExcludeInMultiCharacterFormation"
            for row in oracle_rows
        ),
        "resource_shape_counts": dict(sorted(Counter(row[3] for row in resource_rows).items())),
        "resource_oracle_closed": resource_ok,
    }

def _projection_checks(
    catalog: CharacterAbilityScopeProjectionCatalog,
) -> dict[str, JSONValue]:
    sources = {source.source.source_path for source in catalog.sources}
    records = {record.record_id: record for record in catalog.scope_records}
    roots = [
        record
        for record in catalog.scope_records
        if record.materialization_role == "selected"
        and record.occurrence_kind == "typed_node"
        and record.nominal_scope
        in {"battle_data_projection", "input_projection", "environment_input"}
        and record.effective_scope == record.nominal_scope
    ]
    source_backed = all(
        projection.scope_record_id in records
        and projection.source.source_path in sources
        and bool(projection.source.evidence.get("json_path"))
        and projection.source_opcode == records[projection.scope_record_id].family
        for projection in catalog.projections
    )
    gameplay_ids = {record.record_id for record in catalog.gameplay_records}
    execution_fields_absent = all(
        not {"runtime_executable", "client_operation_executable"}.intersection(
            projection.to_json()
        )
        for projection in catalog.projections
    )
    return {
        "ok": source_backed
        and len(roots) == len(catalog.projections)
        and not any(
            projection.scope_record_id in gameplay_ids
            for projection in catalog.projections
        )
        and execution_fields_absent,
        "source_backed": source_backed,
        "projection_root_count": len(roots),
        "projection_count": len(catalog.projections),
        "execution_fields_absent": execution_fields_absent,
    }

def _decode_checks(
    catalog: CharacterAbilityScopeProjectionCatalog,
) -> dict[str, JSONValue]:
    records = [
        record
        for record in catalog.scope_records
        if record.effective_scope == "decode_required"
    ]
    return {
        "ok": all(
            record.coverage_status == "blocked"
            and record.admission_status == "blocked"
            and bool(record.blocked_reason)
            and bool(record.raw_fields)
            and bool(record.source.evidence.get("json_path"))
            for record in records
        ),
        "count": len(records),
    }

def _catalog_construction_matrix(catalog: CharacterAbilityScopeProjectionCatalog) -> dict[str, JSONValue]:
    record = catalog.scope_records[0]
    dangling = replace(record, parent_record_id="missing:scope_parent")
    dangling_records = tuple(dangling if item.record_id == record.record_id else item for item in catalog.scope_records)
    semantic_projection = next(
        item for item in catalog.projections if item.projection_kind == "special_resource_state_fragment"
        and "CurrentState" in item.payload["resource_fields"]
    )
    changed_payload = semantic_projection.to_json()["payload"]
    assert isinstance(changed_payload, dict)
    fake_projection = _UncheckedProjection(**{item.name: (dict(changed_payload) if item.name == "payload" else getattr(semantic_projection, item.name)) for item in fields(CharacterAbilityProjectionIR)})
    changed_fields = changed_payload["resource_fields"]
    assert isinstance(changed_fields, dict) and isinstance(changed_fields["CurrentState"], str)
    changed_fields["CurrentState"] += "_identity_probe"
    changed_projection = replace(semantic_projection, payload=changed_payload)
    changed_catalog = replace(catalog, projections=tuple(changed_projection if item.projection_id == changed_projection.projection_id else item for item in catalog.projections))
    reordered_catalog = replace(
        catalog, sources=tuple(reversed(catalog.sources)), scope_records=tuple(reversed(catalog.scope_records)), projections=tuple(reversed(catalog.projections)), families=tuple(reversed(catalog.families)),
        external_dependencies=tuple(reversed(catalog.external_dependencies)), issues=tuple(reversed(catalog.issues)))
    main_record = next(item for item in catalog.scope_records if item.source.evidence["source_kind"] == "character_main")
    forged_record = replace(main_record, source=replace(main_record.source, evidence={**main_record.source.evidence, "avatar_id": "forged-avatar"}))
    forged_record_path = replace(main_record, source=replace(main_record.source, evidence={**main_record.source.evidence, "json_path": "$.Forged.$type"}))
    inherited_record = next(item for item in catalog.scope_records if item.source.evidence["inherited_scope_record_id"])
    forged_inherited = replace(inherited_record, source=replace(inherited_record.source, evidence={**inherited_record.source.evidence, "inherited_scope_record_id": "missing:terminal"}))
    forged_projection_source = replace(semantic_projection, source=replace(semantic_projection.source, evidence={**semantic_projection.source.evidence, "json_path": "$.Forged.$type"}))
    def replace_record(forged: Any) -> tuple[Any, ...]:
        return tuple(forged if item.record_id == forged.record_id else item for item in catalog.scope_records)
    summary = catalog.summary_json()
    coverage = summary["coverage_summary"]
    assert isinstance(coverage, dict)
    coverage["forged"] = 1
    def reject_catalog(**changes: Any) -> bool:
        return _expect_rejected(lambda: replace(catalog, **changes))
    return _cases(
        coverage_summary_frozen_and_detached=(
            _mutation_rejected(
                lambda: catalog.coverage_summary.__setitem__("forged", 1)  # type: ignore[attr-defined]
            )
            and "forged" not in catalog.coverage_summary
        ),
        build_counters_frozen=_mutation_rejected(lambda: catalog.build_counters.__setitem__("forged", 1)),  # type: ignore[attr-defined]
        family_counts_frozen=_mutation_rejected(lambda: catalog.families[0].effective_scope_counts.__setitem__("gameplay", 999)),  # type: ignore[attr-defined]
        duplicate_record_rejected=reject_catalog(scope_records=(record, record)),
        duplicate_source_rejected=reject_catalog(sources=(catalog.sources[0], catalog.sources[0])),
        dangling_parent_rejected=reject_catalog(scope_records=dangling_records),
        record_source_evidence_forgery_rejected=reject_catalog(scope_records=replace_record(forged_record)),
        record_path_identity_forgery_rejected=reject_catalog(scope_records=replace_record(forged_record_path)),
        inherited_terminal_forgery_rejected=reject_catalog(scope_records=replace_record(forged_inherited)),
        projection_source_evidence_forgery_rejected=reject_catalog(projections=tuple(forged_projection_source if item.projection_id == forged_projection_source.projection_id else item for item in catalog.projections)),
        projection_subclass_rejected=reject_catalog(projections=tuple(fake_projection if item.projection_id == fake_projection.projection_id else item for item in catalog.projections)),
        inconsistent_completeness_rejected=reject_catalog(fingerprint_kind="partial" if catalog.fingerprint_kind == "complete" else "complete"),
        fake_catalog_digest_rejected=reject_catalog(source_fingerprint="not-sha256"),
        external_dependency_forgery_rejected=reject_catalog(external_dependencies=()),
        nonfinite_counter_rejected=reject_catalog(build_counters={"forged": float("inf")}),
        catalog_identity_binds_projection_semantics=changed_catalog.catalog_id != catalog.catalog_id,
        catalog_identity_is_order_invariant=reordered_catalog.catalog_id == catalog.catalog_id and reordered_catalog.scope_records == catalog.scope_records,
    )

def _fingerprint_checks(snapshot: CharacterAbilityRawSnapshot) -> tuple[dict[str, JSONValue], CharacterAbilityRawSnapshot]:
    def fingerprint(**changes: Any) -> str:
        return character_ability_snapshot_fingerprint(snapshot, **changes)
    main_source = next(source for source in snapshot.sources if source.source_kind == "character_main")
    candidate = next(item for item in snapshot.candidates if item.relative_path == main_source.source.source_path)
    fake_manifest = _UncheckedInventoryManifest(snapshot.inventory_bytes)
    inventory = dict(snapshot.inventory_bytes)
    first_inventory = sorted(inventory)[0]
    inventory[first_inventory] += b"\n"
    inventory_changed = fingerprint(inventory_bytes=inventory)
    source_bytes = dict(snapshot.source_bytes)
    first_source = sorted(source_bytes)[0]
    source_bytes[first_source] += b"\n"
    ability_changed = fingerprint(source_bytes=source_bytes)
    mapping_inventory = dict(snapshot.inventory_bytes)
    for config_path in _ORACLE_INVENTORY_PATHS[:2]:
        rows = json.loads(mapping_inventory[config_path])
        row = next((item for item in rows if _oracle_avatar_id(item.get("AvatarID"), config_path) == main_source.avatar_id), None)
        if row is not None:
            row["AvatarBaseType"] = main_source.base_type + "_probe"
            mapping_inventory[config_path] = json.dumps(rows, separators=(",", ":")).encode()
            break
    mapping_changed = fingerprint(inventory_bytes=mapping_inventory)
    partial_path = sorted(snapshot.source_bytes)[0]
    partial_filter = (partial_path,)
    partial_bytes = {partial_path: snapshot.source_bytes[partial_path]}
    partial_fingerprint = fingerprint(
        source_bytes=partial_bytes,
        fingerprint_kind="partial",
        source_filter=partial_filter,
    )
    partial_snapshot = CharacterAbilityRawSnapshot(
        inventory_manifest=snapshot.inventory_manifest,
        source_bytes=partial_bytes,
        sources=tuple(source for source in snapshot.sources if source.source.source_path == partial_path),
        source_fingerprint=partial_fingerprint,
        fingerprint_kind="partial",
        source_filter=partial_filter,
        build_counters={
            "inventory_source_read_count": len(snapshot.inventory_bytes),
            "inventory_source_parse_count": len(snapshot.inventory_bytes),
            "ability_source_read_count": len(partial_bytes),
            "ability_source_parse_count": len(partial_bytes),
            "source_filter_applied_before_ability_read": True,
        },
    )
    forged_avatar = main_source.avatar_id + "_forged"
    forged_candidate = replace(candidate, avatar_id=forged_avatar)
    forged_candidates = tuple(forged_candidate if item.relative_path == candidate.relative_path else item for item in snapshot.candidates)
    forged_source_id = f"character_ability_source:avatar:{forged_avatar}"
    forged_source = replace(main_source, source_id=forged_source_id, avatar_id=forged_avatar,
                            source=replace(main_source.source, raw_id=forged_source_id, evidence={**main_source.source.evidence, "avatar_id": forged_avatar}))
    forged_sources = tuple(forged_source if item.source_id == main_source.source_id else item for item in snapshot.sources)
    forged_fingerprint = _compute_source_fingerprint(
        snapshot.inventory_bytes, forged_candidates, snapshot.source_bytes,
        snapshot.fingerprint_kind, snapshot.source_filter,
    )
    forged_document = json.loads(snapshot.source_bytes[first_source])
    forged_document["__p9_s0_forged__"] = {"$type": "RPG.GameCore.AddModifier"}
    forged_documents = {**snapshot.documents, first_source: forged_document}
    manifest_rejections = {
        "document_bytes_mismatch_rejected": _expect_rejected(lambda: replace(snapshot, documents=forged_documents)),
        "coordinated_inventory_forgery_rejected": (
            _expect_rejected(lambda: replace(snapshot, sources=forged_sources, source_fingerprint=forged_fingerprint))
            and _expect_rejected(lambda: replace(snapshot, candidates=forged_candidates))
        ),
        "manifest_scalar_types_rejected": all((_expect_rejected(lambda: replace(candidate, avatar_id=1)), _expect_rejected(lambda: replace(candidate, source_kind=[])), _expect_rejected(lambda: _normalize_inventory_avatar_id(True, "probe")), _expect_rejected(lambda: _normalize_inventory_avatar_id(1.5, "probe")), _expect_rejected(lambda: replace(snapshot, inventory_manifest=fake_manifest)))),
        "candidate_order_fingerprint_stable": _compute_source_fingerprint(
            dict(reversed(tuple(snapshot.inventory_bytes.items()))),
            tuple(reversed(snapshot.candidates)),
            dict(reversed(tuple(snapshot.source_bytes.items()))),
            snapshot.fingerprint_kind, snapshot.source_filter,
        ) == snapshot.source_fingerprint,
    }
    return (
        {
            "ok": len(
                {
                    snapshot.source_fingerprint,
                    inventory_changed,
                    ability_changed,
                    mapping_changed,
                    partial_fingerprint,
                }
            )
            == 5
            and all(manifest_rejections.values())
            and not partial_snapshot.source_catalog_complete
            and partial_snapshot.fingerprint_kind == "partial"
            and _expect_rejected(lambda: replace(snapshot, source_fingerprint="0" * 63)),
            "full_fingerprint": snapshot.source_fingerprint, "inventory_changed_fingerprint": inventory_changed,
            "ability_changed_fingerprint": ability_changed, "mapping_changed_fingerprint": mapping_changed,
            "partial_fingerprint": partial_fingerprint,
            **manifest_rejections,
        },
        partial_snapshot,
    )

def _narrow_view_checks(
    catalog: CharacterAbilityScopeProjectionCatalog,
    snapshot: CharacterAbilityRawSnapshot,
    tbgd_root: Path,
) -> dict[str, JSONValue]:
    family = "AddModifier"
    existing = catalog.for_families({family})
    selected_count = sum(item.occurrence_count for item in existing.families)
    parent_ids = {source.source_id for source in existing.sources} | {
        record.record_id for record in existing.scope_records
    }
    missing = catalog.for_families({"__p9_s0_missing_family__"})
    original_read_bytes = Path.read_bytes
    def forbidden_read_bytes(_path: Path) -> bytes:
        raise AssertionError("family view attempted source IO after snapshot creation")
    Path.read_bytes = forbidden_read_bytes
    try:
        direct = build_character_ability_scope_projection(
            tbgd_root,
            families=[family],
            snapshot=snapshot,
        )
    finally:
        Path.read_bytes = original_read_bytes
    direct_parent_ids = {source.source_id for source in direct.sources} | {
        record.record_id for record in direct.scope_records
    }
    return {
        "ok": bool(existing.scope_records)
        and all(record.parent_record_id in parent_ids for record in existing.scope_records)
        and len(existing.scope_records) > selected_count
        and all(
            record.parent_record_id in direct_parent_ids
            for record in direct.scope_records
        )
        and int(direct.build_counters["materialized_record_count"])
        < int(direct.build_counters["discovered_occurrence_count"])
        and not direct.complete
        and not missing.ok
        and not missing.complete
        and any(
            issue.code == "requested_family_not_found" for issue in missing.issues
        ),
        "existing_materialized_record_count": len(existing.scope_records),
        "direct_materialized_record_count": direct.build_counters[
            "materialized_record_count"
        ],
        "direct_discovered_occurrence_count": direct.build_counters[
            "discovered_occurrence_count"
        ],
        "additional_source_reads": 0,
    }

def _all_cases_ok(matrix: Mapping[str, JSONValue]) -> bool:
    return all(
        isinstance(value, Mapping) and value.get("ok") is True
        for value in matrix.values()
    )
def _evidence_size(output_dir: Path) -> int:
    return sum(path.stat().st_size for path in output_dir.iterdir() if path.is_file())
def main() -> int:
    args = _parse_args()
    started = time.perf_counter()
    root = args.tbgd_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    full_mode = not args.family and not args.source_path
    read_counts: Counter[str] = Counter()
    lowering_calls: list[str] = []
    original_read_bytes = Path.read_bytes
    original_lowering_build = TBGDLowering.build
    def tracked_read_bytes(path: Path) -> bytes:
        read_counts[str(path.resolve())] += 1
        return original_read_bytes(path)
    def forbidden_lowering_build(*_args: Any, **_kwargs: Any) -> Any:
        lowering_calls.append("TBGDLowering.build")
        raise AssertionError("S0 narrow projection invoked full lowering")
    rng_before = random.getstate()
    Path.read_bytes = tracked_read_bytes
    TBGDLowering.build = forbidden_lowering_build  # type: ignore[assignment]
    try:
        snapshot = build_character_ability_raw_snapshot(
            root,
            source_paths=args.source_path or None,
        )
        catalog = build_character_ability_scope_projection(
            root,
            families=args.family or None,
            snapshot=snapshot,
        )
    finally:
        TBGDLowering.build = original_lowering_build  # type: ignore[assignment]
        Path.read_bytes = original_read_bytes
    rng_after = random.getstate()
    source_oracle = _source_oracle_checks(snapshot)
    occurrence_oracle = _occurrence_oracle_checks(snapshot, catalog)
    branch_matrix = _branch_matrix()
    projection_construction = _projection_construction_matrix()
    catalog_construction = _catalog_construction_matrix(catalog)
    fingerprint_checks, partial_snapshot = _fingerprint_checks(snapshot)
    partial_catalog = build_character_ability_scope_projection(
        root,
        snapshot=partial_snapshot,
    )
    narrow_view = _narrow_view_checks(catalog, snapshot, root)
    projection_checks = _projection_checks(catalog)
    decode_checks = _decode_checks(catalog)
    selected_paths = set(snapshot.source_filter) if snapshot.source_filter else {
        source.source.source_path for source in snapshot.sources
    }
    expected_read_paths = {
        str((root / path).resolve()) for path in _ORACLE_INVENTORY_PATHS
    } | {str((root / path).resolve()) for path in selected_paths}
    actual_reads_once = set(read_counts) == expected_read_paths and all(
        count == 1 for count in read_counts.values()
    )
    non_gameplay = [
        record
        for record in catalog.scope_records
        if record.effective_scope == "non_gameplay"
    ]
    gameplay_ids = {record.record_id for record in catalog.gameplay_records}
    non_gameplay_closed = all(
        record.admission_status == "retired"
        and record.coverage_status == "audit_only"
        and record.record_id not in gameplay_ids
        and "runtime_executable" not in record.to_json()
        for record in non_gameplay
    )
    oracle_unit_topology = bool(occurrence_oracle["unit_topology_producer_count"])
    dependency_rows = [item.to_json() for item in catalog.external_dependencies]
    external_dependency_ok = (
        not oracle_unit_topology
        and len(dependency_rows) == 1
        and dependency_rows[0]["projection_kind"] == "unit_topology"
        and dependency_rows[0]["status"] == "external_content_dependency"
        and catalog.summary_json()["external_dependencies"] == dependency_rows
    ) if full_mode else all(
        row["status"] != "external_content_dependency" for row in dependency_rows
    )
    checks = _cases(
        target_source_catalog_complete=(
            bool(source_oracle["ok"])
            and actual_reads_once
            and snapshot.build_counters["inventory_source_parse_count"] == len(snapshot.inventory_bytes)
            and snapshot.build_counters["ability_source_parse_count"] == len(selected_paths)
            and (catalog.source_catalog_complete if full_mode else not catalog.complete)
        ),
        typed_node_and_event_scope_reconciled=bool(occurrence_oracle["ok"]),
        branch_scope_propagation_correct=_all_cases_ok(branch_matrix),
        non_gameplay_nodes_executable_count=non_gameplay_closed,
        non_gameplay_rng_consumption=(
            rng_before == rng_after
            and bool(branch_matrix["non_gameplay_rng_unchanged"]["ok"])
        ),
        battle_data_projection_source_backed=bool(projection_checks["ok"]),
        input_projection_does_not_execute_client_operation=bool(
            projection_checks["execution_fields_absent"]
        ),
        decode_required_preserved=bool(decode_checks["ok"]),
        narrow_projection_full_lowering_count=not lowering_calls,
        limited_catalog_cannot_masquerade_as_complete=(
            bool(narrow_view["ok"])
            and not partial_snapshot.source_catalog_complete
            and not partial_catalog.source_catalog_complete
            and not partial_catalog.complete
        ),
        recursive_immutability_and_constructor_boundary=(
            _all_cases_ok(projection_construction)
            and _all_cases_ok(catalog_construction)
        ),
        inventory_and_selection_fingerprint_closed=bool(fingerprint_checks["ok"]),
        external_content_dependency_machine_readable=external_dependency_ok,
        compiler_issues_empty=catalog.ok,
    )
    checks["target_source_catalog_complete"]["source_read_count"] = sum(
        read_counts.values()
    )
    checks["non_gameplay_nodes_executable_count"]["record_count"] = len(
        non_gameplay
    )
    checks["narrow_projection_full_lowering_count"]["intercepted_call_count"] = len(
        lowering_calls
    )
    evidence: dict[str, Any] = {
        "source_inventory.json": {
            "snapshot": snapshot.summary_json(),
            "oracle": source_oracle,
            "sources": [source.to_json() for source in catalog.sources],
        },
        "scope_reconciliation.json": {
            "oracle": occurrence_oracle,
            "coverage_summary": catalog.summary_json()["coverage_summary"],
            "families": [family.to_json() for family in catalog.families],
        },
        "projection_ledger.json": [
            projection.to_json() for projection in catalog.projections
        ],
        "decode_matrix.json": [
            record.to_json()
            for record in catalog.scope_records
            if record.effective_scope == "decode_required"
        ],
        "negative_matrix.json": branch_matrix,
        "construction_matrix.json": {
            "projection": projection_construction,
            "catalog": catalog_construction,
            "fingerprint": fingerprint_checks,
            "narrow_view": narrow_view,
        },
    }
    for name, value in evidence.items():
        _write_json(output_dir / name, value, pretty=name.endswith("matrix.json"))
    wall_seconds = time.perf_counter() - started
    max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    validation_code_lines = sum(
        bool(line.strip()) for line in Path(__file__).read_text(encoding="utf-8").splitlines()
    )
    evidence_before_summary = _evidence_size(output_dir)
    resource_checks = {
        "wall_clock_within_budget": wall_seconds < WALL_CLOCK_BUDGET_SECONDS,
        "rss_within_budget": max_rss_bytes < RSS_BUDGET_BYTES,
        "evidence_within_budget": evidence_before_summary < EVIDENCE_BUDGET_BYTES,
        "validation_code_within_budget": validation_code_lines
        <= VALIDATION_CODE_BUDGET_LINES,
    }
    business_ok = all(check["ok"] for check in checks.values())
    ok = business_ok and all(resource_checks.values())
    summary: dict[str, JSONValue] = {
        "ok": ok,
        "business_ok": business_ok,
        "mode": "full" if full_mode else "diagnostic_slice",
        "authoritative_entry_invocation_count": 1,
        "checks": checks,
        "catalog": catalog.summary_json(),
        "resources": {
            "wall_seconds": round(wall_seconds, 6),
            "max_rss_bytes": max_rss_bytes,
            "evidence_bytes_before_summary": evidence_before_summary,
            "validation_code_lines": validation_code_lines,
            "budgets": {
                "wall_seconds": WALL_CLOCK_BUDGET_SECONDS,
                "max_rss_bytes": RSS_BUDGET_BYTES,
                "evidence_bytes": EVIDENCE_BUDGET_BYTES,
                "validation_code_lines": VALIDATION_CODE_BUDGET_LINES,
            },
            "checks": resource_checks,
        },
        "evidence_files": sorted(path.name for path in output_dir.iterdir()),
    }
    _write_json(output_dir / "summary.json", summary, pretty=True)
    summary["resources"]["evidence_bytes"] = _evidence_size(output_dir)
    summary["evidence_files"] = sorted(path.name for path in output_dir.iterdir())
    _write_json(output_dir / "summary.json", summary, pretty=True)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
