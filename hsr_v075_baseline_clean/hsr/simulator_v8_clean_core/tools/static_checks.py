from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RUNTIME_DIRS = ("core", "rules", "systems")
BANNED_TOKENS = (
    "model_pack_v3_0",
    "simulator_v7_7",
    "SimulatorRuntimeAdapter",
    "_legacy_effects",
    "action_ctx",
    "turnbasedgamedata-main",
    "json.load",
    "json.loads",
)


FOLLOW_UP_DAMAGE_FAMILY_TOKEN = "follow_up_as_damage_formula_family"


@dataclass(frozen=True)
class StaticCheckResult:
    ok: bool
    violations: tuple[dict[str, str | int], ...]

    def to_json(self) -> dict[str, object]:
        return {"ok": self.ok, "violations": list(self.violations)}


def run_static_checks(package_root: Path) -> StaticCheckResult:
    violations: list[dict[str, str | int]] = []
    for dirname in RUNTIME_DIRS:
        root = package_root / dirname
        if not root.exists():
            violations.append({"path": root.as_posix(), "line": 0, "token": "missing_runtime_dir"})
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for token in BANNED_TOKENS:
                    if token in line:
                        violations.append(
                            {
                                "path": path.relative_to(package_root).as_posix(),
                                "line": line_number,
                                "token": token,
                            }
                        )
                if _looks_like_follow_up_damage_family(line):
                    violations.append(
                        {
                            "path": path.relative_to(package_root).as_posix(),
                            "line": line_number,
                            "token": FOLLOW_UP_DAMAGE_FAMILY_TOKEN,
                        }
                    )
    return StaticCheckResult(ok=not violations, violations=tuple(violations))


def _looks_like_follow_up_damage_family(line: str) -> bool:
    if "damage_formula_family" not in line or "follow_up" not in line:
        return False
    if "not a damage formula family" in line or "is an attack type" in line:
        return False
    return True
