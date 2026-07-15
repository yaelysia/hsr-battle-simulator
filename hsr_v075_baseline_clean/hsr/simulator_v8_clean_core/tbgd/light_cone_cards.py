from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from ..equipment.models import (
    EquipmentDefinitionKey,
    LightConeAbilitySourceIR,
    LightConeDefinitionIR,
    LightConeParameterIR,
    LightConePromotionTierIR,
    LightConePromotionValueIR,
    LightConePublicationStatus,
    LightConeStaticPropertyIR,
    LightConeSuperimpositionLevelIR,
    make_equipment_source,
    raw_exact_decimal_text,
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


LIGHT_CONE_CATALOG_SCHEMA_VERSION = "p8.light_cone_catalog.v1"
LIGHT_CONE_CATALOG_FINGERPRINT_ALGORITHM = (
    "sha256-canonical-light-cone-definition-catalog-v1"
)
LIGHT_CONE_TABLE_ROLES = (
    "equipment_config",
    "equipment_promotion_config",
    "equipment_skill_config",
)
PROMOTION_VALUE_FIELDS: tuple[tuple[str, str], ...] = (
    ("base_hp", "BaseHP"),
    ("hp_per_level", "BaseHPAdd"),
    ("base_attack", "BaseAttack"),
    ("attack_per_level", "BaseAttackAdd"),
    ("base_defence", "BaseDefence"),
    ("defence_per_level", "BaseDefenceAdd"),
)


@dataclass(frozen=True, order=True)
class LightConeCatalogIssue:
    issue_code: str
    source_path: str
    json_path: str
    raw_identity: str
    publication_status: LightConePublicationStatus
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
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"light-cone catalog issue {field_name} is required")
        if self.publication_status not in {
            "published",
            "unpublished",
            "status_unknown",
        }:
            raise ValueError("light-cone catalog issue publication_status is invalid")
        if not isinstance(self.candidates, (list, tuple)):
            raise TypeError("light-cone catalog issue candidates must be a list or tuple")
        candidates = tuple(self.candidates)
        if not all(isinstance(item, str) and item for item in candidates):
            raise TypeError("light-cone catalog issue candidates must be strings")
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


@dataclass(frozen=True)
class LightConeCatalogBuildResult:
    source_content_fingerprint: FrozenJSONDict
    catalog_definition_fingerprint: FrozenJSONDict
    diagnostic_definitions: tuple[LightConeDefinitionIR, ...]
    issues: tuple[LightConeCatalogIssue, ...]
    published_source_count: int
    published_lowered_count: int
    published_blocked_count: int
    catalog_complete: bool
    semantic_table_parse_count: int
    ability_file_parse_count: int
    numeric_values_never_pass_through_float: bool
    production_validation_artifact_read_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_content_fingerprint, FrozenJSONDict):
            raise TypeError("source_content_fingerprint must be recursively frozen")
        if not isinstance(self.catalog_definition_fingerprint, FrozenJSONDict):
            raise TypeError("catalog_definition_fingerprint must be recursively frozen")
        if self.production_validation_artifact_read_count != 0:
            raise ValueError("production light-cone building cannot read validation artifacts")
        if not isinstance(self.diagnostic_definitions, (list, tuple)) or not isinstance(
            self.issues, (list, tuple)
        ):
            raise TypeError("light-cone catalog result collections must be lists or tuples")
        definitions = tuple(self.diagnostic_definitions)
        issues = tuple(self.issues)
        if not all(isinstance(item, LightConeDefinitionIR) for item in definitions):
            raise TypeError("diagnostic_definitions must contain light-cone definitions")
        if not all(isinstance(item, LightConeCatalogIssue) for item in issues):
            raise TypeError("issues must contain LightConeCatalogIssue values")
        object.__setattr__(self, "diagnostic_definitions", definitions)
        object.__setattr__(self, "issues", issues)
        for field_name in (
            "published_source_count",
            "published_lowered_count",
            "published_blocked_count",
            "semantic_table_parse_count",
            "ability_file_parse_count",
            "production_validation_artifact_read_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TypeError(f"{field_name} must be a non-negative integer")
        if not isinstance(self.catalog_complete, bool):
            raise TypeError("catalog_complete must be a boolean")
        if not isinstance(self.numeric_values_never_pass_through_float, bool):
            raise TypeError("numeric_values_never_pass_through_float must be a boolean")
        if self.catalog_complete and (
            self.published_blocked_count != 0
            or self.published_lowered_count != self.published_source_count
        ):
            raise ValueError("complete light-cone catalogs require every published card lowered")

    @property
    def canonical_definitions(self) -> tuple[LightConeDefinitionIR, ...]:
        """Only an atomically complete directory may enter CanonicalIR."""

        return self.diagnostic_definitions if self.catalog_complete else ()

    def to_summary_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": LIGHT_CONE_CATALOG_SCHEMA_VERSION,
            "catalog_complete": self.catalog_complete,
            "source_content_fingerprint": cast(
                dict[str, JSONValue], thaw_json(self.source_content_fingerprint)
            ),
            "catalog_definition_fingerprint": cast(
                dict[str, JSONValue], thaw_json(self.catalog_definition_fingerprint)
            ),
            "published_source_count": self.published_source_count,
            "published_lowered_count": self.published_lowered_count,
            "published_blocked_count": self.published_blocked_count,
            "diagnostic_definition_count": len(self.diagnostic_definitions),
            "canonical_definition_count": len(self.canonical_definitions),
            "issues": [issue.to_json() for issue in self.issues],
            "semantic_table_parse_count": self.semantic_table_parse_count,
            "ability_file_parse_count": self.ability_file_parse_count,
            "numeric_values_never_pass_through_float": (
                self.numeric_values_never_pass_through_float
            ),
            "production_validation_artifact_read_count": (
                self.production_validation_artifact_read_count
            ),
        }


