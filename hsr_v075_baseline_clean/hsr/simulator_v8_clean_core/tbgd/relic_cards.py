from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from ..equipment.models import (
    EquipmentDefinitionKey,
    RelicAbilitySourceIR,
    RelicDefinitionReferenceIssue,
    RelicDomainDefinitionIR,
    RelicMainAffixDefinitionIR,
    RelicMainAffixGroupDefinitionIR,
    RelicPublicationStatus,
    RelicSetDefinitionIR,
    RelicSetParameterIR,
    RelicSetStaticPropertyIR,
    RelicSetThresholdIR,
    RelicSlotDefinitionIR,
    RelicSlotFilterIR,
    RelicSubAffixDefinitionIR,
    RelicSubAffixGroupDefinitionIR,
    RelicTemplateDefinitionIR,
    RelicTemplateMode,
    make_equipment_source,
    raw_exact_decimal_text,
    relic_definition_reference_issues,
    validate_equipment_source_fingerprint,
)
from ..immutable_json import FrozenJSONDict, freeze_json, thaw_json
from ..ir_types import JSONValue
from .equipment_discovery import (
    PRIMARY_ABILITY_ROOT,
    PRIMARY_TABLE_ROLES,
    build_primary_equipment_source_fingerprint,
    discover_primary_equipment_paths,
)
from .equipment_inventory_contract import (
    fingerprint_contract_matches,
    validate_live_equipment_source_fingerprint,
)


RELIC_CATALOG_SCHEMA_VERSION = "p8.relic_definition_catalog.v1"
RELIC_CATALOG_FINGERPRINT_ALGORITHM = (
    "sha256-canonical-relic-definition-catalog-v1"
)
RELIC_TABLE_ROLES = (
    "relic_config",
    "relic_base_type",
    "relic_main_affix_config",
    "relic_sub_affix_config",
    "relic_set_config",
    "relic_set_skill_config",
)
RELIC_DOMAIN_NAMES = ("outer", "planar")


@dataclass(frozen=True, order=True)
class RelicCatalogIssue:
    issue_code: str
    source_path: str
    json_path: str
    raw_identity: str
    publication_status: RelicPublicationStatus
    detail: str
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "issue_code",
            "source_path",
            "json_path",
            "raw_identity",
            "detail",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"relic catalog issue {field_name} is required")
        if self.publication_status not in {
            "published",
            "unpublished",
            "status_unknown",
        }:
            raise ValueError("relic catalog issue publication_status is invalid")
        if not isinstance(self.candidates, (list, tuple)):
            raise TypeError("relic catalog issue candidates must be a list or tuple")
        candidates = tuple(self.candidates)
        if not all(isinstance(item, str) and item for item in candidates):
            raise TypeError("relic catalog issue candidates must be strings")
        object.__setattr__(self, "candidates", candidates)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "issue_code": self.issue_code,
            "source_path": self.source_path,
            "json_path": self.json_path,
            "raw_identity": self.raw_identity,
            "publication_status": self.publication_status,
            "detail": self.detail,
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True, order=True)
class RelicSourceInventoryEntry:
    source_role: str
    relative_path: str
    byte_count: int
    sha256: str
    record_count: int

    def __post_init__(self) -> None:
        if not self.source_role or not self.relative_path:
            raise ValueError("relic source inventory identity is required")
        if self.byte_count <= 0 or self.record_count < 0:
            raise ValueError("relic source inventory counts are invalid")
        if (
            len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("relic source inventory sha256 is invalid")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_role": self.source_role,
            "relative_path": self.relative_path,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class RelicAbilitySourceIndex:
    source_content_fingerprint: FrozenJSONDict
    source_kind: Literal["tbgd", "validation_fixture"]
    source_paths: tuple[str, ...]
    entries: tuple[tuple[str, tuple[RelicAbilitySourceIR, ...]], ...]
    issues: tuple[RelicCatalogIssue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_content_fingerprint, FrozenJSONDict):
            raise TypeError("relic ability index fingerprint must be frozen")
        validate_equipment_source_fingerprint(self.source_content_fingerprint)
        if self.source_kind not in {"tbgd", "validation_fixture"}:
            raise ValueError("relic ability index source_kind is invalid")
        paths = tuple(self.source_paths)
        if (
            not all(isinstance(path, str) and path for path in paths)
            or paths != tuple(sorted(paths))
        ):
            raise ValueError("relic ability index source_paths must be sorted strings")
        entries = tuple(
            (name, tuple(candidates))
            for name, candidates in self.entries
        )
        names = tuple(name for name, _ in entries)
        if (
            not all(isinstance(name, str) and name for name in names)
            or names != tuple(sorted(names))
            or len(names) != len(set(names))
        ):
            raise ValueError("relic ability index names must be unique and sorted")
        for name, candidates in entries:
            if not candidates or not all(
                isinstance(item, RelicAbilitySourceIR)
                and item.ability_name == name
                and item.source.evidence.get("source_fingerprint")
                == self.source_content_fingerprint
                for item in candidates
            ):
                raise ValueError("relic ability index candidates are invalid")
        issues = tuple(self.issues)
        if not all(isinstance(item, RelicCatalogIssue) for item in issues):
            raise TypeError("relic ability index issues must be typed")
        object.__setattr__(self, "source_paths", paths)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "issues", issues)

    def as_mapping(self) -> dict[str, tuple[RelicAbilitySourceIR, ...]]:
        return dict(self.entries)


@dataclass(frozen=True)
class RelicCanonicalCatalog:
    domain_definitions: tuple[RelicDomainDefinitionIR, ...]
    slot_definitions: tuple[RelicSlotDefinitionIR, ...]
    main_affix_group_definitions: tuple[RelicMainAffixGroupDefinitionIR, ...]
    main_affix_definitions: tuple[RelicMainAffixDefinitionIR, ...]
    sub_affix_group_definitions: tuple[RelicSubAffixGroupDefinitionIR, ...]
    sub_affix_definitions: tuple[RelicSubAffixDefinitionIR, ...]
    template_definitions: tuple[RelicTemplateDefinitionIR, ...]
    set_definitions: tuple[RelicSetDefinitionIR, ...]
    set_thresholds: tuple[RelicSetThresholdIR, ...]

    def __post_init__(self) -> None:
        fields = (
            ("domain_definitions", RelicDomainDefinitionIR),
            ("slot_definitions", RelicSlotDefinitionIR),
            ("main_affix_group_definitions", RelicMainAffixGroupDefinitionIR),
            ("main_affix_definitions", RelicMainAffixDefinitionIR),
            ("sub_affix_group_definitions", RelicSubAffixGroupDefinitionIR),
            ("sub_affix_definitions", RelicSubAffixDefinitionIR),
            ("template_definitions", RelicTemplateDefinitionIR),
            ("set_definitions", RelicSetDefinitionIR),
            ("set_thresholds", RelicSetThresholdIR),
        )
        for field_name, expected_type in fields:
            value = getattr(self, field_name)
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, expected_type) for item in value
            ):
                raise TypeError(
                    f"relic canonical {field_name} must contain {expected_type.__name__}"
                )
            detached = tuple(value)
            keys = tuple(item.definition_key for item in detached)
            if len(keys) != len(set(keys)):
                raise ValueError(f"relic canonical {field_name} keys must be unique")
            if keys != tuple(sorted(keys, key=lambda key: key.stable_id)):
                raise ValueError(
                    f"relic canonical {field_name} must use canonical key order"
                )
            object.__setattr__(self, field_name, detached)
        sources = [
            item.source
            for field_name, _ in fields
            for item in getattr(self, field_name)
        ]
        fingerprints = [
            source.evidence.get("source_fingerprint") for source in sources
        ]
        if any(value != fingerprints[0] for value in fingerprints[1:]):
            raise ValueError(
                "relic canonical definitions must share one source fingerprint"
            )

    def definitions(self) -> tuple[Any, ...]:
        return tuple(
            definition
            for collection in (
                self.domain_definitions,
                self.slot_definitions,
                self.main_affix_group_definitions,
                self.main_affix_definitions,
                self.sub_affix_group_definitions,
                self.sub_affix_definitions,
                self.template_definitions,
                self.set_definitions,
                self.set_thresholds,
            )
            for definition in collection
        )

    def reference_issues(
        self,
    ) -> tuple[RelicDefinitionReferenceIssue, ...]:
        return relic_definition_reference_issues(
            cast(Any, self.definitions())
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "domain_definitions": [
                item.to_json() for item in self.domain_definitions
            ],
            "slot_definitions": [item.to_json() for item in self.slot_definitions],
            "main_affix_group_definitions": [
                item.to_json() for item in self.main_affix_group_definitions
            ],
            "main_affix_definitions": [
                item.to_json() for item in self.main_affix_definitions
            ],
            "sub_affix_group_definitions": [
                item.to_json() for item in self.sub_affix_group_definitions
            ],
            "sub_affix_definitions": [
                item.to_json() for item in self.sub_affix_definitions
            ],
            "template_definitions": [
                item.to_json() for item in self.template_definitions
            ],
            "set_definitions": [item.to_json() for item in self.set_definitions],
            "set_thresholds": [item.to_json() for item in self.set_thresholds],
        }

    @classmethod
    def from_json(cls, value: object) -> RelicCanonicalCatalog:
        if not isinstance(value, Mapping):
            raise TypeError("relic canonical catalog must be an object")
        expected = {
            "domain_definitions",
            "slot_definitions",
            "main_affix_group_definitions",
            "main_affix_definitions",
            "sub_affix_group_definitions",
            "sub_affix_definitions",
            "template_definitions",
            "set_definitions",
            "set_thresholds",
        }
        unknown = sorted(set(value).difference(expected))
        if unknown:
            raise ValueError(f"relic canonical catalog contains unknown fields: {unknown}")

        def sequence(field_name: str) -> Sequence[object]:
            raw = value.get(field_name)
            if not isinstance(raw, (list, tuple)):
                raise TypeError(f"{field_name} must be an array")
            return raw

        return cls(
            domain_definitions=tuple(
                RelicDomainDefinitionIR.from_json(item)
                for item in sequence("domain_definitions")
            ),
            slot_definitions=tuple(
                RelicSlotDefinitionIR.from_json(item)
                for item in sequence("slot_definitions")
            ),
            main_affix_group_definitions=tuple(
                RelicMainAffixGroupDefinitionIR.from_json(item)
                for item in sequence("main_affix_group_definitions")
            ),
            main_affix_definitions=tuple(
                RelicMainAffixDefinitionIR.from_json(item)
                for item in sequence("main_affix_definitions")
            ),
            sub_affix_group_definitions=tuple(
                RelicSubAffixGroupDefinitionIR.from_json(item)
                for item in sequence("sub_affix_group_definitions")
            ),
            sub_affix_definitions=tuple(
                RelicSubAffixDefinitionIR.from_json(item)
                for item in sequence("sub_affix_definitions")
            ),
            template_definitions=tuple(
                RelicTemplateDefinitionIR.from_json(item)
                for item in sequence("template_definitions")
            ),
            set_definitions=tuple(
                RelicSetDefinitionIR.from_json(item)
                for item in sequence("set_definitions")
            ),
            set_thresholds=tuple(
                RelicSetThresholdIR.from_json(item)
                for item in sequence("set_thresholds")
            ),
        )


