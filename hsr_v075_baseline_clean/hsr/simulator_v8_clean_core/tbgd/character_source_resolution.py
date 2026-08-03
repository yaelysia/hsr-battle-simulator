from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal, cast

from ..ir_types import IRSource, JSONValue
from ..rules.expression_ir import DynamicValueOperationIR
from ..rules.ir import (
    CharacterAbilityDefinitionCandidateIR,
    CharacterAbilityDefinitionPackageOwner,
    CharacterAbilityReferenceResolutionIR,
    CharacterAbilityScopeRecordIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterAbilitySourceResolutionCatalogIR,
    CharacterDecodeFamilyResolutionIR,
    CharacterDecodedPackageOwner,
    CharacterDecodedSourceIR,
    CharacterEquivalentRawType,
    CharacterEquivalentStructureEvidenceIR,
    character_ability_definition_package_owner,
    character_ability_stable_id,
)
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
)
from .expression_lowering import (
    lower_decoded_dynamic_value_operation_spec,
    lower_numeric_expression,
)


PACKAGE_SEARCH_ROOT = "Config/ConfigAbility"


class CharacterAbilitySourcePackageIncomplete(RuntimeError):
    """The current raw package cannot support an exhaustive S3 search."""


@dataclass(frozen=True)
class _DecodeSpec:
    decoded_kind: str
    package_owner: CharacterDecodedPackageOwner
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    equivalent_type: str
    required_equivalent_roles: frozenset[str]
    decoder: Callable[[Mapping[str, Any]], dict[str, JSONValue]]


def _target_alias(value: object) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("target_alias_not_object")
    if value.get("$type") != "RPG.GameCore.TargetAlias":
        raise ValueError("target_alias_type_mismatch")
    alias = value.get("Alias")
    if not isinstance(alias, str) or not alias:
        raise ValueError("target_alias_missing")
    return alias


