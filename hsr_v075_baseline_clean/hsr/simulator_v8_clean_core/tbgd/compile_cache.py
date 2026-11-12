"""Local, disposable cache of already-validated Canonical IR, preserving sharing."""
from __future__ import annotations

import errno
import fcntl
from contextlib import nullcontext
import gzip
import importlib
import json
import os
import pickle
import sys
import tempfile
import threading
import weakref
import zlib
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from .. import BASELINE_VERSION
from ..build_types import require_sha256
from ..immutable_json import FrozenJSONDict, FrozenJSONList
from ..rules.ir import CanonicalIR, _FrozenIRPayloadDict, _FrozenIRPayloadList

_MAGIC = b"HSR_IR_CACHE_V3\n"
_CORE = __package__.rsplit(".tbgd", 1)[0]
_IGNORED_SCAN_ERRORS = frozenset((errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP))

# Local invalidation keys and portable content identities have separate uses.
# Keep both for immutable compiled IR, including builds unable to write a cache.
_SLOT_LOCK = threading.Lock()
_CACHE_SLOTS: dict[int, tuple[weakref.ReferenceType[CanonicalIR], Path, str, tuple[str, str]]] = {}
_SOURCE_READS = threading.local()


def _record_source_read(event, args):
    if event != 'open':
        return
    active = getattr(_SOURCE_READS, 'active', None)
    if active is None or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    root, reads, aliases = active
    path = os.path.abspath(os.fsdecode(args[0]))
    relative = os.path.relpath(path, root) if path.startswith(root + os.sep) else aliases.get(path)
    if relative is not None and relative not in reads:
        reads[relative] = _file_stamp(path)


sys.addaudithook(_record_source_read)


def _file_stamp(path):
    try:
        stat = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]


def _register_slot(ir: CanonicalIR, path: Path, key: str, content_identity: tuple[str, str]) -> None:
    identity = id(ir)

    def clear(reference: weakref.ReferenceType[CanonicalIR]) -> None:
        with _SLOT_LOCK:
            current = _CACHE_SLOTS.get(identity)
            if current is not None and current[0] is reference:
                _CACHE_SLOTS.pop(identity, None)

    with _SLOT_LOCK:
        _CACHE_SLOTS[identity] = (weakref.ref(ir, clear), path, key, content_identity)


def ir_cache_slot(ir: CanonicalIR) -> tuple[Path, str] | None:
    with _SLOT_LOCK:
        entry = _CACHE_SLOTS.get(id(ir))
        if entry is not None and entry[0]() is ir:
            return entry[1], entry[2]
    return None


