"""Narrow, source-authentic target-language projection for P9-S5A.

This module deliberately stops before canonical full lowering.  It reuses the
S0 raw snapshot and scope classifier, then materializes only the observed
target-language families.  The returned catalog is production compiler output,
not a validation-side selection cache.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue
from ..rules.ir import ConditionIR, TargetExpressionIR, TargetExpressionNodeIR
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
    build_character_ability_scope_projection,
)
from .lowering import _target_expression_from_raw


_ALIAS_CONFIG = "Config/GlobalConfig/TargetAliasConfig.json"
_OPERATION_CONFIG = "Config/GlobalConfig/TargetOperationConfig.json"
_RANDOM_TASK_FAMILY = "RandomSelectInTargetList"

TargetResponsibility = Literal[
    "s5a_effect_target",
    "s5c_input_target",
    "s5d_random_target_task",
    "existing_projection_consumer",
    "retired_non_gameplay",
    "blocked_source_scope",
]


def _stable_id(prefix: str, *parts: str) -> str:
    if any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("target source identity parts are required")
    identity = "\0".join(parts).encode("utf-8")
    return f"{prefix}:{sha256(identity).hexdigest()}"


def _source_copy(source: IRSource, *, json_path: str, raw_type: str, raw_id: str) -> IRSource:
    return IRSource(
        source_path=source.source_path,
        raw_type=raw_type,
        raw_id=raw_id,
        evidence=cast(dict[str, JSONValue], freeze_json({"json_path": json_path})),
    )


@dataclass(frozen=True)
class TargetSourceRecordIR:
    record_id: str
    scope_record_id: str
    family: str
    effective_scope: str
    responsibility: TargetResponsibility
    source: IRSource
    coverage_status: Literal["executable", "blocked", "retired", "delegated"]
    blocked_reason: str = ""
    dependency_stages: tuple[str, ...] = ()
    expression: TargetExpressionIR | None = None

    def __post_init__(self) -> None:
        if type(self) is not TargetSourceRecordIR:
            raise TypeError("target source record must not be subclassed")
        if not all(isinstance(value, str) and value for value in (
            self.record_id,
            self.scope_record_id,
            self.family,
            self.effective_scope,
        )):
            raise ValueError("target source record identity is incomplete")
        if self.responsibility not in {
            "s5a_effect_target", "s5c_input_target", "s5d_random_target_task",
            "existing_projection_consumer", "retired_non_gameplay", "blocked_source_scope",
        }:
            raise ValueError("target source responsibility is invalid")
        if self.coverage_status not in {"executable", "blocked", "retired", "delegated"}:
            raise ValueError("target source coverage is invalid")
        if self.coverage_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked target source record requires a reason")
        if self.coverage_status != "blocked" and self.blocked_reason:
            raise ValueError("non-blocked target source record cannot carry a blocker")
        if self.coverage_status != "blocked" and self.dependency_stages:
            raise ValueError("non-blocked target source record cannot carry dependencies")
        if (
            isinstance(self.dependency_stages, str)
            or any(not isinstance(item, str) or not item for item in self.dependency_stages)
            or tuple(sorted(set(self.dependency_stages))) != tuple(self.dependency_stages)
        ):
            raise ValueError("target source dependency stages are invalid")
        if self.record_id != _stable_id(
            "target_source_record", self.scope_record_id, self.responsibility
        ):
            raise ValueError("target source record identity does not close")
        if not isinstance(self.source, IRSource) or not isinstance(self.source.evidence.get("json_path"), str):
            raise ValueError("target source record requires raw JSON lineage")
        source = _source_copy(
            self.source,
            json_path=str(self.source.evidence["json_path"]),
            raw_type=self.source.raw_type,
            raw_id=self.source.raw_id,
        )
        if source.raw_id != self.scope_record_id:
            raise ValueError("target source record raw identity is inconsistent")
        if self.responsibility == "s5a_effect_target":
            if type(self.expression) is not TargetExpressionIR:
                raise TypeError("S5A target source record requires typed expression")
            if (
                self.coverage_status != self.expression.coverage_status
                or self.blocked_reason != self.expression.blocked_reason
                or self.expression.source.source_path != source.source_path
                or self.expression.source.evidence.get("json_path") != source.evidence.get("json_path")
            ):
                raise ValueError("target source expression state is inconsistent")
        elif self.expression is not None:
            raise ValueError("non-S5A target source record cannot materialize effect IR")
        elif self.responsibility in {
            "s5c_input_target", "s5d_random_target_task", "existing_projection_consumer",
        }:
            if self.coverage_status != "delegated":
                raise ValueError("delegated target source record cannot be executable")
        elif self.responsibility == "retired_non_gameplay":
            if self.coverage_status != "retired":
                raise ValueError("retired target source record coverage is inconsistent")
        elif self.responsibility == "blocked_source_scope" and self.coverage_status != "blocked":
            raise ValueError("blocked target source scope cannot be executable")
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_id": self.record_id,
            "scope_record_id": self.scope_record_id,
            "family": self.family,
            "effective_scope": self.effective_scope,
            "responsibility": self.responsibility,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "dependency_stages": list(self.dependency_stages),
            "expression": self.expression.to_json() if self.expression is not None else None,
        }


@dataclass(frozen=True)
class TargetLanguageDefinitionIR:
    definition_id: str
    definition_kind: Literal["alias", "operation"]
    name: str
    source: IRSource
    content_sha256: str
    coverage_status: Literal["executable", "blocked"]
    blocked_reason: str
    dependency_stages: tuple[str, ...]
    expression: TargetExpressionIR
    reference_names: tuple[str, ...] = ()
    reference_definition_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self) is not TargetLanguageDefinitionIR:
            raise TypeError("target language definition must not be subclassed")
        if self.definition_kind not in {"alias", "operation"}:
            raise ValueError("target language definition kind is invalid")
        if isinstance(self.reference_names, str) or isinstance(self.reference_definition_ids, str):
            raise TypeError("target language definition references must be sequences")
        reference_names = tuple(self.reference_names)
        reference_definition_ids = tuple(self.reference_definition_ids)
        if not isinstance(self.source, IRSource) or not isinstance(self.source.evidence.get("json_path"), str):
            raise ValueError("target language definition requires raw JSON lineage")
        source = _source_copy(
            self.source,
            json_path=str(self.source.evidence["json_path"]),
            raw_type=self.source.raw_type,
            raw_id=self.source.raw_id,
        )
        if not all(isinstance(value, str) and value for value in (
            self.definition_id, self.name, self.content_sha256,
        )) or len(self.content_sha256) != 64:
            raise ValueError("target language definition identity is invalid")
        if type(self.expression) is not TargetExpressionIR:
            raise TypeError("target language definition requires typed expression")
        if (
            self.expression.source.source_path != source.source_path
            or self.expression.source.evidence.get("json_path") != source.evidence.get("json_path")
        ):
            raise ValueError("target language definition expression source is inconsistent")
        expected_id = _stable_id(
            "target_language_definition",
            source.source_path,
            self.definition_kind,
            self.name,
        )
        if self.definition_id != expected_id:
            raise ValueError("target language definition identity does not close")
        if len(reference_names) != len(reference_definition_ids) or (
            len(set(reference_names)) != len(reference_names)
            or len(set(reference_definition_ids)) != len(reference_definition_ids)
        ):
            raise ValueError("target language definition references are inconsistent")
        if any(not isinstance(value, str) or not value for value in (*reference_names, *reference_definition_ids)):
            raise ValueError("target language definition references are invalid")
        if self.coverage_status != self.expression.coverage_status:
            raise ValueError("target language definition coverage is inconsistent")
        if self.blocked_reason != self.expression.blocked_reason:
            raise ValueError("target language definition blocker is inconsistent")
        if self.coverage_status != "blocked" and self.dependency_stages:
            raise ValueError("executable target language definition cannot carry dependencies")
        if (
            isinstance(self.dependency_stages, str)
            or any(not isinstance(item, str) or not item for item in self.dependency_stages)
            or tuple(sorted(set(self.dependency_stages))) != tuple(self.dependency_stages)
        ):
            raise ValueError("target language dependency stages are invalid")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reference_names", reference_names)
        object.__setattr__(self, "reference_definition_ids", reference_definition_ids)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "definition_kind": self.definition_kind,
            "name": self.name,
            "source": self.source.to_json(),
            "content_sha256": self.content_sha256,
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "dependency_stages": list(self.dependency_stages),
            "expression": self.expression.to_json(),
            "reference_names": list(self.reference_names),
            "reference_definition_ids": list(self.reference_definition_ids),
        }


@dataclass(frozen=True)
class TargetSourceProjectionCatalog:
    snapshot_id: str
    source_fingerprint: str
    fingerprint_kind: Literal["complete", "partial"]
    source_catalog_complete: bool
    language_fingerprints: Mapping[str, str]
    records: tuple[TargetSourceRecordIR, ...]
    language_definitions: tuple[TargetLanguageDefinitionIR, ...]
    build_counters: Mapping[str, JSONValue]
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not TargetSourceProjectionCatalog:
            raise TypeError("target source catalog must not be subclassed")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise ValueError("target source snapshot identity is required")
        if not isinstance(self.source_fingerprint, str) or len(self.source_fingerprint) != 64:
            raise ValueError("target source fingerprint is invalid")
        if self.fingerprint_kind not in {"complete", "partial"}:
            raise ValueError("target source fingerprint completeness is invalid")
        if self.source_catalog_complete != (self.fingerprint_kind == "complete"):
            raise ValueError("target source catalog completeness is inconsistent")
        fingerprints = freeze_json(dict(self.language_fingerprints))
        if not isinstance(fingerprints, Mapping) or set(fingerprints) != {_ALIAS_CONFIG, _OPERATION_CONFIG}:
            raise ValueError("target language fingerprints are incomplete")
        if any(not isinstance(value, str) or len(value) != 64 for value in fingerprints.values()):
            raise ValueError("target language fingerprint is invalid")
        records = tuple(sorted(self.records, key=lambda item: item.record_id))
        definitions = tuple(sorted(self.language_definitions, key=lambda item: item.definition_id))
        if len({item.record_id for item in records}) != len(records):
            raise ValueError("duplicate target source record identity")
        if len({item.definition_id for item in definitions}) != len(definitions):
            raise ValueError("duplicate target language definition identity")
        definition_ids = {item.definition_id for item in definitions}
        if any(
            not set(item.reference_definition_ids).issubset(definition_ids)
            for item in definitions
        ):
            raise ValueError("target language reference does not close to a definition")
        if any(item.coverage_status == "blocked" and not item.dependency_stages for item in (*records, *definitions)):
            raise ValueError("blocked target source item requires structured dependency stages")
        counters = freeze_json(dict(self.build_counters))
        if not isinstance(counters, Mapping):
            raise TypeError("target source build counters must be an object")
        encoded = json.dumps(
            {
                "snapshot_id": self.snapshot_id,
                "source_fingerprint": self.source_fingerprint,
                "fingerprint_kind": self.fingerprint_kind,
                "language_fingerprints": thaw_json(fingerprints),
                "record_ids": [item.record_id for item in records],
                "definition_ids": [item.definition_id for item in definitions],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "language_fingerprints", MappingProxyType(dict(fingerprints)))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "language_definitions", definitions)
        object.__setattr__(self, "build_counters", MappingProxyType(dict(counters)))
        object.__setattr__(self, "catalog_id", f"target_source_projection:{sha256(encoded).hexdigest()}")

    def summary_json(self) -> dict[str, JSONValue]:
        by_responsibility: dict[str, int] = {}
        for record in self.records:
            by_responsibility[record.responsibility] = by_responsibility.get(record.responsibility, 0) + 1
        return {
            "catalog_id": self.catalog_id,
            "snapshot_id": self.snapshot_id,
            "source_fingerprint": self.source_fingerprint,
            "fingerprint_kind": self.fingerprint_kind,
            "source_catalog_complete": self.source_catalog_complete,
            "language_fingerprints": thaw_json(self.language_fingerprints),
            "record_count": len(self.records),
            "language_definition_count": len(self.language_definitions),
            "records_by_responsibility": dict(sorted(by_responsibility.items())),
            "build_counters": thaw_json(self.build_counters),
        }


def build_target_source_projection(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot,
) -> TargetSourceProjectionCatalog:
    """Build the S5 target view without creating a full Canonical IR."""

    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("target source projection requires an exact S0 raw snapshot")
    observed_families = _target_candidate_families(snapshot)
    scope_catalog = build_character_ability_scope_projection(
        tbgd_root,
        snapshot=snapshot,
        families=observed_families,
    )
    definitions, fingerprints = _target_language_definitions(tbgd_root, snapshot=snapshot)
    records = _target_records_from_scope(snapshot, scope_catalog, definitions)
    return TargetSourceProjectionCatalog(
        snapshot_id=snapshot.snapshot_id,
        source_fingerprint=snapshot.source_fingerprint,
        fingerprint_kind=snapshot.fingerprint_kind,
        source_catalog_complete=snapshot.source_catalog_complete,
        language_fingerprints=fingerprints,
        records=records,
        language_definitions=definitions,
        build_counters={
            "raw_snapshot_reused": True,
            "scope_classifier_projection_count": 1,
            "target_family_candidate_count": len(observed_families),
            "target_filter_applied_before_ir_materialization": True,
            "full_canonical_ir_build_count": 0,
            "additional_ability_source_read_count": 0,
            "additional_ability_source_parse_count": 0,
        },
    )


def _target_candidate_families(snapshot: CharacterAbilityRawSnapshot) -> tuple[str, ...]:
    families: set[str] = set()
    for document in snapshot.documents.values():
        _discover_target_families(document, families)
    if not families:
        raise ValueError("target source projection found no target-language candidates")
    return tuple(sorted(families))


def _discover_target_families(value: Any, families: set[str]) -> None:
    if isinstance(value, Mapping):
        raw_type = value.get("$type")
        if isinstance(raw_type, str):
            family = raw_type.removeprefix("RPG.GameCore.")
            if family.startswith("Target") or family in {"Retarget", _RANDOM_TASK_FAMILY}:
                families.add(family)
        for child in value.values():
            _discover_target_families(child, families)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _discover_target_families(child, families)


def _target_records_from_scope(
    snapshot: CharacterAbilityRawSnapshot,
    scope_catalog: CharacterAbilityScopeProjectionCatalog,
    language_definitions: tuple[TargetLanguageDefinitionIR, ...],
) -> tuple[TargetSourceRecordIR, ...]:
    records: list[TargetSourceRecordIR] = []
    for scope_record in scope_catalog.scope_records:
        if scope_record.materialization_role != "selected" or scope_record.occurrence_kind != "typed_node":
            continue
        if not _is_target_family(scope_record.family):
            continue
        path = str(scope_record.source.evidence["json_path"])
        raw_path = path.removesuffix(".$type")
        source = _source_copy(
            scope_record.source,
            json_path=raw_path,
            raw_type="TargetExpression",
            raw_id=scope_record.record_id,
        )
        responsibility, coverage_status, blocked_reason = _target_record_route(
            scope_record.family,
            scope_record.effective_scope,
            scope_record.nominal_scope,
        )
        expression: TargetExpressionIR | None = None
        if responsibility == "s5a_effect_target":
            raw = _value_at_json_path(snapshot.documents[scope_record.source.source_path], raw_path)
            if not isinstance(raw, Mapping):
                coverage_status, blocked_reason = "blocked", "target_raw_node_missing_at_scope_path"
            else:
                expression = _target_expression_from_raw(
                    dict(raw),
                    field_name="$self",
                    expression_id=f"p9_target_expression:{scope_record.record_id}",
                    source=source,
                )
                if expression is not None:
                    expression = close_target_expression_language(
                        expression, language_definitions
                    )
                if expression is None:
                    coverage_status, blocked_reason = "blocked", "target_scope_record_not_lowerable"
                elif expression.coverage_status == "blocked":
                    coverage_status, blocked_reason = "blocked", expression.blocked_reason
                else:
                    coverage_status, blocked_reason = "executable", ""
        records.append(
            TargetSourceRecordIR(
                record_id=_stable_id("target_source_record", scope_record.record_id, responsibility),
                scope_record_id=scope_record.record_id,
                family=scope_record.family,
                effective_scope=scope_record.effective_scope,
                responsibility=responsibility,
                source=source,
                coverage_status=coverage_status,
                blocked_reason=blocked_reason,
                dependency_stages=(
                    _target_dependency_stages(expression, language_definitions)
                    if coverage_status == "blocked" and expression is not None
                    else (("source_scope_admission",) if coverage_status == "blocked" else ())
                ),
                expression=expression,
            )
        )
    return tuple(records)


def _is_target_family(family: str) -> bool:
    return family.startswith("Target") or family in {"Retarget", _RANDOM_TASK_FAMILY}


def _target_record_route(
    family: str,
    effective_scope: str,
    nominal_scope: str,
) -> tuple[TargetResponsibility, Literal["executable", "blocked", "retired", "delegated"], str]:
    # Scope is a per-record fact.  Family routing is only meaningful after a
    # record has been admitted to gameplay, otherwise presentation/data rows
    # can be incorrectly delegated to the future random-target stage.
    if nominal_scope == "non_gameplay" or effective_scope == "non_gameplay":
        return "retired_non_gameplay", "retired", ""
    if effective_scope == "gameplay":
        if family == _RANDOM_TASK_FAMILY:
            return "s5d_random_target_task", "delegated", ""
        return "s5a_effect_target", "blocked", "target_expression_pending_lowering"
    if effective_scope == "input_projection":
        return "s5c_input_target", "delegated", ""
    if effective_scope in {"build_resolution", "battle_data_projection", "environment_input"}:
        return "existing_projection_consumer", "delegated", ""
    return "blocked_source_scope", "blocked", f"target_scope_not_admitted:{effective_scope}"


def _value_at_json_path(document: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError("target scope path is not rooted")
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
        elif path[index] == "[":
            end = path.find("]", index)
            if end < 0 or not isinstance(current, (list, tuple)):
                return None
            token = path[index + 1:end]
            if not token.isdigit() or int(token) >= len(current):
                return None
            current = current[int(token)]
            index = end + 1
        else:
            return None
    return current


def _target_language_definitions(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot | None = None,
) -> tuple[tuple[TargetLanguageDefinitionIR, ...], Mapping[str, str]]:
    raw_definitions: list[tuple[str, str, str, str, dict[str, Any], IRSource, str]] = []
    fingerprints: dict[str, str] = {}
    for relative, top_key, definition_kind in (
        (_ALIAS_CONFIG, "AliasDict", "alias"),
        (_OPERATION_CONFIG, "OperationDict", "operation"),
    ):
        raw_bytes = (tbgd_root / relative).read_bytes()
        fingerprints[relative] = sha256(raw_bytes).hexdigest()
        document = json.loads(raw_bytes, object_pairs_hook=_unique_json_object)
        if not isinstance(document, dict) or not isinstance(document.get(top_key), dict):
            raise ValueError(f"target language source schema invalid:{relative}")
        entries = cast(dict[str, Any], document[top_key])
        for name, raw in sorted(entries.items()):
            if not isinstance(name, str) or not name or not isinstance(raw, dict):
                raise ValueError(f"target language definition identity invalid:{relative}")
            source = IRSource(
                source_path=relative,
                raw_type=f"{top_key}",
                raw_id=name,
                evidence={"json_path": f"$.{top_key}.{name}"},
            )
            raw_definitions.append((
                definition_kind,
                relative,
                top_key,
                name,
                raw,
                source,
                sha256(
                    json.dumps(raw, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            ))
    if snapshot is not None:
        for relative, document in sorted(snapshot.documents.items()):
            entries = document.get("GlobalTargetAlias") if isinstance(document, Mapping) else None
            if not isinstance(entries, Mapping):
                continue
            for name, raw in sorted(entries.items()):
                if not isinstance(name, str) or not name or not isinstance(raw, dict):
                    raise ValueError(f"local target alias identity invalid:{relative}")
                source = IRSource(
                    source_path=relative,
                    raw_type="GlobalTargetAlias",
                    raw_id=name,
                    evidence={"json_path": f"$.GlobalTargetAlias.{name}"},
                )
                raw_definitions.append((
                    "alias", relative, "GlobalTargetAlias", name, raw, source,
                    sha256(json.dumps(raw, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                ))

    global_names_by_kind = {
        "alias": {item[3] for item in raw_definitions if item[0] == "alias" and item[1] == _ALIAS_CONFIG},
        "operation": {item[3] for item in raw_definitions if item[0] == "operation"},
    }
    local_alias_names = {
        relative: {item[3] for item in raw_definitions if item[0] == "alias" and item[1] == relative}
        for relative in {item[1] for item in raw_definitions if item[0] == "alias" and item[1] != _ALIAS_CONFIG}
    }
    overlap = global_names_by_kind["alias"] & global_names_by_kind["operation"]
    definition_ids = {
        _target_definition_key(kind, relative, name): _stable_id("target_language_definition", relative, kind, name)
        for kind, relative, _top_key, name, _raw, _source, _digest in raw_definitions
    }
    expressions: dict[str, TargetExpressionIR] = {}
    references: dict[str, tuple[str, ...]] = {}
    link_reasons: dict[str, str] = {}
    for kind, relative, top_key, name, raw, source, _digest in raw_definitions:
        key = _target_definition_key(kind, relative, name)
        if relative in {_ALIAS_CONFIG, _OPERATION_CONFIG} and name in overlap:
            link_reasons[key] = f"target_language_definition_name_ambiguous:{name}"
        expression = _target_expression_from_raw(
            raw,
            field_name="$self",
            expression_id=_stable_id("target_language_expression", relative, top_key, name),
            source=source,
        )
        if expression is None:
            raise ValueError(f"target language definition is not a target expression:{relative}:{name}")
        expressions[key] = expression
        target_names, missing = _target_language_reference_names(
            raw,
            source_path=relative,
            global_alias_names=global_names_by_kind["alias"],
            local_alias_names=local_alias_names,
            operation_names=global_names_by_kind["operation"],
        )
        references[key] = target_names
        if missing:
            link_reasons[key] = missing

    graph = {
        definition_ids[key]: tuple(definition_ids[name] for name in ref_names)
        for key, ref_names in references.items()
    }
    cycle_ids = _target_language_cycle_ids(graph)
    for key, definition_id in definition_ids.items():
        if definition_id in cycle_ids:
            link_reasons[key] = "target_language_reference_cycle"

    # Missing/cyclic definitions block every dependent definition as well.
    # This is a source-language closure, so a Python runtime alias must never
    # be used as a substitute for an unavailable configuration definition.
    link_reasons = _propagate_target_language_link_reasons(
        references,
        link_reasons,
    )

    definitions: list[TargetLanguageDefinitionIR] = []
    for kind, relative, _top_key, name, _raw, source, digest in raw_definitions:
        key = _target_definition_key(kind, relative, name)
        expression = expressions[key]
        link_reason = link_reasons.get(key, "")
        if link_reason:
            expression = replace(
                expression,
                coverage_status="blocked",
                blocked_reason=link_reason,
            )
        elif "target_alias_requires_source_closure" in expression.blocked_reason:
            expression = replace(
                expression,
                coverage_status="executable",
                blocked_reason="",
            )
        reference_names = references[key]
        definitions.append(
            TargetLanguageDefinitionIR(
                definition_id=definition_ids[key],
                definition_kind=cast(Literal["alias", "operation"], kind),
                name=name,
                source=source,
                content_sha256=digest,
                coverage_status=cast(Literal["executable", "blocked"], expression.coverage_status),
                blocked_reason=expression.blocked_reason,
                dependency_stages=(),
                expression=expression,
                reference_names=reference_names,
                reference_definition_ids=tuple(definition_ids[item] for item in reference_names),
            )
        )
    definitions_tuple = tuple(definitions)
    definitions_tuple = tuple(
        replace(
            definition,
            dependency_stages=_target_dependency_stages(
                definition.expression, definitions_tuple
            ),
        )
        if definition.coverage_status == "blocked" else definition
        for definition in definitions_tuple
    )
    return definitions_tuple, MappingProxyType(dict(fingerprints))


def build_target_language_definitions(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot | None = None,
) -> tuple[TargetLanguageDefinitionIR, ...]:
    """Return the strict S5A source-language closure for production consumers."""
    definitions, _fingerprints = _target_language_definitions(tbgd_root, snapshot=snapshot)
    return definitions


def close_target_expression_language(
    expression: TargetExpressionIR,
    definitions: tuple[TargetLanguageDefinitionIR, ...],
) -> TargetExpressionIR:
    """Admit aliases only after every source definition closes without ambiguity."""
    global_by_key = {
        (item.definition_kind, item.name): item for item in definitions
        if item.source.source_path in {_ALIAS_CONFIG, _OPERATION_CONFIG}
    }
    local_aliases = {
        (item.source.source_path, item.name): item for item in definitions
        if item.definition_kind == "alias" and item.source.source_path != _ALIAS_CONFIG
    }
    reason = ""
    for alias in _typed_target_aliases(expression.node):
        for token in _target_alias_reference_tokens(alias):
            parts = token.split(".")
            for index, name in enumerate(parts):
                kind = "alias" if index == 0 else "operation"
                if ("alias", name) in global_by_key and ("operation", name) in global_by_key:
                    reason = f"target_language_definition_name_ambiguous:{name}"
                    break
                definition = (
                    local_aliases.get((expression.source.source_path, name))
                    if kind == "alias" else None
                ) or global_by_key.get((kind, name))
                if definition is None:
                    reason = f"target_language_{kind}_definition_missing:{name}"
                    break
                if definition.coverage_status != "executable":
                    reason = f"target_language_dependency_blocked:{kind}:{name}"
                    break
            if reason:
                break
        if reason:
            break
    if reason:
        if (
            expression.coverage_status == "blocked"
            and "target_alias_requires_source_closure" not in expression.blocked_reason
        ):
            return expression
        return replace(expression, coverage_status="blocked", blocked_reason=reason)
    if "target_alias_requires_source_closure" in expression.blocked_reason:
        return replace(expression, coverage_status="executable", blocked_reason="")
    return expression


def _typed_target_aliases(node: TargetExpressionNodeIR | None) -> tuple[str, ...]:
    if node is None:
        return ()
    aliases = [node.alias] if node.expression_kind == "TargetAlias" and node.alias else []
    for child in (*node.children, node.candidate, node.target, node.query_target, node.query_compare):
        if child is not None:
            aliases.extend(_typed_target_aliases(child))
    if isinstance(node.predicate, ConditionIR):
        aliases.extend(_typed_target_aliases_from_value(node.predicate.payload))
    return tuple(aliases)


def _typed_target_aliases_from_value(value: object) -> tuple[str, ...]:
    if type(value) is TargetExpressionNodeIR:
        return _typed_target_aliases(value)
    if type(value) is ConditionIR:
        return _typed_target_aliases_from_value(value.payload)
    if isinstance(value, Mapping):
        return tuple(alias for child in value.values() for alias in _typed_target_aliases_from_value(child))
    if isinstance(value, (list, tuple)):
        return tuple(alias for child in value for alias in _typed_target_aliases_from_value(child))
    return ()


_EVENT_OR_ENTITY_PRODUCER_KINDS = frozenset({
    "TargetFetchAbilityGroup", "TargetFetchAbilityTargetLeader", "TargetFetchActionDelayExceed",
    "TargetFetchAidDefender", "TargetFetchAidProtector", "TargetFetchAimAtTargetList",
    "TargetFetchAliveSourceEntity", "TargetFetchBattleEventCaster", "TargetFetchLockTarget",
    "TargetFetchNextSkillCaster", "TargetFetchNextTurnOwnerEntity", "TargetFetchPassiveEntity",
    "TargetFetchProjectileHitEntity", "TargetFetchProjectileHitPos", "TargetFetchSnapshotEntityList",
    "TargetFetchStanceBreakTargetEntity", "TargetFetchTaskActionTarget", "TargetFetchTemplateEntityList",
    "TargetFetchTurnActionEntity", "TargetMapAttackTargetList", "TargetMapCharacterChangeSource",
    "TargetMapCharacterChangeTarget", "TargetMapCreatedBattleEvent", "TargetMapDamageAttacker",
    "TargetMapDamageDefender", "TargetMapDummyEntity", "TargetMapSkillActualAttacker",
    "TargetMapSkillIndicatorTarget", "TargetMapSkillSubTarget", "TargetMapSkillTarget",
    "TargetMapSnapshotEntity", "TargetFetchPartner", "TargetFetchUniqueNameEntity",
    "TargetMapSkillPointEntity", "TargetFetchLevelEntity",
})


def _target_dependency_stages(
    expression: TargetExpressionIR,
    definitions: tuple[TargetLanguageDefinitionIR, ...],
) -> tuple[str, ...]:
    global_definitions = {
        (item.definition_kind, item.name): item
        for item in definitions
        if item.source.source_path in {_ALIAS_CONFIG, _OPERATION_CONFIG}
    }
    local_aliases = {
        (item.source.source_path, item.name): item
        for item in definitions
        if item.definition_kind == "alias" and item.source.source_path != _ALIAS_CONFIG
    }
    visited: set[str] = set()

    def visit_definition(definition: TargetLanguageDefinitionIR) -> set[str]:
        if definition.definition_id in visited:
            return set()
        visited.add(definition.definition_id)
        return visit_node(definition.expression.node, definition.source.source_path)

    def visit_alias(alias: str, source_path: str) -> set[str]:
        stages: set[str] = set()
        for token in _target_alias_reference_tokens(alias):
            parts = token.split(".")
            definition = local_aliases.get((source_path, parts[0])) or global_definitions.get(("alias", parts[0]))
            if definition is None:
                stages.add("p9_s17_source_language_decode")
            elif definition.coverage_status == "blocked":
                stages.update(visit_definition(definition))
            for operation in parts[1:]:
                definition = global_definitions.get(("operation", operation))
                if definition is None:
                    stages.add("p9_s17_source_language_decode")
                elif definition.coverage_status == "blocked":
                    stages.update(visit_definition(definition))
        return stages

    def visit_node(node: TargetExpressionNodeIR | None, source_path: str) -> set[str]:
        if node is None:
            return {"p9_s17_source_language_decode"}
        stages: set[str] = set()
        kind = node.expression_kind
        original_kind = str(node.payload.get("original_kind") or "") if kind == "TargetUnsupported" else kind
        if kind == "TargetAlias":
            stages.update(visit_alias(node.alias, source_path))
        if kind == "TargetShuffle" or (kind == "Retarget" and node.by_random):
            stages.add("p9_s5d_rng")
        if original_kind in _EVENT_OR_ENTITY_PRODUCER_KINDS:
            stages.add("p9_s9_s17_typed_event_or_entity_producer")
        elif "Part" in original_kind:
            stages.add("p9_s17_body_part_producer")
        elif original_kind.endswith("ClientOnly"):
            stages.add("p9_s5c_action_target_selection")
        elif original_kind == "TargetQuery":
            stages.add("p9_s17_source_language_decode")
        elif kind == "TargetUnsupported":
            stages.add("p9_s5b_entity_relation_deterministic_target")
        if node.predicate is not None:
            stages.add("p9_s6_s7_condition_evaluator")
        for child in (*node.children, node.candidate, node.target, node.query_target, node.query_compare):
            stages.update(visit_node(child, source_path) if child is not None else set())
        return stages

    stages = visit_node(expression.node, expression.source.source_path)
    return tuple(sorted(stages or {"p9_s5b_entity_relation_deterministic_target"}))


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate target language JSON key:{key}")
        value[key] = child
    return value


def _target_language_reference_names(
    raw: Mapping[str, Any],
    *,
    source_path: str,
    global_alias_names: set[str],
    local_alias_names: Mapping[str, set[str]],
    operation_names: set[str],
) -> tuple[tuple[str, ...], str]:
    references: set[str] = set()
    missing: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            raw_type = str(value.get("$type") or "").removeprefix("RPG.GameCore.")
            if raw_type == "TargetAlias":
                alias = value.get("Alias")
                if not isinstance(alias, str) or not alias:
                    missing.append("target_language_alias_missing")
                else:
                    for token in _target_alias_reference_tokens(alias):
                        parts = token.split(".")
                        base = parts[0]
                        if base in local_alias_names.get(source_path, set()):
                            references.add(_target_definition_key("alias", source_path, base))
                        elif base in global_alias_names:
                            references.add(_target_definition_key("alias", _ALIAS_CONFIG, base))
                            if base in operation_names:
                                missing.append(f"target_language_definition_name_ambiguous:{base}")
                        else:
                            missing.append(f"target_language_alias_definition_missing:{base}")
                        for operation in parts[1:]:
                            if operation in operation_names:
                                references.add(_target_definition_key("operation", _OPERATION_CONFIG, operation))
                                if operation in global_alias_names:
                                    missing.append(
                                        f"target_language_definition_name_ambiguous:{operation}"
                                    )
                            else:
                                missing.append(
                                    f"target_language_operation_definition_missing:{operation}"
                                )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(raw)
    return tuple(sorted(references)), min(missing, default="")


def _target_definition_key(kind: str, source_path: str, name: str) -> str:
    if kind == "operation":
        return f"operation:{name}"
    if source_path == _ALIAS_CONFIG:
        return f"alias:{name}"
    return f"alias:{source_path}:{name}"


def _target_alias_reference_tokens(alias: str) -> tuple[str, ...]:
    if alias.startswith("(") and ")." in alias:
        closing = alias.find(").")
        inner = alias[1:closing]
        operations = alias[closing + 2:]
        if inner and operations and not any(not part for part in operations.split(".")):
            bases = tuple(
                token.strip()
                for token in inner.replace("+", "|").replace("-", "|").split("|")
                if token.strip()
            )
            return tuple(f"{base}.{operations}" for base in bases)
    tokens = tuple(
        token.strip()
        for token in alias.replace("+", "|").replace("-", "|").split("|")
        if token.strip()
    )
    return tokens if tokens else (alias,)


def _target_language_cycle_ids(graph: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    visiting: list[str] = []
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            cycles.update(visiting[visiting.index(node_id):])
            return
        if node_id in visited:
            return
        visiting.append(node_id)
        for child_id in graph.get(node_id, ()):
            visit(child_id)
        visiting.pop()
        visited.add(node_id)

    for node_id in sorted(graph):
        visit(node_id)
    return frozenset(cycles)


def _propagate_target_language_link_reasons(
    references: Mapping[str, tuple[str, ...]],
    direct_reasons: Mapping[str, str],
) -> dict[str, str]:
    reasons = dict(direct_reasons)
    while True:
        propagated = False
        for key, ref_names in references.items():
            if key in reasons:
                continue
            blocked_dependency = next(
                (name for name in ref_names if name in reasons),
                "",
            )
            if blocked_dependency:
                reasons[key] = (
                    "target_language_dependency_blocked:"
                    f"{blocked_dependency}"
                )
                propagated = True
        if not propagated:
            return reasons
