"""Phase 1: TBGD 数据注册表 — 中文名/元信息查询。

本包提供从 TBGD 提取的中文名和元信息注册表，供引擎快照使用。

模块：
- text_map_registry: Hash→中文文本（TextMapCHS.json）
- status_registry: StatusID→中文名/类型（StatusConfig.json）
- skill_registry: SkillID→中文名/描述（AvatarSkillConfig + MonsterSkillConfig）
"""

from .text_map_registry import TextMapRegistry
from .status_registry import StatusRegistry, StatusInfo
from .skill_registry import SkillRegistry, SkillInfo

__all__ = [
    "TextMapRegistry",
    "StatusRegistry",
    "StatusInfo",
    "SkillRegistry",
    "SkillInfo",
]
