"""Strict local archive I/O and replay verification for :mod:`session`."""
from __future__ import annotations

import json
import gzip
import io
import math
import os
from contextlib import nullcontext
from pathlib import Path
import tempfile
from typing import Any, Callable

from .archive_json import decode_archive_json, encode_archive_json, validate_json_graph
from .builds.manifest import rulebook_fingerprint
from .rules.rulebook import RuleBook
from .session import BattleSession, SESSION_SCHEMA, command_from_json


_ARCHIVE_FIELDS = frozenset(
    {
        "schema_version",
        "diagnostics",
        "rules_fingerprint",
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
    """Read one v2 archive without expanding shared evidence."""
    return decode_archive_json(read_json_object(path))


def read_json_object(path: str | Path) -> dict[str, Any]:
    """Read a strict JSON object used by scenarios, scripts and archive envelopes."""
    target = Path(path)
    opener = gzip.open if target.suffix == ".gz" else open
    try:
        with opener(target, "rt", encoding="utf-8") as stream:
            value = json.load(stream, object_pairs_hook=_unique_object,
                              parse_constant=_reject_json_constant, parse_float=_finite_float)
    except UnicodeDecodeError as exc:
        raise ValueError("archive is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"archive JSON is invalid: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
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
        encoded_data = encode_archive_json(data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"archive data is not strict JSON: {exc}") from exc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            encoded = (gzip.GzipFile(filename="", fileobj=stream, mode="wb", compresslevel=6, mtime=0)
                       if target.suffix == ".gz" else nullcontext(stream))
            with encoded as output:
                text = io.TextIOWrapper(output, encoding="utf-8", newline="\n")
                try:
                    json.dump(encoded_data, text, allow_nan=False, ensure_ascii=False,
                              separators=(",", ":"), sort_keys=True)
                    text.write("\n")
                    text.flush()
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"archive data is not strict JSON: {exc}") from exc
                finally:
                    text.detach()
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
    return _verify_archive(archive, rules)[0]


def replay_archive(path: str | Path, rules_factory: Callable[[dict[str, Any]], RuleBook]) -> dict[str, Any]:
    """Read shared audit evidence and replay through the formal session boundary."""
    archive = read_archive(path)
    _validate_archive_shape(archive)
    return _verify_archive(archive, rules_factory(archive["scenario"]))[0]


def restore_session(archive: dict[str, Any], rules: RuleBook) -> BattleSession:
    """Return only a fully replayed and verified session, retaining its history."""
    from copy import deepcopy

    report, session = _verify_archive(archive, rules, retain_boundaries=True)
    if session is None:
        raise ValueError("archive_restore_failed:" + ";".join(report["errors"]))
    # State comes from replay. Only the already-compared audit history is copied;
    # caller-owned archive dictionaries must not mutate the resumed session.
    session.operations = deepcopy(archive["operations"])
    return session


def fork_session(original: BattleSession, operation_count: int) -> BattleSession:
    """Branch at an admitted live-session boundary without serializing or replaying."""

    if not isinstance(original, BattleSession):
        raise TypeError("fork requires a BattleSession")
    if type(operation_count) is not int or not 0 <= operation_count <= len(original.operations):
        raise ValueError("fork operation count is outside session history")
    return original.fork(operation_count)


def _verify_archive(
    archive: dict[str, Any], rules: RuleBook, *, retain_boundaries: bool = False,
) -> tuple[dict[str, Any], BattleSession | None]:
    if not isinstance(archive, dict):
        return _failed(0, "archive_root_invalid"), None
    if archive.get("schema_version") != SESSION_SCHEMA:
        return _failed(0, "schema_version_mismatch"), None
    if not isinstance(rules, RuleBook):
        return _failed(0, "rules_invalid"), None
    fingerprint = archive.get("rules_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return _failed(0, "rules_fingerprint_invalid"), None
    if fingerprint != rulebook_fingerprint(rules):
        return _failed(0, "rules_fingerprint_mismatch"), None
    try:
        _validate_archive_shape(archive)
    except (TypeError, ValueError) as exc:
        return _failed(0, f"archive_invalid:{exc}"), None
    try:
        session = BattleSession(rules, archive["scenario"], diagnostics=archive["diagnostics"])
    except (TypeError, ValueError, KeyError) as exc:
        return _failed(0, f"session_rebuild_failed:{type(exc).__name__}:{exc}"), None

    if not _json_equal(session.initial_snapshot, archive["initial_snapshot"]):
        return _failed(0, "initial_snapshot_mismatch"), None
    if not _json_equal(session.setup_audit, archive["setup_audit"]):
        return _failed(0, "setup_audit_mismatch"), None
    if not _json_equal(session.initialization, archive["initialization"]):
        return _failed(0, "initialization_mismatch"), None

    step_count = 0
    states = {0: session.state} if retain_boundaries else {}
    session._history_states = None
    try:
        for operation in archive["operations"]:
            index = step_count
            try:
                _replay_operation(session, operation)
            except (TypeError, ValueError, KeyError) as exc:
                return _failed(step_count, f"operation[{index}]_invalid:{type(exc).__name__}:{exc}"), None
            actual = session.operations[-1]
            if not _json_equal(actual, operation):
                return _failed(step_count, f"operation[{index}]_mismatch"), None
            step_count += 1
            if retain_boundaries:
                states[step_count] = session.state
            session.operations.clear()
            del actual, operation
    except (TypeError, ValueError, KeyError) as exc:
        return _failed(step_count, f"archive_invalid:{exc}"), None

    if not _json_equal(session.state.snapshot().to_json(detach=False), archive["final_snapshot"]):
        return _failed(step_count, "final_snapshot_mismatch"), None
    if session.outcome != archive["outcome"]:
        return _failed(step_count, "outcome_mismatch"), None
    session._history_states = states
    return {"ok": True, "step_count": step_count, "errors": []}, session


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
    if not isinstance(archive["diagnostics"], str) or archive["diagnostics"] not in {"compact", "full"}:
        raise ValueError("archive.diagnostics must be compact or full")
    validate_json_graph(archive)


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
    compared: set[tuple[int, int]] = set()

    def equal(a: Any, b: Any) -> bool:
        if a is b:
            return True
        pair = (id(a), id(b))
        if pair in compared:
            return True
        if isinstance(a, dict) and isinstance(b, dict):
            if all(isinstance(key, str) for key in a) and all(isinstance(key, str) for key in b):
                result = a.keys() == b.keys() and all(equal(a[key], b[key]) for key in a)
            else:
                result = _canonical_json(a) == _canonical_json(b)
        elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            result = len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        elif type(a) is type(b) and type(a) in (str, int, bool, type(None)):
            return a == b
        else:
            return _canonical_json(a) == _canonical_json(b)
        if result:
            compared.add(pair)
        return result

    return equal(left, right)


def _failed(step_count: int, error: str) -> dict[str, Any]:
    return {"ok": False, "step_count": step_count, "errors": [error]}


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