class LightConeCatalogBuildError(ValueError):
    def __init__(self, result: LightConeCatalogBuildResult):
        self.result = result
        codes = sorted({issue.issue_code for issue in result.issues})
        super().__init__(f"light-cone catalog failed closed: {codes}")


@dataclass(frozen=True)
class LightConeCatalogSourceBundle:
    equipment_rows: object
    promotion_rows: object
    skill_rows: object
    ability_documents: tuple[tuple[str, object], ...]
    source_content_fingerprint: dict[str, JSONValue]
    prerequisite_issues: tuple[LightConeCatalogIssue, ...]
    source_integrity_ok: bool


def load_light_cone_catalog_sources(tbgd_root: Path) -> LightConeCatalogSourceBundle:
    """Read primary bytes once and Decimal-parse only S3 semantic sources."""

    root = tbgd_root.resolve()
    discovery = discover_primary_equipment_paths(root)
    table_paths = cast(dict[str, Path], discovery["table_paths"])
    ability_paths = cast(tuple[Path, ...], discovery["ability_paths"])
    loaded: list[tuple[str, bytes]] = []
    missing_paths: list[str] = []
    raw_by_path: dict[str, bytes] = {}
    all_paths = [*table_paths.values(), *ability_paths]
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

    source_content_fingerprint = build_primary_equipment_source_fingerprint(loaded)
    table_documents: dict[str, object] = {}
    parse_issues: list[LightConeCatalogIssue] = []
    for role in LIGHT_CONE_TABLE_ROLES:
        relative_path = PRIMARY_TABLE_ROLES[role]
        raw = raw_by_path.get(relative_path)
        if raw is None:
            continue
        try:
            table_documents[role] = _load_decimal_json(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            parse_issues.append(
                _issue(
                    "light_cone_table_parse_failed",
                    relative_path,
                    "$",
                    role,
                    "status_unknown",
                    str(exc),
                )
            )

    ability_documents: list[tuple[str, object]] = []
    for path in ability_paths:
        relative_path = path.relative_to(root).as_posix()
        raw = raw_by_path.get(relative_path)
        if raw is None:
            continue
        try:
            ability_documents.append((relative_path, _load_decimal_json(raw)))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            parse_issues.append(
                _issue(
                    "light_cone_ability_file_parse_failed",
                    relative_path,
                    "$",
                    path.name,
                    "status_unknown",
                    str(exc),
                )
            )
    for relative_path in sorted(set(missing_paths)):
        parse_issues.append(
            _issue(
                "primary_equipment_source_missing",
                relative_path,
                "$",
                relative_path,
                "status_unknown",
                "required primary equipment source is missing",
            )
        )

    return LightConeCatalogSourceBundle(
        equipment_rows=table_documents.get("equipment_config"),
        promotion_rows=table_documents.get("equipment_promotion_config"),
        skill_rows=table_documents.get("equipment_skill_config"),
        ability_documents=tuple(ability_documents),
        source_content_fingerprint=cast(dict[str, JSONValue], source_content_fingerprint),
        prerequisite_issues=tuple(parse_issues),
        source_integrity_ok=not missing_paths and not parse_issues,
    )


def build_light_cone_catalog(tbgd_root: Path) -> LightConeCatalogBuildResult:
    """Build the full light-cone catalog; generic lowering limits never apply here."""

    sources = load_light_cone_catalog_sources(tbgd_root)
    return build_light_cone_catalog_from_documents(
        equipment_rows=sources.equipment_rows,
        promotion_rows=sources.promotion_rows,
        skill_rows=sources.skill_rows,
        ability_documents=sources.ability_documents,
        source_content_fingerprint=sources.source_content_fingerprint,
        source_kind="tbgd",
        prerequisite_issues=sources.prerequisite_issues,
        source_integrity_ok=sources.source_integrity_ok,
        semantic_table_parse_count=3,
        ability_file_parse_count=len(sources.ability_documents),
    )


def build_light_cone_catalog_from_documents(
    *,
    equipment_rows: object,
    promotion_rows: object,
    skill_rows: object,
    ability_documents: Sequence[tuple[str, object]],
    source_content_fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "validation_fixture"] = "validation_fixture",
    prerequisite_issues: Sequence[LightConeCatalogIssue] = (),
    source_integrity_ok: bool = True,
    semantic_table_parse_count: int = 3,
    ability_file_parse_count: int | None = None,
) -> LightConeCatalogBuildResult:
    """Typed in-memory build chain used by production and raw-snapshot negatives."""

    validate_equipment_source_fingerprint(cast(Mapping[str, object], source_content_fingerprint))
    frozen_source_fingerprint = cast(
        FrozenJSONDict, freeze_json(dict(source_content_fingerprint))
    )
    issues = list(prerequisite_issues)
    equipment = _rows_or_issue(
        equipment_rows,
        PRIMARY_TABLE_ROLES["equipment_config"],
        "equipment_config_root_invalid",
        issues,
    )
    promotions = _rows_or_issue(
        promotion_rows,
        PRIMARY_TABLE_ROLES["equipment_promotion_config"],
        "equipment_promotion_root_invalid",
        issues,
    )
    skills = _rows_or_issue(
        skill_rows,
        PRIMARY_TABLE_ROLES["equipment_skill_config"],
        "equipment_skill_root_invalid",
        issues,
    )

    fingerprint_paths = {
        str(path) for path in cast(Sequence[object], source_content_fingerprint["paths"])
    }
    expected_ability_paths = {
        path
        for path in fingerprint_paths
        if path.startswith(f"{PRIMARY_ABILITY_ROOT}/")
        and path.endswith(".json")
        and not path.endswith(".layout.json")
    }
    ability_path_counts = Counter(path for path, _ in ability_documents)
    for relative_path, count in sorted(ability_path_counts.items()):
        if count != 1:
            issues.append(
                _issue(
                    "equipment_ability_source_path_duplicate",
                    relative_path,
                    "$",
                    relative_path,
                    "status_unknown",
                    f"equipment ability source path occurs {count} times",
                )
            )
        if not _is_equipment_ability_source_path(relative_path):
            issues.append(
                _issue(
                    "equipment_ability_source_path_namespace_invalid",
                    relative_path,
                    "$",
                    relative_path,
                    "status_unknown",
                    "ability source must be a normalized JSON path below Config/ConfigAbility/Equip",
                )
            )
        if relative_path not in fingerprint_paths:
            issues.append(
                _issue(
                    "equipment_ability_source_path_not_fingerprinted",
                    relative_path,
                    "$",
                    relative_path,
                    "status_unknown",
                    "ability source path is not a member of the source content fingerprint",
                )
            )
    observed_ability_paths = set(ability_path_counts)
    if observed_ability_paths != expected_ability_paths:
        issues.append(
            _issue(
                "equipment_ability_source_path_set_incomplete",
                PRIMARY_ABILITY_ROOT,
                "$",
                PRIMARY_ABILITY_ROOT,
                "status_unknown",
                "ability documents must exactly cover fingerprinted equipment ability paths",
                tuple(
                    sorted(
                        {
                            *(f"missing:{path}" for path in expected_ability_paths - observed_ability_paths),
                            *(f"unexpected:{path}" for path in observed_ability_paths - expected_ability_paths),
                        }
                    )
                ),
            )
        )

    ability_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for relative_path, document in ability_documents:
        if not isinstance(document, Mapping):
            issues.append(
                _issue(
                    "equipment_ability_root_invalid",
                    relative_path,
                    "$",
                    relative_path,
                    "status_unknown",
                    "equipment ability root must be an object",
                )
            )
            continue
        ability_list = document.get("AbilityList")
        if not isinstance(ability_list, list):
            issues.append(
                _issue(
                    "equipment_ability_list_missing",
                    relative_path,
                    "$.AbilityList",
                    relative_path,
                    "status_unknown",
                    "equipment ability file must contain an AbilityList array",
                )
            )
            continue
        for record_index, record in enumerate(ability_list):
            if not isinstance(record, Mapping):
                issues.append(
                    _issue(
                        "equipment_ability_record_invalid",
                        relative_path,
                        f"$.AbilityList[{record_index}]",
                        str(record_index),
                        "status_unknown",
                        "ability record must be an object",
                    )
                )
                continue
            name = record.get("Name")
            if not isinstance(name, str) or not name.strip():
                issues.append(
                    _issue(
                        "equipment_ability_identity_missing",
                        relative_path,
                        f"$.AbilityList[{record_index}].Name",
                        str(record_index),
                        "status_unknown",
                        "equipment ability record requires a non-empty Name",
                    )
                )
                continue
            ability_index[name].append((relative_path, record_index))

    promotion_index: dict[int, list[tuple[int, Mapping[str, object]]]] = defaultdict(list)
    for row_index, row in enumerate(promotions):
        equipment_id = _strict_int(row.get("EquipmentID"))
        if equipment_id is None:
            issues.append(
                _issue(
                    "equipment_promotion_identity_invalid",
                    PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                    f"$[{row_index}].EquipmentID",
                    str(row.get("EquipmentID")),
                    "status_unknown",
                    "promotion EquipmentID must be an integer",
                )
            )
            continue
        promotion_index[equipment_id].append((row_index, row))

    skill_index: dict[int, list[tuple[int, Mapping[str, object]]]] = defaultdict(list)
    for row_index, row in enumerate(skills):
        skill_id = _strict_int(row.get("SkillID"))
        if skill_id is None:
            issues.append(
                _issue(
                    "equipment_skill_identity_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].SkillID",
                    str(row.get("SkillID")),
                    "status_unknown",
                    "equipment SkillID must be an integer",
                )
            )
            continue
        skill_index[skill_id].append((row_index, row))

    id_counts = Counter(
        equipment_id
        for row in equipment
        if (equipment_id := _strict_int(row.get("EquipmentID"))) is not None
    )
    definitions: list[LightConeDefinitionIR] = []
    published_source_count = 0
    published_lowered_count = 0
    published_blocked_count = 0
    referenced_promotions: set[int] = set()
    referenced_skills: set[int] = set()

    for row_index, row in enumerate(equipment):
        publication_status, release_field_present = _publication_status(row)
        if publication_status == "published":
            published_source_count += 1
        equipment_id = _strict_int(row.get("EquipmentID"))
        if equipment_id is None:
            issues.append(
                _issue(
                    "equipment_identity_invalid",
                    PRIMARY_TABLE_ROLES["equipment_config"],
                    f"$[{row_index}].EquipmentID",
                    str(row.get("EquipmentID")),
                    publication_status,
                    "EquipmentID must be an integer",
                )
            )
            if publication_status == "published":
                published_blocked_count += 1
            continue
        identity = str(equipment_id)
        card_issue_start = len(issues)
        if id_counts[equipment_id] != 1:
            issues.append(
                _issue(
                    "equipment_duplicate_identity",
                    PRIMARY_TABLE_ROLES["equipment_config"],
                    f"$[{row_index}]",
                    identity,
                    publication_status,
                    "EquipmentID occurs more than once",
                )
            )
        path_type = _required_text_field(
            row, "AvatarBaseType", row_index, identity, publication_status, issues
        )
        rarity = _required_text_field(
            row, "Rarity", row_index, identity, publication_status, issues
        )
        max_promotion = _required_int_field(
            row, "MaxPromotion", row_index, identity, publication_status, issues
        )
        max_rank = _required_int_field(
            row, "MaxRank", row_index, identity, publication_status, issues
        )
        skill_id = _required_int_field(
            row, "SkillID", row_index, identity, publication_status, issues
        )
        equipment_name_hash = _hash_field(
            row,
            "EquipmentName",
            row_index,
            identity,
            publication_status,
            PRIMARY_TABLE_ROLES["equipment_config"],
            issues,
        )
        if max_promotion is not None and max_promotion < 0:
            issues.append(
                _issue(
                    "equipment_max_promotion_invalid",
                    PRIMARY_TABLE_ROLES["equipment_config"],
                    f"$[{row_index}].MaxPromotion",
                    identity,
                    publication_status,
                    "MaxPromotion must be non-negative",
                )
            )
        if max_rank is not None and max_rank <= 0:
            issues.append(
                _issue(
                    "equipment_max_rank_invalid",
                    PRIMARY_TABLE_ROLES["equipment_config"],
                    f"$[{row_index}].MaxRank",
                    identity,
                    publication_status,
                    "MaxRank must be positive",
                )
            )

        promotion_tiers: tuple[LightConePromotionTierIR, ...] = ()
        levels: tuple[LightConeSuperimpositionLevelIR, ...] = ()
        ability_source: LightConeAbilitySourceIR | None = None
        if max_promotion is not None:
            referenced_promotions.add(equipment_id)
            promotion_tiers = _build_promotion_tiers(
                equipment_id,
                max_promotion,
                promotion_index.get(equipment_id, []),
                publication_status,
                source_content_fingerprint,
                source_kind,
                issues,
            )
        if skill_id is not None and max_rank is not None:
            referenced_skills.add(skill_id)
            levels = _build_superimposition_levels(
                skill_id,
                max_rank,
                skill_index.get(skill_id, []),
                publication_status,
                source_content_fingerprint,
                source_kind,
                issues,
            )
            ability_names = {item.ability_name for item in levels}
            if len(ability_names) == 1:
                ability_name = next(iter(ability_names))
                candidates = sorted(ability_index.get(ability_name, []))
                if len(candidates) == 1:
                    ability_path, record_index = candidates[0]
                    ability_source = LightConeAbilitySourceIR(
                        ability_name=ability_name,
                        record_index=record_index,
                        source=make_equipment_source(
                            source_path=ability_path,
                            raw_type="AbilityList",
                            raw_id=ability_name,
                            json_path=f"$.AbilityList[{record_index}]",
                            source_fingerprint=source_content_fingerprint,
                            source_kind=source_kind,
                        ),
                    )
                else:
                    issues.append(
                        _issue(
                            "light_cone_ability_source_not_unique",
                            PRIMARY_ABILITY_ROOT,
                            "$",
                            ability_name,
                            publication_status,
                            "AbilityName must resolve to exactly one ability record",
                            tuple(f"{path}#$.AbilityList[{index}]" for path, index in candidates),
                        )
                    )
            elif levels:
                issues.append(
                    _issue(
                        "light_cone_rank_ability_name_conflict",
                        PRIMARY_TABLE_ROLES["equipment_skill_config"],
                        "$",
                        identity,
                        publication_status,
                        "all ranks of one light cone must use one AbilityName",
                        tuple(sorted(ability_names)),
                    )
                )

        card_has_issue = len(issues) != card_issue_start
        complete_basic_fields = all(
            value is not None
            for value in (
                path_type,
                rarity,
                max_promotion,
                max_rank,
                skill_id,
                equipment_name_hash,
            )
        )
        if complete_basic_fields:
            source = make_equipment_source(
                source_path=PRIMARY_TABLE_ROLES["equipment_config"],
                raw_type="EquipmentConfig",
                raw_id=identity,
                json_path=f"$[{row_index}]",
                source_fingerprint=source_content_fingerprint,
                source_kind=source_kind,
            )
            try:
                definition = LightConeDefinitionIR(
                    definition_key=EquipmentDefinitionKey("light_cone", identity),
                    raw_equipment_id=identity,
                    publication_status=publication_status,
                    release_field_present=release_field_present,
                    equipment_name_hash=cast(str, equipment_name_hash),
                    path_type=cast(str, path_type),
                    rarity=cast(str, rarity),
                    max_promotion=cast(int, max_promotion),
                    max_superimposition=cast(int, max_rank),
                    skill_id=str(cast(int, skill_id)),
                    promotion_tiers=promotion_tiers,
                    superimposition_levels=levels,
                    ability_source=ability_source,
                    mechanism_ref_ids=(),
                    source=source,
                    coverage_status="blocked" if card_has_issue else "lowered",
                    blocked_reason="light_cone_source_closure_failed" if card_has_issue else "",
                )
            except (TypeError, ValueError) as exc:
                issues.append(
                    _issue(
                        "light_cone_definition_invariant_failed",
                        PRIMARY_TABLE_ROLES["equipment_config"],
                        f"$[{row_index}]",
                        identity,
                        publication_status,
                        str(exc),
                    )
                )
            else:
                definitions.append(definition)
                if publication_status == "published":
                    if definition.coverage_status == "lowered":
                        published_lowered_count += 1
                    else:
                        published_blocked_count += 1
        elif publication_status == "published":
            published_blocked_count += 1

    for orphan_equipment_id in sorted(set(promotion_index).difference(referenced_promotions)):
        issues.append(
            _issue(
                "orphan_equipment_promotion_record",
                PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                "$",
                str(orphan_equipment_id),
                "status_unknown",
                "promotion records have no owning equipment definition",
            )
        )
    for orphan_skill_id in sorted(set(skill_index).difference(referenced_skills)):
        issues.append(
            _issue(
                "orphan_equipment_skill_record",
                PRIMARY_TABLE_ROLES["equipment_skill_config"],
                "$",
                str(orphan_skill_id),
                "status_unknown",
                "skill records have no owning equipment definition",
            )
        )

    definitions.sort(key=lambda item: item.definition_key.stable_id)
    ordered_issues = tuple(sorted(set(issues)))
    published_blocked_count = max(
        published_blocked_count,
        published_source_count - published_lowered_count,
    )
    catalog_scope_blocked = any(
        issue.issue_code
        in {
            "equipment_config_root_invalid",
            "equipment_config_root_invalid_row_invalid",
            "equipment_promotion_root_invalid",
            "equipment_promotion_root_invalid_row_invalid",
            "equipment_skill_root_invalid",
            "equipment_skill_root_invalid_row_invalid",
            "equipment_ability_root_invalid",
            "equipment_ability_list_missing",
            "equipment_ability_record_invalid",
            "equipment_ability_identity_missing",
            "equipment_promotion_identity_invalid",
            "equipment_skill_identity_invalid",
            "equipment_ability_source_path_duplicate",
            "equipment_ability_source_path_namespace_invalid",
            "equipment_ability_source_path_not_fingerprinted",
            "equipment_ability_source_path_set_incomplete",
            "orphan_equipment_promotion_record",
            "orphan_equipment_skill_record",
            "primary_equipment_source_missing",
            "light_cone_table_parse_failed",
            "light_cone_ability_file_parse_failed",
        }
        for issue in issues
    )
    catalog_complete = (
        source_integrity_ok
        and not catalog_scope_blocked
        and published_source_count > 0
        and published_lowered_count == published_source_count
        and published_blocked_count == 0
    )
    catalog_fingerprint = _catalog_definition_fingerprint(
        definitions if catalog_complete else (),
        catalog_complete=catalog_complete,
        published_count=published_lowered_count if catalog_complete else 0,
        partial_definition_count=len(definitions),
    )
    return LightConeCatalogBuildResult(
        source_content_fingerprint=frozen_source_fingerprint,
        catalog_definition_fingerprint=cast(
            FrozenJSONDict, freeze_json(catalog_fingerprint)
        ),
        diagnostic_definitions=tuple(definitions),
        issues=ordered_issues,
        published_source_count=published_source_count,
        published_lowered_count=published_lowered_count,
        published_blocked_count=published_blocked_count,
        catalog_complete=catalog_complete,
        semantic_table_parse_count=semantic_table_parse_count,
        ability_file_parse_count=ability_file_parse_count
        if ability_file_parse_count is not None
        else len(ability_documents),
        numeric_values_never_pass_through_float=True,
        production_validation_artifact_read_count=0,
    )


