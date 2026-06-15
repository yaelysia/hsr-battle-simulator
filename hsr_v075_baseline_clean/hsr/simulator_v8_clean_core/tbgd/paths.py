from __future__ import annotations

from pathlib import Path


def find_tbgd_root(start: Path | None = None) -> Path:
    """Find the workspace TurnBasedGameData checkout."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        direct = candidate / "turnbasedgamedata-main"
        if (direct / "ExcelOutput").is_dir() and (direct / "Config").is_dir():
            return direct
        if candidate.name == "turnbasedgamedata-main" and (candidate / "ExcelOutput").is_dir():
            return candidate
    raise FileNotFoundError("turnbasedgamedata-main not found from current workspace")


def relative_source_path(tbgd_root: Path, path: Path) -> str:
    return path.resolve().relative_to(tbgd_root.resolve()).as_posix()

