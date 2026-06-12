
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
import json
import zipfile
import os
import re
from collections import Counter, defaultdict

from .core_rules import coerce_float, normalize_str_list


class TBGDDataError(RuntimeError):
    pass


def unwrap_value(v: Any) -> Any:
    """TurnBasedGameData often stores scalar numbers as {"Value": x}."""
    if isinstance(v, dict) and set(v.keys()) == {"Value"}:
        return unwrap_value(v["Value"])
    if isinstance(v, dict):
        return {k: unwrap_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [unwrap_value(x) for x in v]
    return v


def text_hash(v: Any) -> int | None:
    if isinstance(v, dict) and "Hash" in v:
        try:
            return int(v["Hash"])
        except Exception:
            return None
    return None


@dataclass
class TBGDSource:
    """Read-only source adapter for Dimbreath/TurnBasedGameData-like packages.

    It intentionally does not convert raw game configs directly into battle-kernel
    actions.  It only exposes stable, audited source catalogs used by a later
    ContentCompiler.  This keeps source-format compatibility outside the combat
    kernel.
    """

    root: Path
    zip_path: Path | None = None
    prefix: str = "turnbasedgamedata-main/"
    _names_cache: list[str] | None = field(default=None, init=False, repr=False)
    _names_set_cache: set[str] | None = field(default=None, init=False, repr=False)
    _excel_tables_cache: list[str] | None = field(default=None, init=False, repr=False)
    _table_cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "TBGDSource":
        p = Path(path)
        if not p.exists():
            raise TBGDDataError(f"TurnBasedGameData source does not exist: {p}")
        if p.is_file():
            if not zipfile.is_zipfile(p):
                raise TBGDDataError(f"Not a zip file: {p}")
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
            # Find the common root that contains ExcelOutput.
            prefixes = []
            for n in names:
                if n.endswith("ExcelOutput/AvatarConfig.json"):
                    prefixes.append(n[: -len("ExcelOutput/AvatarConfig.json")])
            prefix = prefixes[0] if prefixes else ""
            return cls(root=Path("."), zip_path=p, prefix=prefix)
        return cls(root=p, zip_path=None, prefix="")

    def _zip_names(self) -> list[str]:
        if not self.zip_path:
            return []
        if self._names_cache is None:
            with zipfile.ZipFile(self.zip_path) as z:
                self._names_cache = z.namelist()
        return self._names_cache

    def _zip_name_set(self) -> set[str]:
        if self._names_set_cache is None:
            self._names_set_cache = set(self._zip_names())
        return self._names_set_cache

    def exists(self, rel: str) -> bool:
        rel = rel.lstrip("/")
        if self.zip_path:
            target = self.prefix + rel
            return target in self._zip_name_set()
        return (self.root / rel).exists()

    def read_json(self, rel: str) -> Any:
        rel = rel.lstrip("/")
        if rel in self._table_cache:
            return self._table_cache[rel]
        if self.zip_path:
            target = self.prefix + rel
            with zipfile.ZipFile(self.zip_path) as z:
                try:
                    with z.open(target) as f:
                        data = json.load(f)
                        self._table_cache[rel] = data
                        return data
                except KeyError:
                    raise TBGDDataError(f"Missing JSON in source: {rel}") from None
        p = self.root / rel
        if not p.exists():
            raise TBGDDataError(f"Missing JSON in source: {rel}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._table_cache[rel] = data
            return data

    def list_files(self, prefix: str = "") -> list[str]:
        prefix = prefix.lstrip("/")
        if self.zip_path:
            names = []
            for n in self._zip_names():
                if not n.startswith(self.prefix):
                    continue
                rel = n[len(self.prefix):]
                if rel.startswith(prefix):
                    names.append(rel)
            return names
        root = self.root / prefix
        if not root.exists():
            return []
        if root.is_file():
            return [prefix]
        out = []
        for p in root.rglob("*"):
            if p.is_file():
                out.append(str(p.relative_to(self.root)).replace("\\", "/"))
        return out

    def list_excel_tables(self) -> list[str]:
        if self._excel_tables_cache is not None:
            return self._excel_tables_cache
        files = self.list_files("ExcelOutput/")
        out = []
        for rel in files:
            if rel.endswith(".json"):
                out.append(Path(rel).stem)
        self._excel_tables_cache = sorted(out)
        return self._excel_tables_cache

    def load_table(self, table: str) -> Any:
        return self.read_json(f"ExcelOutput/{table}.json")

    def file_inventory(self) -> dict[str, Any]:
        files = self.list_files("")
        top = Counter()
        second = Counter()
        json_count = 0
        total_known_size = None
        if self.zip_path:
            total_known_size = 0
            with zipfile.ZipFile(self.zip_path) as z:
                for info in z.infolist():
                    if not info.filename.startswith(self.prefix):
                        continue
                    rel = info.filename[len(self.prefix):]
                    if not rel:
                        continue
                    parts = rel.split("/")
                    top[parts[0]] += 1
                    if len(parts) > 1:
                        second["/".join(parts[:2])] += 1
                    if rel.endswith(".json"):
                        json_count += 1
                    total_known_size += info.file_size
        else:
            total_known_size = 0
            for rel in files:
                parts = rel.split("/")
                top[parts[0]] += 1
                if len(parts) > 1:
                    second["/".join(parts[:2])] += 1
                if rel.endswith(".json"):
                    json_count += 1
                try:
                    total_known_size += (self.root / rel).stat().st_size
                except Exception:
                    pass
        return {
            "source": str(self.zip_path or self.root),
            "prefix": self.prefix,
            "file_count": len(files),
            "json_file_count": json_count,
            "total_uncompressed_bytes": total_known_size,
            "top_directories": dict(top.most_common(30)),
            "major_directories": dict(second.most_common(60)),
            "excel_table_count": len(self.list_excel_tables()),
        }

    def build_avatar_catalog(self) -> list[dict[str, Any]]:
        rows = self.load_table("AvatarConfig")
        promo_rows = self.load_table("AvatarPromotionConfig") if "AvatarPromotionConfig" in self.list_excel_tables() else []
        promo_by_avatar: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in promo_rows:
            if "AvatarID" in r:
                promo_by_avatar[int(r["AvatarID"])].append(unwrap_value(r))
        out = []
        for r in rows:
            row = unwrap_value(r)
            aid = int(row.get("AvatarID"))
            promotions = sorted(promo_by_avatar.get(aid, []), key=lambda x: x.get("MaxLevel", 0))
            max_promo = promotions[-1] if promotions else {}
            out.append({
                "avatar_id": aid,
                "name_hash": text_hash(r.get("AvatarName")),
                "full_name_hash": text_hash(r.get("AvatarFullName")),
                "rarity": row.get("Rarity"),
                "element": row.get("DamageType"),
                "path": row.get("AvatarBaseType"),
                "max_energy": row.get("SPNeed"),
                "skill_ids": row.get("SkillList", []),
                "rank_ids": row.get("RankIDList", []),
                "config_path": row.get("JsonPath"),
                "base_stats_at_max_promotion": {
                    "atk_base": max_promo.get("AttackBase"),
                    "atk_add": max_promo.get("AttackAdd"),
                    "def_base": max_promo.get("DefenceBase"),
                    "def_add": max_promo.get("DefenceAdd"),
                    "hp_base": max_promo.get("HPBase"),
                    "hp_add": max_promo.get("HPAdd"),
                    "spd_base": max_promo.get("SpeedBase"),
                    "crit_rate": max_promo.get("CriticalChance"),
                    "crit_dmg": max_promo.get("CriticalDamage"),
                    "aggro": max_promo.get("BaseAggro"),
                    "max_level": max_promo.get("MaxLevel"),
                },
            })
        return out

    def build_equipment_catalog(self) -> list[dict[str, Any]]:
        rows = self.load_table("EquipmentConfig")
        skills = self.load_table("EquipmentSkillConfig") if "EquipmentSkillConfig" in self.list_excel_tables() else []
        skill_by_id = defaultdict(list)
        for s in skills:
            skill_by_id[int(s.get("SkillID"))].append(unwrap_value(s))
        out = []
        for r in rows:
            row = unwrap_value(r)
            eid = int(row.get("EquipmentID"))
            out.append({
                "equipment_id": eid,
                "name_hash": text_hash(r.get("EquipmentName")),
                "rarity": row.get("Rarity"),
                "path": row.get("AvatarBaseType"),
                "max_promotion": row.get("MaxPromotion"),
                "max_rank": row.get("MaxRank"),
                "skill_id": row.get("SkillID"),
                "skill_levels": skill_by_id.get(int(row.get("SkillID")), []),
            })
        return out

    def build_relic_set_catalog(self) -> list[dict[str, Any]]:
        sets = self.load_table("RelicSetConfig")
        skills = self.load_table("RelicSetSkillConfig") if "RelicSetSkillConfig" in self.list_excel_tables() else []
        by_set = defaultdict(list)
        for s in skills:
            by_set[int(s.get("SetID"))].append(unwrap_value(s))
        out = []
        for r in sets:
            row = unwrap_value(r)
            sid = int(row.get("SetID"))
            out.append({
                "set_id": sid,
                "name_hash": text_hash(r.get("SetName")),
                "set_skill_list": row.get("SetSkillList", []),
                "release": row.get("Release"),
                "release_version": row.get("ReleaseVersion"),
                "bonuses": sorted(by_set.get(sid, []), key=lambda x: x.get("RequireNum", 0)),
            })
        return out

    def build_monster_catalog(self) -> list[dict[str, Any]]:
        rows = self.load_table("MonsterConfig")
        out = []
        for r in rows:
            row = unwrap_value(r)
            out.append({
                "monster_id": row.get("MonsterID"),
                "template_id": row.get("MonsterTemplateID"),
                "name_hash": text_hash(r.get("MonsterName")),
                "level_group": row.get("HardLevelGroup"),
                "elite_group": row.get("EliteGroup"),
                "weaknesses": row.get("StanceWeakList", []),
                "resistances": row.get("DamageTypeResistance", []),
                "debuff_resist": row.get("DebuffResist", []),
                "summon_ids": row.get("SummonIDList", []),
                "skill_ids": row.get("SkillList", []),
                "ability_names": row.get("AbilityNameList", []),
                "override_ai_path": row.get("OverrideAIPath"),
            })
        return out

    def build_stage_catalog(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = self.load_table("StageConfig")
        out = []
        for r in rows[:limit]:
            row = unwrap_value(r)
            out.append({
                "stage_id": row.get("StageID"),
                "stage_type": row.get("StageType"),
                "name_hash": text_hash(r.get("StageName")),
                "hard_level_group": row.get("HardLevelGroup"),
                "level": row.get("Level"),
                "monster_list": row.get("MonsterList", []),
                "stage_config_data": row.get("StageConfigData", []),
                "stage_ability_config": row.get("StageAbilityConfig", []),
                "forbid_auto_battle": row.get("ForbidAutoBattle"),
                "trial_avatar_list": row.get("TrialAvatarList", []),
            })
        return out

    def core_catalog_summary(self) -> dict[str, Any]:
        tables = set(self.list_excel_tables())
        summary = {
            "inventory": self.file_inventory(),
            "core_tables": {},
            "content_counts": {},
            "representative_tables_present": {
                k: k in tables
                for k in [
                    "AvatarConfig", "AvatarSkillConfig", "AvatarPromotionConfig", "AvatarSkillTreeConfig",
                    "EquipmentConfig", "EquipmentSkillConfig", "RelicSetConfig", "RelicSetSkillConfig",
                    "MonsterConfig", "MonsterSkillConfig", "StageConfig", "MazeBuff",
                ]
            },
        }
        for t in ["AvatarConfig", "AvatarSkillConfig", "EquipmentConfig", "EquipmentSkillConfig", "RelicSetConfig", "RelicSetSkillConfig", "MonsterConfig", "MonsterSkillConfig", "StageConfig", "MazeBuff"]:
            if t in tables:
                data = self.load_table(t)
                summary["core_tables"][t] = {
                    "row_count": len(data) if hasattr(data, "__len__") else None,
                    "sample_keys": sorted(list(data[0].keys()))[:40] if isinstance(data, list) and data else [],
                }
        # Full catalog counts, without embedding all rows.
        try:
            summary["content_counts"]["avatars"] = len(self.build_avatar_catalog())
            summary["content_counts"]["light_cones"] = len(self.build_equipment_catalog())
            summary["content_counts"]["relic_sets"] = len(self.build_relic_set_catalog())
            summary["content_counts"]["monsters"] = len(self.build_monster_catalog())
            summary["content_counts"]["stages"] = len(self.load_table("StageConfig")) if "StageConfig" in tables else None
        except Exception as e:
            summary["catalog_error"] = str(e)
        return summary


def write_catalog_bundle(source_path: str | os.PathLike[str], out_dir: str | os.PathLike[str], include_stage_rows: int = 200) -> dict[str, Any]:
    src = TBGDSource.open(source_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = src.core_catalog_summary()

    catalogs = {
        "avatars": src.build_avatar_catalog(),
        "light_cones": src.build_equipment_catalog(),
        "relic_sets": src.build_relic_set_catalog(),
        "monsters": src.build_monster_catalog(),
        "stages_sample": src.build_stage_catalog(limit=include_stage_rows),
    }
    (out / "tbgd_source_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, data in catalogs.items():
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inspect and summarize TurnBasedGameData source packages")
    parser.add_argument("source", help="Path to turnbasedgamedata-main.zip or extracted directory")
    parser.add_argument("--output-dir", "-o", help="Write JSON catalog bundle to this directory")
    parser.add_argument("--summary", action="store_true", help="Print summary JSON")
    args = parser.parse_args(argv)
    src = TBGDSource.open(args.source)
    if args.output_dir:
        summary = write_catalog_bundle(args.source, args.output_dir)
    else:
        summary = src.core_catalog_summary()
    if args.summary or not args.output_dir:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
