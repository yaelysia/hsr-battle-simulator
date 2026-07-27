from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .validation_registry import load_default_registry
from .validation_selection import (
    ExternalInputValue,
    SelectionContractError,
    SelectionRequest,
    build_selection_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the VG validator registry and build deterministic "
            "selection manifests. This command never executes validators."
        ),
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List registered validator modes.",
        allow_abbrev=False,
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    describe_parser = subparsers.add_parser(
        "describe",
        help="Describe one exact registry entry.",
        allow_abbrev=False,
    )
    describe_parser.add_argument("entry_id")
    describe_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    select_parser = subparsers.add_parser(
        "select",
        help="Build a dry-run selection manifest.",
        allow_abbrev=False,
    )
    select_parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Required; execution is intentionally unavailable in VG-S3.",
    )
    select_parser.add_argument(
        "--intent",
        choices=("direct", "catalog"),
        required=True,
    )
    select_parser.add_argument(
        "--id",
        dest="entry_ids",
        action="append",
        default=[],
        help="Exact registry entry ID; repeat as needed.",
    )
    select_parser.add_argument(
        "--trigger",
        action="append",
        default=[],
        help="Exact registered direct trigger; repeat as needed.",
    )
    select_parser.add_argument(
        "--domain",
        action="append",
        default=[],
        help="Narrow an existing ID/trigger selection; repeat as needed.",
    )
    select_parser.add_argument(
        "--output-root",
        required=True,
        help="Absolute root used only to render per-entry output argv.",
    )
    select_parser.add_argument(
        "--input",
        dest="external_inputs",
        action="append",
        default=[],
        metavar="INPUT_ID=/ABS/PATH",
        help="Typed external path input; repeat as needed.",
    )
    select_parser.add_argument(
        "--confirm-heavy-plan",
        action="store_true",
        help="Required for catalog/full planning.",
    )
    select_parser.add_argument(
        "--manifest",
        help="Optionally write exactly one compact JSON manifest.",
    )
    select_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete manifest instead of a human summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    registry = load_default_registry()
    if args.command == "list":
        return _list_entries(registry, machine_readable=args.json)
    if args.command == "describe":
        try:
            entry = registry.get(args.entry_id)
        except KeyError:
            parser.error(f"unknown registry entry: {args.entry_id}")
        return _describe_entry(
            registry.schema_version,
            registry.fingerprint,
            entry.to_json(),
            machine_readable=args.json,
        )
    if args.command != "select":
        parser.error(f"unsupported command: {args.command}")

    try:
        external_inputs = tuple(
            _parse_external_input(value)
            for value in args.external_inputs
        )
        request = SelectionRequest(
            intent=args.intent,
            entry_ids=tuple(args.entry_ids),
            triggers=tuple(args.trigger),
            domains=tuple(args.domain),
            output_root=args.output_root,
            external_inputs=external_inputs,
            heavy_plan_confirmed=args.confirm_heavy_plan,
        )
        manifest = build_selection_manifest(registry, request)
    except SelectionContractError as exc:
        parser.error(str(exc))

    payload = manifest.to_json()
    if args.manifest:
        try:
            _write_manifest(args.manifest, payload)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        _print_selection_summary(payload, manifest_path=args.manifest)
    return 0 if manifest.ok else 2


def _list_entries(registry: Any, *, machine_readable: bool) -> int:
    rows = [
        {
            "entry_id": entry.entry_id,
            "module": entry.module,
            "mode_id": entry.mode_id,
            "lifecycle_classification": entry.lifecycle_classification,
            "tier": entry.tier,
            "build_requirement": entry.resources.build_requirement,
            "current_selectable": entry.current_selectable,
        }
        for entry in registry.entries
    ]
    if machine_readable:
        print(
            json.dumps(
                {
                    "schema_version": registry.schema_version,
                    "registry_fingerprint": registry.fingerprint,
                    "entry_count": len(rows),
                    "entries": rows,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    print(
        f"registry_schema={registry.schema_version} "
        f"entries={len(rows)} fingerprint={registry.fingerprint}"
    )
    for row in rows:
        print(
            f"{row['entry_id']} lifecycle={row['lifecycle_classification']} "
            f"tier={row['tier']} resource={row['build_requirement']} "
            f"selectable={str(row['current_selectable']).lower()}"
        )
    return 0


def _describe_entry(
    schema_version: str,
    fingerprint: str,
    entry: dict[str, Any],
    *,
    machine_readable: bool,
) -> int:
    payload = {
        "schema_version": schema_version,
        "registry_fingerprint": fingerprint,
        "entry": entry,
    }
    if machine_readable:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    print(
        f"{entry['entry_id']} module={entry['module']} "
        f"mode={entry['mode_id']}"
    )
    print(
        f"lifecycle={entry['lifecycle_classification']} "
        f"tier={entry['tier']} selectable="
        f"{str(entry['current_selectable']).lower()}"
    )
    print(
        "domains="
        + ",".join(entry["domains"])
        + " triggers="
        + ",".join(entry["triggers"])
    )
    resources = entry["resources"]
    print(
        f"resource={resources['build_requirement']} "
        f"reads_tbgd={str(resources['reads_tbgd']).lower()} "
        f"rulebook={resources['rulebook_build_kind']}"
    )
    print(
        f"fixed_argv={json.dumps(entry['fixed_argv'])} "
        f"summary={entry['summary_relative_path']}"
    )
    return 0


def _parse_external_input(value: str) -> ExternalInputValue:
    if "=" not in value:
        raise SelectionContractError(
            "external_input_syntax_invalid",
            "--input must use INPUT_ID=/ABS/PATH"
        )
    input_id, path_value = value.split("=", 1)
    return ExternalInputValue(input_id=input_id, value=path_value)


def _write_manifest(path_value: str, payload: dict[str, Any]) -> None:
    pure_path = PurePosixPath(path_value)
    if (
        not pure_path.is_absolute()
        or ".." in pure_path.parts
        or pure_path.suffix != ".json"
    ):
        raise ValueError(
            "--manifest must be an absolute traversal-free JSON path"
        )
    path = Path(path_value)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    path.write_text(encoded, encoding="utf-8")


def _print_selection_summary(
    payload: dict[str, Any],
    *,
    manifest_path: str | None,
) -> None:
    print(
        f"ok={str(payload['ok']).lower()} "
        f"selected={len(payload['selected_entries'])} "
        f"blocked={len(payload['blocked_issues'])} "
        f"fingerprint={payload['selection_fingerprint']}"
    )
    for entry in payload["selected_entries"]:
        print(
            f"{entry['entry_id']} module={entry['module']} "
            f"argv={json.dumps(entry['argv'], ensure_ascii=False)}"
        )
    for issue in payload["blocked_issues"]:
        print(
            f"blocked code={issue['code']} message={issue['message']}"
        )
    if manifest_path:
        print(f"manifest={manifest_path}")


if __name__ == "__main__":
    raise SystemExit(main())