@dataclass(frozen=True)
class RelicCatalogBuildResult:
    source_content_fingerprint: FrozenJSONDict
    catalog_definition_fingerprint: FrozenJSONDict
    source_inventory: tuple[RelicSourceInventoryEntry, ...]
    slot_filters: tuple[RelicSlotFilterIR, ...]
    diagnostic_catalog: RelicCanonicalCatalog
    issues: tuple[RelicCatalogIssue, ...]
    published_template_source_count: int
    published_template_lowered_count: int
    published_template_blocked_count: int
    catalog_complete: bool
    semantic_table_parse_count: int
    ability_file_parse_count: int
    ability_index_build_count: int
    numeric_values_never_pass_through_float: bool
    production_validation_artifact_read_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_content_fingerprint, FrozenJSONDict):
            raise TypeError("relic source fingerprint must be recursively frozen")
        if not isinstance(self.catalog_definition_fingerprint, FrozenJSONDict):
            raise TypeError("relic definition fingerprint must be recursively frozen")
        if not isinstance(self.diagnostic_catalog, RelicCanonicalCatalog):
            raise TypeError("diagnostic_catalog must be RelicCanonicalCatalog")
        source_inventory = tuple(self.source_inventory)
        slot_filters = tuple(self.slot_filters)
        issues = tuple(self.issues)
        if not all(
            isinstance(item, RelicSourceInventoryEntry)
            for item in source_inventory
        ):
            raise TypeError("source_inventory entries must be typed")
        if not all(isinstance(item, RelicSlotFilterIR) for item in slot_filters):
            raise TypeError("slot_filters entries must be typed")
        if not all(isinstance(item, RelicCatalogIssue) for item in issues):
            raise TypeError("issues entries must be typed")
        object.__setattr__(self, "source_inventory", source_inventory)
        object.__setattr__(self, "slot_filters", slot_filters)
        object.__setattr__(self, "issues", issues)
        for field_name in (
            "published_template_source_count",
            "published_template_lowered_count",
            "published_template_blocked_count",
            "semantic_table_parse_count",
            "ability_file_parse_count",
            "ability_index_build_count",
            "production_validation_artifact_read_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TypeError(f"{field_name} must be a non-negative integer")
        if self.production_validation_artifact_read_count != 0:
            raise ValueError("production relic building cannot read validation artifacts")
        if self.ability_index_build_count != 1:
            raise ValueError("relic catalog must build the ability identity index once")
        if not isinstance(self.catalog_complete, bool):
            raise TypeError("catalog_complete must be boolean")
        if not isinstance(self.numeric_values_never_pass_through_float, bool):
            raise TypeError(
                "numeric_values_never_pass_through_float must be boolean"
            )
        if self.catalog_complete and (
            self.issues
            or self.published_template_blocked_count
            or self.published_template_lowered_count
            != self.published_template_source_count
            or self.diagnostic_catalog.reference_issues()
        ):
            raise ValueError(
                "complete relic catalogs require every published template lowered"
            )

    @property
    def canonical_catalog(self) -> RelicCanonicalCatalog | None:
        return self.diagnostic_catalog if self.catalog_complete else None

    def to_summary_json(self) -> dict[str, JSONValue]:
        catalog = self.diagnostic_catalog
        return {
            "schema_version": RELIC_CATALOG_SCHEMA_VERSION,
            "catalog_complete": self.catalog_complete,
            "source_content_fingerprint": cast(
                dict[str, JSONValue],
                thaw_json(self.source_content_fingerprint),
            ),
            "catalog_definition_fingerprint": cast(
                dict[str, JSONValue],
                thaw_json(self.catalog_definition_fingerprint),
            ),
            "source_inventory": [item.to_json() for item in self.source_inventory],
            "counts": {
                "domains": len(catalog.domain_definitions),
                "slots": len(catalog.slot_definitions),
                "slot_filters": len(self.slot_filters),
                "main_affix_groups": len(catalog.main_affix_group_definitions),
                "main_affixes": len(catalog.main_affix_definitions),
                "sub_affix_groups": len(catalog.sub_affix_group_definitions),
                "sub_affixes": len(catalog.sub_affix_definitions),
                "templates": len(catalog.template_definitions),
                "sets": len(catalog.set_definitions),
                "thresholds": len(catalog.set_thresholds),
            },
            "published_template_source_count": self.published_template_source_count,
            "published_template_lowered_count": self.published_template_lowered_count,
            "published_template_blocked_count": self.published_template_blocked_count,
            "issues": [issue.to_json() for issue in self.issues],
            "semantic_table_parse_count": self.semantic_table_parse_count,
            "ability_file_parse_count": self.ability_file_parse_count,
            "ability_index_build_count": self.ability_index_build_count,
            "numeric_values_never_pass_through_float": (
                self.numeric_values_never_pass_through_float
            ),
            "production_validation_artifact_read_count": (
                self.production_validation_artifact_read_count
            ),
        }


class RelicCatalogBuildError(ValueError):
    def __init__(self, result: RelicCatalogBuildResult):
        self.result = result
        codes = sorted({issue.issue_code for issue in result.issues})
        super().__init__(f"relic catalog failed closed: {codes}")


@dataclass(frozen=True)
class RelicCatalogSourceBundle:
    relic_rows: object
    base_type_rows: object
    main_affix_rows: object
    sub_affix_rows: object
    set_rows: object
    set_skill_rows: object
    ability_documents: tuple[tuple[str, object], ...]
    ability_source_index: RelicAbilitySourceIndex
    source_content_fingerprint: dict[str, JSONValue]
    source_inventory: tuple[RelicSourceInventoryEntry, ...]
    prerequisite_issues: tuple[RelicCatalogIssue, ...]
    source_integrity_ok: bool


def load_relic_catalog_sources(tbgd_root: Path) -> RelicCatalogSourceBundle:
    """Read the six relic tables and every equipment ability file exactly once."""

    root = tbgd_root.resolve()
    discovery = discover_primary_equipment_paths(root)
    table_paths = cast(dict[str, Path], discovery["table_paths"])
    ability_paths = cast(tuple[Path, ...], discovery["ability_paths"])
    selected_table_paths = {
        role: table_paths[role]
        for role in RELIC_TABLE_ROLES
    }
    all_paths = [*selected_table_paths.values(), *ability_paths]
    missing_paths: list[str] = []
    loaded: list[tuple[str, bytes]] = []
    raw_by_path: dict[str, bytes] = {}
    if not cast(Path, discovery["ability_root"]).is_dir() or not ability_paths:
        missing_paths.append(PRIMARY_ABILITY_ROOT)
    for path in all_paths:
        relative_path = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError:
            missing_paths.append(relative_path)
            continue
        loaded.append((relative_path, raw))
        raw_by_path[relative_path] = raw

    fingerprint = cast(
        dict[str, JSONValue],
        build_primary_equipment_source_fingerprint(loaded),
    )
    required_paths = [
        *(PRIMARY_TABLE_ROLES[role] for role in RELIC_TABLE_ROLES),
        *(path.relative_to(root).as_posix() for path in ability_paths),
    ]
    prerequisite_issues: list[RelicCatalogIssue] = []
    try:
        validate_live_equipment_source_fingerprint(
            cast(Mapping[str, object], fingerprint),
            required_paths=required_paths,
        )
    except (TypeError, ValueError) as exc:
        prerequisite_issues.append(
            _issue(
                "relic_live_source_fingerprint_invalid",
                "relic_source_inventory",
                "$",
                "current",
                "status_unknown",
                str(exc),
            )
        )

    table_documents: dict[str, object] = {}
    source_inventory: list[RelicSourceInventoryEntry] = []
    for role, path in selected_table_paths.items():
        relative_path = path.relative_to(root).as_posix()
        raw = raw_by_path.get(relative_path)
        if raw is None:
            continue
        try:
            document = _load_decimal_json(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            prerequisite_issues.append(
                _issue(
                    "relic_table_parse_failed",
                    relative_path,
                    "$",
                    role,
                    "status_unknown",
                    str(exc),
                )
            )
            continue
        table_documents[role] = document
        source_inventory.append(
            _inventory_entry(role, relative_path, raw, document)
        )

    ability_documents: list[tuple[str, object]] = []
    for path in ability_paths:
        relative_path = path.relative_to(root).as_posix()
        raw = raw_by_path.get(relative_path)
        if raw is None:
            continue
        try:
            document = _load_decimal_json(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            prerequisite_issues.append(
                _issue(
                    "relic_ability_file_parse_failed",
                    relative_path,
                    "$",
                    path.name,
                    "status_unknown",
                    str(exc),
                )
            )
            continue
        ability_documents.append((relative_path, document))
        source_inventory.append(
            _inventory_entry(
                "equipment_ability_file",
                relative_path,
                raw,
                document,
            )
        )
    for relative_path in sorted(set(missing_paths)):
        prerequisite_issues.append(
            _issue(
                "relic_primary_source_missing",
                relative_path,
                "$",
                relative_path,
                "status_unknown",
                "required relic source is missing",
            )
        )
    ability_source_index = build_relic_ability_source_index(
        ability_documents,
        fingerprint,
        source_kind="tbgd",
    )

    return RelicCatalogSourceBundle(
        relic_rows=table_documents.get("relic_config"),
        base_type_rows=table_documents.get("relic_base_type"),
        main_affix_rows=table_documents.get("relic_main_affix_config"),
        sub_affix_rows=table_documents.get("relic_sub_affix_config"),
        set_rows=table_documents.get("relic_set_config"),
        set_skill_rows=table_documents.get("relic_set_skill_config"),
        ability_documents=tuple(ability_documents),
        ability_source_index=ability_source_index,
        source_content_fingerprint=fingerprint,
        source_inventory=tuple(sorted(source_inventory)),
        prerequisite_issues=tuple(prerequisite_issues),
        source_integrity_ok=(
            not missing_paths
            and not prerequisite_issues
            and not ability_source_index.issues
        ),
    )


def build_relic_catalog(tbgd_root: Path) -> RelicCatalogBuildResult:
    sources = load_relic_catalog_sources(tbgd_root)
    return build_relic_catalog_from_source_bundle(sources)


def build_relic_catalog_from_source_bundle(
    sources: RelicCatalogSourceBundle,
) -> RelicCatalogBuildResult:
    """Build from one already-loaded typed source bundle."""

    if not isinstance(sources, RelicCatalogSourceBundle):
        raise TypeError("sources must be a RelicCatalogSourceBundle")
    return build_relic_catalog_from_documents(
        relic_rows=sources.relic_rows,
        base_type_rows=sources.base_type_rows,
        main_affix_rows=sources.main_affix_rows,
        sub_affix_rows=sources.sub_affix_rows,
        set_rows=sources.set_rows,
        set_skill_rows=sources.set_skill_rows,
        ability_documents=sources.ability_documents,
        ability_source_index=sources.ability_source_index,
        source_content_fingerprint=sources.source_content_fingerprint,
        expected_source_content_fingerprint=sources.source_content_fingerprint,
        source_inventory=sources.source_inventory,
        source_kind="tbgd",
        prerequisite_issues=sources.prerequisite_issues,
        source_integrity_ok=sources.source_integrity_ok,
        semantic_table_parse_count=len(RELIC_TABLE_ROLES),
        ability_file_parse_count=len(sources.ability_documents),
    )


def require_complete_relic_catalog(
    result: RelicCatalogBuildResult,
) -> RelicCanonicalCatalog:
    if not result.catalog_complete or result.canonical_catalog is None:
        raise RelicCatalogBuildError(result)
    return result.canonical_catalog


def build_relic_catalog_from_documents(
    *,
    relic_rows: object,
    base_type_rows: object,
    main_affix_rows: object,
    sub_affix_rows: object,
    set_rows: object,
    set_skill_rows: object,
    ability_documents: Sequence[tuple[str, object]],
    ability_source_index: RelicAbilitySourceIndex | None = None,
    source_content_fingerprint: Mapping[str, JSONValue],
    expected_source_content_fingerprint: Mapping[str, JSONValue] | None = None,
    source_inventory: Sequence[RelicSourceInventoryEntry] = (),
    source_kind: Literal["tbgd", "validation_fixture"] = "validation_fixture",
    prerequisite_issues: Sequence[RelicCatalogIssue] = (),
    source_integrity_ok: bool = True,
    source_row_indexes: Mapping[str, Sequence[int]] | None = None,
    semantic_table_parse_count: int = 6,
    ability_file_parse_count: int | None = None,
) -> RelicCatalogBuildResult:
    """Build an atomic typed relic directory from one in-memory source snapshot."""

    validate_equipment_source_fingerprint(
        cast(Mapping[str, object], source_content_fingerprint)
    )
    frozen_source_fingerprint = cast(
        FrozenJSONDict,
        freeze_json(dict(source_content_fingerprint)),
    )
    issues = list(prerequisite_issues)
    if (
        expected_source_content_fingerprint is not None
        and not fingerprint_contract_matches(
            cast(dict[str, Any], dict(source_content_fingerprint)),
            cast(dict[str, Any], dict(expected_source_content_fingerprint)),
        )
    ):
        issues.append(
            _issue(
                "relic_source_fingerprint_stale_or_incomplete",
                "relic_source_inventory",
                "$",
                "current",
                "status_unknown",
                "provided relic fingerprint does not match the live snapshot",
            )
        )
    fingerprint_paths = source_content_fingerprint.get("paths")
    fingerprint_path_set = (
        {str(path) for path in fingerprint_paths}
        if isinstance(fingerprint_paths, (list, tuple))
        else set()
    )
    required_fingerprint_paths = {
        *(PRIMARY_TABLE_ROLES[role] for role in RELIC_TABLE_ROLES),
        *(path for path, _ in ability_documents),
    }
    missing_fingerprint_paths = sorted(
        required_fingerprint_paths.difference(fingerprint_path_set)
    )
    if missing_fingerprint_paths:
        issues.append(
            _issue(
                "relic_source_fingerprint_stale_or_incomplete",
                "relic_source_inventory",
                "$.paths",
                "current",
                "status_unknown",
                "relic semantic sources must all be present in the fingerprint",
                tuple(missing_fingerprint_paths),
            )
        )
    rows_by_role = {
        "relic_config": _rows_or_issue(
            relic_rows,
            "relic_config",
            issues,
        ),
        "relic_base_type": _rows_or_issue(
            base_type_rows,
            "relic_base_type",
            issues,
        ),
        "relic_main_affix_config": _rows_or_issue(
            main_affix_rows,
            "relic_main_affix_config",
            issues,
        ),
        "relic_sub_affix_config": _rows_or_issue(
            sub_affix_rows,
            "relic_sub_affix_config",
            issues,
        ),
        "relic_set_config": _rows_or_issue(
            set_rows,
            "relic_set_config",
            issues,
        ),
        "relic_set_skill_config": _rows_or_issue(
            set_skill_rows,
            "relic_set_skill_config",
            issues,
        ),
    }
    indexes_by_role = {
        role: _projection_source_row_indexes(
            role,
            rows,
            source_row_indexes,
        )
        for role, rows in rows_by_role.items()
    }

    prepared_ability_index = ability_source_index or build_relic_ability_source_index(
        ability_documents,
        source_content_fingerprint,
        source_kind=source_kind,
    )
    expected_ability_paths = tuple(sorted(path for path, _ in ability_documents))
    if (
        (
            source_kind == "tbgd"
            and prepared_ability_index.source_kind != "tbgd"
        )
        or prepared_ability_index.source_paths != expected_ability_paths
        or prepared_ability_index.source_content_fingerprint
        != frozen_source_fingerprint
    ):
        issues.append(
            _issue(
                "relic_ability_source_index_snapshot_mismatch",
                PRIMARY_ABILITY_ROOT,
                "$",
                "ability_source_index",
                "status_unknown",
                "prepared ability index must match the current source snapshot",
            )
        )
        ability_index: dict[str, tuple[RelicAbilitySourceIR, ...]] = {}
    else:
        issues.extend(prepared_ability_index.issues)
        ability_index = prepared_ability_index.as_mapping()
    source_args = {
        "source_fingerprint": source_content_fingerprint,
        "source_kind": source_kind,
    }

    base_records, slot_filters = _build_slot_records(
        rows_by_role["relic_base_type"],
        indexes_by_role["relic_base_type"],
        issues,
        source_args,
    )
    main_affixes, main_groups = _build_main_affixes(
        rows_by_role["relic_main_affix_config"],
        indexes_by_role["relic_main_affix_config"],
        issues,
        source_args,
    )
    sub_affixes, sub_groups = _build_sub_affixes(
        rows_by_role["relic_sub_affix_config"],
        indexes_by_role["relic_sub_affix_config"],
        issues,
        source_args,
    )

    set_records = _unique_rows(
        rows_by_role["relic_set_config"],
        indexes_by_role["relic_set_config"],
        ("SetID",),
        "relic_set_duplicate_identity",
        "relic_set_config",
        issues,
    )
    template_records = _unique_rows(
        rows_by_role["relic_config"],
        indexes_by_role["relic_config"],
        ("ID",),
        "relic_template_duplicate_identity",
        "relic_config",
        issues,
    )
    main_group_rarities = _project_main_group_rarities(template_records)
    main_groups = {
        group_id: replace(
            group,
            rarity_types=main_group_rarities.get(group_id, ()),
        )
        for group_id, group in main_groups.items()
    }
    threshold_records = _unique_rows(
        rows_by_role["relic_set_skill_config"],
        indexes_by_role["relic_set_skill_config"],
        ("SetID", "RequireNum"),
        "relic_set_threshold_duplicate_identity",
        "relic_set_skill_config",
        issues,
    )

    set_publication = {
        identity: _publication_status(row, source_index, issues)
        for identity, (row, source_index) in set_records.items()
    }
    memberships = _build_memberships(
        template_records,
        set_records,
        base_records,
        issues,
    )
    slot_domain_names, set_domain_names = _derive_domains(
        set_records,
        memberships,
        base_records,
        issues,
    )
    domain_definitions = _build_domain_definitions(
        slot_domain_names,
        set_domain_names,
        source_args,
    )
    slot_definitions = _build_slot_definitions(
        base_records,
        slot_domain_names,
        source_args,
    )
    threshold_definitions = _build_thresholds(
        threshold_records,
        set_records,
        ability_index,
        issues,
        source_args,
    )
    thresholds_by_set: dict[str, list[RelicSetThresholdIR]] = defaultdict(list)
    for threshold in threshold_definitions:
        thresholds_by_set[threshold.set_key.definition_identity].append(threshold)
    template_definitions = _build_templates(
        template_records,
        set_records,
        set_publication,
        base_records,
        slot_domain_names,
        main_groups,
        sub_groups,
        issues,
        source_args,
    )
    templates_by_set: dict[str, list[RelicTemplateDefinitionIR]] = defaultdict(list)
    for definition in template_definitions:
        templates_by_set[definition.set_key.definition_identity].append(definition)
    set_definitions = _build_sets(
        set_records,
        set_publication,
        memberships,
        set_domain_names,
        templates_by_set,
        thresholds_by_set,
        issues,
        source_args,
    )

    diagnostic_catalog = RelicCanonicalCatalog(
        domain_definitions=tuple(domain_definitions),
        slot_definitions=tuple(slot_definitions),
        main_affix_group_definitions=tuple(main_groups.values()),
        main_affix_definitions=tuple(main_affixes),
        sub_affix_group_definitions=tuple(sub_groups.values()),
        sub_affix_definitions=tuple(sub_affixes),
        template_definitions=tuple(template_definitions),
        set_definitions=tuple(set_definitions),
        set_thresholds=tuple(threshold_definitions),
    )
    catalog_definitions = diagnostic_catalog.definitions()
    definitions_by_key = {
        definition.definition_key: definition
        for definition in catalog_definitions
    }
    for reference_issue in diagnostic_catalog.reference_issues():
        definition = definitions_by_key[reference_issue.definition_key]
        json_path = definition.source.evidence.get("json_path")
        publication_status = getattr(
            definition,
            "publication_status",
            "status_unknown",
        )
        issues.append(
            _issue(
                reference_issue.issue_code,
                definition.source.source_path,
                json_path if isinstance(json_path, str) else "$",
                reference_issue.definition_key.stable_id,
                cast(RelicPublicationStatus, publication_status),
                "canonical relic reference closure is invalid",
                (
                    (reference_issue.related_key.stable_id,)
                    if reference_issue.related_key is not None
                    else ()
                ),
            )
        )
    catalog_fingerprint = _catalog_definition_fingerprint(
        diagnostic_catalog,
        slot_filters,
    )
    published_template_source_count = sum(
        set_publication.get(
            _identity(row.get("SetID")),
            ("status_unknown", False),
        )[0]
        == "published"
        for row, _ in template_records.values()
    )
    published_templates = tuple(
        item
        for item in template_definitions
        if item.publication_status == "published"
    )
    catalog_complete = (
        source_integrity_ok
        and not issues
        and len(slot_definitions) == 6
        and len(slot_filters) >= 1
        and len(template_definitions) == len(template_records)
        and len(set_definitions) == len(set_records)
        and len(threshold_definitions) == len(threshold_records)
        and {item.domain for item in domain_definitions}
        == set(RELIC_DOMAIN_NAMES)
        and all(
            item.coverage_status == "lowered"
            for collection in (
                domain_definitions,
                slot_definitions,
                tuple(main_groups.values()),
                main_affixes,
                tuple(sub_groups.values()),
                sub_affixes,
                template_definitions,
                set_definitions,
                threshold_definitions,
            )
            for item in collection
        )
    )
    return RelicCatalogBuildResult(
        source_content_fingerprint=frozen_source_fingerprint,
        catalog_definition_fingerprint=cast(
            FrozenJSONDict,
            freeze_json(catalog_fingerprint),
        ),
        source_inventory=tuple(source_inventory),
        slot_filters=tuple(slot_filters),
        diagnostic_catalog=diagnostic_catalog,
        issues=tuple(sorted(issues)),
        published_template_source_count=published_template_source_count,
        published_template_lowered_count=sum(
            item.coverage_status == "lowered"
            for item in published_templates
        ),
        published_template_blocked_count=sum(
            item.coverage_status == "blocked"
            for item in published_templates
        ),
        catalog_complete=catalog_complete,
        semantic_table_parse_count=semantic_table_parse_count,
        ability_file_parse_count=(
            len(ability_documents)
            if ability_file_parse_count is None
            else ability_file_parse_count
        ),
        ability_index_build_count=1,
        numeric_values_never_pass_through_float=not _contains_float(
            (
                relic_rows,
                base_type_rows,
                main_affix_rows,
                sub_affix_rows,
                set_rows,
                set_skill_rows,
                ability_documents,
            )
        ),
    )


def _load_decimal_json(raw: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")

    return json.loads(
        raw.decode("utf-8"),
        parse_float=Decimal,
        parse_int=int,
        parse_constant=reject_constant,
    )


def _inventory_entry(
    role: str,
    relative_path: str,
    raw: bytes,
    document: object,
) -> RelicSourceInventoryEntry:
    if role == "equipment_ability_file" and isinstance(document, Mapping):
        records = document.get("AbilityList")
        record_count = len(records) if isinstance(records, list) else 0
    else:
        record_count = len(document) if isinstance(document, (list, dict)) else 1
    return RelicSourceInventoryEntry(
        source_role=role,
        relative_path=relative_path,
        byte_count=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        record_count=record_count,
    )


def _rows_or_issue(
    value: object,
    role: str,
    issues: list[RelicCatalogIssue],
) -> list[Mapping[str, object]]:
    source_path = PRIMARY_TABLE_ROLES[role]
    if not isinstance(value, list):
        issues.append(
            _issue(
                f"{role}_root_invalid",
                source_path,
                "$",
                role,
                "status_unknown",
                "relic source table root must be an array",
            )
        )
        return []
    rows: list[Mapping[str, object]] = []
    for index, row in enumerate(value):
        if isinstance(row, Mapping):
            rows.append(cast(Mapping[str, object], row))
        else:
            issues.append(
                _issue(
                    f"{role}_row_invalid",
                    source_path,
                    f"$[{index}]",
                    str(index),
                    "status_unknown",
                    "relic source row must be an object",
                )
            )
    return rows


def _projection_source_row_indexes(
    role: str,
    rows: Sequence[Mapping[str, object]],
    source_row_indexes: Mapping[str, Sequence[int]] | None,
) -> tuple[int, ...]:
    if source_row_indexes is None:
        return tuple(range(len(rows)))
    indexes = source_row_indexes.get(role)
    if (
        indexes is None
        or len(indexes) != len(rows)
        or any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            for index in indexes
        )
        or len(set(indexes)) != len(indexes)
    ):
        raise ValueError(f"relic projection source row indexes invalid:{role}")
    return tuple(indexes)


def _unique_rows(
    rows: Sequence[Mapping[str, object]],
    source_indexes: Sequence[int],
    key_fields: tuple[str, ...],
    issue_code: str,
    role: str,
    issues: list[RelicCatalogIssue],
) -> dict[str, tuple[Mapping[str, object], int]]:
    candidates: dict[str, list[tuple[Mapping[str, object], int]]] = defaultdict(list)
    for row, source_index in zip(rows, source_indexes, strict=True):
        parts = [_identity(row.get(field)) for field in key_fields]
        if any(part is None for part in parts):
            issues.append(
                _issue(
                    f"{issue_code}_missing",
                    PRIMARY_TABLE_ROLES[role],
                    f"$[{source_index}]",
                    str(source_index),
                    "status_unknown",
                    f"identity fields are required: {key_fields}",
                )
            )
            continue
        identity = ":".join(cast(list[str], parts))
        candidates[identity].append((row, source_index))
    result: dict[str, tuple[Mapping[str, object], int]] = {}
    for identity, values in sorted(candidates.items()):
        if len(values) != 1:
            issues.append(
                _issue(
                    issue_code,
                    PRIMARY_TABLE_ROLES[role],
                    "$",
                    identity,
                    "status_unknown",
                    "relic source identity must be unique",
                    tuple(f"$[{index}]" for _, index in values),
                )
            )
            continue
        result[identity] = values[0]
    return result


def build_relic_ability_source_index(
    ability_documents: Sequence[tuple[str, object]],
    fingerprint: Mapping[str, JSONValue],
    *,
    source_kind: Literal["tbgd", "validation_fixture"],
) -> RelicAbilitySourceIndex:
    issues: list[RelicCatalogIssue] = []
    paths = fingerprint.get("paths")
    fingerprint_paths = (
        {str(path) for path in paths}
        if isinstance(paths, (list, tuple))
        else set()
    )
    expected_paths = {
        path
        for path in fingerprint_paths
        if path.startswith(f"{PRIMARY_ABILITY_ROOT}/")
        and path.endswith(".json")
        and not path.endswith(".layout.json")
    }
    path_counts = Counter(path for path, _ in ability_documents)
    for path, count in sorted(path_counts.items()):
        if count != 1:
            issues.append(
                _issue(
                    "relic_ability_source_path_duplicate",
                    path,
                    "$",
                    path,
                    "status_unknown",
                    "equipment ability source path must be unique",
                )
            )
    if source_kind == "tbgd":
        for missing_path in sorted(expected_paths.difference(path_counts)):
            issues.append(
                _issue(
                    "relic_ability_source_path_missing",
                    missing_path,
                    "$",
                    missing_path,
                    "status_unknown",
                    "fingerprinted equipment ability source was not parsed",
                )
            )
        for extra_path in sorted(set(path_counts).difference(expected_paths)):
            issues.append(
                _issue(
                    "relic_ability_source_path_not_fingerprinted",
                    extra_path,
                    "$",
                    extra_path,
                    "status_unknown",
                    "equipment ability source is absent from current fingerprint",
                )
            )
    index: dict[str, list[RelicAbilitySourceIR]] = defaultdict(list)
    for relative_path, document in ability_documents:
        if not isinstance(document, Mapping):
            issues.append(
                _issue(
                    "relic_ability_document_root_invalid",
                    relative_path,
                    "$",
                    relative_path,
                    "status_unknown",
                    "equipment ability document root must be an object",
                )
            )
            continue
        records = document.get("AbilityList")
        if not isinstance(records, list):
            issues.append(
                _issue(
                    "relic_ability_list_missing",
                    relative_path,
                    "$.AbilityList",
                    relative_path,
                    "status_unknown",
                    "equipment ability document must contain AbilityList",
                )
            )
            continue
        for record_index, record in enumerate(records):
            ability_name = (
                record.get("Name")
                if isinstance(record, Mapping)
                else None
            )
            if not isinstance(ability_name, str) or not ability_name:
                issues.append(
                    _issue(
                        "relic_ability_identity_missing",
                        relative_path,
                        f"$.AbilityList[{record_index}]",
                        str(record_index),
                        "status_unknown",
                        "equipment AbilityList record Name is required",
                    )
                )
                continue
            index[ability_name].append(
                RelicAbilitySourceIR(
                    ability_name=ability_name,
                    record_index=record_index,
                    source=make_equipment_source(
                        source_path=relative_path,
                        raw_type="AbilityList",
                        raw_id=ability_name,
                        json_path=f"$.AbilityList[{record_index}]",
                        source_fingerprint=fingerprint,
                        source_kind=source_kind,
                    ),
                )
            )
    for ability_name, candidates in sorted(index.items()):
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "relic_ability_identity_ambiguous",
                    PRIMARY_ABILITY_ROOT,
                    "$.AbilityList",
                    ability_name,
                    "status_unknown",
                    "equipment ability identity must resolve uniquely",
                    tuple(
                        f"{item.source.source_path}#{item.record_index}"
                        for item in candidates
                    ),
                )
            )
    return RelicAbilitySourceIndex(
        source_content_fingerprint=cast(
            FrozenJSONDict,
            freeze_json(dict(fingerprint)),
        ),
        source_kind=source_kind,
        source_paths=tuple(sorted(path for path, _ in ability_documents)),
        entries=tuple(
            (name, tuple(candidates))
            for name, candidates in sorted(index.items())
        ),
        issues=tuple(sorted(issues)),
    )


def _build_slot_records(
    rows: Sequence[Mapping[str, object]],
    source_indexes: Sequence[int],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[
    dict[str, tuple[Mapping[str, object], int, tuple[str, ...]]],
    tuple[RelicSlotFilterIR, ...],
]:
    records: dict[str, list[tuple[Mapping[str, object], int, tuple[str, ...]]]] = (
        defaultdict(list)
    )
    filters: list[RelicSlotFilterIR] = []
    for row, source_index in zip(rows, source_indexes, strict=True):
        properties = _text_sequence(row.get("ValidPropertyList"))
        slot_type = row.get("Type")
        source_identity = (
            slot_type
            if isinstance(slot_type, str) and slot_type
            else f"untyped:{source_index}"
        )
        source = _source(
            "relic_base_type",
            source_index,
            "RelicBaseType",
            source_identity,
            source_args,
        )
        if properties is None or not properties:
            issues.append(
                _issue(
                    "relic_base_type_properties_invalid",
                    PRIMARY_TABLE_ROLES["relic_base_type"],
                    f"$[{source_index}].ValidPropertyList",
                    str(slot_type or source_index),
                    "status_unknown",
                    "ValidPropertyList must be a non-empty string array",
                )
            )
            continue
        if not isinstance(slot_type, str) or not slot_type:
            filters.append(
                RelicSlotFilterIR(
                    filter_identity=source_identity,
                    allowed_property_types=properties,
                    source=source,
                )
            )
            continue
        records[slot_type].append((row, source_index, properties))
    unique: dict[str, tuple[Mapping[str, object], int, tuple[str, ...]]] = {}
    for slot_type, candidates in sorted(records.items()):
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "relic_slot_duplicate_identity",
                    PRIMARY_TABLE_ROLES["relic_base_type"],
                    "$",
                    slot_type,
                    "status_unknown",
                    "typed relic slot records must be unique",
                )
            )
            continue
        unique[slot_type] = candidates[0]
    if len(unique) != 6:
        issues.append(
            _issue(
                "relic_real_slot_count_not_six",
                PRIMARY_TABLE_ROLES["relic_base_type"],
                "$",
                "typed_slots",
                "status_unknown",
                f"current relic schema requires six typed slots, got {len(unique)}",
            )
        )
    if not filters:
        issues.append(
            _issue(
                "relic_untyped_filter_row_missing",
                PRIMARY_TABLE_ROLES["relic_base_type"],
                "$",
                "untyped_filter",
                "status_unknown",
                "untyped all-property filter must be classified separately",
            )
        )
    return unique, tuple(sorted(filters, key=lambda item: item.filter_identity))


