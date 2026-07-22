from __future__ import annotations


def tbgd_dynamic_key_hash(value: str) -> int:
    """Return the signed 32-bit hash used by TBGD DynamicKey references."""

    if not isinstance(value, str) or not value:
        raise ValueError("dynamic key must be a non-empty string")
    raw = value.encode("utf-16-le")
    code_units = [
        raw[index] | (raw[index + 1] << 8)
        for index in range(0, len(raw), 2)
    ]
    first = 5381
    second = 5381
    index = 0
    while index < len(code_units):
        first = (((first << 5) + first) ^ code_units[index]) & 0xFFFFFFFF
        index += 1
        if index >= len(code_units):
            break
        second = (((second << 5) + second) ^ code_units[index]) & 0xFFFFFFFF
        index += 1
    result = (first + second * 1566083941) & 0xFFFFFFFF
    return result if result < 0x80000000 else result - 0x100000000
