"""Phase 1: SkillID→中文名/类型注册表。

从 TBGD AvatarSkillConfig.json 和 MonsterSkillConfig.json 构建索引。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tbgd_loader import TBGDSource
    from .text_map_registry import TextMapRegistry


@dataclass
class SkillInfo:
    """单个技能的元信息。"""

    skill_id: int
    name_cn: str = ""                       # 技能中文名
    tag_cn: str = ""                        # 标签中文名（单攻/扩散/群攻等）
    type_desc_cn: str = ""                  # 类型描述（普攻/战技/终结技等）
    desc_cn: str = ""                       # 技能描述
    trigger_key: str = ""                   # Skill01/Skill02/...
    attack_type: str = ""                   # Normal / ...
    skill_effect: str = ""                  # SingleAttack / Blast / AOE / ...
    damage_type: str = ""                   # 伤害元素
    icon_path: str = ""                     # 技能图标路径
    owner_type: str = ""                    # "avatar" | "monster"
    max_level: int = 1
    param_list: list[float] = field(default_factory=list)  # 技能参数（Level 1）
    toughness_damage_list: list[float] = field(default_factory=list)  # 削韧显示值


class SkillRegistry:
    """惰性加载的技能注册表。

    用法::

        skill_reg = SkillRegistry(tbgd_source)
        info = skill_reg.lookup(110201)
        print(info.name_cn)  # → "强袭"
    """

    def __init__(self, source: TBGDSource, text_map: TextMapRegistry) -> None:
        self._source = source
        self._text_map = text_map
        self._by_id: dict[int, SkillInfo] | None = None

    @property
    def loaded(self) -> bool:
        return self._by_id is not None

    def _ensure_loaded(self) -> None:
        if self._by_id is not None:
            return
        self._by_id = {}
        self._load_avatar_skills()
        self._load_monster_skills()

    def _resolve_hash(self, obj) -> int:
        """提取 Hash 值。"""
        if isinstance(obj, dict):
            return obj.get("Hash", 0)
        return 0

    def _resolve_value(self, obj) -> float:
        """提取 Value 包装的数值。"""
        if isinstance(obj, dict) and "Value" in obj:
            v = obj["Value"]
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
        try:
            return float(obj)
        except (ValueError, TypeError):
            return 0.0

    def _load_table(self, table_name: str, owner_type: str) -> None:
        assert self._by_id is not None
        table = self._source.load_table(table_name)
        # 技能表按 Level 展开，同一 SkillID 有多个 Level 行
        # 只取 Level 1 作为元信息
        seen: set[int] = set()

        for row in table:
            sid = row.get("SkillID")
            if sid is None:
                continue
            try:
                sid = int(sid)
            except (ValueError, TypeError):
                continue

            if sid in seen:
                continue
            seen.add(sid)

            name_cn = self._text_map.lookup(self._resolve_hash(row.get("SkillName", {})))
            tag_cn = self._text_map.lookup(self._resolve_hash(row.get("SkillTag", {})))
            type_desc_cn = self._text_map.lookup(self._resolve_hash(row.get("SkillTypeDesc", {})))
            desc_cn = self._text_map.lookup(self._resolve_hash(row.get("SkillDesc", {})))

            param_list = [self._resolve_value(v) for v in row.get("ParamList", [])]
            stance_list = [self._resolve_value(v) for v in row.get("ShowStanceList", [])]

            info = SkillInfo(
                skill_id=sid,
                name_cn=name_cn,
                tag_cn=tag_cn,
                type_desc_cn=type_desc_cn,
                desc_cn=desc_cn,
                trigger_key=row.get("SkillTriggerKey", ""),
                attack_type=row.get("AttackType", ""),
                skill_effect=row.get("SkillEffect", ""),
                damage_type=row.get("DamageType", ""),
                icon_path=row.get("SkillIcon", ""),
                owner_type=owner_type,
                max_level=row.get("MaxLevel", 1),
                param_list=param_list,
                toughness_damage_list=stance_list,
            )
            self._by_id[sid] = info

    def _load_avatar_skills(self) -> None:
        self._load_table("AvatarSkillConfig", "avatar")

    def _load_monster_skills(self) -> None:
        self._load_table("MonsterSkillConfig", "monster")

    def lookup(self, skill_id: int) -> SkillInfo | None:
        """按 SkillID 查询。"""
        self._ensure_loaded()
        assert self._by_id is not None
        return self._by_id.get(skill_id)

    def __contains__(self, skill_id: int) -> bool:
        self._ensure_loaded()
        assert self._by_id is not None
        return skill_id in self._by_id

    def __len__(self) -> int:
        self._ensure_loaded()
        assert self._by_id is not None
        return len(self._by_id)
