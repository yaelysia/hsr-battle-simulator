"""Strict native named-boolean source registration; no runtime raw syntax.

Source-risk note (2026-11-06 review): the archived
docs/archive/character/CHARACTER_ABILITY_SCOPE_LEDGER.md still classifies
AGAGMFCPBED / DFDELJOIGBJ as combat_decode_required. This mapping is inferred
from the native write/read shapes and the RawString key template, not from
cited research; keep or fail-close it as a user decision before freeze.
"""
from __future__ import annotations
import re


def boolean_opcode(opcode: str) -> str:
    return {"AGAGMFCPBED": "ByNamedBooleanFlag", "DFDELJOIGBJ": "SetNamedBooleanFlag"}.get(opcode, opcode)


def compile_named_key(value):
    if isinstance(value, str):
        text, interpolate = value, False
    elif isinstance(value, dict) and set(value) == {"Value"} and isinstance(value["Value"], str):
        text, interpolate = value["Value"], False
    elif isinstance(value, dict) and set(value) == {"RawString"} and isinstance(value["RawString"], str):
        text, interpolate = value["RawString"], True
    else:
        raise ValueError("named_key_source_shape_not_admitted")
    if not text:
        raise ValueError("named_key_empty")
    parts = []
    cursor = 0
    if interpolate:
        for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", text):
            literal = text[cursor:match.start()]
            if "{" in literal or "}" in literal:
                raise ValueError("named_key_template_not_admitted")
            if literal:
                parts.append({"literal": literal})
            parts.append({"parameter": match.group(1)})
            cursor = match.end()
    tail = text[cursor:]
    if interpolate and ("{" in tail or "}" in tail):
        raise ValueError("named_key_template_not_admitted")
    if tail:
        parts.append({"literal": tail})
    return {"schema_version": "hsr.named_key.v1", "parts": parts}


def normalize_boolean_source(raw, opcode):
    """Return canonical fields while retaining the original node as provenance."""
    expected = {"$type", "HILNFHCPEAD", "FHLJGDGMMHK"}
    if opcode == "SetNamedBooleanFlag":
        expected.add("EKFIEAALOFF")
        if set(raw) != expected or type(raw.get("EKFIEAALOFF")) is not bool:
            raise ValueError("named_boolean_write_shape_not_admitted")
    elif opcode == "ByNamedBooleanFlag":
        if not expected.issubset(raw) or set(raw) - expected - {"Inverse"} or type(raw.get("Inverse", False)) is not bool:
            raise ValueError("named_boolean_read_shape_not_admitted")
    else:
        raise ValueError("named_boolean_opcode_not_admitted")
    target = raw["HILNFHCPEAD"]
    if not isinstance(target, dict) or set(target) != {"$type", "Alias"} or target["$type"] != "RPG.GameCore.TargetAlias" or not isinstance(target["Alias"], str) or not target["Alias"]:
        raise ValueError("named_boolean_target_not_admitted")
    result = {"TargetType": target, "KeyExpression": compile_named_key(raw["FHLJGDGMMHK"])}
    result["Value" if opcode == "SetNamedBooleanFlag" else "Inverse"] = raw["EKFIEAALOFF"] if opcode == "SetNamedBooleanFlag" else raw.get("Inverse", False)
    return result
