"""Phase 1: StatusID→中文名/类型注册表。

从 TBGD StatusConfig.json 构建索引，通过 TextMap 解析中文名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tbgd_loader import TBGDSource
    from .text_map_registry import TextMapRegistry


@dataclass
class StatusInfo:
    """单个 Status 的元信息。"""

    status_id: int
    modifier_name: str                          # 内部 modifier 名
    name_cn: str                                # 中文名（通过 TextMap 解析）
    desc_cn: str = ""                           # 中文描述
    status_type: str = ""                       # Buff / Debuff / Other
    icon_path: str = ""
    read_params: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class StatusRegistry:
    """惰性加载的 Status 注册表。

    用法::

        status_reg = StatusRegistry(tbgd_source)
        se_info = status_reg.lookup(64888024)
        print(se_info.name_cn)  # → "攻击力提高"
    """

    def __init__(self, source: TBGDSource, text_map: TextMapRegistry) -> None:
        self._source = source
        self._text_map = text_map
        self._by_id: dict[int, StatusInfo] | None = None
        self._by_modifier: dict[str, StatusInfo] | None = None

    @property
    def loaded(self) -> bool:
        return self._by_id is not None

    def _ensure_loaded(self) -> None:
        if self._by_id is not None:
            return

        table = self._source.load_table("StatusConfig")
        self._by_id = {}
        self._by_modifier = {}

        for row in table:
            sid = row.get("StatusID")
            if sid is None:
                continue
            try:
                sid = int(sid)
            except (ValueError, TypeError):
                continue

            name_hash = 0
            name_obj = row.get("StatusName", {})
            if isinstance(name_obj, dict):
                name_hash = name_obj.get("Hash", 0)

            desc_hash = 0
            desc_obj = row.get("StatusDesc", {})
            if isinstance(desc_obj, dict):
                desc_hash = desc_obj.get("Hash", 0)

            info = StatusInfo(
                status_id=sid,
                modifier_name=row.get("ModifierName", ""),
                name_cn=self._text_map.lookup(name_hash),
                desc_cn=self._text_map.lookup(desc_hash),
                status_type=row.get("StatusType", ""),
                icon_path=row.get("StatusIconPath", ""),
                read_params=row.get("ReadParamList", []),
                tags=row.get("TagList", []),
            )
            self._by_id[sid] = info

            mod_name = info.modifier_name
            if mod_name:
                self._by_modifier[mod_name] = info

    def lookup(self, status_id: int) -> StatusInfo | None:
        """按 StatusID 查询。"""
        self._ensure_loaded()
        assert self._by_id is not None
        return self._by_id.get(status_id)

    def lookup_by_modifier(self, modifier_name: str) -> StatusInfo | None:
        """按内部 ModifierName 查询。"""
        self._ensure_loaded()
        assert self._by_modifier is not None
        return self._by_modifier.get(modifier_name)

    def __contains__(self, status_id: int) -> bool:
        self._ensure_loaded()
        assert self._by_id is not None
        return status_id in self._by_id

    def __len__(self) -> int:
        self._ensure_loaded()
        assert self._by_id is not None
        return len(self._by_id)
