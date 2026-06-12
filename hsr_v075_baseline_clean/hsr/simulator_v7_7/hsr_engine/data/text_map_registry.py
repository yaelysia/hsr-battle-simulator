"""Phase 1: TextMap hash→中文注册表。

使用 TBGDSource 加载 TextMapCHS.json，提供 O(1) 的 Hash→文本查询。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tbgd_loader import TBGDSource


class TextMapRegistry:
    """惰性加载的中文 TextMap 注册表。

    用法::

        tbgd = TBGDSource.open("path/to/tbgd")
        text_map = TextMapRegistry(tbgd)
        name = text_map.lookup(6186714091647966180)  # → "三月七"
    """

    def __init__(self, source: TBGDSource, *, language: str = "CHS") -> None:
        self._source = source
        self._language = language
        self._map: dict[int, str] | None = None
        self._path = f"TextMap/TextMap{language}.json"

    @property
    def loaded(self) -> bool:
        return self._map is not None

    def _ensure_loaded(self) -> None:
        if self._map is not None:
            return
        raw = self._source.read_json(self._path)
        # raw 格式: {"12345678": "中文文本", ...}
        # keys 是字符串形式的 hash
        self._map = {}
        for k, v in raw.items():
            try:
                self._map[int(k)] = v
            except (ValueError, TypeError):
                pass

    def lookup(self, hash_value: int | str) -> str:
        """按 Hash 查询中文文本，未找到返回空字符串。"""
        self._ensure_loaded()
        assert self._map is not None
        if isinstance(hash_value, str):
            try:
                hash_value = int(hash_value)
            except (ValueError, TypeError):
                return ""
        return self._map.get(hash_value, "")

    def __contains__(self, hash_value: int | str) -> bool:
        self._ensure_loaded()
        assert self._map is not None
        if isinstance(hash_value, str):
            try:
                hash_value = int(hash_value)
            except (ValueError, TypeError):
                return False
        return hash_value in self._map