def _project_main_group_rarities(
    template_records: Mapping[str, tuple[Mapping[str, object], int]],
) -> dict[str, tuple[str, ...]]:
    """Project each main affix group's usable rarities from real template rows."""

    rarities: dict[str, set[str]] = defaultdict(set)
    for row, _source_index in template_records.values():
        group_id = row.get("MainAffixGroup")
        rarity = row.get("Rarity")
        if (
            isinstance(group_id, int)
            and not isinstance(group_id, bool)
            and isinstance(rarity, str)
            and rarity
        ):
            rarities[str(group_id)].add(rarity)
    return {
        group_id: tuple(sorted(values)) for group_id, values in rarities.items()
    }


def _build_main_affixes(
    rows: Sequence[Mapping[str, object]],
    source_indexes: Sequence[int],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[
    tuple[RelicMainAffixDefinitionIR, ...],
    dict[str, RelicMainAffixGroupDefinitionIR],
]:
    unique = _unique_rows(
        rows,
        source_indexes,
        ("GroupID", "AffixID"),
        "relic_main_affix_duplicate_identity",
        "relic_main_affix_config",
        issues,
    )
    definitions: list[RelicMainAffixDefinitionIR] = []
    by_group: dict[str, list[RelicMainAffixDefinitionIR]] = defaultdict(list)
    for identity, (row, source_index) in unique.items():
        group_id, affix_id = identity.split(":", 1)
        property_type = row.get("Property")
        base_value = _wrapped_decimal(row.get("BaseValue"))
        level_add = _wrapped_decimal(row.get("LevelAdd"))
        if (
            not isinstance(property_type, str)
            or not property_type
            or base_value is None
            or level_add is None
        ):
            issues.append(
                _issue(
                    "relic_main_affix_payload_invalid",
                    PRIMARY_TABLE_ROLES["relic_main_affix_config"],
                    f"$[{source_index}]",
                    identity,
                    "status_unknown",
                    "main affix property/base/level values are required",
                )
            )
            continue
        definition = RelicMainAffixDefinitionIR(
            definition_key=EquipmentDefinitionKey(
                "relic_main_affix",
                identity,
            ),
            group_key=EquipmentDefinitionKey(
                "relic_main_affix_group",
                group_id,
            ),
            raw_affix_id=affix_id,
            property_type=property_type,
            base_value=base_value,
            level_add=level_add,
            source=_source(
                "relic_main_affix_config",
                source_index,
                "RelicMainAffixConfig",
                identity,
                source_args,
            ),
            coverage_status="lowered",
            blocked_reason="",
        )
        definitions.append(definition)
        by_group[group_id].append(definition)
    groups = {
        group_id: RelicMainAffixGroupDefinitionIR(
            definition_key=EquipmentDefinitionKey(
                "relic_main_affix_group",
                group_id,
            ),
            raw_group_id=group_id,
            affix_keys=tuple(
                sorted(
                    (item.definition_key for item in members),
                    key=lambda key: key.stable_id,
                )
            ),
            property_types=tuple(
                sorted({item.property_type for item in members})
            ),
            rarity_types=(),
            source=_derived_source(
                "relic_main_affix_config",
                "RelicMainAffixGroupProjection",
                group_id,
                source_args,
            ),
            coverage_status="lowered",
            blocked_reason="",
        )
        for group_id, members in sorted(by_group.items())
    }
    return (
        tuple(sorted(definitions, key=lambda item: item.definition_key.stable_id)),
        groups,
    )


def _build_sub_affixes(
    rows: Sequence[Mapping[str, object]],
    source_indexes: Sequence[int],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[
    tuple[RelicSubAffixDefinitionIR, ...],
    dict[str, RelicSubAffixGroupDefinitionIR],
]:
    unique = _unique_rows(
        rows,
        source_indexes,
        ("GroupID", "AffixID"),
        "relic_sub_affix_duplicate_identity",
        "relic_sub_affix_config",
        issues,
    )
    definitions: list[RelicSubAffixDefinitionIR] = []
    by_group: dict[str, list[RelicSubAffixDefinitionIR]] = defaultdict(list)
    for identity, (row, source_index) in unique.items():
        group_id, affix_id = identity.split(":", 1)
        property_type = row.get("Property")
        base_value = _wrapped_decimal(row.get("BaseValue"))
        step_value = _wrapped_decimal(row.get("StepValue"))
        step_count = _strict_int(row.get("StepNum"))
        if (
            not isinstance(property_type, str)
            or not property_type
            or base_value is None
            or step_value is None
            or step_count is None
            or step_count <= 0
        ):
            issues.append(
                _issue(
                    "relic_sub_affix_payload_invalid",
                    PRIMARY_TABLE_ROLES["relic_sub_affix_config"],
                    f"$[{source_index}]",
                    identity,
                    "status_unknown",
                    "sub affix property/base/step values are required",
                )
            )
            continue
        definition = RelicSubAffixDefinitionIR(
            definition_key=EquipmentDefinitionKey(
                "relic_sub_affix",
                identity,
            ),
            group_key=EquipmentDefinitionKey(
                "relic_sub_affix_group",
                group_id,
            ),
            raw_affix_id=affix_id,
            property_type=property_type,
            base_value=base_value,
            step_value=step_value,
            step_count=step_count,
            source=_source(
                "relic_sub_affix_config",
                source_index,
                "RelicSubAffixConfig",
                identity,
                source_args,
            ),
            coverage_status="lowered",
            blocked_reason="",
        )
        definitions.append(definition)
        by_group[group_id].append(definition)
    groups = {
        group_id: RelicSubAffixGroupDefinitionIR(
            definition_key=EquipmentDefinitionKey(
                "relic_sub_affix_group",
                group_id,
            ),
            raw_group_id=group_id,
            affix_keys=tuple(
                sorted(
                    (item.definition_key for item in members),
                    key=lambda key: key.stable_id,
                )
            ),
            property_types=tuple(
                sorted({item.property_type for item in members})
            ),
            source=_derived_source(
                "relic_sub_affix_config",
                "RelicSubAffixGroupProjection",
                group_id,
                source_args,
            ),
            coverage_status="lowered",
            blocked_reason="",
        )
        for group_id, members in sorted(by_group.items())
    }
    return (
        tuple(sorted(definitions, key=lambda item: item.definition_key.stable_id)),
        groups,
    )


def _build_memberships(
    template_records: Mapping[str, tuple[Mapping[str, object], int]],
    set_records: Mapping[str, tuple[Mapping[str, object], int]],
    base_records: Mapping[
        str,
        tuple[Mapping[str, object], int, tuple[str, ...]],
    ],
    issues: list[RelicCatalogIssue],
) -> dict[str, dict[str, set[str]]]:
    memberships: dict[str, dict[str, set[str]]] = {
        set_id: {"slots": set(), "templates": set()}
        for set_id in set_records
    }
    for template_id, (row, source_index) in template_records.items():
        set_id = _identity(row.get("SetID"))
        slot_type = row.get("Type")
        if set_id is None or set_id not in set_records:
            issues.append(
                _issue(
                    "relic_template_set_reference_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].SetID",
                    template_id,
                    "status_unknown",
                    "template SetID must resolve uniquely",
                )
            )
            continue
        if not isinstance(slot_type, str) or slot_type not in base_records:
            issues.append(
                _issue(
                    "relic_template_slot_reference_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].Type",
                    template_id,
                    "status_unknown",
                    "template Type must resolve to a typed slot",
                )
            )
            continue
        memberships[set_id]["slots"].add(slot_type)
        memberships[set_id]["templates"].add(template_id)
    for set_id, members in memberships.items():
        if not members["slots"] or not members["templates"]:
            issues.append(
                _issue(
                    "relic_set_membership_empty",
                    PRIMARY_TABLE_ROLES["relic_set_config"],
                    "$",
                    set_id,
                    "status_unknown",
                    "each relic set requires template and slot members",
                )
            )
    return memberships


def _derive_domains(
    set_records: Mapping[str, tuple[Mapping[str, object], int]],
    memberships: Mapping[str, Mapping[str, set[str]]],
    base_records: Mapping[
        str,
        tuple[Mapping[str, object], int, tuple[str, ...]],
    ],
    issues: list[RelicCatalogIssue],
) -> tuple[dict[str, str], dict[str, str]]:
    declared_domains: dict[str, str] = {}
    slot_candidates: dict[str, set[str]] = defaultdict(set)
    for set_id, (row, source_index) in set_records.items():
        raw_flag = row.get("IsPlanarSuit")
        if "IsPlanarSuit" in row and not isinstance(raw_flag, bool):
            issues.append(
                _issue(
                    "relic_set_domain_flag_invalid",
                    PRIMARY_TABLE_ROLES["relic_set_config"],
                    f"$[{source_index}].IsPlanarSuit",
                    set_id,
                    "status_unknown",
                    "IsPlanarSuit must be boolean when present",
                )
            )
            continue
        declared = "planar" if raw_flag is True else "outer"
        declared_domains[set_id] = declared
        for slot_type in memberships.get(set_id, {}).get("slots", set()):
            slot_candidates[slot_type].add(declared)

    slot_domains: dict[str, str] = {}
    for slot_type in sorted(base_records):
        candidates = slot_candidates.get(slot_type, set())
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "relic_slot_cross_domain_membership",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    "$",
                    slot_type,
                    "status_unknown",
                    "slot membership must derive exactly one domain",
                    tuple(sorted(candidates)),
                )
            )
            continue
        slot_domains[slot_type] = next(iter(candidates))

    set_domains: dict[str, str] = {}
    for set_id, declared in declared_domains.items():
        member_domains = {
            slot_domains[slot]
            for slot in memberships.get(set_id, {}).get("slots", set())
            if slot in slot_domains
        }
        if member_domains != {declared}:
            issues.append(
                _issue(
                    "relic_set_cross_domain_membership",
                    PRIMARY_TABLE_ROLES["relic_set_config"],
                    "$",
                    set_id,
                    "status_unknown",
                    "set domain must agree with every member slot",
                    tuple(sorted(member_domains)),
                )
            )
            continue
        set_domains[set_id] = declared
    if set(slot_domains.values()) != set(RELIC_DOMAIN_NAMES):
        issues.append(
            _issue(
                "relic_domain_partition_incomplete",
                PRIMARY_TABLE_ROLES["relic_config"],
                "$",
                "domains",
                "status_unknown",
                "membership must derive outer and planar domains",
            )
        )
    return slot_domains, set_domains