def require_complete_light_cone_catalog(
    result: LightConeCatalogBuildResult,
) -> tuple[LightConeDefinitionIR, ...]:
    if not result.catalog_complete:
        raise LightConeCatalogBuildError(result)
    return result.canonical_definitions


def _load_decimal_json(raw: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")

    return json.loads(
        raw.decode("utf-8"),
        parse_float=Decimal,
        parse_int=int,
        parse_constant=reject_constant,
    )


def _rows_or_issue(
    value: object,
    source_path: str,
    issue_code: str,
    issues: list[LightConeCatalogIssue],
) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        issues.append(
            _issue(
                issue_code,
                source_path,
                "$",
                source_path,
                "status_unknown",
                "light-cone source table root must be an array",
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
                    f"{issue_code}_row_invalid",
                    source_path,
                    f"$[{index}]",
                    str(index),
                    "status_unknown",
                    "source row must be an object",
                )
            )
    return rows


def _build_promotion_tiers(
    equipment_id: int,
    max_promotion: int,
    rows: Sequence[tuple[int, Mapping[str, object]]],
    publication_status: LightConePublicationStatus,
    fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "validation_fixture"],
    issues: list[LightConeCatalogIssue],
) -> tuple[LightConePromotionTierIR, ...]:
    by_stage: dict[int, list[tuple[int, Mapping[str, object], bool]]] = defaultdict(list)
    for row_index, row in rows:
        field_present = "Promotion" in row
        stage = _strict_int(row.get("Promotion")) if field_present else 0
        if stage is None:
            issues.append(
                _issue(
                    "equipment_promotion_stage_invalid",
                    PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                    f"$[{row_index}].Promotion",
                    str(equipment_id),
                    publication_status,
                    "Promotion must be an integer when present",
                )
            )
            continue
        by_stage[stage].append((row_index, row, field_present))
    actual_stages = set(by_stage)
    expected_stages = set(range(max_promotion + 1))
    if actual_stages != expected_stages:
        issues.append(
            _issue(
                "equipment_promotion_stage_set_incomplete",
                PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                "$",
                str(equipment_id),
                publication_status,
                f"expected stages {sorted(expected_stages)}, found {sorted(actual_stages)}",
            )
        )
    tiers: list[LightConePromotionTierIR] = []
    for stage in sorted(actual_stages):
        candidates = by_stage[stage]
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "equipment_promotion_stage_duplicate",
                    PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                    "$",
                    f"{equipment_id}:{stage}",
                    publication_status,
                    "promotion stage must have exactly one row",
                    tuple(str(index) for index, _, _ in candidates),
                )
            )
            continue
        row_index, row, field_present = candidates[0]
        max_level = _strict_int(row.get("MaxLevel"))
        if max_level is None or max_level <= 0:
            issues.append(
                _issue(
                    "equipment_promotion_max_level_invalid",
                    PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                    f"$[{row_index}].MaxLevel",
                    f"{equipment_id}:{stage}",
                    publication_status,
                    "MaxLevel must be a positive integer",
                )
            )
            continue
        values: list[LightConePromotionValueIR] = []
        row_valid = True
        for field_name, raw_field in PROMOTION_VALUE_FIELDS:
            raw_container = row.get(raw_field)
            raw_value = raw_container.get("Value") if isinstance(raw_container, Mapping) else None
            try:
                exact_value = raw_exact_decimal_text(
                    raw_value, f"{raw_field}.Value"
                )
            except (TypeError, ValueError) as exc:
                row_valid = False
                issues.append(
                    _issue(
                        "equipment_promotion_decimal_invalid",
                        PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                        f"$[{row_index}].{raw_field}.Value",
                        f"{equipment_id}:{stage}",
                        publication_status,
                        str(exc),
                    )
                )
                continue
            values.append(
                LightConePromotionValueIR(
                    field_name=field_name,
                    exact_value=exact_value,
                    source=make_equipment_source(
                        source_path=PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                        raw_type="EquipmentPromotionConfigValue",
                        raw_id=f"{equipment_id}:{stage}:{field_name}",
                        json_path=f"$[{row_index}].{raw_field}.Value",
                        source_fingerprint=fingerprint,
                        source_kind=source_kind,
                    ),
                )
            )
        if not row_valid:
            continue
        tiers.append(
            LightConePromotionTierIR(
                promotion_stage=stage,
                promotion_field_present=field_present,
                max_level=max_level,
                stat_values=tuple(values),
                source=make_equipment_source(
                    source_path=PRIMARY_TABLE_ROLES["equipment_promotion_config"],
                    raw_type="EquipmentPromotionConfig",
                    raw_id=f"{equipment_id}:{stage}",
                    json_path=f"$[{row_index}]",
                    source_fingerprint=fingerprint,
                    source_kind=source_kind,
                ),
            )
        )
    return tuple(sorted(tiers, key=lambda item: item.promotion_stage))


