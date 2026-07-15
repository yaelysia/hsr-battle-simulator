from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ..equipment.models import validate_equipment_source_fingerprint


S0_SUMMARY_SCHEMA_VERSION = "p8_s0_equipment_source_inventory_summary_v1"
PRIMARY_FINGERPRINT_ALGORITHM = "sha256-path-and-full-content-v1"
PRIMARY_FINGERPRINT_COVERAGE = "full_content_for_every_primary_source_file"
FINGERPRINT_REQUIRED_FIELDS = frozenset(
    {"algorithm", "sha256", "file_count", "byte_count", "paths", "coverage"}
)


def validate_s0_summary_payload(payload: object) -> dict[str, Any]:
    """Validate a review artifact; production lowering must never call this."""

    row = payload if isinstance(payload, dict) else {}
    fingerprint = row.get("primary_source_fingerprint")
    fingerprint_row = fingerprint if isinstance(fingerprint, dict) else {}
    paths = fingerprint_row.get("paths")
    file_count = fingerprint_row.get("file_count")
    byte_count = fingerprint_row.get("byte_count")
    sha256 = fingerprint_row.get("sha256")
    try:
        validate_equipment_source_fingerprint(fingerprint_row)
    except (TypeError, ValueError):
        production_fingerprint_valid = False
    else:
        production_fingerprint_valid = True
    checks = {
        "summary_is_object": isinstance(payload, dict),
        "schema_exact": row.get("schema_version") == S0_SUMMARY_SCHEMA_VERSION,
        "s0_ok_is_true": row.get("ok") is True,
        "s0_ready_for_review_is_true": row.get("ready_for_review") is True,
        "primary_fingerprint_is_object": isinstance(fingerprint, dict),
        "production_fingerprint_validation_passed": production_fingerprint_valid,
        "primary_fingerprint_fields_complete": FINGERPRINT_REQUIRED_FIELDS.issubset(
            fingerprint_row
        ),
        "primary_fingerprint_algorithm_exact": fingerprint_row.get("algorithm")
        == PRIMARY_FINGERPRINT_ALGORITHM,
        "primary_fingerprint_coverage_is_full": fingerprint_row.get("coverage")
        == PRIMARY_FINGERPRINT_COVERAGE,
        "primary_fingerprint_sha256_shape": isinstance(sha256, str)
        and len(sha256) == 64
        and all(character in "0123456789abcdef" for character in sha256),
        "primary_fingerprint_file_count_positive": isinstance(file_count, int)
        and not isinstance(file_count, bool)
        and file_count > 0,
        "primary_fingerprint_byte_count_positive": isinstance(byte_count, int)
        and not isinstance(byte_count, bool)
        and byte_count > 0,
        "primary_fingerprint_paths_complete": isinstance(paths, list)
        and bool(paths)
        and all(isinstance(path, str) and bool(path) for path in paths)
        and len(paths) == file_count
        and len(set(paths)) == len(paths),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "ok": checks["ok"],
        "checks": checks,
        "reason": "" if checks["ok"] else "p8_s0_summary_fail_closed",
    }


def load_s0_summary_fail_closed(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"P8-S0 summary is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"P8-S0 summary cannot be read as JSON: {path}") from exc
    validation = validate_s0_summary_payload(payload)
    if validation["ok"] is not True:
        failed = sorted(
            key
            for key, value in dict(validation["checks"]).items()
            if key != "ok" and value is not True
        )
        raise ValueError(f"P8-S0 summary failed closed checks: {failed}")
    return cast(dict[str, Any], payload)


def fingerprint_contract_matches(
    current: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return FINGERPRINT_REQUIRED_FIELDS.issubset(current) and FINGERPRINT_REQUIRED_FIELDS.issubset(
        expected
    ) and all(current[key] == expected[key] for key in FINGERPRINT_REQUIRED_FIELDS)
