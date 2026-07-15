from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EQUIPMENT_DISCOVERY_SCHEMA_VERSION = "p8.equipment_source_discovery.v1"
PRIMARY_FINGERPRINT_ALGORITHM = "sha256-path-and-full-content-v1"
FULL_AUXILIARY_FINGERPRINT_ALGORITHM = "sha256-path-and-file-sha256-v1"
SAMPLED_AUXILIARY_FINGERPRINT_ALGORITHM = "sha256-path-size-range-and-sample-v1"

PRIMARY_TABLE_ROLES: dict[str, str] = {
    "equipment_config": "ExcelOutput/EquipmentConfig.json",
    "equipment_promotion_config": "ExcelOutput/EquipmentPromotionConfig.json",
    "equipment_skill_config": "ExcelOutput/EquipmentSkillConfig.json",
    "relic_config": "ExcelOutput/RelicConfig.json",
    "relic_base_type": "ExcelOutput/RelicBaseType.json",
    "relic_main_affix_config": "ExcelOutput/RelicMainAffixConfig.json",
    "relic_sub_affix_config": "ExcelOutput/RelicSubAffixConfig.json",
    "relic_set_config": "ExcelOutput/RelicSetConfig.json",
    "relic_set_skill_config": "ExcelOutput/RelicSetSkillConfig.json",
}
PRIMARY_ABILITY_ROOT = "Config/ConfigAbility/Equip"

PUBLICATION_STATES = {"published", "unpublished", "status_unknown"}
MECHANISM_CLASSIFICATIONS = {"gameplay", "non_gameplay", "unknown"}

MAX_FULL_AUXILIARY_BYTES = 1024 * 1024
MAX_AUXILIARY_SAMPLE_BYTES = 64 * 1024
MAX_SOURCE_SAMPLES = 5