def _build_domain_definitions(
    slot_domains: Mapping[str, str],
    set_domains: Mapping[str, str],
    source_args: Mapping[str, object],
) -> tuple[RelicDomainDefinitionIR, ...]:
    definitions: list[RelicDomainDefinitionIR] = []
    for domain in RELIC_DOMAIN_NAMES:
        slot_keys = tuple(
            EquipmentDefinitionKey("relic_slot", slot)
            for slot, value in sorted(slot_domains.items())
            if value == domain
        )
        set_keys = tuple(
            EquipmentDefinitionKey("relic_set", set_id)
            for set_id, value in sorted(set_domains.items())
            if value == domain
        )
        if not slot_keys or not set_keys:
            continue
        definitions.append(
            RelicDomainDefinitionIR(
                definition_key=EquipmentDefinitionKey("relic_domain", domain),
                domain=cast(Any, domain),
                slot_keys=slot_keys,
                set_keys=set_keys,
                source=_derived_source(
                    "relic_config",
                    "RelicDomainMembershipProjection",
                    domain,
                    source_args,
                ),
                coverage_status="lowered",
                blocked_reason="",
            )
        )
    return tuple(definitions)


def _build_slot_definitions(
    base_records: Mapping[
        str,
        tuple[Mapping[str, object], int, tuple[str, ...]],
    ],
    slot_domains: Mapping[str, str],
    source_args: Mapping[str, object],
) -> tuple[RelicSlotDefinitionIR, ...]:
    definitions: list[RelicSlotDefinitionIR] = []
    for slot_type, (_, source_index, properties) in sorted(base_records.items()):
        domain = slot_domains.get(slot_type)
        if domain is None:
            continue
        definitions.append(
            RelicSlotDefinitionIR(
                definition_key=EquipmentDefinitionKey("relic_slot", slot_type),
                raw_slot_type=slot_type,
                domain_key=EquipmentDefinitionKey("relic_domain", domain),
                allowed_main_property_types=properties,
                source=_source(
                    "relic_base_type",
                    source_index,
                    "RelicBaseType",
                    slot_type,
                    source_args,
                ),
                coverage_status="lowered",
                blocked_reason="",
            )
        )
    return tuple(definitions)


