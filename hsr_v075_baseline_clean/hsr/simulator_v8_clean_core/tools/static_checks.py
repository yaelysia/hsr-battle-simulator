from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RUNTIME_DIRS = ("core", "rules", "systems")
RUNTIME_MAIN_PATHS = (
    "core/action_plan.py",
    "core/executor.py",
    "core/model.py",
    "core/reducer.py",
    "core/settlement.py",
    "core/snapshot_contract.py",
    "core/transition_contract.py",
    "rules",
    "systems",
)
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
RUNTIME_MAIN_BANNED_IMPORT_TOKENS = (
    "from ..tbgd",
    "import simulator_v8_clean_core.tbgd",
)
RUNTIME_MAIN_BANNED_ACTION_INFERENCE_TOKENS = (
    "param_list[0]",
    "show_damage_list[",
    "show_stance_list[",
    "ConfigAbility",
    "ConfigCharacter",
    "AbilityList",
    "DamageByAttackProperty",
    "AttackData",
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
            relative_path = path.relative_to(package_root).as_posix()
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for token in BANNED_TOKENS:
                    if token in line:
                        violations.append(
                            {
                                "path": relative_path,
                                "line": line_number,
                                "token": token,
                            }
                        )
                if _is_runtime_main_path(relative_path):
                    for token in RUNTIME_MAIN_BANNED_IMPORT_TOKENS:
                        if token in line:
                            violations.append(
                                {
                                    "path": relative_path,
                                    "line": line_number,
                                    "token": f"runtime_main_import:{token}",
                                }
                            )
                    for token in RUNTIME_MAIN_BANNED_ACTION_INFERENCE_TOKENS:
                        if token in line:
                            violations.append(
                                {
                                    "path": relative_path,
                                    "line": line_number,
                                    "token": f"runtime_action_inference:{token}",
                                }
                            )
                if _looks_like_follow_up_damage_family(line):
                    violations.append(
                        {
                            "path": relative_path,
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


def _is_runtime_main_path(relative_path: str) -> bool:
    return any(
        relative_path == path or relative_path.startswith(f"{path}/")
        for path in RUNTIME_MAIN_PATHS
    )
