from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


class FrozenJSONDict(dict[str, Any]):
    """dict-compatible recursively immutable JSON object."""

    def __init__(self, values: Mapping[str, Any] | None = None):
        source = values or {}
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
    """Normalize a JSON-like value into a detached immutable tree."""

    if isinstance(value, (FrozenJSONDict, FrozenJSONList)):
        return value
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return FrozenJSONDict({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return FrozenJSONList([freeze_json(item) for item in value])
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


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