def _build_templates(
    template_records: Mapping[str, tuple[Mapping[str, object], int]],
    set_records: Mapping[str, tuple[Mapping[str, object], int]],
    set_publication: Mapping[str, tuple[RelicPublicationStatus, bool]],
    base_records: Mapping[
        str,
        tuple[Mapping[str, object], int, tuple[str, ...]],
    ],
    slot_domains: Mapping[str, str],
    main_groups: Mapping[str, RelicMainAffixGroupDefinitionIR],
    sub_groups: Mapping[str, RelicSubAffixGroupDefinitionIR],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[RelicTemplateDefinitionIR, ...]:
    definitions: list[RelicTemplateDefinitionIR] = []
    for template_id, (row, source_index) in sorted(template_records.items()):
        local_reasons: list[str] = []
        set_id = _identity(row.get("SetID"))
        slot_type = row.get("Type")
        main_group_id = _identity(row.get("MainAffixGroup"))
        sub_group_id = _identity(row.get("SubAffixGroup"))
        rarity = row.get("Rarity")
        max_level = _strict_int(row.get("MaxLevel"))
        raw_mode = row.get("Mode")
        publication_status = (
            set_publication.get(set_id, ("status_unknown", False))[0]
            if set_id is not None
            else "status_unknown"
        )
        mode: RelicTemplateMode
        if raw_mode in {"BASIC", "CUSTOM"}:
            mode = cast(RelicTemplateMode, raw_mode)
        else:
            mode = "UNKNOWN"
            local_reasons.append("relic_template_mode_unknown")
            issues.append(
                _issue(
                    "relic_template_mode_unknown",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].Mode",
                    template_id,
                    publication_status,
                    "template mode must be BASIC or CUSTOM",
                )
            )
        if set_id is None or set_id not in set_records:
            local_reasons.append("relic_template_set_reference_missing")
            issues.append(
                _issue(
                    "relic_template_set_reference_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].SetID",
                    template_id,
                    publication_status,
                    "template SetID must resolve uniquely",
                )
            )
        if (
            not isinstance(slot_type, str)
            or slot_type not in base_records
            or slot_type not in slot_domains
        ):
            local_reasons.append("relic_template_slot_reference_missing")
            issues.append(
                _issue(
                    "relic_template_slot_reference_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].Type",
                    template_id,
                    publication_status,
                    "template Type must resolve to one source-derived slot domain",
                )
            )
        if main_group_id is None or main_group_id not in main_groups:
            local_reasons.append("relic_template_main_group_missing")
            issues.append(
                _issue(
                    "relic_template_main_group_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].MainAffixGroup",
                    template_id,
                    publication_status,
                    "template main affix group must resolve uniquely",
                )
            )
        if sub_group_id is None or sub_group_id not in sub_groups:
            local_reasons.append("relic_template_sub_group_missing")
            issues.append(
                _issue(
                    "relic_template_sub_group_missing",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].SubAffixGroup",
                    template_id,
                    publication_status,
                    "template sub affix group must resolve uniquely",
                )
            )
        if not isinstance(rarity, str) or not rarity:
            local_reasons.append("relic_template_rarity_invalid")
            issues.append(
                _issue(
                    "relic_template_rarity_invalid",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].Rarity",
                    template_id,
                    publication_status,
                    "template Rarity must be a non-empty string",
                )
            )
        if max_level is None or max_level < 0:
            local_reasons.append("relic_template_max_level_invalid")
            issues.append(
                _issue(
                    "relic_template_max_level_invalid",
                    PRIMARY_TABLE_ROLES["relic_config"],
                    f"$[{source_index}].MaxLevel",
                    template_id,
                    publication_status,
                    "template MaxLevel must be a non-negative integer",
                )
            )
        if (
            isinstance(slot_type, str)
            and slot_type in base_records
            and main_group_id in main_groups
        ):
            allowed = set(base_records[slot_type][2])
            selected = set(main_groups[cast(str, main_group_id)].property_types)
            if not selected.issubset(allowed):
                local_reasons.append("relic_template_main_group_slot_mismatch")
                issues.append(
                    _issue(
                        "relic_template_main_group_slot_mismatch",
                        PRIMARY_TABLE_ROLES["relic_config"],
                        f"$[{source_index}]",
                        template_id,
                        publication_status,
                        "template main group contains properties outside slot pool",
                        tuple(sorted(selected.difference(allowed))),
                    )
                )
        if (
            set_id is None
            or set_id not in set_records
            or not isinstance(slot_type, str)
            or slot_type not in base_records
            or slot_type not in slot_domains
            or main_group_id is None
            or main_group_id not in main_groups
            or sub_group_id is None
            or sub_group_id not in sub_groups
            or not isinstance(rarity, str)
            or not rarity
            or max_level is None
            or not isinstance(raw_mode, str)
            or not raw_mode
        ):
            continue
        blocked_reason = ";".join(sorted(set(local_reasons)))
        definitions.append(
            RelicTemplateDefinitionIR(
                definition_key=EquipmentDefinitionKey(
                    "relic_template",
                    template_id,
                ),
                raw_relic_id=template_id,
                publication_status=publication_status,
                slot_key=EquipmentDefinitionKey("relic_slot", slot_type),
                domain_key=EquipmentDefinitionKey(
                    "relic_domain",
                    slot_domains[slot_type],
                ),
                set_key=EquipmentDefinitionKey("relic_set", set_id),
                rarity=rarity,
                max_level=max_level,
                main_affix_group_key=EquipmentDefinitionKey(
                    "relic_main_affix_group",
                    main_group_id,
                ),
                sub_affix_group_key=EquipmentDefinitionKey(
                    "relic_sub_affix_group",
                    sub_group_id,
                ),
                mode=mode,
                raw_mode=raw_mode,
                source=_source(
                    "relic_config",
                    source_index,
                    "RelicConfig",
                    template_id,
                    source_args,
                ),
                coverage_status="blocked" if blocked_reason else "lowered",
                blocked_reason=blocked_reason,
            )
        )
    return tuple(
        sorted(definitions, key=lambda item: item.definition_key.stable_id)
    )