@dataclass(frozen=True)
class EquipmentSourceDocument:
    role: str
    relative_path: str
    byte_count: int
    sha256: str
    data: Any

    @property
    def root_type(self) -> str:
        if isinstance(self.data, list):
            return "list"
        if isinstance(self.data, dict):
            return "object"
        return type(self.data).__name__

    @property
    def record_count(self) -> int:
        if isinstance(self.data, (list, dict)):
            return len(self.data)
        return 1 if self.data is not None else 0

    def inventory_json(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "relative_path": self.relative_path,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "root_type": self.root_type,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class EquipmentSourceSnapshot:
    tbgd_root: Path
    table_documents: dict[str, EquipmentSourceDocument]
    ability_documents: tuple[EquipmentSourceDocument, ...]
    missing_required_paths: tuple[str, ...]
    parse_errors: tuple[dict[str, str], ...]
    primary_source_fingerprint: dict[str, Any]
    primary_bytes_read: int
    primary_json_parse_count: int

    @property
    def documents(self) -> tuple[EquipmentSourceDocument, ...]:
        return tuple(self.table_documents.values()) + self.ability_documents

    def table(self, role: str) -> Any:
        document = self.table_documents.get(role)
        return document.data if document is not None else []


@dataclass(frozen=True)
class AuxiliaryPolicy:
    source_role: str
    classification: str
    rationale: str


DISPLAY_AUXILIARY = AuxiliaryPolicy(
    "display_source",
    "non_gameplay",
    "table is registered as item/atlas display metadata and contains no structured combat-graph marker",
)
RECOMMENDATION_AUXILIARY = AuxiliaryPolicy(
    "recommendation_or_score_source",
    "non_gameplay",
    "table is registered as recommendation/score metadata and contains no structured combat-graph marker",
)
PROGRESSION_AUXILIARY = AuxiliaryPolicy(
    "progression_economy_or_reward_source",
    "non_gameplay",
    "table is registered as progression/economy/reward metadata and contains no structured combat-graph marker",
)
SPECIAL_MODE_AUXILIARY = AuxiliaryPolicy(
    "special_mode_or_tooling_candidate",
    "unknown",
    "table may belong to a special mode, account tool, or alternate upgrade flow and is retained for later confirmation",
)
SPECIAL_RELIC_AUXILIARY = AuxiliaryPolicy(
    "special_relic_candidate",
    "unknown",
    "SpecialAvatarRelic data is retained as a separate candidate and is not assumed to be normal relic gameplay or non-gameplay",
)


AUXILIARY_TABLE_POLICIES: dict[str, AuxiliaryPolicy] = {
    "ActivityEquipMaterialQuest.json": PROGRESSION_AUXILIARY,
    "ActivityEquipmentReward.json": PROGRESSION_AUXILIARY,
    "ActivityRelicBoxClientConst.json": PROGRESSION_AUXILIARY,
    "ActivityRelicBoxCommonConst.json": PROGRESSION_AUXILIARY,
    "ActivityRelicBoxQuestConfig.json": PROGRESSION_AUXILIARY,
    "ActivityRelicBoxQuestTab.json": PROGRESSION_AUXILIARY,
    "AvatarRelicRecommend.json": RECOMMENDATION_AUXILIARY,
    "AvatarRelicRecommendLD.json": RECOMMENDATION_AUXILIARY,
    "AvatarEquipRecommend.json": RECOMMENDATION_AUXILIARY,
    "AvatarEquipRecommendLD.json": RECOMMENDATION_AUXILIARY,
    "EquipmentAtlas.json": DISPLAY_AUXILIARY,
    "EquipmentExpItemConfig.json": PROGRESSION_AUXILIARY,
    "EquipmentExpType.json": PROGRESSION_AUXILIARY,
    "GMAccountEquipmentConfig.json": SPECIAL_MODE_AUXILIARY,
    "GMAccountRelicConfig.json": SPECIAL_MODE_AUXILIARY,
    "GridFightBackEquipment.json": SPECIAL_MODE_AUXILIARY,
    "GridFightElationEquip.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipCategoryInfo.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipMazebuff.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipRecommendRole.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipTag.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipUpgrade.json": SPECIAL_MODE_AUXILIARY,
    "GridFightEquipment.json": SPECIAL_MODE_AUXILIARY,
    "GridFightRoleRecommendEquip.json": SPECIAL_MODE_AUXILIARY,
    "GridFightTraitEquipRelation.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveEquip.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveEquipDiscard.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveEquipProperty.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveEquipRarity.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveEquipSlot.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveQuestEquip.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveQuestionSpEquip.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveSpEquip.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveSpEquipSkill.json": SPECIAL_MODE_AUXILIARY,
    "IdleLiveSpEquipSlot.json": SPECIAL_MODE_AUXILIARY,
    "ItemConfigEquipment.json": DISPLAY_AUXILIARY,
    "ItemConfigRelic.json": DISPLAY_AUXILIARY,
    "PlayerReturnRelic.json": PROGRESSION_AUXILIARY,
    "PixAirEquipConfig.json": SPECIAL_MODE_AUXILIARY,
    "PixAirEquipEnchantConfig.json": SPECIAL_MODE_AUXILIARY,
    "PixAirEquipLevelConfig.json": SPECIAL_MODE_AUXILIARY,
    "PixAirEquipPriceConfig.json": SPECIAL_MODE_AUXILIARY,
    "RelicComposeConfig.json": PROGRESSION_AUXILIARY,
    "RelicDataInfo.json": SPECIAL_MODE_AUXILIARY,
    "RelicExpItem.json": PROGRESSION_AUXILIARY,
    "RelicExpType.json": PROGRESSION_AUXILIARY,
    "RelicMainAffixAvatarValue.json": RECOMMENDATION_AUXILIARY,
    "RelicMainAffixBaseValue.json": RECOMMENDATION_AUXILIARY,
    "RelicSetBonusValue.json": RECOMMENDATION_AUXILIARY,
    "RelicSubAffixAvatarValue.json": RECOMMENDATION_AUXILIARY,
    "RelicSubAffixBaseValue.json": RECOMMENDATION_AUXILIARY,
    "RogueUpgradeAvatarEquipment.json": SPECIAL_MODE_AUXILIARY,
    "RogueUpgradeAvatarSubRelic.json": SPECIAL_MODE_AUXILIARY,
    "SpecialAvatarRelic.json": SPECIAL_RELIC_AUXILIARY,
    "SpecialAvatarRelicMainValue.json": SPECIAL_RELIC_AUXILIARY,
    "SpecialAvatarRelicSubValue.json": SPECIAL_RELIC_AUXILIARY,
    "UpgradeAvatarEquipment.json": SPECIAL_MODE_AUXILIARY,
    "UpgradeAvatarSubRelic.json": SPECIAL_MODE_AUXILIARY,
}


EXTERNAL_SEMANTIC_REFERENCES: tuple[dict[str, Any], ...] = (
    {
        "topic": "light_cone_identity_growth_and_superimposition",
        "url": "https://honkai-star-rail.fandom.com/wiki/Light_Cone",
    },
    {
        "topic": "off_path_light_cone_equipping_semantics",
        "url": "https://www.prydwen.gg/star-rail/guides/light-cones",
    },
    {
        "topic": "relic_affix_and_upgrade_semantics",
        "url": "https://honkai-star-rail.fandom.com/wiki/Relic/Stats",
    },
    {
        "topic": "relic_slot_and_set_semantics",
        "url": "https://www.prydwen.gg/star-rail/guides/relics",
    },
    {
        "topic": "panel_assembly_cross_check",
        "url": "https://www.hoyolab.com/article/25247883",
    },
    {
        "topic": "seele_example_build_cross_check",
        "url": "https://hsr.keqingmains.com/seele/",
    },
    {
        "topic": "seele_example_build_cross_check",
        "url": "https://game8.co/games/Honkai-Star-Rail/archives/405758",
    },
    {
        "topic": "seele_example_build_cross_check",
        "url": "https://www.prydwen.gg/star-rail/characters/seele",
    },
)


def discover_primary_equipment_paths(tbgd_root: Path) -> dict[str, Any]:
    root = tbgd_root.resolve()
    table_paths = {
        role: root / relative_path
        for role, relative_path in PRIMARY_TABLE_ROLES.items()
    }
    ability_root = root / PRIMARY_ABILITY_ROOT
    ability_paths = tuple(
        sorted(
            (
                path
                for path in ability_root.rglob("*.json")
                if not path.name.endswith(".layout.json")
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    ) if ability_root.exists() else ()
    return {
        "table_paths": table_paths,
        "ability_root": ability_root,
        "ability_paths": ability_paths,
    }


def load_equipment_source_snapshot(tbgd_root: Path) -> EquipmentSourceSnapshot:
    root = tbgd_root.resolve()
    discovery = discover_primary_equipment_paths(root)
    missing_required_paths: list[str] = []
    parse_errors: list[dict[str, str]] = []
    table_documents: dict[str, EquipmentSourceDocument] = {}
    ability_documents: list[EquipmentSourceDocument] = []
    loaded: list[tuple[str, bytes]] = []

    for role, path in discovery["table_paths"].items():
        relative_path = path.relative_to(root).as_posix()
        if not path.is_file():
            missing_required_paths.append(relative_path)
            continue
        document, raw, error = _load_full_document(root, path, role)
        if error:
            parse_errors.append(error)
            continue
        assert document is not None and raw is not None
        table_documents[role] = document
        loaded.append((relative_path, raw))

    ability_root = discovery["ability_root"]
    if not ability_root.is_dir():
        missing_required_paths.append(PRIMARY_ABILITY_ROOT)
    elif not discovery["ability_paths"]:
        missing_required_paths.append(f"{PRIMARY_ABILITY_ROOT}/*.json")
    for path in discovery["ability_paths"]:
        relative_path = path.relative_to(root).as_posix()
        document, raw, error = _load_full_document(root, path, "equipment_ability_file")
        if error:
            parse_errors.append(error)
            continue
        assert document is not None and raw is not None
        ability_documents.append(document)
        loaded.append((relative_path, raw))

    fingerprint = build_primary_equipment_source_fingerprint(loaded)
    return EquipmentSourceSnapshot(
        tbgd_root=root,
        table_documents=table_documents,
        ability_documents=tuple(ability_documents),
        missing_required_paths=tuple(sorted(missing_required_paths)),
        parse_errors=tuple(parse_errors),
        primary_source_fingerprint=fingerprint,
        primary_bytes_read=int(fingerprint["byte_count"]),
        primary_json_parse_count=len(loaded),
    )


def build_primary_equipment_source_fingerprint(
    loaded_sources: Iterable[tuple[str, bytes]],
) -> dict[str, Any]:
    """Fingerprint raw primary bytes; callers may use different semantic parsers."""

    loaded = sorted(tuple(loaded_sources), key=lambda item: item[0])
    fingerprint_digest = hashlib.sha256()
    fingerprint_paths: list[str] = []
    fingerprint_bytes = 0
    for relative_path, raw in loaded:
        fingerprint_digest.update(relative_path.encode("utf-8"))
        fingerprint_digest.update(b"\0")
        fingerprint_digest.update(raw)
        fingerprint_digest.update(b"\0")
        fingerprint_paths.append(relative_path)
        fingerprint_bytes += len(raw)

    return {
        "schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "algorithm": PRIMARY_FINGERPRINT_ALGORITHM,
        "sha256": fingerprint_digest.hexdigest(),
        "file_count": len(fingerprint_paths),
        "byte_count": fingerprint_bytes,
        "paths": fingerprint_paths,
        "coverage": "full_content_for_every_primary_source_file",
    }


def discover_equipment_candidate_paths(tbgd_root: Path) -> tuple[Path, ...]:
    root = tbgd_root.resolve()
    candidates: set[Path] = set()
    excel_root = root / "ExcelOutput"
    if excel_root.is_dir():
        for path in excel_root.glob("*.json"):
            lowered = path.name.lower()
            if "equip" in lowered or "relic" in lowered:
                candidates.add(path.resolve())

    ability_root = root / "Config/ConfigAbility"
    primary_ability_root = root / PRIMARY_ABILITY_ROOT
    if primary_ability_root.is_dir():
        candidates.update(path.resolve() for path in primary_ability_root.rglob("*.json"))
    if ability_root.is_dir():
        for path in ability_root.rglob("*.json"):
            lowered = path.name.lower()
            if "equip" in lowered or "relic" in lowered:
                candidates.add(path.resolve())
    return tuple(sorted(candidates, key=lambda path: path.relative_to(root).as_posix()))


def classify_equipment_candidate_sources(
    snapshot: EquipmentSourceSnapshot,
    *,
    max_full_auxiliary_bytes: int = MAX_FULL_AUXILIARY_BYTES,
    max_sample_bytes: int = MAX_AUXILIARY_SAMPLE_BYTES,
) -> dict[str, Any]:
    root = snapshot.tbgd_root
    candidates = discover_equipment_candidate_paths(root)
    primary_by_path = {document.relative_path: document for document in snapshot.documents}
    primary_ability_names = _ability_name_index(snapshot)
    rows: list[dict[str, Any]] = []
    full_auxiliary_items: list[dict[str, Any]] = []
    sampled_auxiliary_items: list[dict[str, Any]] = []
    full_auxiliary_bytes_read = 0
    full_auxiliary_json_parse_count = 0
    sampled_auxiliary_bytes_read = 0

    for path in candidates:
        relative_path = path.relative_to(root).as_posix()
        primary_document = primary_by_path.get(relative_path)
        if primary_document is not None:
            rows.append(
                {
                    "relative_path": relative_path,
                    "source_role": primary_document.role,
                    "classification": "gameplay",
                    "classification_status": "classified_full_content",
                    "classification_basis": "P8 primary source role and full JSON document",
                    "fingerprint_scope": "primary_full_content",
                    "sha256": primary_document.sha256,
                    "byte_count": primary_document.byte_count,
                    "root_type": primary_document.root_type,
                    "record_count": primary_document.record_count,
                    "sample_scope": None,
                }
            )
            continue

        if path.name.endswith(".layout.json"):
            row, raw = _classify_full_auxiliary(
                root,
                path,
                policy=AuxiliaryPolicy(
                    "layout_metadata",
                    "non_gameplay",
                    "layout suffix is an explicit structural marker for editor layout metadata",
                ),
            )
            rows.append(row)
            if raw is not None:
                full_auxiliary_items.append(_full_auxiliary_fingerprint_item(row, raw))
                full_auxiliary_bytes_read += len(raw)
                full_auxiliary_json_parse_count += 1
            continue

        if _is_root_legacy_ability_mirror(relative_path):
            row, raw = _classify_legacy_ability_mirror(root, path, primary_ability_names)
            rows.append(row)
            if raw is not None:
                full_auxiliary_items.append(_full_auxiliary_fingerprint_item(row, raw))
                full_auxiliary_bytes_read += len(raw)
                full_auxiliary_json_parse_count += 1
            continue

        policy = _auxiliary_policy_for_path(relative_path, path.name)
        if policy is None:
            row, sample = _classify_unregistered_candidate(root, path, max_sample_bytes)
            rows.append(row)
            sampled_auxiliary_items.append(_sampled_auxiliary_fingerprint_item(row, sample))
            sampled_auxiliary_bytes_read += len(sample)
            continue

        if path.stat().st_size > max_full_auxiliary_bytes:
            row, sample = _classify_sampled_pending_candidate(root, path, policy, max_sample_bytes)
            rows.append(row)
            sampled_auxiliary_items.append(_sampled_auxiliary_fingerprint_item(row, sample))
            sampled_auxiliary_bytes_read += len(sample)
            continue

        row, raw = _classify_full_auxiliary(root, path, policy=policy)
        rows.append(row)
        if raw is not None:
            full_auxiliary_items.append(_full_auxiliary_fingerprint_item(row, raw))
            full_auxiliary_bytes_read += len(raw)
            full_auxiliary_json_parse_count += 1

    full_auxiliary_fingerprint = _combined_auxiliary_fingerprint(
        FULL_AUXILIARY_FINGERPRINT_ALGORITHM,
        full_auxiliary_items,
        full_content=True,
    )
    sampled_auxiliary_fingerprint = _combined_auxiliary_fingerprint(
        SAMPLED_AUXILIARY_FINGERPRINT_ALGORITHM,
        sampled_auxiliary_items,
        full_content=False,
    )
    classification_counts = Counter(str(row["classification"]) for row in rows)
    status_counts = Counter(str(row["classification_status"]) for row in rows)
    return {
        "schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "candidate_discovery": {
            "selection": "all ExcelOutput JSON basenames containing equip/relic, all JSON below ConfigAbility/Equip, and equip/relic-named ConfigAbility JSON",
            "candidate_count": len(candidates),
            "candidate_paths": [path.relative_to(root).as_posix() for path in candidates],
            "unregistered_candidate_paths": sorted(
                row["relative_path"]
                for row in rows
                if row["classification_status"] == "unclassified"
            ),
        },
        "classification_counts": dict(sorted(classification_counts.items())),
        "classification_status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
        "full_auxiliary_fingerprint": full_auxiliary_fingerprint,
        "sampled_pending_auxiliary_fingerprint": sampled_auxiliary_fingerprint,
        "external_semantic_references": [
            {
                **row,
                "usage": "semantic_discovery_and_cross_check_only",
                "runtime_source": False,
                "source_trace_eligible": False,
                "fetched_during_p8_s0": False,
            }
            for row in EXTERNAL_SEMANTIC_REFERENCES
        ],
        "resource_budget": {
            "full_auxiliary_bytes_read": full_auxiliary_bytes_read,
            "full_auxiliary_json_parse_count": full_auxiliary_json_parse_count,
            "sampled_auxiliary_bytes_read": sampled_auxiliary_bytes_read,
            "sampled_auxiliary_file_count": len(sampled_auxiliary_items),
            "max_full_auxiliary_bytes_per_file": max_full_auxiliary_bytes,
            "max_sample_bytes_per_file": max_sample_bytes,
            "large_sampled_files_fully_classified": False,
        },
    }


def build_equipment_reference_integrity(snapshot: EquipmentSourceSnapshot) -> dict[str, Any]:
    equipment_rows = _list_rows(snapshot.table("equipment_config"))
    promotion_rows = _list_rows(snapshot.table("equipment_promotion_config"))
    skill_rows = _list_rows(snapshot.table("equipment_skill_config"))
    relic_rows = _list_rows(snapshot.table("relic_config"))
    base_type_rows = _list_rows(snapshot.table("relic_base_type"))
    main_affix_rows = _list_rows(snapshot.table("relic_main_affix_config"))
    sub_affix_rows = _list_rows(snapshot.table("relic_sub_affix_config"))
    set_rows = _list_rows(snapshot.table("relic_set_config"))
    set_skill_rows = _list_rows(snapshot.table("relic_set_skill_config"))

    issues: list[dict[str, Any]] = []
    ability_index = _ability_name_index(snapshot)
    ability_record_count = 0
    for document in snapshot.ability_documents:
        ability_list = document.data.get("AbilityList") if isinstance(document.data, dict) else None
        if not isinstance(ability_list, list):
            continue
        ability_record_count += len(ability_list)
        for row_index, row in enumerate(ability_list):
            if not isinstance(row, dict) or not row.get("Name"):
                issues.append(
                    _issue(
                        "equipment_ability_identity_missing",
                        document.relative_path,
                        f"AbilityList:{row_index}",
                        "status_unknown",
                        json_path=f"$/AbilityList/{row_index}",
                    )
                )
    for ability_name, sources in sorted(ability_index.items()):
        if len(sources) != 1:
            issues.append(
                _issue(
                    "equipment_ability_name_not_globally_unique",
                    "Config/ConfigAbility/Equip",
                    ability_name,
                    "status_unknown",
                    sources=sources,
                )
            )
    promotion_index: dict[Any, list[tuple[int, int]]] = defaultdict(list)
    skill_index: dict[Any, list[tuple[int, str, int]]] = defaultdict(list)
    for index, row in enumerate(promotion_rows):
        stage = _optional_int(row.get("Promotion"))
        promotion_index[row.get("EquipmentID")].append((0 if stage is None else stage, index))
    for index, row in enumerate(skill_rows):
        level = _optional_int(row.get("Level"))
        skill_index[row.get("SkillID")].append((0 if level is None else level, str(row.get("AbilityName") or ""), index))

    _record_duplicate_keys(issues, equipment_rows, ("EquipmentID",), "equipment_duplicate_identity")
    _record_duplicate_keys(issues, promotion_rows, ("EquipmentID", "Promotion"), "equipment_promotion_duplicate_key", missing_defaults={"Promotion": 0})
    _record_duplicate_keys(issues, skill_rows, ("SkillID", "Level"), "equipment_skill_duplicate_key")
    _record_duplicate_keys(issues, relic_rows, ("ID",), "relic_duplicate_identity")
    _record_duplicate_keys(
        issues,
        base_type_rows,
        ("Type",),
        "relic_base_type_duplicate_identity",
        missing_defaults={"Type": "<untyped_filter>"},
    )
    _record_duplicate_keys(issues, main_affix_rows, ("GroupID", "AffixID"), "main_affix_duplicate_key")
    _record_duplicate_keys(issues, sub_affix_rows, ("GroupID", "AffixID"), "sub_affix_duplicate_key")
    _record_duplicate_keys(issues, set_rows, ("SetID",), "relic_set_duplicate_identity")
    _record_duplicate_keys(issues, set_skill_rows, ("SetID", "RequireNum"), "relic_set_skill_duplicate_key")

    equipment_ids = {row.get("EquipmentID") for row in equipment_rows}
    referenced_skill_ids = {row.get("SkillID") for row in equipment_rows}
    orphan_promotions = [
        {
            "equipment_id": row.get("EquipmentID"),
            "promotion": row.get("Promotion", 0),
            "classification": "orphaned_record",
            "publication_status": "status_unknown",
            "source": {
                "source_path": "ExcelOutput/EquipmentPromotionConfig.json",
                "raw_type": "EquipmentPromotionConfig",
                "raw_id": f"{row.get('EquipmentID')}:{row.get('Promotion', 0)}",
                "json_path": f"$[{row_index}]",
            },
        }
        for row_index, row in enumerate(promotion_rows)
        if row.get("EquipmentID") not in equipment_ids
    ]
    orphan_skills = [
        {
            "skill_id": row.get("SkillID"),
            "level": row.get("Level"),
            "ability_name": str(row.get("AbilityName") or ""),
            "classification": "orphaned_record",
            "publication_status": "status_unknown",
            "source": {
                "source_path": "ExcelOutput/EquipmentSkillConfig.json",
                "raw_type": "EquipmentSkillConfig",
                "raw_id": f"{row.get('SkillID')}:{row.get('Level')}",
                "json_path": f"$[{row_index}]",
            },
        }
        for row_index, row in enumerate(skill_rows)
        if row.get("SkillID") not in referenced_skill_ids
    ]
    for row in orphan_promotions:
        issues.append(
            _issue(
                "orphan_equipment_promotion_record",
                row["source"]["source_path"],
                row["source"]["raw_id"],
                row["publication_status"],
                source=row["source"],
            )
        )
    for row in orphan_skills:
        issues.append(
            _issue(
                "orphan_equipment_skill_record",
                row["source"]["source_path"],
                row["source"]["raw_id"],
                row["publication_status"],
                ability_name=row["ability_name"],
                source=row["source"],
            )
        )

    equipment_inventory: list[dict[str, Any]] = []
    referenced_abilities: dict[str, set[str]] = defaultdict(set)
    referenced_ability_publication: dict[str, set[str]] = defaultdict(set)
    for row_index, row in enumerate(equipment_rows):
        equipment_id = row.get("EquipmentID")
        skill_id = row.get("SkillID")
        publication_status = _publication_status(row.get("Release"))
        max_promotion = _optional_int(row.get("MaxPromotion"))
        max_rank = _optional_int(row.get("MaxRank"))
        promotion_stages = sorted(stage for stage, _ in promotion_index.get(equipment_id, ()))
        skill_levels = sorted(level for level, _, _ in skill_index.get(skill_id, ()))
        ability_names = sorted({name for _, name, _ in skill_index.get(skill_id, ()) if name})
        expected_promotion_stages = list(range(0, max_promotion + 1)) if max_promotion is not None and max_promotion >= 0 else []
        expected_skill_levels = list(range(1, max_rank + 1)) if max_rank is not None and max_rank > 0 else []
        if promotion_stages != expected_promotion_stages:
            issues.append(
                _issue(
                    "equipment_promotion_reference_incomplete",
                    "ExcelOutput/EquipmentConfig.json",
                    equipment_id,
                    publication_status,
                    actual=promotion_stages,
                    expected=expected_promotion_stages,
                )
            )
        if skill_levels != expected_skill_levels:
            issues.append(
                _issue(
                    "equipment_skill_reference_incomplete",
                    "ExcelOutput/EquipmentConfig.json",
                    equipment_id,
                    publication_status,
                    actual=skill_levels,
                    expected=expected_skill_levels,
                )
            )
        if len(ability_names) != 1:
            issues.append(
                _issue(
                    "equipment_skill_ability_name_not_unique",
                    "ExcelOutput/EquipmentSkillConfig.json",
                    skill_id,
                    publication_status,
                    ability_names=ability_names,
                )
            )
        ability_resolutions: list[dict[str, Any]] = []
        for ability_name in ability_names:
            sources = ability_index.get(ability_name, [])
            referenced_abilities[ability_name].add("light_cone")
            referenced_ability_publication[ability_name].add(publication_status)
            ability_resolutions.append(
                {
                    "ability_name": ability_name,
                    "match_count": len(sources),
                    "sources": sources,
                }
            )
            if len(sources) != 1:
                issues.append(
                    _issue(
                        "equipment_ability_reference_not_unique",
                        "ExcelOutput/EquipmentSkillConfig.json",
                        skill_id,
                        publication_status,
                        ability_name=ability_name,
                        sources=sources,
                    )
                )
        equipment_inventory.append(
            {
                "equipment_id": equipment_id,
                "skill_id": skill_id,
                "publication_status": publication_status,
                "avatar_base_type": str(row.get("AvatarBaseType") or ""),
                "max_promotion": max_promotion,
                "max_rank": max_rank,
                "promotion_stages": promotion_stages,
                "skill_levels": skill_levels,
                "ability_resolutions": ability_resolutions,
                "source": {
                    "source_path": "ExcelOutput/EquipmentConfig.json",
                    "raw_type": "EquipmentConfig",
                    "raw_id": str(equipment_id),
                    "json_path": f"$[{row_index}]",
                },
            }
        )

    set_by_id = {row.get("SetID"): row for row in set_rows if row.get("SetID") is not None}
    set_skill_index: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    set_threshold_inventory: list[dict[str, Any]] = []
    for row_index, row in enumerate(set_skill_rows):
        set_id = row.get("SetID")
        require_num = row.get("RequireNum")
        publication_status = _publication_status(set_by_id.get(set_id, {}).get("Release"))
        set_skill_index[set_id].append(row)
        ability_name = str(row.get("AbilityName") or "")
        ability_sources = ability_index.get(ability_name, []) if ability_name else []
        if ability_name:
            referenced_abilities[ability_name].add("relic_set")
            referenced_ability_publication[ability_name].add(publication_status)
            if len(ability_sources) != 1:
                issues.append(
                    _issue(
                        "relic_set_ability_reference_not_unique",
                        "ExcelOutput/RelicSetSkillConfig.json",
                        f"{set_id}:{require_num}",
                        publication_status,
                        ability_name=ability_name,
                        sources=ability_sources,
                    )
                )
        if set_id not in set_by_id:
            issues.append(
                _issue(
                    "relic_set_skill_missing_set",
                    "ExcelOutput/RelicSetSkillConfig.json",
                    f"{set_id}:{require_num}",
                    publication_status,
                )
            )
        elif require_num not in _list_values(set_by_id[set_id].get("SetSkillList")):
            issues.append(
                _issue(
                    "relic_set_threshold_not_declared",
                    "ExcelOutput/RelicSetSkillConfig.json",
                    f"{set_id}:{require_num}",
                    publication_status,
                    declared_thresholds=_list_values(set_by_id[set_id].get("SetSkillList")),
                )
            )
        set_threshold_inventory.append(
            {
                "set_id": set_id,
                "require_num": require_num,
                "publication_status": publication_status,
                "static_property_count": len(_list_values(row.get("PropertyList"))),
                "ability_name": ability_name,
                "ability_match_count": len(ability_sources),
                "ability_sources": ability_sources,
                "source": {
                    "source_path": "ExcelOutput/RelicSetSkillConfig.json",
                    "raw_type": "RelicSetSkillConfig",
                    "raw_id": f"{set_id}:{require_num}",
                    "json_path": f"$[{row_index}]",
                },
            }
        )

    relic_set_inventory: list[dict[str, Any]] = []
    for row_index, row in enumerate(set_rows):
        set_id = row.get("SetID")
        publication_status = _publication_status(row.get("Release"))
        declared_thresholds = sorted(_optional_int(value) for value in _list_values(row.get("SetSkillList")) if _optional_int(value) is not None)
        actual_thresholds = sorted(
            _optional_int(item.get("RequireNum"))
            for item in set_skill_index.get(set_id, ())
            if _optional_int(item.get("RequireNum")) is not None
        )
        if declared_thresholds != actual_thresholds:
            issues.append(
                _issue(
                    "relic_set_threshold_reference_incomplete",
                    "ExcelOutput/RelicSetConfig.json",
                    set_id,
                    publication_status,
                    declared_thresholds=declared_thresholds,
                    actual_thresholds=actual_thresholds,
                )
            )
        relic_set_inventory.append(
            {
                "set_id": set_id,
                "publication_status": publication_status,
                "is_planar_suit": row.get("IsPlanarSuit") is True,
                "declared_thresholds": declared_thresholds,
                "actual_thresholds": actual_thresholds,
                "source": {
                    "source_path": "ExcelOutput/RelicSetConfig.json",
                    "raw_type": "RelicSetConfig",
                    "raw_id": str(set_id),
                    "json_path": f"$[{row_index}]",
                },
            }
        )

    typed_base_types = {str(row.get("Type")) for row in base_type_rows if row.get("Type")}
    untyped_base_type_rows = [index for index, row in enumerate(base_type_rows) if not row.get("Type")]
    main_affix_groups = {row.get("GroupID") for row in main_affix_rows}
    sub_affix_groups = {row.get("GroupID") for row in sub_affix_rows}
    relic_template_types = {str(row.get("Type")) for row in relic_rows if row.get("Type")}
    relic_template_inventory: list[dict[str, Any]] = []
    for row_index, row in enumerate(relic_rows):
        relic_id = row.get("ID")
        mode = str(row.get("Mode") or "status_unknown")
        publication_status = _publication_status(row.get("Release"))
        references = {
            "base_type_exists": str(row.get("Type")) in typed_base_types,
            "main_affix_group_exists": row.get("MainAffixGroup") in main_affix_groups,
            "sub_affix_group_exists": row.get("SubAffixGroup") in sub_affix_groups,
            "set_exists": row.get("SetID") in set_by_id,
        }
        for reference_kind, ok in references.items():
            if not ok:
                issues.append(
                    _issue(
                        f"relic_template_{reference_kind}_failed",
                        "ExcelOutput/RelicConfig.json",
                        relic_id,
                        publication_status,
                        mode=mode,
                        type=row.get("Type"),
                        set_id=row.get("SetID"),
                        main_affix_group=row.get("MainAffixGroup"),
                        sub_affix_group=row.get("SubAffixGroup"),
                    )
                )
        relic_template_inventory.append(
            {
                "relic_id": relic_id,
                "publication_status": publication_status,
                "mode": mode,
                "type": str(row.get("Type") or ""),
                "rarity": str(row.get("Rarity") or ""),
                "set_id": row.get("SetID"),
                "main_affix_group": row.get("MainAffixGroup"),
                "sub_affix_group": row.get("SubAffixGroup"),
                "references": references,
                "source": {
                    "source_path": "ExcelOutput/RelicConfig.json",
                    "raw_type": "RelicConfig",
                    "raw_id": str(relic_id),
                    "json_path": f"$[{row_index}]",
                },
            }
        )

    if relic_template_types != typed_base_types:
        issues.append(
            _issue(
                "relic_template_and_typed_base_type_sets_differ",
                "ExcelOutput/RelicBaseType.json",
                "typed_base_types",
                "status_unknown",
                relic_template_types=sorted(relic_template_types),
                typed_base_types=sorted(typed_base_types),
            )
        )
    if not untyped_base_type_rows:
        issues.append(
            _issue(
                "relic_untyped_filter_row_missing",
                "ExcelOutput/RelicBaseType.json",
                "untyped_filter",
                "status_unknown",
            )
        )

    ability_inventory: list[dict[str, Any]] = []
    for ability_name in sorted(ability_index):
        domains = sorted(referenced_abilities.get(ability_name, set()))
        publication_statuses = sorted(referenced_ability_publication.get(ability_name, set()))
        if publication_statuses == ["published"]:
            publication_status = "published"
        elif publication_statuses == ["unpublished"]:
            publication_status = "unpublished"
        else:
            publication_status = "status_unknown"
        ability_inventory.append(
            {
                "ability_name": ability_name,
                "reference_domains": domains,
                "reference_status": "referenced" if domains else "unreferenced",
                "publication_status": publication_status,
                "publication_statuses_from_references": publication_statuses,
                "sources": ability_index[ability_name],
            }
        )
    unreferenced_abilities = [row for row in ability_inventory if row["reference_status"] == "unreferenced"]
    issue_counts = Counter(str(row["issue_kind"]) for row in issues)
    publication_summary = {
        "equipment": dict(sorted(Counter(row["publication_status"] for row in equipment_inventory).items())),
        "relic_templates": dict(sorted(Counter(row["publication_status"] for row in relic_template_inventory).items())),
        "relic_sets": dict(sorted(Counter(row["publication_status"] for row in relic_set_inventory).items())),
        "relic_set_thresholds": dict(sorted(Counter(row["publication_status"] for row in set_threshold_inventory).items())),
        "abilities": dict(sorted(Counter(row["publication_status"] for row in ability_inventory).items())),
    }
    return {
        "schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "ok": not issues,
        "publication_summary": publication_summary,
        "equipment_inventory": equipment_inventory,
        "relic_template_inventory": relic_template_inventory,
        "relic_set_inventory": relic_set_inventory,
        "relic_set_threshold_inventory": set_threshold_inventory,
        "affix_inventory": {
            "main_affix_record_count": len(main_affix_rows),
            "main_affix_group_count": len(main_affix_groups),
            "sub_affix_record_count": len(sub_affix_rows),
            "sub_affix_group_count": len(sub_affix_groups),
        },
        "base_type_partition": {
            "typed_base_types": sorted(typed_base_types),
            "relic_template_types": sorted(relic_template_types),
            "untyped_filter_row_indexes": untyped_base_type_rows,
            "base_type_record_count": len(base_type_rows),
            "typed_base_type_record_count": len(base_type_rows) - len(untyped_base_type_rows),
            "typed_base_type_unique_count": len(typed_base_types),
            "untyped_filter_record_count": len(untyped_base_type_rows),
        },
        "ability_inventory": ability_inventory,
        "unreferenced_abilities": unreferenced_abilities,
        "orphan_source_inventory": {
            "equipment_promotions": orphan_promotions,
            "equipment_skills": orphan_skills,
        },
        "counts": {
            "equipment": len(equipment_inventory),
            "relic_templates": len(relic_template_inventory),
            "relic_sets": len(relic_set_inventory),
            "relic_set_thresholds": len(set_threshold_inventory),
            "abilities": len(ability_inventory),
            "ability_records": ability_record_count,
            "referenced_abilities": len(ability_inventory) - len(unreferenced_abilities),
            "unreferenced_abilities": len(unreferenced_abilities),
        },
        "issues": issues,
        "issue_counts": dict(sorted(issue_counts.items())),
    }


def build_equipment_mechanism_family_matrix(snapshot: EquipmentSourceSnapshot) -> dict[str, Any]:
    aggregate: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    scan_scope_occurrences: Counter[str] = Counter()
    scan_scope_dimension_occurrences: dict[str, Counter[str]] = defaultdict(Counter)
    scan_documents: list[dict[str, Any]] = []

    def add(
        dimension: str,
        raw_value: str,
        source_path: str,
        ability_name: str,
        json_path: str,
        source_scope: str,
    ) -> None:
        family, classification, rationale = _classify_mechanism(dimension, raw_value)
        key = (dimension, raw_value, family, classification, rationale)
        row = aggregate.setdefault(
            key,
            {
                "dimension": dimension,
                "raw_value": raw_value,
                "mechanism_family": family,
                "classification": classification,
                "classification_basis": rationale,
                "occurrence_count": 0,
                "source_paths": set(),
                "ability_names": set(),
                "source_scope_counts": Counter(),
                "samples": [],
            },
        )
        row["occurrence_count"] += 1
        row["source_paths"].add(source_path)
        row["ability_names"].add(ability_name)
        row["source_scope_counts"][source_scope] += 1
        scan_scope_occurrences[source_scope] += 1
        scan_scope_dimension_occurrences[source_scope][dimension] += 1
        if len(row["samples"]) < MAX_SOURCE_SAMPLES:
            row["samples"].append(
                {
                    "source_path": source_path,
                    "ability_name": ability_name,
                    "json_path": json_path,
                    "raw_value": raw_value,
                    "source_scope": source_scope,
                }
            )

    for document in snapshot.ability_documents:
        data = document.data
        if not isinstance(data, dict):
            _walk_mechanism_value(
                data,
                "$",
                document.relative_path,
                "<file-root>",
                add,
                "file_root",
            )
            scan_documents.append(
                {
                    "source_path": document.relative_path,
                    "root_type": document.root_type,
                    "discovered_top_level_sections": ["<root>"],
                    "scanned_top_level_sections": ["<root>"],
                    "unscanned_top_level_sections": [],
                }
            )
            continue

        discovered_sections = sorted(str(key) for key in data)
        scanned_sections: list[str] = []
        for section_name, section_value in data.items():
            section_name = str(section_name)
            scanned_sections.append(section_name)
            if section_name == "AbilityList" and isinstance(section_value, list):
                for ability_index, ability in enumerate(section_value):
                    ability_name = (
                        str(ability.get("Name") or f"<unnamed:{ability_index}>")
                        if isinstance(ability, dict)
                        else f"<non_object:{ability_index}>"
                    )
                    _walk_mechanism_value(
                        ability,
                        f"$/AbilityList/{ability_index}",
                        document.relative_path,
                        ability_name,
                        add,
                        "ability_list",
                    )
                continue
            source_scope = f"file_global:{section_name}"
            _walk_mechanism_value(
                section_value,
                f"$/{_json_pointer_token(section_name)}",
                document.relative_path,
                f"<file-global:{section_name}>",
                add,
                source_scope,
            )
        scan_documents.append(
            {
                "source_path": document.relative_path,
                "root_type": document.root_type,
                "discovered_top_level_sections": discovered_sections,
                "scanned_top_level_sections": sorted(scanned_sections),
                "unscanned_top_level_sections": sorted(set(discovered_sections) - set(scanned_sections)),
            }
        )

    rows: list[dict[str, Any]] = []
    for key in sorted(aggregate):
        row = aggregate[key]
        rows.append(
            {
                **row,
                "source_paths": sorted(row["source_paths"]),
                "ability_names": sorted(row["ability_names"]),
                "source_scope_counts": dict(sorted(row["source_scope_counts"].items())),
            }
        )
    classification_counts = Counter(row["classification"] for row in rows)
    family_counts = Counter(row["mechanism_family"] for row in rows)
    dimension_counts = Counter(row["dimension"] for row in rows)
    unknown_rows = [row for row in rows if row["classification"] == "unknown"]
    file_global_scope_occurrences = {
        scope: count
        for scope, count in sorted(scan_scope_occurrences.items())
        if scope.startswith("file_global:")
    }
    file_global_dimension_occurrences: Counter[str] = Counter()
    for scope, counts in scan_scope_dimension_occurrences.items():
        if scope.startswith("file_global:"):
            file_global_dimension_occurrences.update(counts)
    return {
        "schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "rows": rows,
        "unknown_rows": unknown_rows,
        "scan_coverage": {
            "scope": "entire_primary_equipment_ability_document_including_ability_list_and_all_file_level_sections",
            "document_count": len(scan_documents),
            "documents": scan_documents,
            "unscanned_top_level_sections": [
                {
                    "source_path": document["source_path"],
                    "section": section,
                }
                for document in scan_documents
                for section in document["unscanned_top_level_sections"]
            ],
            "source_scope_occurrence_counts": dict(sorted(scan_scope_occurrences.items())),
            "source_scope_dimension_occurrence_counts": {
                scope: dict(sorted(counts.items()))
                for scope, counts in sorted(scan_scope_dimension_occurrences.items())
            },
            "file_global_scope_occurrence_counts": file_global_scope_occurrences,
            "file_global_dimension_occurrence_counts": dict(sorted(file_global_dimension_occurrences.items())),
            "file_global_mechanism_occurrence_count": sum(file_global_scope_occurrences.values()),
            "ability_list_mechanism_occurrence_count": int(scan_scope_occurrences.get("ability_list") or 0),
        },
        "summary": {
            "row_count": len(rows),
            "classification_counts": dict(sorted(classification_counts.items())),
            "family_counts": dict(sorted(family_counts.items())),
            "dimension_counts": dict(sorted(dimension_counts.items())),
            "unknown_row_count": len(unknown_rows),
            "unknown_occurrence_count": sum(int(row["occurrence_count"]) for row in unknown_rows),
        },
    }


def build_equipment_source_inventory(
    snapshot: EquipmentSourceSnapshot,
    special_sources: dict[str, Any],
    references: dict[str, Any],
) -> dict[str, Any]:
    documents = [document.inventory_json() for document in snapshot.documents]
    table_counts = {
        role: document.record_count
        for role, document in sorted(snapshot.table_documents.items())
    }
    ability_records = sum(
        len(document.data.get("AbilityList") or [])
        for document in snapshot.ability_documents
        if isinstance(document.data, dict)
    )
    release_dimensions = references.get("publication_summary", {})
    return {
        "schema_version": EQUIPMENT_DISCOVERY_SCHEMA_VERSION,
        "primary_source_fingerprint": snapshot.primary_source_fingerprint,
        "primary_documents": documents,
        "missing_required_paths": list(snapshot.missing_required_paths),
        "parse_errors": list(snapshot.parse_errors),
        "table_record_counts": table_counts,
        "ability_discovery": {
            "root": PRIMARY_ABILITY_ROOT,
            "selection": "recursive_non_layout_json",
            "file_count": len(snapshot.ability_documents),
            "ability_record_count": ability_records,
            "paths": [document.relative_path for document in snapshot.ability_documents],
            "single_legacy_file_dependency": False,
        },
        "candidate_discovery": special_sources.get("candidate_discovery", {}),
        "publication_dimensions": release_dimensions,
        "mode_dimensions": {
            "relic_mode_counts": dict(
                sorted(
                    Counter(
                        str(row.get("mode") or "status_unknown")
                        for row in references.get("relic_template_inventory", [])
                    ).items()
                )
            ),
            "special_modes_retained": sorted(
                {
                    str(row.get("mode"))
                    for row in references.get("relic_template_inventory", [])
                    if str(row.get("mode") or "status_unknown") != "BASIC"
                }
            ),
        },
    }


def validate_equipment_source_inventory(
    inventory: dict[str, Any],
    special_sources: dict[str, Any],
) -> dict[str, Any]:
    documents = inventory.get("primary_documents") if isinstance(inventory.get("primary_documents"), list) else []
    fingerprint = inventory.get("primary_source_fingerprint") if isinstance(inventory.get("primary_source_fingerprint"), dict) else {}
    document_paths = {str(row.get("relative_path")) for row in documents if isinstance(row, dict)}
    fingerprint_paths = set(str(path) for path in fingerprint.get("paths", []) if isinstance(path, str))
    table_counts = inventory.get("table_record_counts") if isinstance(inventory.get("table_record_counts"), dict) else {}
    candidate_paths = set(
        str(path)
        for path in special_sources.get("candidate_discovery", {}).get("candidate_paths", [])
        if isinstance(path, str)
    )
    classified_paths = {
        str(row.get("relative_path"))
        for row in special_sources.get("rows", [])
        if isinstance(row, dict)
    }
    checks = {
        "all_required_primary_paths_present": not inventory.get("missing_required_paths"),
        "all_primary_json_parsed": not inventory.get("parse_errors"),
        "all_core_tables_nonempty": set(PRIMARY_TABLE_ROLES).issubset(table_counts)
        and all(int(table_counts.get(role) or 0) > 0 for role in PRIMARY_TABLE_ROLES),
        "ability_inventory_nonempty": int(inventory.get("ability_discovery", {}).get("file_count") or 0) > 0
        and int(inventory.get("ability_discovery", {}).get("ability_record_count") or 0) > 0,
        "ability_discovery_recursive_and_not_legacy_single_file": inventory.get("ability_discovery", {}).get("selection") == "recursive_non_layout_json"
        and inventory.get("ability_discovery", {}).get("single_legacy_file_dependency") is False,
        "primary_fingerprint_full_content": fingerprint.get("algorithm") == PRIMARY_FINGERPRINT_ALGORITHM
        and fingerprint.get("coverage") == "full_content_for_every_primary_source_file",
        "primary_fingerprint_covers_exact_documents": fingerprint.get("file_count") == len(documents)
        and fingerprint_paths == document_paths
        and len(fingerprint_paths) == len(documents),
        "primary_documents_have_full_hashes": bool(documents)
        and all(isinstance(row.get("sha256"), str) and len(row["sha256"]) == 64 for row in documents),
        "candidate_discovery_not_self_limited_to_primary_roles": len(candidate_paths - document_paths) > 0,
        "every_discovered_candidate_has_a_row": candidate_paths == classified_paths,
        "publication_dimensions_retained": bool(inventory.get("publication_dimensions"))
        and all(
            set(dict(counts)) <= PUBLICATION_STATES
            for counts in inventory.get("publication_dimensions", {}).values()
            if isinstance(counts, dict)
        ),
        "special_relic_modes_retained": bool(inventory.get("mode_dimensions", {}).get("special_modes_retained")),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def validate_equipment_reference_integrity(reference: dict[str, Any]) -> dict[str, Any]:
    equipment = reference.get("equipment_inventory") if isinstance(reference.get("equipment_inventory"), list) else []
    relic_templates = reference.get("relic_template_inventory") if isinstance(reference.get("relic_template_inventory"), list) else []
    relic_sets = reference.get("relic_set_inventory") if isinstance(reference.get("relic_set_inventory"), list) else []
    set_thresholds = reference.get("relic_set_threshold_inventory") if isinstance(reference.get("relic_set_threshold_inventory"), list) else []
    abilities = reference.get("ability_inventory") if isinstance(reference.get("ability_inventory"), list) else []
    base_type_partition = reference.get("base_type_partition") if isinstance(reference.get("base_type_partition"), dict) else {}
    orphan_inventory = reference.get("orphan_source_inventory") if isinstance(reference.get("orphan_source_inventory"), dict) else {}
    ability_resolutions = [
        resolution
        for row in equipment
        if isinstance(row, dict)
        for resolution in row.get("ability_resolutions", [])
        if isinstance(resolution, dict)
    ] + [
        {
            "ability_name": row.get("ability_name"),
            "match_count": row.get("ability_match_count"),
        }
        for row in set_thresholds
        if isinstance(row, dict) and row.get("ability_name")
    ]
    checks = {
        "reference_issue_count_zero": reference.get("issues") == [] and reference.get("issue_counts") == {},
        "all_identity_domains_nonempty": bool(equipment) and bool(relic_templates) and bool(relic_sets) and bool(set_thresholds) and bool(abilities),
        "all_ability_references_resolve_once": bool(ability_resolutions)
        and all(row.get("match_count") == 1 for row in ability_resolutions),
        "all_ability_names_globally_unique": bool(abilities)
        and all(len(row.get("sources") or []) == 1 for row in abilities if isinstance(row, dict))
        and int(reference.get("counts", {}).get("ability_records") or 0) == len(abilities),
        "all_relic_template_references_resolve": all(
            all(value is True for value in dict(row.get("references") or {}).values())
            for row in relic_templates
            if isinstance(row, dict)
        ),
        "typed_slots_and_untyped_filter_are_separate": base_type_partition.get("typed_base_types")
        == base_type_partition.get("relic_template_types")
        and bool(base_type_partition.get("untyped_filter_row_indexes")),
        "relic_base_type_identity_is_lossless_and_unique": int(base_type_partition.get("base_type_record_count") or 0)
        == int(base_type_partition.get("typed_base_type_unique_count") or 0)
        + int(base_type_partition.get("untyped_filter_record_count") or 0)
        and int(base_type_partition.get("typed_base_type_record_count") or 0)
        == int(base_type_partition.get("typed_base_type_unique_count") or 0)
        and int(base_type_partition.get("untyped_filter_record_count") or 0) == 1,
        "growth_and_superimposition_orphans_are_explicit_and_empty": orphan_inventory.get("equipment_promotions") == []
        and orphan_inventory.get("equipment_skills") == [],
        "publication_status_present_on_all_content_records": all(
            row.get("publication_status") in PUBLICATION_STATES
            for rows in (equipment, relic_templates, relic_sets, set_thresholds, abilities)
            for row in rows
            if isinstance(row, dict)
        ),
        "ability_partition_is_lossless": len(abilities)
        == int(reference.get("counts", {}).get("referenced_abilities") or 0)
        + int(reference.get("counts", {}).get("unreferenced_abilities") or 0),
        "unreferenced_abilities_retain_sources": all(
            row.get("reference_status") == "unreferenced" and bool(row.get("sources"))
            for row in reference.get("unreferenced_abilities", [])
            if isinstance(row, dict)
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def validate_equipment_mechanism_family_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    unknown_rows = matrix.get("unknown_rows") if isinstance(matrix.get("unknown_rows"), list) else []
    scan_coverage = matrix.get("scan_coverage") if isinstance(matrix.get("scan_coverage"), dict) else {}
    scan_documents = scan_coverage.get("documents") if isinstance(scan_coverage.get("documents"), list) else []
    file_global_dimension_counts = (
        scan_coverage.get("file_global_dimension_occurrence_counts")
        if isinstance(scan_coverage.get("file_global_dimension_occurrence_counts"), dict)
        else {}
    )
    derived_file_global_dimension_counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        global_occurrence_count = sum(
            int(count or 0)
            for scope, count in dict(row.get("source_scope_counts") or {}).items()
            if str(scope).startswith("file_global:")
        )
        if global_occurrence_count:
            derived_file_global_dimension_counts[str(row.get("dimension"))] += global_occurrence_count
    required_dimensions = {"raw_type", "event", "condition", "target_type", "target_alias", "dynamic_read_type"}
    dimensions = {str(row.get("dimension")) for row in rows if isinstance(row, dict)}
    checks = {
        "mechanism_rows_nonempty": bool(rows),
        "required_structural_dimensions_present": required_dimensions.issubset(dimensions),
        "entire_ability_file_structure_scanned": scan_coverage.get("scope")
        == "entire_primary_equipment_ability_document_including_ability_list_and_all_file_level_sections"
        and int(scan_coverage.get("document_count") or 0) == len(scan_documents)
        and bool(scan_documents)
        and scan_coverage.get("unscanned_top_level_sections") == []
        and all(
            set(document.get("discovered_top_level_sections") or [])
            == set(document.get("scanned_top_level_sections") or [])
            and document.get("unscanned_top_level_sections") == []
            for document in scan_documents
            if isinstance(document, dict)
        ),
        "file_level_mechanisms_retained": int(scan_coverage.get("file_global_mechanism_occurrence_count") or 0) > 0
        and bool(scan_coverage.get("file_global_scope_occurrence_counts")),
        "file_level_mechanism_dimensions_are_lossless": int(scan_coverage.get("file_global_mechanism_occurrence_count") or 0)
        == sum(int(count or 0) for count in file_global_dimension_counts.values())
        and int(file_global_dimension_counts.get("raw_type") or 0) > 0
        and file_global_dimension_counts == dict(sorted(derived_file_global_dimension_counts.items())),
        "all_rows_classified": all(row.get("classification") in MECHANISM_CLASSIFICATIONS for row in rows),
        "all_rows_have_structural_evidence": all(
            bool(row.get("raw_value"))
            and bool(row.get("mechanism_family"))
            and bool(row.get("classification_basis"))
            and int(row.get("occurrence_count") or 0) > 0
            and bool(row.get("source_paths"))
            and bool(row.get("ability_names"))
            and sum(int(count or 0) for count in dict(row.get("source_scope_counts") or {}).values())
            == int(row.get("occurrence_count") or 0)
            and bool(row.get("samples"))
            and all(bool(sample.get("source_scope")) for sample in row.get("samples", []) if isinstance(sample, dict))
            for row in rows
            if isinstance(row, dict)
        ),
        "unknown_rows_are_visible_and_sampled": all(
            row.get("classification") == "unknown" and bool(row.get("samples"))
            for row in unknown_rows
            if isinstance(row, dict)
        )
        and int(matrix.get("summary", {}).get("unknown_row_count") or 0) == len(unknown_rows),
        "no_unknown_reclassified_as_non_gameplay": all(
            "explicit client marker" in str(row.get("classification_basis"))
            for row in rows
            if isinstance(row, dict) and row.get("classification") == "non_gameplay"
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def validate_equipment_candidate_classification(special_sources: dict[str, Any]) -> dict[str, Any]:
    rows = special_sources.get("rows") if isinstance(special_sources.get("rows"), list) else []
    candidate_paths = set(
        str(path)
        for path in special_sources.get("candidate_discovery", {}).get("candidate_paths", [])
        if isinstance(path, str)
    )
    row_paths = {str(row.get("relative_path")) for row in rows if isinstance(row, dict)}
    fully_classified = [row for row in rows if row.get("classification_status") == "classified_full_content"]
    sampled_pending = [row for row in rows if row.get("classification_status") == "sampled_pending_confirmation"]
    full_aux_paths = set(special_sources.get("full_auxiliary_fingerprint", {}).get("paths", []))
    sampled_paths = set(special_sources.get("sampled_pending_auxiliary_fingerprint", {}).get("paths", []))
    legacy_mirrors = [row for row in rows if row.get("source_role") == "legacy_ability_mirror"]
    checks = {
        "candidate_rows_cover_dynamic_discovery": bool(rows) and candidate_paths == row_paths,
        "unregistered_candidate_count_zero": special_sources.get("candidate_discovery", {}).get("unregistered_candidate_paths") == [],
        "all_rows_have_explicit_classification": all(
            row.get("classification") in MECHANISM_CLASSIFICATIONS
            and bool(row.get("classification_status"))
            and bool(row.get("classification_basis"))
            for row in rows
            if isinstance(row, dict)
        ),
        "fully_classified_files_have_full_content_fingerprint": all(
            row.get("fingerprint_scope") in {"primary_full_content", "auxiliary_full_content"}
            and isinstance(row.get("sha256"), str)
            and len(row["sha256"]) == 64
            and (
                row.get("fingerprint_scope") == "primary_full_content"
                or row.get("relative_path") in full_aux_paths
            )
            for row in fully_classified
        ),
        "sampled_files_are_unknown_pending_with_explicit_range": all(
            row.get("classification") == "unknown"
            and row.get("fingerprint_scope") == "auxiliary_prefix_sample"
            and row.get("relative_path") in sampled_paths
            and isinstance(row.get("sample_scope"), dict)
            and row["sample_scope"].get("start_byte") == 0
            and int(row["sample_scope"].get("sampled_byte_count") or 0) > 0
            and int(row["sample_scope"].get("file_byte_count") or 0) >= int(row["sample_scope"].get("sampled_byte_count") or 0)
            for row in sampled_pending
        ),
        "legacy_mirror_differences_retained": bool(legacy_mirrors)
        and all(
            row.get("classification") == "gameplay"
            and isinstance(row.get("mirror_evidence"), dict)
            and "only_in_primary" in row["mirror_evidence"]
            and "only_in_mirror" in row["mirror_evidence"]
            for row in legacy_mirrors
        ),
        "external_semantics_never_runtime_source": bool(special_sources.get("external_semantic_references"))
        and all(
            row.get("runtime_source") is False
            and row.get("source_trace_eligible") is False
            and row.get("fetched_during_p8_s0") is False
            for row in special_sources.get("external_semantic_references", [])
            if isinstance(row, dict)
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {"ok": checks["ok"], "checks": checks}


def equipment_fingerprint_matches(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    required = {"algorithm", "sha256", "file_count", "byte_count", "paths", "coverage"}
    return required.issubset(current) and required.issubset(expected) and all(current[key] == expected[key] for key in required)


def _load_full_document(
    root: Path,
    path: Path,
    role: str,
) -> tuple[EquipmentSourceDocument | None, bytes | None, dict[str, str] | None]:
    relative_path = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return None, None, {"relative_path": relative_path, "error": str(exc)}
    return (
        EquipmentSourceDocument(
            role=role,
            relative_path=relative_path,
            byte_count=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            data=data,
        ),
        raw,
        None,
    )


def _classify_full_auxiliary(
    root: Path,
    path: Path,
    *,
    policy: AuxiliaryPolicy,
) -> tuple[dict[str, Any], bytes | None]:
    relative_path = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return (
            {
                "relative_path": relative_path,
                "source_role": policy.source_role,
                "classification": "unknown",
                "classification_status": "unclassified",
                "classification_basis": f"full auxiliary parse failed: {exc}",
                "fingerprint_scope": "none",
                "sha256": "",
                "byte_count": path.stat().st_size,
                "root_type": "invalid_json",
                "record_count": 0,
                "sample_scope": None,
            },
            None,
        )
    classification = policy.classification
    rationale = policy.rationale
    combat_markers = sorted(_combat_graph_markers(data))
    if classification == "non_gameplay" and combat_markers:
        classification = "unknown"
        rationale = "registered auxiliary role contains combat-graph markers and cannot be accepted as non-gameplay"
    sample = _json_shape_sample(data)
    return (
        {
            "relative_path": relative_path,
            "source_role": policy.source_role,
            "classification": classification,
            "classification_status": "classified_full_content",
            "classification_basis": rationale,
            "fingerprint_scope": "auxiliary_full_content",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            **sample,
            "combat_graph_markers": combat_markers,
            "sample_scope": {
                "kind": "first_record_keys_from_full_json",
                "start_byte": 0,
                "sampled_byte_count": len(raw),
                "file_byte_count": len(raw),
                "full_file_parsed": True,
            },
        },
        raw,
    )


def _classify_legacy_ability_mirror(
    root: Path,
    path: Path,
    primary_ability_names: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], bytes | None]:
    relative_path = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return (
            {
                "relative_path": relative_path,
                "source_role": "legacy_ability_mirror",
                "classification": "unknown",
                "classification_status": "unclassified",
                "classification_basis": f"legacy ability mirror parse failed: {exc}",
                "fingerprint_scope": "none",
                "sha256": "",
                "byte_count": path.stat().st_size,
                "root_type": "invalid_json",
                "record_count": 0,
                "sample_scope": None,
            },
            None,
        )
    mirror_names = {
        str(row.get("Name"))
        for row in (data.get("AbilityList") or [])
        if isinstance(row, dict) and row.get("Name")
    } if isinstance(data, dict) else set()
    primary_names = set(primary_ability_names)
    mirror_evidence = {
        "mirror_ability_count": len(mirror_names),
        "overlap_count": len(mirror_names & primary_names),
        "only_in_mirror": sorted(mirror_names - primary_names),
        "only_in_primary": sorted(primary_names - mirror_names),
        "mirror_is_subset_of_primary": mirror_names <= primary_names,
        "identical_name_set": mirror_names == primary_names,
    }
    return (
        {
            "relative_path": relative_path,
            "source_role": "legacy_ability_mirror",
            "classification": "gameplay",
            "classification_status": "classified_full_content",
            "classification_basis": "full ability-name comparison proves this root file is a gameplay mirror candidate; differences remain explicit and it is not a primary resolver input",
            "fingerprint_scope": "auxiliary_full_content",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            **_json_shape_sample(data),
            "mirror_evidence": mirror_evidence,
            "sample_scope": {
                "kind": "full_ability_name_set",
                "start_byte": 0,
                "sampled_byte_count": len(raw),
                "file_byte_count": len(raw),
                "full_file_parsed": True,
            },
        },
        raw,
    )


def _classify_sampled_pending_candidate(
    root: Path,
    path: Path,
    policy: AuxiliaryPolicy,
    max_sample_bytes: int,
) -> tuple[dict[str, Any], bytes]:
    sample = _read_prefix(path, max_sample_bytes)
    sample_shape = _json_prefix_shape_sample(sample)
    return (
        {
            "relative_path": path.relative_to(root).as_posix(),
            "source_role": policy.source_role,
            "classification": "unknown",
            "classification_status": "sampled_pending_confirmation",
            "classification_basis": f"{policy.rationale}; file exceeds full-parse budget so the whole file remains pending confirmation",
            "fingerprint_scope": "auxiliary_prefix_sample",
            "sha256": hashlib.sha256(sample).hexdigest(),
            "byte_count": path.stat().st_size,
            **sample_shape,
            "sample_scope": {
                "kind": "byte_prefix_and_first_record_keys_if_decodable",
                "start_byte": 0,
                "end_byte_exclusive": len(sample),
                "sampled_byte_count": len(sample),
                "file_byte_count": path.stat().st_size,
                "full_file_parsed": False,
            },
        },
        sample,
    )


def _classify_unregistered_candidate(
    root: Path,
    path: Path,
    max_sample_bytes: int,
) -> tuple[dict[str, Any], bytes]:
    sample = _read_prefix(path, max_sample_bytes)
    return (
        {
            "relative_path": path.relative_to(root).as_posix(),
            "source_role": "unregistered_equipment_candidate",
            "classification": "unknown",
            "classification_status": "unclassified",
            "classification_basis": "candidate was dynamically discovered but has no reviewed source-role policy",
            "fingerprint_scope": "auxiliary_prefix_sample",
            "sha256": hashlib.sha256(sample).hexdigest(),
            "byte_count": path.stat().st_size,
            **_json_prefix_shape_sample(sample),
            "sample_scope": {
                "kind": "byte_prefix_for_unregistered_candidate",
                "start_byte": 0,
                "end_byte_exclusive": len(sample),
                "sampled_byte_count": len(sample),
                "file_byte_count": path.stat().st_size,
                "full_file_parsed": False,
            },
        },
        sample,
    )


def _full_auxiliary_fingerprint_item(row: dict[str, Any], raw: bytes) -> dict[str, Any]:
    return {
        "relative_path": row["relative_path"],
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _sampled_auxiliary_fingerprint_item(row: dict[str, Any], sample: bytes) -> dict[str, Any]:
    return {
        "relative_path": row["relative_path"],
        "file_byte_count": row["byte_count"],
        "sample_start_byte": 0,
        "sample_end_byte_exclusive": len(sample),
        "sample_sha256": hashlib.sha256(sample).hexdigest(),
    }


def _combined_auxiliary_fingerprint(
    algorithm: str,
    items: Iterable[dict[str, Any]],
    *,
    full_content: bool,
) -> dict[str, Any]:
    normalized = sorted(items, key=lambda row: str(row["relative_path"]))
    digest = hashlib.sha256()
    for row in normalized:
        digest.update(str(row["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        if full_content:
            digest.update(str(row["sha256"]).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(row["byte_count"]).encode("ascii"))
        else:
            digest.update(str(row["file_byte_count"]).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(row["sample_start_byte"]).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(row["sample_end_byte_exclusive"]).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(row["sample_sha256"]).encode("ascii"))
        digest.update(b"\0")
    return {
        "algorithm": algorithm,
        "sha256": digest.hexdigest(),
        "file_count": len(normalized),
        "paths": [str(row["relative_path"]) for row in normalized],
        "coverage": "full_content" if full_content else "explicit_prefix_samples_only_pending_confirmation",
        "items": normalized,
    }


def _ability_name_index(snapshot: EquipmentSourceSnapshot) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in snapshot.ability_documents:
        ability_list = document.data.get("AbilityList") if isinstance(document.data, dict) else None
        if not isinstance(ability_list, list):
            continue
        for row_index, row in enumerate(ability_list):
            if not isinstance(row, dict) or not row.get("Name"):
                continue
            ability_name = str(row["Name"])
            index[ability_name].append(
                {
                    "source_path": document.relative_path,
                    "raw_type": "AbilityList",
                    "raw_id": ability_name,
                    "json_path": f"$/AbilityList/{row_index}",
                }
            )
    return dict(index)


def _record_duplicate_keys(
    issues: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    keys: tuple[str, ...],
    issue_kind: str,
    *,
    missing_defaults: dict[str, Any] | None = None,
) -> None:
    counts: Counter[tuple[Any, ...]] = Counter()
    missing_defaults = missing_defaults or {}
    for row in rows:
        counts[tuple(row.get(key, missing_defaults.get(key)) for key in keys)] += 1
    for key, count in counts.items():
        if count > 1:
            issues.append(
                _issue(
                    issue_kind,
                    "table_key_uniqueness",
                    ":".join(str(value) for value in key),
                    "status_unknown",
                    count=count,
                    keys=list(keys),
                )
            )


def _issue(
    issue_kind: str,
    source_path: str,
    raw_id: Any,
    publication_status: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "issue_kind": issue_kind,
        "source_path": source_path,
        "raw_id": str(raw_id),
        "publication_status": publication_status if publication_status in PUBLICATION_STATES else "status_unknown",
        "details": details,
    }


def _publication_status(value: Any) -> str:
    if value is True:
        return "published"
    if value is False:
        return "unpublished"
    return "status_unknown"


def _walk_mechanism_value(
    value: Any,
    json_path: str,
    source_path: str,
    ability_name: str,
    add: Any,
    source_scope: str,
) -> None:
    if isinstance(value, dict):
        raw_type = value.get("$type")
        if isinstance(raw_type, str) and raw_type:
            add("raw_type", raw_type, source_path, ability_name, f"{json_path}/$type", source_scope)
            short = _short_type(raw_type)
            if short.startswith("By"):
                add("condition", raw_type, source_path, ability_name, f"{json_path}/$type", source_scope)
            if short.startswith("Target") or short == "Retarget":
                add("target_type", raw_type, source_path, ability_name, f"{json_path}/$type", source_scope)
            if short == "TargetAlias" and isinstance(value.get("Alias"), str):
                add("target_alias", value["Alias"], source_path, ability_name, f"{json_path}/Alias", source_scope)
        event = value.get("Event")
        if isinstance(event, str) and event:
            add("event", event, source_path, ability_name, f"{json_path}/Event", source_scope)
        read_info = value.get("ReadInfo")
        if isinstance(read_info, dict) and isinstance(read_info.get("Type"), str):
            add("dynamic_read_type", read_info["Type"], source_path, ability_name, f"{json_path}/ReadInfo/Type", source_scope)
        for key, nested in value.items():
            _walk_mechanism_value(
                nested,
                f"{json_path}/{_json_pointer_token(str(key))}",
                source_path,
                ability_name,
                add,
                source_scope,
            )
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_mechanism_value(nested, f"{json_path}/{index}", source_path, ability_name, add, source_scope)


def _classify_mechanism(dimension: str, raw_value: str) -> tuple[str, str, str]:
    if dimension == "event":
        if raw_value.endswith("_CL") or "ClientOnly" in raw_value:
            return "event", "non_gameplay", "explicit client marker in structured callback event"
        return "event", "gameplay", "structured modifier/ability callback event"
    if dimension == "condition":
        return "condition", "gameplay", "RPG.GameCore.By* structured predicate"
    if dimension in {"target_type", "target_alias"}:
        return "target", "gameplay", "structured target expression or alias"
    if dimension == "dynamic_read_type":
        return "dynamic_value", "gameplay", "structured DynamicValues.ReadInfo.Type binding"
    if dimension != "raw_type":
        return "unknown", "unknown", "unrecognized mechanism dimension retained for review"

    short = _short_type(raw_value)
    if "ClientOnly" in raw_value:
        return "client", "non_gameplay", "explicit client marker in structured raw type"
    if not raw_value.startswith("RPG.GameCore."):
        return "unknown", "unknown", "raw type is obfuscated or outside the recognized RPG.GameCore namespace"
    if short.startswith("By"):
        return "condition", "gameplay", "RPG.GameCore.By* structured predicate"
    if short.startswith("Target") or short == "Retarget":
        return "target", "gameplay", "RPG.GameCore target operation"
    if short in {"PredicateTaskList", "LoopExecuteTaskList", "IncludeTaskListTemplate"}:
        return "control_flow", "gameplay", "structured gameplay task-list control flow"
    if short.startswith(("DefineDynamicValue", "SetDynamicValue", "SetModifierDynamicValue")):
        return "dynamic_value", "gameplay", "structured dynamic-value operation"
    if short in {"AddModifier", "RemoveModifier", "RemoveSelfModifier", "Remodifier", "DispelStatus"}:
        return "status", "gameplay", "structured modifier/status mutation operation"
    if short == "StackProperty":
        return "property", "gameplay", "structured modifier property contribution"
    if short in {"ModifyDamageData", "DamageByAttackProperty", "AttackData"}:
        return "damage", "gameplay", "structured damage calculation or damage-data operation"
    if short in {"HealHP", "ModifyHealData"}:
        return "heal", "gameplay", "structured healing operation"
    if short in {"InitShield", "RemoveShield"}:
        return "shield", "gameplay", "structured shield operation"
    if short.startswith("LoseHP"):
        return "hp", "gameplay", "structured HP-loss operation"
    if short.startswith("ModifySP") or short.startswith("ModifyTeamBoostPoint"):
        return "resource", "gameplay", "structured team resource operation"
    if short in {"ModifyActionDelay", "ModifyCurrentSkillDelayCost"}:
        return "timeline", "gameplay", "structured action-delay/timeline operation"
    if short == "SetResilience":
        return "toughness", "gameplay", "structured resilience/toughness operation"
    if short == "RandomConfig":
        return "rng", "gameplay", "structured random-choice configuration"
    return "unknown", "unknown", "RPG.GameCore raw type has no reviewed P8-S0 mechanism-family rule"


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _short_type(value: str) -> str:
    return value.rsplit(".", 1)[-1]


def _combat_graph_markers(value: Any) -> set[str]:
    markers: set[str] = set()
    marker_keys = {"$type", "AbilityList", "AbilityName", "Modifiers", "ModifierMap", "_CallbackList", "OnStart", "Event"}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if str(key) in marker_keys and nested not in (None, "", [], {}):
                    markers.add(str(key))
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return markers


def _json_shape_sample(data: Any) -> dict[str, Any]:
    first: Any = None
    if isinstance(data, list) and data:
        first = data[0]
    elif isinstance(data, dict) and data:
        first = data[next(iter(data))]
    return {
        "root_type": "list" if isinstance(data, list) else "object" if isinstance(data, dict) else type(data).__name__,
        "record_count": len(data) if isinstance(data, (list, dict)) else (1 if data is not None else 0),
        "first_record_keys": sorted(str(key) for key in first) if isinstance(first, dict) else [],
    }


def _json_prefix_shape_sample(sample: bytes) -> dict[str, Any]:
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"root_type": "unknown", "record_count": None, "first_record_keys": [], "sample_parse_error": str(exc)}
    stripped = text.lstrip()
    try:
        if stripped.startswith("["):
            offset = len(text) - len(stripped) + 1
            while offset < len(text) and text[offset].isspace():
                offset += 1
            first, _ = json.JSONDecoder().raw_decode(text, offset)
            return {
                "root_type": "list_prefix",
                "record_count": None,
                "first_record_keys": sorted(str(key) for key in first) if isinstance(first, dict) else [],
            }
        if stripped.startswith("{"):
            first, _ = json.JSONDecoder().raw_decode(text, len(text) - len(stripped))
            return {
                "root_type": "object_prefix",
                "record_count": None,
                "first_record_keys": sorted(str(key) for key in first) if isinstance(first, dict) else [],
            }
    except (json.JSONDecodeError, ValueError) as exc:
        return {"root_type": "json_prefix", "record_count": None, "first_record_keys": [], "sample_parse_error": str(exc)}
    return {"root_type": "unknown", "record_count": None, "first_record_keys": [], "sample_parse_error": "prefix is not a JSON list/object"}


def _read_prefix(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _is_root_legacy_ability_mirror(relative_path: str) -> bool:
    return relative_path in {
        "Config/ConfigAbility/EquipmemtAbility.json",
        "Config/ConfigAbility/RelicAbility.json",
    }


def _auxiliary_policy_for_path(relative_path: str, basename: str) -> AuxiliaryPolicy | None:
    policy = AUXILIARY_TABLE_POLICIES.get(basename)
    if policy is not None:
        return policy
    if (
        relative_path.startswith("Config/ConfigAbility/BattleEvent/GridFight/")
        and "/EquipmentAbility/" in relative_path
    ):
        return AuxiliaryPolicy(
            "special_mode_equipment_ability_candidate",
            "unknown",
            "ability graph belongs to the structurally separate GridFight special-mode EquipmentAbility directory and is not a normal light-cone/relic source",
        )
    return None


def _list_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _list_values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
