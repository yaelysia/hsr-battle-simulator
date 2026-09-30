"""Strict local archive I/O and replay verification for :mod:`session`."""
from __future__ import annotations

import json
import gzip
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from .builds.manifest import canonical_ir_fingerprint
from .rules.rulebook import RuleBook
from .session import BattleSession, SESSION_SCHEMA, command_from_json


_ARCHIVE_FIELDS = frozenset(
    {
        "schema_version",
        "canonical_ir_fingerprint",
        "scenario",
        "initial_snapshot",
        "setup_audit",
        "initialization",
        "operations",
        "final_snapshot",
        "outcome",
    }
)


def read_archive(path: str | Path) -> dict[str, Any]:
    """Read one archive while rejecting ambiguous or non-standard JSON."""
    target = Path(path)
    try:
        if target.suffix == ".gz":
            text = gzip.decompress(target.read_bytes()).decode("utf-8")
        else:
            text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("archive is not valid UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
            parse_float=_finite_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"archive JSON is invalid: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("archive root must be an object")
    return value


def write_archive(path: str | Path, data: dict[str, Any]) -> Path:
    """Atomically publish an archive without replacing an existing file."""
    if not isinstance(data, dict):
        raise TypeError("archive data must be an object")
    target = Path(path)
    if not target.name:
        raise ValueError("archive path must name a file")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"archive directory does not exist: {target.parent}")
    try:
        payload = _canonical_json(data).encode("utf-8") + b"\n"
        if target.suffix == ".gz":
            payload = gzip.compress(payload, compresslevel=6, mtime=0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"archive data is not strict JSON: {exc}") from exc

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileExistsError(f"archive already exists: {target}") from exc
        _fsync_directory(target.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def verify_archive(archive: dict[str, Any], rules: RuleBook) -> dict[str, Any]:
    """Rebuild and replay a session archive through the DecisionSystem boundary."""
    if not isinstance(archive, dict):
        return _failed(0, "archive_root_invalid")
    if archive.get("schema_version") != SESSION_SCHEMA:
        return _failed(0, "schema_version_mismatch")
    if not isinstance(rules, RuleBook):
        return _failed(0, "rules_invalid")
    fingerprint = archive.get("canonical_ir_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return _failed(0, "canonical_ir_fingerprint_invalid")
    if fingerprint != canonical_ir_fingerprint(rules.ir):
        return _failed(0, "canonical_ir_fingerprint_mismatch")
    try:
        _validate_archive_shape(archive)
    except (TypeError, ValueError) as exc:
        return _failed(0, f"archive_invalid:{exc}")
    try:
        session = BattleSession(rules, archive["scenario"])
    except (TypeError, ValueError, KeyError) as exc:
        return _failed(0, f"session_rebuild_failed:{type(exc).__name__}:{exc}")

    if not _json_equal(session.initial_snapshot, archive["initial_snapshot"]):
        return _failed(0, "initial_snapshot_mismatch")
    if not _json_equal(session.setup_audit, archive["setup_audit"]):
        return _failed(0, "setup_audit_mismatch")
    if not _json_equal(session.initialization, archive["initialization"]):
        return _failed(0, "initialization_mismatch")

    step_count = 0
    for index, operation in enumerate(archive["operations"]):
        try:
            _replay_operation(session, operation)
        except (TypeError, ValueError, KeyError) as exc:
            return _failed(step_count, f"operation[{index}]_invalid:{type(exc).__name__}:{exc}")
        actual = session.operations[-1]
        if not _json_equal(actual, operation):
            return _failed(step_count, f"operation[{index}]_mismatch")
        step_count += 1

    if not _json_equal(session.state.snapshot().to_json(), archive["final_snapshot"]):
        return _failed(step_count, "final_snapshot_mismatch")
    if session.outcome != archive["outcome"]:
        return _failed(step_count, "outcome_mismatch")
    return {"ok": True, "step_count": step_count, "errors": []}


def _replay_operation(session: BattleSession, operation: Any) -> None:
    if not isinstance(operation, dict):
        raise TypeError("operation must be an object")
    kind = operation.get("kind")
    if kind == "advance":
        if set(operation) != {"kind", "decision_id", "blocked_reason", "transitions"}:
            raise ValueError("advance operation fields mismatch")
        if operation["decision_id"] is not None and not isinstance(operation["decision_id"], str):
            raise TypeError("advance operation decision_id must be a string or null")
        if not isinstance(operation["blocked_reason"], str):
            raise TypeError("advance operation blocked_reason must be a string")
        if not isinstance(operation["transitions"], list):
            raise TypeError("advance operation transitions must be an array")
        session.advance()
        return
    if kind == "submit":
        if set(operation) != {"kind", "command", "transition"}:
            raise ValueError("submit operation fields mismatch")
        if not isinstance(operation["command"], dict):
            raise TypeError("submit operation command must be an object")
        if not isinstance(operation["transition"], dict):
            raise TypeError("submit operation transition must be an object")
        session.submit(command_from_json(operation["command"]))
        return
    raise ValueError("operation kind is unsupported")


def _validate_archive_shape(archive: dict[str, Any]) -> None:
    if set(archive) != _ARCHIVE_FIELDS:
        missing = sorted(_ARCHIVE_FIELDS - set(archive))
        extra = sorted(set(archive) - _ARCHIVE_FIELDS)
        raise ValueError(f"archive fields mismatch: missing={missing}, extra={extra}")
    for field_name in (
        "scenario",
        "initial_snapshot",
        "setup_audit",
        "initialization",
        "final_snapshot",
    ):
        if not isinstance(archive[field_name], dict):
            raise TypeError(f"archive.{field_name} must be an object")
    if not isinstance(archive["operations"], list):
        raise TypeError("archive.operations must be an array")
    if not isinstance(archive["outcome"], str):
        raise TypeError("archive.outcome must be a string")
    _canonical_json(archive)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"archive JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"archive JSON contains non-finite number: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _reject_json_constant(value)
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_equal(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _failed(step_count: int, error: str) -> dict[str, Any]:
    return {"ok": False, "step_count": step_count, "errors": [error]}


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