def _build_thresholds(
    threshold_records: Mapping[str, tuple[Mapping[str, object], int]],
    set_records: Mapping[str, tuple[Mapping[str, object], int]],
    ability_index: Mapping[str, tuple[RelicAbilitySourceIR, ...]],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[RelicSetThresholdIR, ...]:
    definitions: list[RelicSetThresholdIR] = []
    for identity, (row, source_index) in sorted(threshold_records.items()):
        set_id = _identity(row.get("SetID"))
        require_count = _strict_int(row.get("RequireNum"))
        if set_id is None or require_count is None or require_count <= 0:
            issues.append(
                _issue(
                    "relic_threshold_identity_invalid",
                    PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                    f"$[{source_index}]",
                    identity,
                    "status_unknown",
                    "threshold SetID and positive integer RequireNum are required",
                )
            )
            continue
        publication_status: RelicPublicationStatus = "status_unknown"
        if set_id in set_records:
            publication_status = _publication_status(
                *set_records[set_id],
                issues,
            )[0]
        local_reasons: list[str] = []
        if set_id not in set_records:
            local_reasons.append("relic_threshold_set_reference_missing")
            issues.append(
                _issue(
                    "relic_threshold_set_reference_missing",
                    PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                    f"$[{source_index}].SetID",
                    identity,
                    publication_status,
                    "threshold SetID must resolve uniquely",
                )
            )
        static_properties = _threshold_static_properties(
            row.get("PropertyList"),
            set_id,
            require_count,
            source_index,
            publication_status,
            issues,
            source_args,
        )
        parameters = _threshold_parameters(
            row.get("AbilityParamList"),
            set_id,
            require_count,
            source_index,
            publication_status,
            issues,
            source_args,
        )
        ability_name = row.get("AbilityName")
        ability_source: RelicAbilitySourceIR | None = None
        if isinstance(ability_name, str) and ability_name:
            candidates = ability_index.get(ability_name, ())
            if len(candidates) == 1:
                ability_source = candidates[0]
            else:
                local_reasons.append("relic_threshold_ability_source_not_unique")
                issues.append(
                    _issue(
                        "relic_threshold_ability_source_not_unique",
                        PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                        f"$[{source_index}].AbilityName",
                        identity,
                        publication_status,
                        "threshold ability must resolve to one real record",
                        tuple(
                            f"{item.source.source_path}#{item.record_index}"
                            for item in candidates
                        ),
                    )
                )
        elif ability_name not in {"", None}:
            local_reasons.append("relic_threshold_ability_name_invalid")
        if not static_properties and ability_source is None:
            local_reasons.append("relic_threshold_payload_empty")
            issues.append(
                _issue(
                    "relic_threshold_payload_empty",
                    PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                    f"$[{source_index}]",
                    identity,
                    publication_status,
                    "threshold requires static properties or a real ability source",
                )
            )
            continue
        blocked_reason = ";".join(sorted(set(local_reasons)))
        definitions.append(
            RelicSetThresholdIR(
                definition_key=EquipmentDefinitionKey(
                    "relic_set_threshold",
                    f"{set_id}:{require_count}",
                ),
                set_key=EquipmentDefinitionKey("relic_set", set_id),
                require_count=require_count,
                static_properties=static_properties,
                parameters=parameters,
                ability_source=ability_source,
                source=_source(
                    "relic_set_skill_config",
                    source_index,
                    "RelicSetSkillConfig",
                    f"{set_id}:{require_count}",
                    source_args,
                ),
                coverage_status="blocked" if blocked_reason else "lowered",
                blocked_reason=blocked_reason,
            )
        )
    return tuple(
        sorted(definitions, key=lambda item: item.definition_key.stable_id)
    )


def _threshold_static_properties(
    value: object,
    set_id: str,
    require_count: int,
    source_index: int,
    publication_status: RelicPublicationStatus,
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[RelicSetStaticPropertyIR, ...]:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "relic_threshold_property_list_invalid",
                PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                f"$[{source_index}].PropertyList",
                f"{set_id}:{require_count}",
                publication_status,
                "PropertyList must be an array",
            )
        )
        return ()
    result: list[RelicSetStaticPropertyIR] = []
    for property_index, item in enumerate(value):
        property_type = (
            item.get("FODBMMCKAEN")
            if isinstance(item, Mapping)
            else None
        )
        exact_value = (
            _wrapped_decimal(item.get("MNDFOPKBHKP"))
            if isinstance(item, Mapping)
            else None
        )
        if (
            not isinstance(item, Mapping)
            or set(item) != {"FODBMMCKAEN", "MNDFOPKBHKP"}
            or not isinstance(property_type, str)
            or not property_type
            or exact_value is None
        ):
            issues.append(
                _issue(
                    "relic_threshold_static_property_invalid",
                    PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                    f"$[{source_index}].PropertyList[{property_index}]",
                    f"{set_id}:{require_count}:{property_index}",
                    publication_status,
                    "static property must have typed property and exact value",
                )
            )
            continue
        result.append(
            RelicSetStaticPropertyIR(
                property_index=property_index,
                property_type=property_type,
                exact_value=exact_value,
                source=_source(
                    "relic_set_skill_config",
                    source_index,
                    "RelicSetSkillStaticProperty",
                    f"{set_id}:{require_count}:{property_index}",
                    source_args,
                    suffix=(
                        f".PropertyList[{property_index}].MNDFOPKBHKP.Value"
                    ),
                ),
            )
        )
    return tuple(result)


