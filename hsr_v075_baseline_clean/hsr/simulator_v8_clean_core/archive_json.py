"""Lossless JSON graph encoding for audit output; never a combat-rule input."""
from __future__ import annotations

import json
from typing import Any


ARCHIVE_FORMAT = "hsr_battle_archive_v2"


def encode_archive_json(value: dict[str, Any]) -> dict[str, Any]:
    """Store each distinct container once, with children preceding parents."""
    objects: list[Any] = []
    identities: dict[int, int] = {}
    signatures: dict[tuple[Any, ...], int] = {}
    visiting: set[int] = set()

    def visit(item: Any) -> tuple[Any, tuple[Any, ...]]:
        if not isinstance(item, (dict, list, tuple)):
            if type(item) not in (str, int, float, bool, type(None)):
                raise TypeError(f"unsupported JSON value: {type(item).__name__}")
            # JSON spelling distinguishes bool/int/float and signed zero.
            return item, ("scalar", json.dumps(item, allow_nan=False, ensure_ascii=False))
        identity = id(item)
        if identity in visiting:
            raise ValueError("circular JSON container")
        if identity in identities:
            index = identities[identity]
            return {"$ref": index}, ("ref", index)
        visiting.add(identity)
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("JSON object keys must be strings")
            children = [(key, visit(item[key])) for key in sorted(item)]
            record = ["object", {key: child[0] for key, child in children}]
            signature = ("object", tuple((key, child[1]) for key, child in children))
        else:
            children = [visit(child) for child in item]
            record = ["array", [child[0] for child in children]]
            signature = ("array", tuple(child[1] for child in children))
        visiting.remove(identity)
        index = signatures.get(signature)
        if index is None:
            index = len(objects)
            objects.append(record)
            signatures[signature] = index
        identities[identity] = index
        return {"$ref": index}, ("ref", index)

    if not isinstance(value, dict):
        raise TypeError("archive root must be an object")
    root, _ = visit(value)
    return {"format": ARCHIVE_FORMAT, "root": root["$ref"], "objects": objects}


def decode_archive_json(envelope: Any) -> dict[str, Any]:
    """Resolve only earlier references, rejecting cycles and unreferenced data."""
    if (not isinstance(envelope, dict) or set(envelope) != {"format", "root", "objects"}
            or envelope["format"] != ARCHIVE_FORMAT):
        raise ValueError(f"unsupported archive format; expected {ARCHIVE_FORMAT}")
    records, root = envelope["objects"], envelope["root"]
    if (not isinstance(records, list) or not records or type(root) is not int
            or root != len(records) - 1):
        raise ValueError("archive root must reference the final object")
    objects: list[Any] = []
    referenced: set[int] = set()

    def resolve(item: Any) -> Any:
        if isinstance(item, dict):
            index = item.get("$ref")
            if set(item) != {"$ref"} or type(index) is not int or not 0 <= index < len(objects):
                raise ValueError("archive reference must point to an earlier object")
            referenced.add(index)
            return objects[index]
        if type(item) not in (str, int, float, bool, type(None)):
            raise ValueError("archive container must use an object reference")
        json.dumps(item, allow_nan=False)
        return item

    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            raise ValueError("archive object record is invalid")
        kind, payload = record
        if kind == "object" and isinstance(payload, dict):
            if not all(isinstance(key, str) for key in payload):
                raise ValueError("archive object keys must be strings")
            objects.append({key: resolve(item) for key, item in payload.items()})
        elif kind == "array" and isinstance(payload, list):
            objects.append([resolve(item) for item in payload])
        else:
            raise ValueError("archive object kind or payload is invalid")
    if referenced != set(range(root)):
        raise ValueError("archive contains unreferenced objects")
    if not isinstance(objects[root], dict):
        raise ValueError("archive root must be an object")
    return objects[root]


def validate_json_graph(value: Any) -> None:
    """Validate shared JSON subtrees once without expanding them into text."""
    seen: set[int] = set()
    visiting: set[int] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, (dict, list, tuple)):
            if type(item) not in (str, int, float, bool, type(None)):
                raise TypeError(f"unsupported JSON value: {type(item).__name__}")
            if isinstance(item, float):
                json.dumps(item, allow_nan=False)
            return
        identity = id(item)
        if identity in visiting:
            raise ValueError("circular JSON container")
        if identity in seen:
            return
        visiting.add(identity)
        if isinstance(item, dict) and not all(isinstance(key, str) for key in item):
            raise TypeError("JSON object keys must be strings")
        for child in item.values() if isinstance(item, dict) else item:
            visit(child)
        visiting.remove(identity)
        seen.add(identity)

    visit(value)
