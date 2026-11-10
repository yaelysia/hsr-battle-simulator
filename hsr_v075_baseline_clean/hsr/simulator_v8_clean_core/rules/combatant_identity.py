"""Numeric identity comes only from a canonical combatant definition reference."""
from __future__ import annotations


def combatant_character_id(unit) -> int | None:
    reference = getattr(unit, "template_id", None)
    if not isinstance(reference, str):
        return None
    namespace, separator, raw_id = reference.partition(":")
    if (separator != ":" or namespace not in {"avatar", "servant", "monster"}
            or not raw_id.isascii() or not raw_id.isdecimal()
            or not 0 < int(raw_id) <= 2 ** 53):
        return None
    return int(raw_id)