def _threshold_parameters(
    value: object,
    set_id: str,
    require_count: int,
    source_index: int,
    publication_status: RelicPublicationStatus,
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[RelicSetParameterIR, ...]:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "relic_threshold_parameter_list_invalid",
                PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                f"$[{source_index}].AbilityParamList",
                f"{set_id}:{require_count}",
                publication_status,
                "AbilityParamList must be an array",
            )
        )
        return ()
    result: list[RelicSetParameterIR] = []
    for parameter_index, item in enumerate(value):
        exact_value = _wrapped_decimal(item)
        if (
            not isinstance(item, Mapping)
            or set(item) != {"Value"}
            or exact_value is None
        ):
            issues.append(
                _issue(
                    "relic_threshold_parameter_invalid",
                    PRIMARY_TABLE_ROLES["relic_set_skill_config"],
                    f"$[{source_index}].AbilityParamList[{parameter_index}]",
                    f"{set_id}:{require_count}:{parameter_index}",
                    publication_status,
                    "threshold parameter must contain one exact Value",
                )
            )
            continue
        result.append(
            RelicSetParameterIR(
                parameter_index=parameter_index,
                exact_value=exact_value,
                source=_source(
                    "relic_set_skill_config",
                    source_index,
                    "RelicSetSkillParameter",
                    f"{set_id}:{require_count}:{parameter_index}",
                    source_args,
                    suffix=f".AbilityParamList[{parameter_index}].Value",
                ),
            )
        )
    return tuple(result)


