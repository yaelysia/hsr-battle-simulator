from __future__ import annotations

from pathlib import Path
from typing import Any


CLEAN_RUNTIME_FILES = {
    "state.py",
    "rules.py",
    "effect_registry.py",
    "effects.py",
    "coverage.py",
}
BANNED_TOKENS = {
    "simulator_import": "hsr_simulator_prototype_v7_7",
    "dunder_getattr": "__getattr__",
    "runtime_adapter": "SimulatorRuntimeAdapter",
    "bind_globals": "bind_simulator_module_globals",
}


def run_clean_core_static_checks(core_dir: str | Path) -> dict[str, Any]:
    core = Path(core_dir)
    violations: list[dict[str, Any]] = []
    checked_files: list[str] = []
    for name in sorted(CLEAN_RUNTIME_FILES):
        path = core / name
        if not path.exists():
            violations.append({"file": name, "token": "missing_file", "line": 0})
            continue
        checked_files.append(name)
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token_name, token in BANNED_TOKENS.items():
                if token in line:
                    violations.append({"file": name, "token": token_name, "line": line_no, "text": line.strip()})
    return {
        "encoding": "hsr.clean_core.static_checks.v1",
        "ok": not violations,
        "checked_files": checked_files,
        "violation_count": len(violations),
        "violations": violations,
    }