def _string(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(reason)
    return value


def _numeric_expression(value: object) -> dict[str, JSONValue]:
    expression = lower_numeric_expression(value)
    if expression.get("supported") is not True:
        raise ValueError(f"numeric_expression_unsupported:{expression.get('reason', '')}")
    return expression


def _decode_dynamic_definition(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    return {
        "target_alias": _target_alias(raw["HILNFHCPEAD"]),
        "dynamic_key": _string(raw["FHLJGDGMMHK"], "dynamic_key_missing"),
    }


def _decode_dynamic_write(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    operation = raw.get("FKCKKFALPBK")
    if operation is not None and (not isinstance(operation, str) or not operation):
        raise ValueError("dynamic_write_operation_invalid")
    return {
        "target_alias": _target_alias(raw["HILNFHCPEAD"]),
        "dynamic_key": _string(raw["FHLJGDGMMHK"], "dynamic_key_missing"),
        "value_expression": _numeric_expression(raw["AJHHCOHFIFA"]),
        "operation": cast(JSONValue, operation),
    }


def _decode_action_queue_precheck(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    metric = _string(raw["GMPGDEINODK"], "precheck_metric_missing")
    if metric != "SameTagInsertUnusedCount":
        raise ValueError("precheck_metric_mismatch")
    return {
        "metric": metric,
        "threshold_expression": _numeric_expression(raw["HOCMHABKLGJ"]),
    }


def _decode_target_alias(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    return {"alias": _string(raw["Alias"], "target_alias_missing")}


_DECODE_SPECS: dict[str, _DecodeSpec] = {
    "NKLOMENKLHK": _DecodeSpec(
        decoded_kind="dynamic_value_definition",
        package_owner="character_dynamic_values",
        required_fields=frozenset({"$type", "FHLJGDGMMHK", "HILNFHCPEAD"}),
        optional_fields=frozenset(),
        equivalent_type="RPG.GameCore.DefineDynamicValue",
        required_equivalent_roles=frozenset({"target_alias", "dynamic_key"}),
        decoder=_decode_dynamic_definition,
    ),
    "LAJIKDENEOO": _DecodeSpec(
        decoded_kind="dynamic_value_write",
        package_owner="character_dynamic_values",
        required_fields=frozenset(
            {"$type", "AJHHCOHFIFA", "FHLJGDGMMHK", "HILNFHCPEAD"}
        ),
        optional_fields=frozenset({"FKCKKFALPBK"}),
        equivalent_type="RPG.GameCore.SetDynamicValue",
        required_equivalent_roles=frozenset(
            {"target_alias", "dynamic_key", "value_expression"}
        ),
        decoder=_decode_dynamic_write,
    ),
    "IKDAKCBKFAB": _DecodeSpec(
        decoded_kind="action_queue_precheck",
        package_owner="character_action_queue",
        required_fields=frozenset({"$type", "GMPGDEINODK", "HOCMHABKLGJ"}),
        optional_fields=frozenset(),
        equivalent_type="",
        required_equivalent_roles=frozenset(),
        decoder=_decode_action_queue_precheck,
    ),
    "TargetAlias": _DecodeSpec(
        decoded_kind="target_alias",
        package_owner="character_target_expression",
        required_fields=frozenset({"$type", "Alias"}),
        optional_fields=frozenset(),
        equivalent_type="RPG.GameCore.TargetAlias",
        required_equivalent_roles=frozenset({"alias"}),
        decoder=_decode_target_alias,
    ),
}


def character_dynamic_value_decode_families() -> tuple[str, ...]:
    return tuple(
        sorted(
            family
            for family, spec in _DECODE_SPECS.items()
            if spec.package_owner == "character_dynamic_values"
            and spec.decoded_kind
            in {"dynamic_value_definition", "dynamic_value_write"}
        )
    )


def lower_character_decoded_dynamic_value_operation(
    record: CharacterAbilityScopeRecordIR,
) -> DynamicValueOperationIR:
    spec = _DECODE_SPECS.get(record.family)
    if (
        spec is None
        or spec.package_owner != "character_dynamic_values"
        or spec.decoded_kind
        not in {"dynamic_value_definition", "dynamic_value_write"}
    ):
        raise ValueError("scope record is not an S3 dynamic value source")
    actual_fields = frozenset(str(key) for key in record.raw_fields)
    if (
        not spec.required_fields.issubset(actual_fields)
        or actual_fields - spec.required_fields - spec.optional_fields
    ):
        raise ValueError("decoded dynamic value raw field schema mismatch")
    payload = spec.decoder(record.raw_fields)
    return DynamicValueOperationIR.from_spec(
        lower_decoded_dynamic_value_operation_spec(spec.decoded_kind, payload),
        record.source,
    )
_EQUIVALENT_REQUIRED_ROLES: dict[str, frozenset[str]] = {
    spec.equivalent_type: spec.required_equivalent_roles
    for spec in _DECODE_SPECS.values()
    if spec.equivalent_type
}


def _child_path(path: str, key: object) -> str:
    text = str(key)
    if text and all(character.isalnum() or character == "_" for character in text):
        return f"{path}.{text}"
    return f"{path}[{json.dumps(text, ensure_ascii=True)}]"


def _short_type(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _name_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) and isinstance(value.get("Value"), str):
        return cast(str, value["Value"])
    return ""


def _package_owner(relative_path: str) -> CharacterAbilityDefinitionPackageOwner:
    return character_ability_definition_package_owner(relative_path)


def _ability_references(
    snapshot: CharacterAbilityRawSnapshot,
    source_graph: CharacterAbilitySourceGraphCatalogIR,
) -> tuple[dict[str, Any], ...]:
    known_names = {definition.ability_name for definition in source_graph.definitions}
    sources_by_path = {
        source.source.source_path: source for source in snapshot.sources
    }
    rows: list[dict[str, Any]] = []

    def walk(source_path: str, value: object, path: str) -> None:
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(source_path, item, f"{path}[{index}]")
            return
        if not isinstance(value, Mapping):
            return
        ability_name = _name_value(value.get("AbilityName"))
        if (
            ability_name
            and ability_name not in known_names
        ):
            opcode = _short_type(value.get("$type")) or "AbilityNameReference"
            subject_id = character_ability_stable_id(
                "character_ability_task_reference",
                source_path,
                path,
                opcode,
                ability_name,
            )
            source_ir = sources_by_path[source_path]
            rows.append(
                {
                    "subject_id": subject_id,
                    "owner_avatar_id": source_ir.avatar_id,
                    "ability_name": ability_name,
                    "reference_opcode": opcode,
                    "source": IRSource(
                        source_path=source_path,
                        raw_type=opcode,
                        raw_id=subject_id,
                        evidence={
                            "ability_name": ability_name,
                            "json_path": path,
                            "owner_avatar_id": source_ir.avatar_id,
                            "content_sha256": source_ir.content_sha256,
                        },
                    ),
                }
            )
        for key, child in value.items():
            walk(source_path, child, _child_path(path, key))

    for source_path, document in snapshot.documents.items():
        walk(source_path, document, "$")
    rows.sort(key=lambda row: cast(str, row["subject_id"]))
    identities = [cast(str, row["subject_id"]) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("unresolved ability task reference identity is duplicated")
    return tuple(rows)


def _equivalent_field_roles(
    raw_type: str,
    value: Mapping[str, Any],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    if raw_type in {
        "RPG.GameCore.DefineDynamicValue",
        "RPG.GameCore.SetDynamicValue",
    }:
        try:
            _target_alias(value.get("TargetType"))
            roles["TargetType"] = "target_alias"
        except (KeyError, TypeError, ValueError):
            pass
        try:
            if not _name_value(value.get("DynamicKey")):
                raise ValueError("dynamic_key_missing")
            roles["DynamicKey"] = "dynamic_key"
        except (TypeError, ValueError):
            pass
    if raw_type == "RPG.GameCore.SetDynamicValue":
        try:
            _numeric_expression(value.get("Value"))
            roles["Value"] = "value_expression"
        except (TypeError, ValueError):
            pass
        operation = value.get("SetType")
        if isinstance(operation, str) and operation:
            roles["SetType"] = "operation"
    elif raw_type == "RPG.GameCore.TargetAlias":
        try:
            _string(value.get("Alias"), "target_alias_missing")
            roles["Alias"] = "alias"
        except (TypeError, ValueError):
            pass
    return roles


def _equivalent_evidence(
    *,
    raw_type: str,
    value: Mapping[str, Any],
    source_path: str,
    json_path: str,
    content_sha256: str,
) -> CharacterEquivalentStructureEvidenceIR | None:
    roles = _equivalent_field_roles(raw_type, value)
    if not roles:
        return None
    observed_fields = tuple(sorted(str(key) for key in value))
    evidence_id = character_ability_stable_id(
        "character_equivalent_structure_evidence",
        raw_type,
        source_path,
        json_path,
        content_sha256,
        *observed_fields,
        *(f"{key}:{roles[key]}" for key in sorted(roles)),
    )
    return CharacterEquivalentStructureEvidenceIR(
        evidence_id=evidence_id,
        raw_type=cast(CharacterEquivalentRawType, raw_type),
        observed_fields=observed_fields,
        field_role_mapping=roles,
        source=IRSource(
            source_path=source_path,
            raw_type=raw_type,
            raw_id=evidence_id,
            evidence={
                "json_path": json_path,
                "content_sha256": content_sha256,
            },
        ),
    )


def _package_index(
    root: Path,
    requested_names: frozenset[str],
) -> tuple[
    dict[str, str],
    dict[str, int],
    dict[str, tuple[CharacterAbilityDefinitionCandidateIR, ...]],
    dict[str, tuple[CharacterEquivalentStructureEvidenceIR, ...]],
]:
    package_root = root / PACKAGE_SEARCH_ROOT
    if not package_root.is_dir():
        raise CharacterAbilitySourcePackageIncomplete(
            f"ability source package missing:{PACKAGE_SEARCH_ROOT}"
        )
    paths = tuple(sorted(path for path in package_root.rglob("*.json") if path.is_file()))
    if not paths:
        raise CharacterAbilitySourcePackageIncomplete("ability source package is empty")
    manifests: dict[str, str] = {}
    sizes: dict[str, int] = {}
    candidates: dict[str, list[CharacterAbilityDefinitionCandidateIR]] = defaultdict(list)
    equivalent_evidence: dict[
        str, list[CharacterEquivalentStructureEvidenceIR]
    ] = defaultdict(list)
    equivalent_types = {
        spec.equivalent_type for spec in _DECODE_SPECS.values() if spec.equivalent_type
    }

    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        try:
            raw_bytes = path.read_bytes()
            document = json.loads(raw_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CharacterAbilitySourcePackageIncomplete(
                f"ability source unreadable:{relative_path}:{type(exc).__name__}"
            ) from exc
        digest = sha256(raw_bytes).hexdigest()
        manifests[relative_path] = digest
        sizes[relative_path] = len(raw_bytes)

        def walk(value: object, json_path: str) -> None:
            if isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    walk(item, f"{json_path}[{index}]")
                return
            if not isinstance(value, Mapping):
                return
            raw_type = value.get("$type")
            if (
                isinstance(raw_type, str)
                and raw_type in equivalent_types
            ):
                evidence = _equivalent_evidence(
                    raw_type=raw_type,
                    value=value,
                    source_path=relative_path,
                    json_path=json_path,
                    content_sha256=digest,
                )
                if evidence is not None:
                    rows = equivalent_evidence[raw_type]
                    required_roles = _EQUIVALENT_REQUIRED_ROLES[raw_type]
                    compatible = required_roles.issubset(
                        set(evidence.field_role_mapping.values())
                    )
                    retained_compatible = bool(rows) and required_roles.issubset(
                        set(rows[0].field_role_mapping.values())
                    )
                    if compatible and not retained_compatible:
                        rows.clear()
                        retained_compatible = True
                    if (compatible and len(rows) < 16) or (
                        not retained_compatible and len(rows) < 16
                    ):
                        rows.append(evidence)
            ability_list = value.get("AbilityList")
            if isinstance(ability_list, (list, tuple)):
                list_path = _child_path(json_path, "AbilityList")
                for index, ability in enumerate(ability_list):
                    if not isinstance(ability, Mapping):
                        continue
                    ability_name = _name_value(ability.get("Name"))
                    if not ability_name or ability_name not in requested_names:
                        continue
                    candidate_path = f"{list_path}[{index}]"
                    package_owner = _package_owner(relative_path)
                    candidate_id = character_ability_stable_id(
                        "character_ability_definition_candidate",
                        relative_path,
                        candidate_path,
                        ability_name,
                        digest,
                    )
                    candidates[ability_name].append(
                        CharacterAbilityDefinitionCandidateIR(
                            candidate_id=candidate_id,
                            ability_name=ability_name,
                            package_owner=package_owner,
                            source=IRSource(
                                source_path=relative_path,
                                raw_type="character_ability_definition_candidate",
                                raw_id=candidate_id,
                                evidence={
                                    "ability_name": ability_name,
                                    "json_path": candidate_path,
                                    "content_sha256": digest,
                                    "byte_size": len(raw_bytes),
                                    "package_owner": package_owner,
                                },
                            ),
                        )
                    )
            for key, child in value.items():
                walk(child, _child_path(json_path, key))

        walk(document, "$")

    normalized_candidates = {
        name: tuple(sorted(values, key=lambda item: item.candidate_id))
        for name, values in candidates.items()
    }
    return (
        manifests,
        sizes,
        normalized_candidates,
        {
            raw_type: tuple(
                sorted(
                    {row.evidence_id: row for row in items}.values(),
                    key=lambda item: item.evidence_id,
                )
            )
            for raw_type, items in equivalent_evidence.items()
        },
    )


def _walk_target_aliases(value: object) -> tuple[str, ...]:
    aliases: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
            return
        if not isinstance(item, Mapping):
            return
        if item.get("$type") == "RPG.GameCore.TargetAlias":
            alias = item.get("Alias")
            if isinstance(alias, str) and alias:
                aliases.add(alias)
        for child in item.values():
            walk(child)

    walk(value)
    return tuple(sorted(aliases))


def _value_shape(field_name: str, value: object) -> str:
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)):
        kind = "number"
    elif isinstance(value, str):
        kind = "string"
    elif isinstance(value, (list, tuple)):
        kind = "array"
    elif isinstance(value, Mapping):
        if value.get("$type") == "RPG.GameCore.TargetAlias":
            kind = "target_alias"
        elif "FixedValue" in value or "PostfixExpr" in value:
            kind = "numeric_expression"
        else:
            kind = "object"
    elif value is None:
        kind = "null"
    else:
        kind = type(value).__name__
    return f"{field_name}:{kind}"


def _family_context_error(
    family: str,
    records: tuple[CharacterAbilityScopeRecordIR, ...],
    records_by_id: Mapping[str, CharacterAbilityScopeRecordIR],
) -> str:
    if family != "IKDAKCBKFAB":
        return ""
    for record in records:
        parent = records_by_id.get(record.parent_record_id)
        json_path = record.source.evidence.get("json_path")
        parent_path = (
            parent.source.evidence.get("json_path") if parent is not None else None
        )
        if (
            parent is None
            or parent.family != "TurnInsertAction"
            or not isinstance(json_path, str)
            or not isinstance(parent_path, str)
            or not parent_path.endswith(".$type")
            or json_path
            != f"{parent_path.removesuffix('.$type')}.PreCheck.$type"
        ):
            return "queue_precheck_context_mismatch"
        if record.raw_fields.get("GMPGDEINODK") != "SameTagInsertUnusedCount":
            return "queue_precheck_metric_mismatch"
    return ""


def _family_resolutions(
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
    equivalent_evidence: Mapping[
        str, tuple[CharacterEquivalentStructureEvidenceIR, ...]
    ],
) -> tuple[
    tuple[CharacterDecodeFamilyResolutionIR, ...],
    tuple[CharacterDecodedSourceIR, ...],
]:
    decode_records = tuple(
        record
        for record in scope_catalog.scope_records
        if record.effective_scope == "decode_required"
        and record.materialization_role == "selected"
    )
    records_by_id = {record.record_id: record for record in scope_catalog.scope_records}
    children_by_id: dict[str, list[CharacterAbilityScopeRecordIR]] = defaultdict(list)
    for record in scope_catalog.scope_records:
        children_by_id[record.parent_record_id].append(record)
    records_by_family: dict[str, list[CharacterAbilityScopeRecordIR]] = defaultdict(list)
    for record in decode_records:
        records_by_family[record.family].append(record)
    family_rows: list[CharacterDecodeFamilyResolutionIR] = []
    decoded_items: list[CharacterDecodedSourceIR] = []

    for family, records in sorted(records_by_family.items()):
        records = sorted(records, key=lambda item: item.record_id)
        record_ids = tuple(record.record_id for record in records)
        parent_families: set[str] = set()
        condition_families: set[str] = set()
        neighbor_families: set[str] = set()
        aliases: set[str] = set()
        fields: set[str] = set()
        value_shapes: set[str] = set()
        source_paths: set[str] = set()
        for record in records:
            fields.update(str(key) for key in record.raw_fields)
            value_shapes.update(
                _value_shape(str(key), value)
                for key, value in record.raw_fields.items()
                if key != "$type"
            )
            aliases.update(_walk_target_aliases(record.raw_fields))
            source_paths.add(record.source.source_path)
            parent = records_by_id.get(record.parent_record_id)
            if parent is not None:
                parent_families.add(parent.family)
                neighbor_families.add(parent.family)
            for child in children_by_id.get(record.record_id, ()):
                neighbor_families.add(child.family)
            ancestor = parent
            while ancestor is not None:
                if ancestor.semantic_kind in {
                    "combat_condition",
                    "combat_control_flow",
                }:
                    condition_families.add(ancestor.family)
                ancestor = records_by_id.get(ancestor.parent_record_id)

        spec = _DECODE_SPECS.get(family)
        family_items: list[CharacterDecodedSourceIR] = []
        blocked_reason = ""
        candidate_types: tuple[str, ...] = ()
        candidate_rows: tuple[CharacterEquivalentStructureEvidenceIR, ...] = ()
        if spec is None:
            blocked_reason = "obfuscated_semantics_not_proven_from_current_source"
        else:
            blocked_reason = _family_context_error(
                family, tuple(records), records_by_id
            )
            if spec.equivalent_type:
                candidate_types = (spec.equivalent_type,)
                observed_candidates = tuple(
                    equivalent_evidence.get(spec.equivalent_type, ())
                )
                compatible_candidates = tuple(
                    item
                    for item in observed_candidates
                    if spec.required_equivalent_roles.issubset(
                        set(item.field_role_mapping.values())
                    )
                )
                candidate_rows = compatible_candidates or observed_candidates
                if not observed_candidates:
                    blocked_reason = "same_package_equivalent_schema_not_found"
                elif not compatible_candidates:
                    blocked_reason = "same_package_equivalent_schema_incompatible"
            if not blocked_reason:
                try:
                    for record in records:
                        actual_fields = frozenset(str(key) for key in record.raw_fields)
                        if (
                            not spec.required_fields.issubset(actual_fields)
                            or actual_fields - spec.required_fields - spec.optional_fields
                        ):
                            raise ValueError("raw_field_schema_mismatch")
                        payload = spec.decoder(record.raw_fields)
                        typed_operation: dict[str, JSONValue] | None = None
                        if spec.decoded_kind in {
                            "dynamic_value_definition",
                            "dynamic_value_write",
                        }:
                            operation = DynamicValueOperationIR.from_spec(
                                lower_decoded_dynamic_value_operation_spec(
                                    spec.decoded_kind,
                                    payload,
                                ),
                                record.source,
                            )
                            typed_operation = operation.to_spec_json()
                        decoded_id = character_ability_stable_id(
                            "character_decoded_source",
                            record.record_id,
                            family,
                            record.occurrence_kind,
                            spec.decoded_kind,
                            spec.package_owner,
                            record.source.source_path,
                            record.source.evidence.get("json_path"),
                        )
                        family_items.append(
                            CharacterDecodedSourceIR(
                                decoded_id=decoded_id,
                                scope_record_id=record.record_id,
                                source_family=family,
                                source_occurrence_kind=record.occurrence_kind,
                                decoded_kind=cast(Any, spec.decoded_kind),
                                package_owner=spec.package_owner,
                                payload=payload,
                                source=record.source,
                                typed_operation=typed_operation,
                            )
                        )
                except (KeyError, TypeError, ValueError) as exc:
                    family_items = []
                    blocked_reason = f"typed_schema_unresolved:{exc}"
        outcome = "decoded_to_package" if family_items else "source_gap_blocked"
        package_owner = spec.package_owner if family_items and spec is not None else ""
        family_decoded_ids = tuple(sorted(item.decoded_id for item in family_items))
        candidate_rows = tuple(
            sorted(candidate_rows, key=lambda item: item.evidence_id)
        )
        decoded_items.extend(family_items)
        family_rows.append(
            CharacterDecodeFamilyResolutionIR(
                resolution_id=character_ability_stable_id(
                    "character_decode_family_resolution",
                    family,
                    outcome,
                    package_owner,
                    *record_ids,
                    *family_decoded_ids,
                    *(item.evidence_id for item in candidate_rows),
                    blocked_reason,
                ),
                family=family,
                outcome=cast(Any, outcome),
                scope_record_ids=record_ids,
                decoded_item_ids=family_decoded_ids,
                package_owner=package_owner,
                observed_fields=tuple(sorted(fields)),
                parent_families=tuple(sorted(parent_families or {"<source_root>"})),
                target_aliases=tuple(sorted(aliases)),
                value_shapes=tuple(sorted(value_shapes or {"<no_value_fields>"})),
                condition_families=tuple(sorted(condition_families)),
                graph_neighbor_families=tuple(sorted(neighbor_families)),
                source_paths=tuple(sorted(source_paths)),
                candidate_equivalent_types=candidate_types,
                candidate_evidence=candidate_rows,
                blocked_reason=blocked_reason,
            )
        )
    return tuple(family_rows), tuple(decoded_items)


def _reference_resolution(
    *,
    subject_kind: str,
    subject_id: str,
    owner_avatar_id: str,
    ability_name: str,
    reference_opcode: str,
    source: IRSource,
    candidates: tuple[CharacterAbilityDefinitionCandidateIR, ...],
    forced_block: str = "",
    source_graph_gap_kind: str = "",
    source_graph_candidate_definition_ids: tuple[str, ...] = (),
    source_graph_candidate_action_source_ids: tuple[str, ...] = (),
) -> CharacterAbilityReferenceResolutionIR:
    if forced_block:
        outcome = "source_gap_blocked"
        package_owner = ""
        blocked_reason = forced_block
    elif len(candidates) == 1:
        outcome = "decoded_to_package"
        package_owner = candidates[0].package_owner
        blocked_reason = ""
    elif not candidates:
        outcome = "source_gap_blocked"
        package_owner = ""
        blocked_reason = "ability_definition_absent_after_complete_package_search"
    else:
        outcome = "source_gap_blocked"
        package_owner = ""
        blocked_reason = "ability_definition_ambiguous_after_complete_package_search"
    return CharacterAbilityReferenceResolutionIR(
        resolution_id=character_ability_stable_id(
            "character_ability_reference_resolution", subject_kind, subject_id
        ),
        subject_kind=cast(Any, subject_kind),
        subject_id=subject_id,
        owner_avatar_id=owner_avatar_id,
        ability_name=ability_name,
        reference_opcode=reference_opcode,
        outcome=cast(Any, outcome),
        package_owner=package_owner,
        candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
        source=source,
        source_graph_gap_kind=cast(Any, source_graph_gap_kind),
        source_graph_candidate_definition_ids=(
            source_graph_candidate_definition_ids
        ),
        source_graph_candidate_action_source_ids=(
            source_graph_candidate_action_source_ids
        ),
        blocked_reason=blocked_reason,
    )


def build_character_ability_source_resolution(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot,
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
    source_graph_catalog: CharacterAbilitySourceGraphCatalogIR,
) -> CharacterAbilitySourceResolutionCatalogIR:
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("S3 source resolution requires the exact S0 snapshot")
    if type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
        raise TypeError("S3 source resolution requires the exact S0 scope catalog")
    if type(source_graph_catalog) is not CharacterAbilitySourceGraphCatalogIR:
        raise TypeError("S3 source resolution requires the exact S1 source graph catalog")
    if (
        not snapshot.source_catalog_complete
        or not scope_catalog.scope_reconciliation_complete
        or not source_graph_catalog.source_catalog_complete
        or snapshot.snapshot_id != scope_catalog.snapshot_id
        or snapshot.snapshot_id != source_graph_catalog.snapshot_id
        or scope_catalog.catalog_id != source_graph_catalog.scope_catalog_id
        or len(
            {
                snapshot.source_fingerprint,
                scope_catalog.source_fingerprint,
                source_graph_catalog.source_fingerprint,
            }
        )
        != 1
    ):
        raise ValueError("S3 source resolution prerequisite closure is inconsistent")
    lowering_gaps = tuple(
        gap for gap in source_graph_catalog.gaps if gap.gap_kind == "lowering_gap"
    )
    if lowering_gaps:
        raise ValueError("S3 cannot adjudicate source gaps over S1 lowering gaps")

    task_references = _ability_references(snapshot, source_graph_catalog)
    requested_names = frozenset(
        {
            gap.requested_ability_name
            for gap in source_graph_catalog.gaps
            if gap.requested_ability_name
        }
        | {
            cast(str, reference["ability_name"])
            for reference in task_references
        }
    )
    manifests, sizes, candidates_by_name, equivalent_evidence = _package_index(
        tbgd_root.resolve(), requested_names
    )
    family_resolutions, decoded_items = _family_resolutions(
        scope_catalog, equivalent_evidence
    )

    reference_resolutions: list[CharacterAbilityReferenceResolutionIR] = []
    for gap in source_graph_catalog.gaps:
        candidates = candidates_by_name.get(gap.requested_ability_name, ())
        forced_block = (
            f"s1_relationship_gap:{gap.gap_kind}"
            if gap.gap_kind != "source_gap_blocked"
            else ""
        )
        reference_resolutions.append(
            _reference_resolution(
                subject_kind="source_graph_gap",
                subject_id=gap.gap_id,
                owner_avatar_id=gap.owner_avatar_id,
                ability_name=gap.requested_ability_name,
                reference_opcode=gap.expected_binding_kind,
                source=gap.source,
                candidates=candidates,
                forced_block=forced_block,
                source_graph_gap_kind=gap.gap_kind,
                source_graph_candidate_definition_ids=(
                    gap.candidate_definition_ids
                ),
                source_graph_candidate_action_source_ids=(
                    gap.candidate_action_source_ids
                ),
            )
        )
    for reference in task_references:
        ability_name = cast(str, reference["ability_name"])
        reference_resolutions.append(
            _reference_resolution(
                subject_kind="ability_task_reference",
                subject_id=cast(str, reference["subject_id"]),
                owner_avatar_id=cast(str, reference["owner_avatar_id"]),
                ability_name=ability_name,
                reference_opcode=cast(str, reference["reference_opcode"]),
                source=cast(IRSource, reference["source"]),
                candidates=candidates_by_name.get(ability_name, ()),
            )
        )
    referenced_candidates = {
        candidate_id
        for resolution in reference_resolutions
        for candidate_id in resolution.candidate_ids
    }
    definition_candidates = tuple(
        candidate
        for values in candidates_by_name.values()
        for candidate in values
        if candidate.candidate_id in referenced_candidates
    )
    decode_record_ids = tuple(
        record.record_id
        for record in scope_catalog.scope_records
        if record.effective_scope == "decode_required"
        and record.materialization_role == "selected"
    )
    return CharacterAbilitySourceResolutionCatalogIR(
        scope_catalog_id=scope_catalog.catalog_id,
        source_graph_catalog_id=source_graph_catalog.catalog_id,
        source_fingerprint=snapshot.source_fingerprint,
        package_search_root=PACKAGE_SEARCH_ROOT,
        package_manifest_digests=manifests,
        package_manifest_sizes=sizes,
        decode_required_record_ids=tuple(sorted(decode_record_ids)),
        source_graph_gap_ids=tuple(
            sorted(gap.gap_id for gap in source_graph_catalog.gaps)
        ),
        unresolved_reference_ids=tuple(
            sorted(cast(str, row["subject_id"]) for row in task_references)
        ),
        family_resolutions=family_resolutions,
        decoded_items=decoded_items,
        definition_candidates=definition_candidates,
        reference_resolutions=tuple(reference_resolutions),
        build_counters={
            "package_file_read_count": len(manifests),
            "package_file_parse_count": len(manifests),
            "package_byte_count": sum(sizes.values()),
            "requested_ability_name_count": len(requested_names),
            "definition_candidate_count": len(definition_candidates),
            "source_graph_gap_count": len(source_graph_catalog.gaps),
            "unresolved_task_reference_count": len(task_references),
            "lowering_gap_count": len(lowering_gaps),
            "package_scan_error_count": 0,
        },
    )