def _build_superimposition_levels(
    skill_id: int,
    max_rank: int,
    rows: Sequence[tuple[int, Mapping[str, object]]],
    publication_status: LightConePublicationStatus,
    fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "validation_fixture"],
    issues: list[LightConeCatalogIssue],
) -> tuple[LightConeSuperimpositionLevelIR, ...]:
    by_level: dict[int, list[tuple[int, Mapping[str, object]]]] = defaultdict(list)
    for row_index, row in rows:
        level = _strict_int(row.get("Level"))
        if level is None:
            issues.append(
                _issue(
                    "equipment_skill_level_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].Level",
                    str(skill_id),
                    publication_status,
                    "Level must be an integer",
                )
            )
            continue
        by_level[level].append((row_index, row))
    actual_levels = set(by_level)
    expected_levels = set(range(1, max_rank + 1))
    if actual_levels != expected_levels:
        issues.append(
            _issue(
                "equipment_skill_level_set_incomplete",
                PRIMARY_TABLE_ROLES["equipment_skill_config"],
                "$",
                str(skill_id),
                publication_status,
                f"expected levels {sorted(expected_levels)}, found {sorted(actual_levels)}",
            )
        )
    levels: list[LightConeSuperimpositionLevelIR] = []
    for level in sorted(actual_levels):
        candidates = by_level[level]
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "equipment_skill_level_duplicate",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    "$",
                    f"{skill_id}:{level}",
                    publication_status,
                    "skill level must have exactly one row",
                    tuple(str(index) for index, _ in candidates),
                )
            )
            continue
        row_index, row = candidates[0]
        ability_name = row.get("AbilityName")
        skill_name_hash = _nested_hash(row.get("SkillName"))
        skill_description_hash = _nested_hash(row.get("SkillDesc"))
        if not isinstance(ability_name, str) or not ability_name.strip():
            issues.append(
                _issue(
                    "equipment_skill_ability_name_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].AbilityName",
                    f"{skill_id}:{level}",
                    publication_status,
                    "AbilityName must be a non-empty string",
                )
            )
            continue
        if skill_name_hash is None or skill_description_hash is None:
            issues.append(
                _issue(
                    "equipment_skill_text_hash_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}]",
                    f"{skill_id}:{level}",
                    publication_status,
                    "SkillName and SkillDesc must contain hash identities",
                )
            )
            continue
        parameters = _build_parameters(
            skill_id,
            level,
            row_index,
            row.get("ParamList"),
            publication_status,
            fingerprint,
            source_kind,
            issues,
        )
        properties = _build_static_properties(
            skill_id,
            level,
            row_index,
            row.get("AbilityProperty"),
            publication_status,
            fingerprint,
            source_kind,
            issues,
        )
        if parameters is None or properties is None:
            continue
        levels.append(
            LightConeSuperimpositionLevelIR(
                skill_id=str(skill_id),
                level=level,
                ability_name=ability_name,
                skill_name_hash=skill_name_hash,
                skill_description_hash=skill_description_hash,
                parameters=parameters,
                static_properties=properties,
                source=make_equipment_source(
                    source_path=PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    raw_type="EquipmentSkillConfig",
                    raw_id=f"{skill_id}:{level}",
                    json_path=f"$[{row_index}]",
                    source_fingerprint=fingerprint,
                    source_kind=source_kind,
                ),
            )
        )
    return tuple(sorted(levels, key=lambda item: item.level))


