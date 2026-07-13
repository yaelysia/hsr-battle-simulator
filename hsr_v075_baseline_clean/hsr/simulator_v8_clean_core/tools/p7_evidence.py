from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable


CURRENT_REGRESSION_REQUIRED_CHECKS = {
    "p4_s2": frozenset({"matrix", "static"}),
    "p4_s3": frozenset({"matrix", "static"}),
    "p6_s1": frozenset({"matrix"}),
    "p6_static": frozenset({"matrix"}),
}


def source_tree_fingerprint(package_root: Path) -> dict[str, object]:
    """Return a deterministic fingerprint for the current Python implementation tree."""

    paths = tuple(
        sorted(
            (
                path
                for path in package_root.rglob("*.py")
                if "__pycache__" not in path.parts
            ),
            key=lambda path: path.relative_to(package_root).as_posix(),
        )
    )
    return source_paths_fingerprint(package_root, paths)


def source_paths_fingerprint(package_root: Path, paths: Iterable[Path]) -> dict[str, object]:
    digest = hashlib.sha256()
    normalized = tuple(
        sorted(
            {path.resolve() for path in paths if path.is_file()},
            key=lambda path: path.relative_to(package_root.resolve()).as_posix(),
        )
    )
    for path in normalized:
        relative = path.relative_to(package_root.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "algorithm": "sha256-path-and-content-v1",
        "sha256": digest.hexdigest(),
        "file_count": len(normalized),
        "paths": [path.relative_to(package_root.resolve()).as_posix() for path in normalized],
    }


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_regression_structured_check_contract(
    name: str,
    summary: dict[str, Any],
) -> dict[str, bool]:
    """Validate the non-vacuous structured check contract for targeted P4/P6 evidence."""

    raw_checks = summary.get("checks")
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    required = CURRENT_REGRESSION_REQUIRED_CHECKS.get(name, frozenset())
    required_present = bool(required) and required.issubset(checks)
    return {
        "structured_checks_object": isinstance(raw_checks, dict),
        "structured_checks_nonempty": bool(checks),
        "required_check_items_present": required_present,
        "required_check_items_structured_and_ok": required_present
        and all(
            isinstance(checks[key], dict) and checks[key].get("ok") is True
            for key in required
        ),
        "all_check_items_structured_and_ok": bool(checks)
        and all(
            isinstance(value, dict) and value.get("ok") is True
            for value in checks.values()
        ),
    }


def current_regression_structured_check_negative_cases(
    checker: Callable[[str, dict[str, Any]], dict[str, bool]],
) -> dict[str, Any]:
    """Prove a consumer rejects vacuous, incomplete, and ill-typed P4/P6 checks."""

    budget = {
        "lowering_build_count": 0,
        "rulebook_build_count": 0,
        "shared_rulebook_reused": True,
        "large_artifacts_written": False,
    }

    def accepted(checks: Any) -> bool:
        result = checker(
            "p4_s2",
            {"ok": True, "checks": checks, "resource_budget": budget},
        )
        return bool(result) and all(value is True for value in result.values())

    checks = {
        "valid_control_accepted": accepted(
            {"matrix": {"ok": True}, "static": {"ok": True}}
        ),
        "empty_checks_rejected": not accepted({}),
        "missing_required_check_rejected": not accepted({"matrix": {"ok": True}}),
        "wrong_checks_type_rejected": not accepted([]),
        "wrong_check_item_type_rejected": not accepted(
            {"matrix": True, "static": {"ok": True}}
        ),
        "non_boolean_ok_rejected": not accepted(
            {"matrix": {"ok": 1}, "static": {"ok": True}}
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}
