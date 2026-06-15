from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .paths import relative_source_path


DEFAULT_DOMAINS: tuple[tuple[str, str], ...] = (
    ("excel", "ExcelOutput"),
    ("ability", "Config/ConfigAbility"),
    ("global_modifier", "Config/ConfigGlobalModifier"),
    ("summon_config", "Config/ConfigSummonUnit"),
    ("character_config", "Config/ConfigCharacter"),
    ("ai", "Config/ConfigAI"),
)


EFFECT_OPCODE_PREFIX = "RPG.GameCore."


@dataclass(frozen=True)
class FileDiscovery:
    relative_path: str
    domain: str
    shape: str
    record_count: int
    raw_type: str
    gamecore_types: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    formula_count: int = 0
    dynamic_hash_count: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "domain": self.domain,
            "shape": self.shape,
            "record_count": self.record_count,
            "raw_type": self.raw_type,
            "gamecore_types": list(self.gamecore_types),
            "events": list(self.events),
            "formula_count": self.formula_count,
            "dynamic_hash_count": self.dynamic_hash_count,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


@dataclass(frozen=True)
class DiscoveryReport:
    tbgd_root: str
    files: tuple[FileDiscovery, ...]
    by_domain: dict[str, int] = field(default_factory=dict)
    by_shape: dict[str, int] = field(default_factory=dict)
    gamecore_type_counts: dict[str, int] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    formula_files: int = 0
    error_count: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "tbgd_root": self.tbgd_root,
            "summary": {
                "file_count": len(self.files),
                "by_domain": self.by_domain,
                "by_shape": self.by_shape,
                "gamecore_type_counts": self.gamecore_type_counts,
                "event_counts": self.event_counts,
                "formula_files": self.formula_files,
                "error_count": self.error_count,
            },
            "files": [item.to_json() for item in self.files],
        }


class TBGDDiscovery:
    """Scans TBGD files without lowering them into executable rules."""

    def __init__(self, tbgd_root: Path, domains: Iterable[tuple[str, str]] = DEFAULT_DOMAINS):
        self.tbgd_root = tbgd_root.resolve()
        self.domains = tuple(domains)

    def scan(self) -> DiscoveryReport:
        files: list[FileDiscovery] = []
        for domain, relative_root in self.domains:
            root = self.tbgd_root / relative_root
            if not root.exists():
                files.append(
                    FileDiscovery(
                        relative_path=relative_root,
                        domain=domain,
                        shape="missing",
                        record_count=0,
                        raw_type=Path(relative_root).name,
                        error="domain root missing",
                    )
                )
                continue
            for path in sorted(root.rglob("*.json")):
                files.append(self._scan_file(domain, path))

        by_domain = Counter(item.domain for item in files)
        by_shape = Counter(item.shape for item in files)
        gamecore_counts: Counter[str] = Counter()
        event_counts: Counter[str] = Counter()
        formula_files = 0
        error_count = 0
        for item in files:
            gamecore_counts.update(item.gamecore_types)
            event_counts.update(item.events)
            if item.formula_count:
                formula_files += 1
            if item.error:
                error_count += 1
        return DiscoveryReport(
            tbgd_root=self.tbgd_root.as_posix(),
            files=tuple(files),
            by_domain=dict(sorted(by_domain.items())),
            by_shape=dict(sorted(by_shape.items())),
            gamecore_type_counts=dict(sorted(gamecore_counts.items())),
            event_counts=dict(sorted(event_counts.items())),
            formula_files=formula_files,
            error_count=error_count,
        )

    def _scan_file(self, domain: str, path: Path) -> FileDiscovery:
        relative = relative_source_path(self.tbgd_root, path)
        raw_type = path.name.removesuffix(".layout.json").removesuffix(".json")
        if path.name.endswith(".layout.json"):
            return FileDiscovery(
                relative_path=relative,
                domain=domain,
                shape="layout",
                record_count=0,
                raw_type=raw_type,
                skipped_reason="layout metadata is not runtime rule data",
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return FileDiscovery(
                relative_path=relative,
                domain=domain,
                shape="invalid_json",
                record_count=0,
                raw_type=raw_type,
                error=str(exc),
            )
        shape, record_count = self._shape(data)
        visitor = _DiscoveryVisitor()
        visitor.visit(data)
        return FileDiscovery(
            relative_path=relative,
            domain=domain,
            shape=shape,
            record_count=record_count,
            raw_type=raw_type,
            gamecore_types=tuple(sorted(visitor.gamecore_types)),
            events=tuple(sorted(visitor.events)),
            formula_count=visitor.formula_count,
            dynamic_hash_count=visitor.dynamic_hash_count,
        )

    def _shape(self, data: Any) -> tuple[str, int]:
        if isinstance(data, list):
            return "list", len(data)
        if isinstance(data, dict):
            if "AbilityList" in data:
                return "ability_config", len(data.get("AbilityList") or [])
            if "ModifierMap" in data:
                return "modifier_map", len(data.get("ModifierMap") or {})
            return "object", len(data)
        return type(data).__name__, 1


class _DiscoveryVisitor:
    def __init__(self) -> None:
        self.gamecore_types: set[str] = set()
        self.events: set[str] = set()
        self.formula_count = 0
        self.dynamic_hash_count = 0

    def visit(self, value: Any) -> None:
        if isinstance(value, dict):
            raw_type = value.get("$type")
            if isinstance(raw_type, str) and raw_type.startswith(EFFECT_OPCODE_PREFIX):
                self.gamecore_types.add(raw_type.removeprefix(EFFECT_OPCODE_PREFIX))
            event = value.get("Event")
            if isinstance(event, str):
                self.events.add(event)
            if "PostfixExpr" in value:
                self.formula_count += 1
            dynamic_hashes = value.get("DynamicHashes")
            if isinstance(dynamic_hashes, list):
                self.dynamic_hash_count += len(dynamic_hashes)
            for nested in value.values():
                self.visit(nested)
        elif isinstance(value, list):
            for nested in value:
                self.visit(nested)

