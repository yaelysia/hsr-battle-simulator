from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from functools import lru_cache
from typing import Any


class FrozenJSONDict(dict[str, Any]):
    """dict-compatible recursively immutable JSON object."""

    # Every hashed node needs this slot; rare derived caches use a lazy dict.
    __slots__ = ("_json_tree_digest_cache", "__dict__")

    def __init__(self, values: Mapping[str, Any] | None = None):
        source = {} if values is None else values
        if not all(isinstance(key, str) for key in source):
            raise TypeError("JSON object keys must be strings")
        dict.__init__(self, {key: freeze_json(item) for key, item in source.items()})

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen JSON object cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self) -> FrozenJSONDict:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> FrozenJSONDict:
        return self


class FrozenJSONList(list[Any]):
    """list-compatible recursively immutable JSON array."""

    __slots__ = ("_json_tree_digest_cache", "__dict__")

    def __init__(self, values: list[Any] | tuple[Any, ...] = ()):
        list.__init__(self, [freeze_json(item) for item in values])

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen JSON array cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable

    def __copy__(self) -> FrozenJSONList:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> FrozenJSONList:
        return self


def freeze_json(value: Any) -> Any:
    """Freeze JSON containers while sharing exact internally-frozen subtrees."""

    if type(value) in (FrozenJSONDict, FrozenJSONList):
        return value
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        return FrozenJSONDict(value)
    if isinstance(value, (list, tuple)):
        return FrozenJSONList(value)
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


@lru_cache(maxsize=8192, typed=True)
def _scalar_tree_digest(value: None | bool | int | str) -> bytes:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).digest()


def json_tree_digest(value: Any) -> bytes:
    """Canonical typed tree digest; only immutable subtrees retain their digest.

    Fixed-size child digests and distinct container tags preserve boundaries.
    The cache follows each frozen object's lifetime, including shared branches.
    """
    value_type = type(value)
    # Most visited children are keys/identities, not containers. Resolve the
    # bounded scalar cache before testing container shape or object attributes.
    if value is None or value_type in (bool, int) or value_type is str and len(value) <= 512:
        return _scalar_tree_digest(value)
    frozen = value_type in (FrozenJSONDict, FrozenJSONList)
    cached = getattr(value, "_json_tree_digest_cache", None) if frozen else None
    if cached is not None:
        return cached
    if isinstance(value, dict):
        digest = hashlib.sha256(b"dict")
        for key, item in sorted(value.items()):
            digest.update(json_tree_digest(key))
            digest.update(json_tree_digest(item))
    elif isinstance(value, (list, tuple)):
        digest = hashlib.sha256(b"list")
        for item in value:
            digest.update(json_tree_digest(item))
    else:
        # Ponytail: cache short scalar values only (bounded to 8192 entries).
        # Floats stay uncached so +0.0/-0.0 retain distinct canonical identities.
        return hashlib.sha256(json.dumps(value, ensure_ascii=True, allow_nan=False,
            separators=(",", ":")).encode("utf-8")).digest()
    result = digest.digest()
    if frozen:
        value._json_tree_digest_cache = result
    return result


def thaw_json(value: Any) -> Any:
    """Return a detached mutable JSON tree from frozen or ordinary JSON input."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")