def _build_parameters(
    skill_id: int,
    level: int,
    row_index: int,
    value: object,
    publication_status: LightConePublicationStatus,
    fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "validation_fixture"],
    issues: list[LightConeCatalogIssue],
) -> tuple[LightConeParameterIR, ...] | None:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "equipment_skill_parameter_list_invalid",
                PRIMARY_TABLE_ROLES["equipment_skill_config"],
                f"$[{row_index}].ParamList",
                f"{skill_id}:{level}",
                publication_status,
                "ParamList must be an array",
            )
        )
        return None
    result: list[LightConeParameterIR] = []
    valid = True
    for index, item in enumerate(value):
        raw_value = item.get("Value") if isinstance(item, Mapping) else None
        try:
            exact_value = raw_exact_decimal_text(raw_value, "light-cone parameter")
        except (TypeError, ValueError) as exc:
            valid = False
            issues.append(
                _issue(
                    "equipment_skill_parameter_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].ParamList[{index}].Value",
                    f"{skill_id}:{level}:{index}",
                    publication_status,
                    str(exc),
                )
            )
            continue
        result.append(
            LightConeParameterIR(
                parameter_index=index,
                exact_value=exact_value,
                source=make_equipment_source(
                    source_path=PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    raw_type="EquipmentSkillParameter",
                    raw_id=f"{skill_id}:{level}:{index}",
                    json_path=f"$[{row_index}].ParamList[{index}].Value",
                    source_fingerprint=fingerprint,
                    source_kind=source_kind,
                ),
            )
        )
    return tuple(result) if valid else None


