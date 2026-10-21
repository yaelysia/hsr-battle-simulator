"""Local, disposable cache of already-validated Canonical IR, preserving sharing."""
from __future__ import annotations

import errno
import fcntl
import gzip
import importlib
import json
import os
import pickle
import sys
import tempfile
import zlib
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from .. import BASELINE_VERSION
from ..immutable_json import FrozenJSONDict, FrozenJSONList
from ..rules.ir import CanonicalIR, _FrozenIRPayloadDict, _FrozenIRPayloadList

_MAGIC = b"HSR_IR_CACHE_V1\n"
_CORE = __package__.rsplit(".tbgd", 1)[0]
_IGNORED_SCAN_ERRORS = frozenset((errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP))


def _mapping_proxy(values):
    return MappingProxyType(values)


class _IRPickler(pickle.Pickler):
    def reducer_override(self, value):
        if type(value) in (FrozenJSONDict, _FrozenIRPayloadDict):
            return type(value), (dict(value),)
        if type(value) in (FrozenJSONList, _FrozenIRPayloadList):
            return type(value), (list(value),)
        if type(value) is MappingProxyType:
            return _mapping_proxy, (dict(value),)
        return NotImplemented


class _IRUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        # UI and CLI import the same package under two names; restore current types.
        suffix = module.split("simulator_v8_clean_core.", 1)[-1]
        if module not in {f"simulator_v8_clean_core.{suffix}", f"hsr.simulator_v8_clean_core.{suffix}"}:
            raise pickle.UnpicklingError("cache global is outside the IR package")
        if suffix == "tbgd.compile_cache" and name == "_mapping_proxy":
            return _mapping_proxy
        if suffix == "immutable_json" and name in {"FrozenJSONDict", "FrozenJSONList"}:
            return {"FrozenJSONDict": FrozenJSONDict, "FrozenJSONList": FrozenJSONList}[name]
        if suffix == "rules.ir" and name in {"_FrozenIRPayloadDict", "_FrozenIRPayloadList"}:
            return {"_FrozenIRPayloadDict": _FrozenIRPayloadDict, "_FrozenIRPayloadList": _FrozenIRPayloadList}[name]
        if suffix in {"ir_types", "equipment.models"} or suffix.startswith("rules."):
            value = getattr(importlib.import_module(f"{_CORE}.{suffix}"), name)
            if isinstance(value, type) and is_dataclass(value) and not hasattr(value, "__setstate__"):
                return value
        raise pickle.UnpicklingError("cache global is not an IR data type")


