"""Switchable eager identity audits (2026-11-10 direction correction).

Per-construction identity rehashing is a debugging and testing capability, not
a runtime invariant: correctness is judged by game-value comparison, and atomic
commit plus determinism do not depend on these checks. They default to off so
execution hot paths do not pay audit costs; enable them with
``HSR_EAGER_IDENTITY_AUDIT=1`` or :func:`set_eager_identity_audit` when tracing a
concrete identity problem. Disabling a check never relaxes atomic commit, RNG
determinism, or the identity values themselves.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_ENABLED = os.environ.get("HSR_EAGER_IDENTITY_AUDIT", "") == "1"

# Standalone L1 calculations retain their explanatory API. The public session
# explicitly selects compact diagnostics unless full tracing is requested.
_DETAILED_DIAGNOSTICS = ContextVar("hsr_detailed_diagnostics", default=True)


@contextmanager
def diagnostic_detail(enabled: bool):
    token = _DETAILED_DIAGNOSTICS.set(enabled)
    try:
        yield
    finally:
        _DETAILED_DIAGNOSTICS.reset(token)


def detailed_diagnostics_enabled() -> bool:
    return _DETAILED_DIAGNOSTICS.get()


def source_reference(source: Mapping[str, Any]) -> dict[str, Any]:
    if detailed_diagnostics_enabled():
        return dict(source)
    reference = {
        key: value for key, value in source.items()
        if (key in {"source_path", "raw_type", "raw_id", "json_path", "content_sha256", "row_index"}
            or key.endswith(("_id", "_ref")))
        and isinstance(value, (str, int, float, bool, type(None)))
    }
    evidence = source.get("evidence")
    if isinstance(evidence, Mapping):
        reference["evidence"] = {key: evidence[key] for key in
                                 ("json_path", "content_sha256", "row_index") if key in evidence}
    for key in ("effect_source", "ability_task_source", "status_source", "break_template_source"):
        nested = source.get(key)
        if isinstance(nested, Mapping):
            reference[key] = source_reference(nested)
    return reference


def diagnostic_json(value: Any) -> Any:
    """Trim explanatory source trees, preserving numerical and identity fields."""
    if detailed_diagnostics_enabled():
        return value
    if isinstance(value, Mapping):
        if {"source_path", "raw_type", "raw_id"} <= value.keys() <= {
            "source_path", "raw_type", "raw_id", "evidence",
        }:
            return source_reference(value)
        return {
            key: item if key == "source_frame" else
            source_reference(item) if key == "source_trace" and isinstance(item, Mapping) else
            diagnostic_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [diagnostic_json(item) for item in value]
    return value


def eager_identity_audit_enabled() -> bool:
    return _ENABLED


def set_eager_identity_audit(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)
