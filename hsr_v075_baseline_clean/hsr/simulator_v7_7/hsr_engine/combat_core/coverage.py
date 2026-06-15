from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable

from .effect_registry import EffectRegistry


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk(child, f"{path}[{idx}]")


def _condition_type(cond: Any) -> str:
    if isinstance(cond, dict):
        return str(cond.get("type") or cond.get("op") or "dict_condition")
    if isinstance(cond, str):
        return "string_condition"
    if isinstance(cond, bool):
        return "bool_condition"
    return type(cond).__name__


EFFECT_PATH_RE = re.compile(r"\.(effects|effects_[A-Za-z0-9_]+|effects_if_true|effects_if_false)\[\d+\]$")


def _is_effect_node(path: str, value: dict[str, Any]) -> bool:
    if not isinstance(value.get("type"), str):
        return False
    return bool(EFFECT_PATH_RE.search(path))


def build_canonical_ir_coverage_matrix(case: dict[str, Any], registry: EffectRegistry | None = None) -> dict[str, Any]:
    """Scan simulator-facing Canonical IR/case data for clean-core coverage."""

    registry = registry or EffectRegistry()
    effects: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []
    for path, value in _walk(case):
        if isinstance(value, dict) and _is_effect_node(path, value):
            raw_type = str(value.get("type") or "")
            canonical = registry.canonical_type(raw_type)
            if canonical in registry.handlers:
                status = "executable"
            elif raw_type != canonical:
                status = "supported_alias"
            else:
                status = "legacy_fallback"
            effects.append(
                {
                    "path": path,
                    "effect_type": raw_type,
                    "canonical_type": canonical,
                    "status": status,
                    "source_path": value.get("source_path", ""),
                    "raw_type": value.get("raw_type", value.get("source_node_type", "")),
                    "raw_id": value.get("raw_id", value.get("id", "")),
                    "keys": sorted(str(k) for k in value.keys()),
                }
            )
        if isinstance(value, dict) and "condition" in value:
            cond = value.get("condition")
            conditions.append(
                {
                    "path": f"{path}.condition",
                    "condition_type": _condition_type(cond),
                    "status": "legacy_callback",
                    "source_path": value.get("source_path", ""),
                }
            )
        if isinstance(value, dict):
            for key in ("formula", "expression", "dynamic_value", "scaling"):
                if key in value:
                    formulas.append(
                        {
                            "path": f"{path}.{key}",
                            "formula_type": key,
                            "status": "legacy_callback",
                            "source_path": value.get("source_path", ""),
                        }
                    )

    def summarize(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            typ = str(row.get(key) or "")
            by_status[status] = by_status.get(status, 0) + 1
            by_type[typ] = by_type.get(typ, 0) + 1
        return {"count": len(rows), "by_status": by_status, "by_type": by_type}

    return {
        "encoding": "hsr.clean_core.canonical_ir_coverage.v1",
        "effects": {
            "summary": summarize(effects, "effect_type"),
            "records": effects,
        },
        "conditions": {
            "summary": summarize(conditions, "condition_type"),
            "records": conditions,
        },
        "formulas": {
            "summary": summarize(formulas, "formula_type"),
            "records": formulas,
        },
        "case_metadata": deepcopy(case.get("metadata") or {}),
    }