def _build_static_properties(
    skill_id: int,
    level: int,
    row_index: int,
    value: object,
    publication_status: LightConePublicationStatus,
    fingerprint: Mapping[str, JSONValue],
    source_kind: Literal["tbgd", "validation_fixture"],
    issues: list[LightConeCatalogIssue],
) -> tuple[LightConeStaticPropertyIR, ...] | None:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "equipment_skill_property_list_invalid",
                PRIMARY_TABLE_ROLES["equipment_skill_config"],
                f"$[{row_index}].AbilityProperty",
                f"{skill_id}:{level}",
                publication_status,
                "AbilityProperty must be an array",
            )
        )
        return None
    result: list[LightConeStaticPropertyIR] = []
    valid = True
    for index, item in enumerate(value):
        property_type = item.get("PropertyType") if isinstance(item, Mapping) else None
        raw_container = item.get("Value") if isinstance(item, Mapping) else None
        raw_value = raw_container.get("Value") if isinstance(raw_container, Mapping) else None
        if not isinstance(property_type, str) or not property_type.strip():
            valid = False
            issues.append(
                _issue(
                    "equipment_skill_property_type_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].AbilityProperty[{index}].PropertyType",
                    f"{skill_id}:{level}:{index}",
                    publication_status,
                    "PropertyType must be a non-empty string",
                )
            )
            continue
        try:
            exact_value = raw_exact_decimal_text(raw_value, "light-cone static property")
        except (TypeError, ValueError) as exc:
            valid = False
            issues.append(
                _issue(
                    "equipment_skill_property_value_invalid",
                    PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    f"$[{row_index}].AbilityProperty[{index}].Value.Value",
                    f"{skill_id}:{level}:{index}",
                    publication_status,
                    str(exc),
                )
            )
            continue
        result.append(
            LightConeStaticPropertyIR(
                property_index=index,
                property_type=property_type,
                exact_value=exact_value,
                source=make_equipment_source(
                    source_path=PRIMARY_TABLE_ROLES["equipment_skill_config"],
                    raw_type="EquipmentSkillStaticProperty",
                    raw_id=f"{skill_id}:{level}:{index}",
                    json_path=f"$[{row_index}].AbilityProperty[{index}].Value.Value",
                    source_fingerprint=fingerprint,
                    source_kind=source_kind,
                ),
            )
        )
    return tuple(result) if valid else None