def ir_content_identity(ir: CanonicalIR) -> tuple[str, str] | None:
    """Canonical IR and source-content fingerprints, independent of the cache key."""
    with _SLOT_LOCK:
        entry = _CACHE_SLOTS.get(id(ir))
        if entry is not None and entry[0]() is ir:
            return entry[3]
    return None


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
    return sha256(json.dumps({"format": 2, "python": sys.version_info[:2],
        "root": str(root.resolve()), "limits": asdict(limits), "scope": scope},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source_entries(root: Path, suffix: str, *, directories: dict | None = None) -> list[tuple[tuple[str, ...], os.DirEntry]]:
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
        if directories is not None:
            directories[os.sep.join(parts)] = _file_stamp(directory)
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


def _cache_key(root: Path, limits, scope: dict, *, code_root: Path | None = None, dependencies: dict | None = None) -> str:
    if dependencies is not None:
        current = {kind: {name: _file_stamp(root / name) for name in paths}
                   for kind, paths in dependencies.items()}
        return _dependency_key(root, limits, scope, current, _production_fingerprint(code_root))
    digest = sha256(_request_key(root, limits, scope).encode())
    # ponytail: local FS metadata avoids rereading gigabytes on every hit. If the
    # source store can forge size/mtime/ctime/inode together, use content hashes.
    for parts, entry in _source_entries(root, ".json"):
        stat = entry.stat()
        digest.update(json.dumps((os.sep.join(parts), stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)).encode())
    digest.update(_production_fingerprint(code_root).encode())
    return digest.hexdigest()


def _production_fingerprint(code_root: Path | None = None) -> str:
    digest = sha256()
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
        if parts[0] == "content_processors":
            continue  # L2 content processors consume IR; L0 never imports them.
        if parts == ("core", "content_hooks.py"):
            continue  # Processor hook protocol consumes IR; L0 does not import it.
        digest.update(os.sep.join(parts).encode())
        with open(entry.path, "rb") as stream:
            digest.update(stream.read())
    return digest.hexdigest()


def _dependency_key(root, limits, scope, dependencies, production_fingerprint):
    return sha256(json.dumps([_request_key(root, limits, scope), production_fingerprint, dependencies],
                            sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _read_dependencies(path: Path) -> dict | None:
    try:
        with path.open('rb') as stream:
            if stream.read(len(_MAGIC)) != _MAGIC:
                return None
            stream.readline(66)
            value = json.loads(stream.readline(8 * 1024 * 1024))
        if not isinstance(value, dict) or set(value) != {'files', 'directories'}:
            return None
        if any(not isinstance(paths, dict) or any(
            not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts
            for name in paths) for paths in value.values()):
            return None
        return value
    except (OSError, ValueError):
        return None


def _body_digest(stream, header: bytes = b'') -> bytes:
    digest = sha256(header)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest().encode()


def _read_cache(path: Path, key: str) -> CanonicalIR | None:
    try:
        with path.open("rb") as stream:
            if stream.read(len(_MAGIC)) != _MAGIC or stream.readline() != key.encode() + b"\n":
                return None
            dependency_header = stream.readline(8 * 1024 * 1024)
            expected = stream.readline()
            if len(expected) != 65:
                return None
            offset = stream.tell()
            if _body_digest(stream, dependency_header) + b"\n" != expected:
                return None
            stream.seek(offset)
            with gzip.GzipFile(fileobj=stream, mode="rb") as body:
                result, fingerprint, source_fingerprint = _IRUnpickler(body).load()
                if body.read(1) or type(result) is not CanonicalIR or result.version != BASELINE_VERSION:
                    return None
            require_sha256(fingerprint, 'cached_rules_fingerprint')
            require_sha256(source_fingerprint, 'cached_source_fingerprint')
            _register_slot(result, path, key, (fingerprint, source_fingerprint))
            return result
    except (OSError, EOFError, ValueError, TypeError, AttributeError, ImportError,
            pickle.UnpicklingError, zlib.error):
        return None


def _write_cache(path: Path, key: str, ir: CanonicalIR, dependencies: dict, content_identity: tuple[str, str]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            header = json.dumps(dependencies, sort_keys=True, separators=(',', ':')).encode() + b'\n'
            stream.write(_MAGIC + key.encode() + b"\n" + header + b"0" * 64 + b"\n")
            offset = stream.tell()
            with gzip.GzipFile(fileobj=stream, mode="wb", compresslevel=1, mtime=0) as body:
                _IRPickler(body, protocol=pickle.HIGHEST_PROTOCOL).dump((ir, *content_identity))
            stream.seek(offset)
            body_digest = _body_digest(stream, header)
            stream.seek(len(_MAGIC) + 65 + len(header))
            stream.write(body_digest)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cached_ir(root: Path, limits, scope: dict, build: Callable[[], CanonicalIR],
              *, cache_dir: Path | None = None) -> CanonicalIR:
    root = root.resolve()
    directory = cache_dir or Path(os.environ.get("HSR_IR_CACHE_DIR",
        f"/tmp/hsr-v8-ir-cache-{os.getuid()}"))
    # One slot per scope replaces outdated revisions instead of accumulating GB.
    path = directory / f"{_request_key(root, limits, scope)}.ir.gz"
    def load():
        dependencies = _read_dependencies(path)
        if dependencies is None:
            return None
        try:
            key = _cache_key(root, limits, scope, dependencies=dependencies)
        except OSError:
            return None
        return _read_cache(path, key)

    result = load()
    # A hit is an immutable snapshot of the inputs observed at entry. Later
    # source edits are picked up by the next call; no second directory walk.
    if result is not None:
        return result
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (directory / "compile.lock").open("a+b")
    except OSError:
        lock = None
    with lock if lock is not None else nullcontext():
        # ponytail: one lock serializes cold builds to protect WSL memory; split
        # by scope only after per-process memory budgets can bound parallelism.
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = load()
            if result is not None:
                return result
        directories = {}
        before, aliases = {}, {}
        for parts, entry in _source_entries(root, '.json', directories=directories):
            relative = os.sep.join(parts)
            before[relative] = _file_stamp(entry.path)
            if entry.is_symlink():
                aliases[os.path.realpath(entry.path)] = relative
        # Cache artifacts must not invalidate their own input directory stamps.
        cache_root = directory.resolve()
        if cache_root != root and cache_root.is_relative_to(root):
            directories = {name: stamp for name, stamp in directories.items()
                           if not (root / name).is_relative_to(cache_root)}
        production = _production_fingerprint()
        reads = {}
        previous = getattr(_SOURCE_READS, 'active', None)
        _SOURCE_READS.active = (str(root), reads, aliases)
        try:
            result = build()
        finally:
            _SOURCE_READS.active = previous
        # ponytail: all directory stamps conservatively catch additions, renames and negative
        # existence probes even when no file was opened. Warm loads only stat
        # these directories and files actually read; they never enumerate JSON.
        # Replace with explicit discovery dependencies if directory stats become a bottleneck.
        dependencies = {'files': {name: before.get(name, stamp) for name, stamp in reads.items()},
                        'directories': directories}
        if type(result) is not CanonicalIR or result.version != BASELINE_VERSION:
            raise TypeError("compile cache requires current, validated CanonicalIR")
        from ..builds.manifest import canonical_ir_fingerprint, _source_fingerprint

        fingerprint = canonical_ir_fingerprint(result)
        content_identity = (fingerprint, _source_fingerprint(result) or fingerprint)
        key = _dependency_key(root, limits, scope, dependencies, production)
        if key != _cache_key(root, limits, scope, dependencies=dependencies):
            raise RuntimeError("sources or production code changed during IR compilation; retry")
        if lock is not None:
            try:
                _write_cache(path, key, result, dependencies, content_identity)
            except OSError:
                pass  # A cache write failure must not discard a successful compilation.
        _register_slot(result, path, key, content_identity)
        return result