def _build_sets(
    set_records: Mapping[str, tuple[Mapping[str, object], int]],
    set_publication: Mapping[str, tuple[RelicPublicationStatus, bool]],
    memberships: Mapping[str, Mapping[str, set[str]]],
    set_domains: Mapping[str, str],
    templates_by_set: Mapping[str, Sequence[RelicTemplateDefinitionIR]],
    thresholds_by_set: Mapping[str, Sequence[RelicSetThresholdIR]],
    issues: list[RelicCatalogIssue],
    source_args: Mapping[str, object],
) -> tuple[RelicSetDefinitionIR, ...]:
    definitions: list[RelicSetDefinitionIR] = []
    for set_id, (row, source_index) in sorted(set_records.items()):
        publication_status, release_present = set_publication[set_id]
        templates = tuple(templates_by_set.get(set_id, ()))
        thresholds = tuple(thresholds_by_set.get(set_id, ()))
        slots = sorted(memberships.get(set_id, {}).get("slots", set()))
        domain = set_domains.get(set_id)
        declared_thresholds = _int_sequence(row.get("SetSkillList"))
        actual_thresholds = tuple(
            sorted(item.require_count for item in thresholds)
        )
        local_reasons: list[str] = []
        if domain is None:
            local_reasons.append("relic_set_domain_unresolved")
        if not templates or not slots:
            local_reasons.append("relic_set_membership_empty")
        if declared_thresholds is None or tuple(sorted(declared_thresholds)) != actual_thresholds:
            local_reasons.append("relic_set_threshold_reference_mismatch")
            issues.append(
                _issue(
                    "relic_set_threshold_reference_mismatch",
                    PRIMARY_TABLE_ROLES["relic_set_config"],
                    f"$[{source_index}].SetSkillList",
                    set_id,
                    publication_status,
                    "SetSkillList must equal lowered RequireNum rows",
                    tuple(map(str, actual_thresholds)),
                )
            )
        if (
            domain is None
            or not templates
            or not slots
            or not thresholds
        ):
            continue
        blocked_reason = ";".join(sorted(set(local_reasons)))
        definitions.append(
            RelicSetDefinitionIR(
                definition_key=EquipmentDefinitionKey("relic_set", set_id),
                raw_set_id=set_id,
                publication_status=publication_status,
                release_field_present=release_present,
                domain_key=EquipmentDefinitionKey("relic_domain", domain),
                slot_keys=tuple(
                    EquipmentDefinitionKey("relic_slot", slot)
                    for slot in slots
                ),
                template_keys=tuple(
                    sorted(
                        (item.definition_key for item in templates),
                        key=lambda key: key.stable_id,
                    )
                ),
                threshold_keys=tuple(
                    sorted(
                        (item.definition_key for item in thresholds),
                        key=lambda key: key.stable_id,
                    )
                ),
                source=_source(
                    "relic_set_config",
                    source_index,
                    "RelicSetConfig",
                    set_id,
                    source_args,
                ),
                coverage_status="blocked" if blocked_reason else "lowered",
                blocked_reason=blocked_reason,
            )
        )
    return tuple(
        sorted(definitions, key=lambda item: item.definition_key.stable_id)
    )


def _publication_status(
    row: Mapping[str, object],
    source_index: int,
    issues: list[RelicCatalogIssue],
) -> tuple[RelicPublicationStatus, bool]:
    if "Release" not in row:
        return "status_unknown", False
    release = row.get("Release")
    if not isinstance(release, bool):
        issues.append(
            _issue(
                "relic_set_release_invalid",
                PRIMARY_TABLE_ROLES["relic_set_config"],
                f"$[{source_index}].Release",
                str(row.get("SetID") or source_index),
                "status_unknown",
                "Release must be boolean when present",
            )
        )
        return "status_unknown", True
    return ("published" if release else "unpublished"), True


def _catalog_definition_fingerprint(
    catalog: RelicCanonicalCatalog,
    slot_filters: Sequence[RelicSlotFilterIR],
) -> dict[str, JSONValue]:
    payload = {
        "schema_version": RELIC_CATALOG_SCHEMA_VERSION,
        "catalog": catalog.to_json(),
        "slot_filters": [item.to_json() for item in slot_filters],
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": RELIC_CATALOG_SCHEMA_VERSION,
        "algorithm": RELIC_CATALOG_FINGERPRINT_ALGORITHM,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "definition_count": sum(
            len(value)
            for value in (
                catalog.domain_definitions,
                catalog.slot_definitions,
                catalog.main_affix_group_definitions,
                catalog.main_affix_definitions,
                catalog.sub_affix_group_definitions,
                catalog.sub_affix_definitions,
                catalog.template_definitions,
                catalog.set_definitions,
                catalog.set_thresholds,
            )
        ),
        "slot_filter_count": len(slot_filters),
    }


def _source(
    role: str,
    source_index: int,
    raw_type: str,
    raw_id: str,
    source_args: Mapping[str, object],
    *,
    suffix: str = "",
):
    fingerprint = source_args.get("source_fingerprint")
    source_kind = source_args.get("source_kind", "validation_fixture")
    if not isinstance(fingerprint, Mapping):
        raise TypeError("relic source fingerprint is required")
    return make_equipment_source(
        source_path=PRIMARY_TABLE_ROLES[role],
        raw_type=raw_type,
        raw_id=raw_id,
        json_path=f"$[{source_index}]{suffix}",
        source_fingerprint=cast(Mapping[str, JSONValue], fingerprint),
        source_kind=cast(Any, source_kind),
    )


def _derived_source(
    role: str,
    raw_type: str,
    raw_id: str,
    source_args: Mapping[str, object],
):
    fingerprint = source_args.get("source_fingerprint")
    if not isinstance(fingerprint, Mapping):
        raise TypeError("relic source fingerprint is required")
    return make_equipment_source(
        source_path=PRIMARY_TABLE_ROLES[role],
        raw_type=raw_type,
        raw_id=raw_id,
        json_path="$",
        source_fingerprint=cast(Mapping[str, JSONValue], fingerprint),
        source_kind="derived",
    )


def _identity(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _strict_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text_sequence(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        return None
    result = tuple(value)
    return result if len(result) == len(set(result)) else None


def _int_sequence(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0
        for item in value
    ):
        return None
    result = tuple(value)
    return result if len(result) == len(set(result)) else None


def _wrapped_decimal(value: object) -> str | None:
    if not isinstance(value, Mapping) or set(value) != {"Value"}:
        return None
    try:
        return raw_exact_decimal_text(value.get("Value"))
    except (TypeError, ValueError):
        return None


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


def _issue(
    issue_code: str,
    source_path: str,
    json_path: str,
    raw_identity: str,
    publication_status: RelicPublicationStatus,
    detail: str,
    candidates: tuple[str, ...] = (),
) -> RelicCatalogIssue:
    return RelicCatalogIssue(
        issue_code=issue_code,
        source_path=source_path,
        json_path=json_path,
        raw_identity=raw_identity,
        publication_status=publication_status,
        detail=detail,
        candidates=candidates,
    )