def _request_key(root: Path, limits, scope: dict) -> str:
    return sha256(json.dumps({"format": 1, "python": sys.version_info[:2],
        "root": str(root.resolve()), "limits": asdict(limits), "scope": scope},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source_entries(root: Path, suffix: str) -> list[tuple[tuple[str, ...], os.DirEntry]]:
    """Enumerate source names under root with Path.rglob visibility semantics.

    Hidden entries stay visible, symlinked directories are not entered (linked
    files still match), unreadable directories are skipped, entry kinds that
    cannot be read count as non-directories, and results sort by path parts.
    A denied kind check keeps that directory's own matches but stops classifying
    its remaining entries, exactly like Path.rglob; denied stats of matched names
    still propagate. The source store keeps 123k JSON files, so this avoids
    building a Path object per file without changing what is seen.
    """
    found: dict[tuple[str, ...], os.DirEntry] = {}

    def scan(directory: str, parts: tuple[str, ...]) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except PermissionError:
            return
        # Path.rglob matches a directory's own names before it classifies their
        # kinds, so a denied kind check must not drop same-directory matches.
        for entry in entries:
            if entry.name.endswith(suffix):
                found.setdefault(parts + (entry.name,), entry)
        try:
            for entry in entries:
                try:
                    is_dir = entry.is_dir()
                except OSError as error:
                    if error.errno not in _IGNORED_SCAN_ERRORS:
                        raise
                    is_dir = False
                if is_dir and not entry.is_symlink():
                    scan(os.path.join(directory, entry.name), parts + (entry.name,))
        except PermissionError:
            return  # Path.rglob also stops classifying this directory's entries.

    if root.is_dir():
        scan(str(root), ())
    return sorted(found.items())


def _cache_key(root: Path, limits, scope: dict, *, code_root: Path | None = None) -> str:
    digest = sha256(_request_key(root, limits, scope).encode())
    # ponytail: local FS metadata avoids rereading gigabytes on every hit. If the
    # source store can forge size/mtime/ctime/inode together, use content hashes.
    for parts, entry in _source_entries(root, ".json"):
        stat = entry.stat()
        digest.update(json.dumps((os.sep.join(parts), stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)).encode())
    production = code_root or Path(__file__).resolve().parents[1]
    for parts, entry in _source_entries(production, ".py"):
        if set(parts) & {"tests", "tools", "docs", "examples", "__pycache__"}:
            continue
        # L0 does not depend on combat systems. Keep the shared evaluator's
        # indirect unit_stats dependency; other runtime edits do not change IR.
        if parts[0] == "systems" and parts != ("systems", "unit_stats.py"):
            continue
        if parts == ("session.py",):
            continue  # The L3 session boundary is never imported by L0.
        if parts == ("core", "executor.py"):
            continue  # Combat execution consumes IR; L0 does not import it.
        digest.update(os.sep.join(parts).encode())
        with open(entry.path, "rb") as stream:
            digest.update(stream.read())
    return digest.hexdigest()


def _body_digest(stream) -> bytes:
    digest = sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest().encode()


def _read_cache(path: Path, key: str) -> CanonicalIR | None:
    try:
        with path.open("rb") as stream:
            if stream.read(len(_MAGIC)) != _MAGIC or stream.readline() != key.encode() + b"\n":
                return None
            expected = stream.readline()
            if len(expected) != 65:
                return None
            offset = stream.tell()
            if _body_digest(stream) + b"\n" != expected:
                return None
            stream.seek(offset)
            with gzip.GzipFile(fileobj=stream, mode="rb") as body:
                result = _IRUnpickler(body).load()
                if body.read(1) or type(result) is not CanonicalIR or result.version != BASELINE_VERSION:
                    return None
            return result
    except (OSError, EOFError, ValueError, TypeError, AttributeError, ImportError,
            pickle.UnpicklingError, zlib.error):
        return None


def _write_cache(path: Path, key: str, ir: CanonicalIR) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_MAGIC + key.encode() + b"\n" + b"0" * 64 + b"\n")
            offset = stream.tell()
            with gzip.GzipFile(fileobj=stream, mode="wb", compresslevel=1, mtime=0) as body:
                _IRPickler(body, protocol=pickle.HIGHEST_PROTOCOL).dump(ir)
            stream.seek(offset)
            body_digest = _body_digest(stream)
            stream.seek(len(_MAGIC) + 65)
            stream.write(body_digest)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cached_ir(root: Path, limits, scope: dict, build: Callable[[], CanonicalIR],
              *, cache_dir: Path | None = None) -> CanonicalIR:
    directory = cache_dir or Path(os.environ.get("HSR_IR_CACHE_DIR",
        f"/tmp/hsr-v8-ir-cache-{os.getuid()}"))
    # One slot per scope replaces outdated revisions instead of accumulating GB.
    path = directory / f"{_request_key(root, limits, scope)}.ir.gz"
    key = _cache_key(root, limits, scope)
    result = _read_cache(path, key)
    if result is not None and key == _cache_key(root, limits, scope):
        return result
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (directory / "compile.lock").open("a+b")
    except OSError:
        return build()
    with lock:
        # ponytail: one lock serializes cold builds to protect WSL memory; split
        # by scope only after per-process memory budgets can bound parallelism.
        fcntl.flock(lock, fcntl.LOCK_EX)
        key = _cache_key(root, limits, scope)
        result = _read_cache(path, key)
        if result is not None and key == _cache_key(root, limits, scope):
            return result
        result = build()
        if key != _cache_key(root, limits, scope):
            raise RuntimeError("sources or production code changed during IR compilation; retry")
        if type(result) is not CanonicalIR or result.version != BASELINE_VERSION:
            raise TypeError("compile cache requires current, validated CanonicalIR")
        try:
            _write_cache(path, key, result)
        except OSError:
            pass  # A cache write failure must not discard a successful compilation.
        return result