def _catalog_definition_fingerprint(
    definitions: Sequence[LightConeDefinitionIR],
    *,
    catalog_complete: bool,
    published_count: int,
    partial_definition_count: int,
) -> dict[str, JSONValue]:
    payload = [
        _catalog_semantic_value(definition.to_json())
        for definition in sorted(
            definitions, key=lambda item: item.definition_key.stable_id
        )
    ]
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "algorithm": LIGHT_CONE_CATALOG_FINGERPRINT_ALGORITHM,
        "sha256": hashlib.sha256(raw).hexdigest() if catalog_complete else "",
        "catalog_complete": catalog_complete,
        "definition_count": len(definitions) if catalog_complete else 0,
        "published_definition_count": published_count,
        "partial_diagnostic_definition_count": partial_definition_count,
        "normalization": "stable_definition_order_and_audit_evidence_excluded",
    }


def _catalog_semantic_value(value: object) -> JSONValue:
    if isinstance(value, Mapping):
        if {"source_path", "raw_type", "raw_id", "evidence"}.issubset(value):
            return {
                "source_path": str(value["source_path"]),
                "raw_type": str(value["raw_type"]),
                "raw_id": str(value["raw_id"]),
            }
        return {
            str(key): _catalog_semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key != "record_index"
        }
    if isinstance(value, (list, tuple)):
        return [_catalog_semantic_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported catalog fingerprint value: {type(value).__name__}")


def _publication_status(
    row: Mapping[str, object],
) -> tuple[LightConePublicationStatus, bool]:
    if "Release" not in row:
        return "status_unknown", False
    if row.get("Release") is True:
        return "published", True
    if row.get("Release") is False:
        return "unpublished", True
    return "status_unknown", True


def _required_text_field(
    row: Mapping[str, object],
    field: str,
    row_index: int,
    identity: str,
    publication_status: LightConePublicationStatus,
    issues: list[LightConeCatalogIssue],
) -> str | None:
    value = row.get(field)
    if isinstance(value, str) and value.strip():
        return value
    issues.append(
        _issue(
            f"equipment_{field.lower()}_invalid",
            PRIMARY_TABLE_ROLES["equipment_config"],
            f"$[{row_index}].{field}",
            identity,
            publication_status,
            f"{field} must be a non-empty string",
        )
    )
    return None


def _required_int_field(
    row: Mapping[str, object],
    field: str,
    row_index: int,
    identity: str,
    publication_status: LightConePublicationStatus,
    issues: list[LightConeCatalogIssue],
) -> int | None:
    value = _strict_int(row.get(field))
    if value is not None:
        return value
    issues.append(
        _issue(
            f"equipment_{field.lower()}_invalid",
            PRIMARY_TABLE_ROLES["equipment_config"],
            f"$[{row_index}].{field}",
            identity,
            publication_status,
            f"{field} must be an integer",
        )
    )
    return None


def _hash_field(
    row: Mapping[str, object],
    field: str,
    row_index: int,
    identity: str,
    publication_status: LightConePublicationStatus,
    source_path: str,
    issues: list[LightConeCatalogIssue],
) -> str | None:
    value = _nested_hash(row.get(field))
    if value is not None:
        return value
    issues.append(
        _issue(
            f"equipment_{field.lower()}_hash_invalid",
            source_path,
            f"$[{row_index}].{field}.Hash",
            identity,
            publication_status,
            f"{field} must contain a hash identity",
        )
    )
    return None


def _nested_hash(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    hash_value = value.get("Hash")
    if isinstance(hash_value, bool) or not isinstance(hash_value, (int, str)):
        return None
    text = str(hash_value)
    return text if text else None


def _strict_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_equipment_ability_source_path(relative_path: object) -> bool:
    if not isinstance(relative_path, str) or not relative_path:
        return False
    path = PurePosixPath(relative_path)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and relative_path == path.as_posix()
        and relative_path.startswith(f"{PRIMARY_ABILITY_ROOT}/")
        and path.suffix == ".json"
        and not path.name.endswith(".layout.json")
    )


def _issue(
    issue_code: str,
    source_path: str,
    json_path: str,
    raw_identity: str,
    publication_status: LightConePublicationStatus,
    detail: str,
    candidates: tuple[str, ...] = (),
) -> LightConeCatalogIssue:
    return LightConeCatalogIssue(
        issue_code=issue_code,
        source_path=source_path,
        json_path=json_path,
        raw_identity=raw_identity,
        publication_status=publication_status,
        detail=detail,
        candidates=candidates,
    )
