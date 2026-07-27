from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, TypeVar

from .validation_registry import ValidationRegistry, ValidatorEntry


SELECTION_SCHEMA_VERSION = "vg-s3.validation-selection.v2"
SELECTION_INTENTS = frozenset({"direct", "catalog"})
_T = TypeVar("_T")


class SelectionContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise SelectionContractError(code, message)


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _fail("invalid_type", f"{field} must be a plain string")
    return value


def _strings(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        _fail("invalid_type", f"{field} must be a sequence")
    copied = tuple(values)
    if any(type(value) is not str or not value for value in copied):
        _fail("invalid_type", f"{field} contains a non-string value")
    return tuple(sorted(set(copied)))


def _ordered_strings(
    values: Iterable[str], field: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        _fail("invalid_type", f"{field} must be a sequence")
    copied = tuple(values)
    if any(type(value) is not str or not value for value in copied):
        _fail("invalid_type", f"{field} contains a non-string value")
    return copied


def _typed_tuple(
    values: Iterable[_T],
    expected_type: type[_T],
    field: str,
) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        _fail("invalid_type", f"{field} must be a sequence")
    copied = tuple(values)
    if any(type(value) is not expected_type for value in copied):
        _fail("invalid_type", f"{field} contains the wrong type")
    return copied


def _safe_path(value: str) -> bool:
    if not value or any(ord(character) < 32 for character in value):
        return False
    path = PurePosixPath(value)
    return path.is_absolute() and ".." not in path.parts


@dataclass(frozen=True, slots=True)
class ExternalInputValue:
    input_id: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_id", _text(self.input_id, "input_id"))
        object.__setattr__(self, "value", _text(self.value, "value"))

    def to_json(self) -> dict[str, str]:
        return {"input_id": self.input_id, "value": self.value}


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    intent: str
    entry_ids: tuple[str, ...]
    triggers: tuple[str, ...]
    domains: tuple[str, ...]
    output_root: str
    external_inputs: tuple[ExternalInputValue, ...]
    heavy_plan_confirmed: bool

    def __post_init__(self) -> None:
        intent = _text(self.intent, "intent")
        output_root = _text(
            self.output_root, "output_root", allow_empty=True
        )
        if type(self.heavy_plan_confirmed) is not bool:
            _fail("invalid_type", "heavy_plan_confirmed must be bool")
        inputs = _typed_tuple(
            self.external_inputs, ExternalInputValue, "external_inputs"
        )
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "entry_ids", _strings(self.entry_ids, "entry_ids"))
        object.__setattr__(self, "triggers", _strings(self.triggers, "triggers"))
        object.__setattr__(self, "domains", _strings(self.domains, "domains"))
        object.__setattr__(self, "output_root", output_root)
        object.__setattr__(
            self,
            "external_inputs",
            tuple(sorted(inputs, key=lambda item: (item.input_id, item.value))),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "entry_ids": list(self.entry_ids),
            "triggers": list(self.triggers),
            "domains": list(self.domains),
            "output_root": self.output_root,
            "external_inputs": [item.to_json() for item in self.external_inputs],
            "heavy_plan_confirmed": self.heavy_plan_confirmed,
        }


@dataclass(frozen=True, slots=True)
class SelectionIssue:
    code: str
    message: str
    entry_ids: tuple[str, ...] = ()
    fields: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        code = _text(self.code, "issue code")
        message = _text(self.message, "issue message")
        entry_ids = _strings(self.entry_ids, "issue entry_ids")
        if isinstance(self.fields, (str, bytes, Mapping)):
            _fail("invalid_type", "issue fields must be pairs")
        fields = tuple(self.fields)
        if any(
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            for pair in fields
        ):
            _fail("invalid_type", "issue fields must be string pairs")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "entry_ids", entry_ids)
        object.__setattr__(self, "fields", tuple(sorted(fields)))

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "entry_ids": list(self.entry_ids),
            "fields": [
                {"name": name, "value": value} for name, value in self.fields
            ],
        }


@dataclass(frozen=True, slots=True)
class MissingInput:
    entry_id: str
    input_id: str
    flag: str
    cli_required: bool
    semantic_required: bool

    def __post_init__(self) -> None:
        for field in ("entry_id", "input_id", "flag"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if type(self.cli_required) is not bool or type(self.semantic_required) is not bool:
            _fail("invalid_type", "missing input requirement flags must be bool")

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "input_id": self.input_id,
            "flag": self.flag,
            "cli_required": self.cli_required,
            "semantic_required": self.semantic_required,
        }


@dataclass(frozen=True, slots=True)
class ExcludedEntry:
    entry_id: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _text(self.entry_id, "entry_id"))
        object.__setattr__(
            self,
            "reason_code",
            _text(self.reason_code, "reason_code"),
        )

    def to_json(self) -> dict[str, str]:
        return {"entry_id": self.entry_id, "reason_code": self.reason_code}


@dataclass(frozen=True, slots=True)
class RenderedCliInput:
    input_id: str
    flag: str
    cli_required: bool
    semantic_required: bool
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_id", _text(self.input_id, "input_id"))
        object.__setattr__(self, "flag", _text(self.flag, "flag"))
        object.__setattr__(self, "value", _text(self.value, "value"))
        if type(self.cli_required) is not bool or type(self.semantic_required) is not bool:
            _fail("invalid_type", "rendered CLI requirement flags must be bool")

    def to_json(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "flag": self.flag,
            "cli_required": self.cli_required,
            "semantic_required": self.semantic_required,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class SelectedEntryPlan:
    entry_id: str
    module: str
    argv: tuple[str, ...]
    lifecycle_classification: str
    tier: str
    domains: tuple[str, ...]
    triggers: tuple[str, ...]
    build_requirement: str
    reads_tbgd: bool
    full_lowering_required: bool
    rulebook_build_kind: str
    source_identity: str
    builder_identity: str
    artifact_identity: str
    shared_build_key: str | None
    output_dir: str
    summary_path: str
    cli_inputs: tuple[RenderedCliInput, ...]

    def __post_init__(self) -> None:
        for field in (
            "entry_id",
            "module",
            "lifecycle_classification",
            "tier",
            "build_requirement",
            "rulebook_build_kind",
            "source_identity",
            "builder_identity",
            "artifact_identity",
            "output_dir",
            "summary_path",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if type(self.reads_tbgd) is not bool or type(self.full_lowering_required) is not bool:
            _fail("invalid_type", "resource flags must be bool")
        if self.shared_build_key is not None:
            object.__setattr__(
                self,
                "shared_build_key",
                _text(self.shared_build_key, "shared_build_key"),
            )
        object.__setattr__(
            self, "argv", _ordered_strings(self.argv, "argv")
        )
        object.__setattr__(self, "domains", _strings(self.domains, "domains"))
        object.__setattr__(self, "triggers", _strings(self.triggers, "triggers"))
        object.__setattr__(
            self,
            "cli_inputs",
            _typed_tuple(self.cli_inputs, RenderedCliInput, "cli_inputs"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "module": self.module,
            "argv": list(self.argv),
            "lifecycle_classification": self.lifecycle_classification,
            "tier": self.tier,
            "domains": list(self.domains),
            "triggers": list(self.triggers),
            "resources": {
                "build_requirement": self.build_requirement,
                "reads_tbgd": self.reads_tbgd,
                "full_lowering_required": self.full_lowering_required,
                "rulebook_build_kind": self.rulebook_build_kind,
                "source_identity": self.source_identity,
                "builder_identity": self.builder_identity,
                "artifact_identity": self.artifact_identity,
                "shared_build_key": self.shared_build_key,
            },
            "output_dir": self.output_dir,
            "summary_path": self.summary_path,
            "cli_inputs": [item.to_json() for item in self.cli_inputs],
        }


@dataclass(frozen=True, slots=True)
class CandidateBuildGroup:
    group_id: str
    build_requirement: str
    source_identity: str
    builder_identity: str
    artifact_identity: str
    rulebook_build_kind: str
    full_lowering_required: bool
    entry_ids: tuple[str, ...]
    shareability_status: str
    adapter_status: str = "not_implemented"
    grouping_only: bool = True
    shared_build_executed: bool = False

    def __post_init__(self) -> None:
        for field in (
            "group_id",
            "build_requirement",
            "source_identity",
            "builder_identity",
            "artifact_identity",
            "rulebook_build_kind",
            "shareability_status",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(
            self, "entry_ids", _strings(self.entry_ids, "entry_ids")
        )
        if not self.entry_ids:
            _fail("build_group_empty", self.group_id)
        if type(self.full_lowering_required) is not bool:
            _fail("invalid_type", "full_lowering_required must be bool")
        if self.shareability_status not in {"no_build", "unproven", "registry_declared"}:
            _fail("shareability_status_invalid", self.shareability_status)
        if (
            self.adapter_status != "not_implemented"
            or self.grouping_only is not True
            or self.shared_build_executed is not False
        ):
            _fail(
                "shared_build_claim_forbidden",
                "VG-S3 groups are planning-only with no adapter",
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "build_requirement": self.build_requirement,
            "source_identity": self.source_identity,
            "builder_identity": self.builder_identity,
            "artifact_identity": self.artifact_identity,
            "rulebook_build_kind": self.rulebook_build_kind,
            "full_lowering_required": self.full_lowering_required,
            "entry_ids": list(self.entry_ids),
            "shareability_status": self.shareability_status,
            "adapter_status": self.adapter_status,
            "grouping_only": self.grouping_only,
            "shared_build_executed": self.shared_build_executed,
        }


@dataclass(frozen=True, slots=True)
class SelectionManifest:
    registry_schema_version: str
    registry_fingerprint: str
    request: SelectionRequest
    selected_entries: tuple[SelectedEntryPlan, ...]
    excluded_entries: tuple[ExcludedEntry, ...]
    blocked_issues: tuple[SelectionIssue, ...]
    missing_required_inputs: tuple[MissingInput, ...]
    build_groups: tuple[CandidateBuildGroup, ...]
    execution_performed: bool = False
    validation_call_count: int = 0
    subprocess_count: int = 0
    tbgd_read_count: int = 0
    lowering_build_count: int = 0
    rulebook_build_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "registry_schema_version",
            _text(self.registry_schema_version, "registry_schema_version"),
        )
        object.__setattr__(
            self,
            "registry_fingerprint",
            _text(self.registry_fingerprint, "registry_fingerprint"),
        )
        if type(self.request) is not SelectionRequest:
            _fail("invalid_type", "request must be SelectionRequest")
        object.__setattr__(
            self,
            "selected_entries",
            _typed_tuple(
                self.selected_entries, SelectedEntryPlan, "selected_entries"
            ),
        )
        object.__setattr__(
            self,
            "excluded_entries",
            _typed_tuple(
                self.excluded_entries, ExcludedEntry, "excluded_entries"
            ),
        )
        object.__setattr__(
            self,
            "blocked_issues",
            _typed_tuple(self.blocked_issues, SelectionIssue, "blocked_issues"),
        )
        object.__setattr__(
            self,
            "missing_required_inputs",
            _typed_tuple(
                self.missing_required_inputs,
                MissingInput,
                "missing_required_inputs",
            ),
        )
        object.__setattr__(
            self,
            "build_groups",
            _typed_tuple(self.build_groups, CandidateBuildGroup, "build_groups"),
        )
        counters = (
            self.validation_call_count,
            self.subprocess_count,
            self.tbgd_read_count,
            self.lowering_build_count,
            self.rulebook_build_count,
        )
        if (
            self.execution_performed is not False
            or any(type(value) is not int or value != 0 for value in counters)
        ):
            _fail("dry_run_counter_nonzero", "manifest must describe zero execution")

    @property
    def ok(self) -> bool:
        return not self.blocked_issues

    def _payload(self) -> dict[str, Any]:
        return {
            "selection_schema_version": SELECTION_SCHEMA_VERSION,
            "registry_schema_version": self.registry_schema_version,
            "registry_fingerprint": self.registry_fingerprint,
            "request": self.request.to_json(),
            "selected_entries": [item.to_json() for item in self.selected_entries],
            "excluded_entries": [item.to_json() for item in self.excluded_entries],
            "blocked_issues": [item.to_json() for item in self.blocked_issues],
            "missing_required_inputs": [
                item.to_json() for item in self.missing_required_inputs
            ],
            "build_groups": [item.to_json() for item in self.build_groups],
            "execution_performed": self.execution_performed,
            "validation_call_count": self.validation_call_count,
            "subprocess_count": self.subprocess_count,
            "tbgd_read_count": self.tbgd_read_count,
            "lowering_build_count": self.lowering_build_count,
            "rulebook_build_count": self.rulebook_build_count,
        }

    @property
    def selection_fingerprint(self) -> str:
        encoded = json.dumps(
            self._payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "ok": self.ok,
            "selection_fingerprint": self.selection_fingerprint,
        }


def build_selection_manifest(
    registry: ValidationRegistry,
    request: SelectionRequest,
) -> SelectionManifest:
    if type(registry) is not ValidationRegistry or type(request) is not SelectionRequest:
        _fail("invalid_type", "registry/request type mismatch")
    issues = _request_issues(registry, request)
    candidates: tuple[ValidatorEntry, ...] = ()
    if not issues:
        candidates, mode_issues = (
            _direct_candidates(registry, request)
            if request.intent == "direct"
            else _catalog_candidates(registry, request)
        )
        issues.extend(mode_issues)
    supplied = {item.input_id: item.value for item in request.external_inputs}
    missing: tuple[MissingInput, ...] = ()
    if not issues:
        used = {spec.input_id for entry in candidates for spec in entry.cli_inputs}
        unused = sorted(set(supplied) - used)
        if unused:
            issues.append(
                _issue(
                    "unused_external_input",
                    fields=(("input_id", value) for value in unused),
                )
            )
        missing = tuple(
            MissingInput(
                entry.entry_id,
                spec.input_id,
                spec.flag,
                spec.cli_required,
                spec.semantic_required,
            )
            for entry in candidates
            for spec in entry.cli_inputs
            if spec.selection_required and spec.input_id not in supplied
        )
        if missing:
            issues.append(
                _issue(
                    "missing_required_cli_input",
                    entry_ids=(item.entry_id for item in missing),
                    fields=(("input_id", item.input_id) for item in missing),
                )
            )
    plans = (
        tuple(_render(entry, request.output_root, supplied) for entry in candidates)
        if not issues
        else ()
    )
    paths = tuple(plan.output_dir for plan in plans)
    if len(set(paths)) != len(paths):
        issues.append(
            _issue(
                "validator_output_directory_collision",
                entry_ids=(plan.entry_id for plan in plans),
            )
        )
        plans = ()
    if issues:
        plans = ()
    selected_ids = {plan.entry_id for plan in plans}
    excluded = tuple(
        ExcludedEntry(
            entry.entry_id,
            "request_blocked"
            if issues
            else "not_requested"
            if entry.entry_id not in request.entry_ids
            and not set(entry.triggers).intersection(request.triggers)
            else "domain_filter_mismatch",
        )
        for entry in registry.entries
        if entry.entry_id not in selected_ids
    )
    return SelectionManifest(
        registry.schema_version,
        registry.fingerprint,
        request,
        plans,
        excluded,
        tuple(sorted(issues, key=lambda item: (item.code, item.entry_ids))),
        missing,
        _build_groups(plans) if not issues else (),
    )


def _issue(
    code: str,
    *,
    entry_ids: Iterable[str] = (),
    fields: Iterable[tuple[str, str]] = (),
) -> SelectionIssue:
    messages = {
        "unknown_selection_intent": "Intent must be direct or catalog.",
        "unknown_entry_id": "Requested entry is not registered.",
        "unknown_trigger": "Requested trigger is not registered.",
        "unknown_domain": "Domain filter is not registered.",
        "domain_only_request_forbidden": "Domain can only narrow ID/trigger selection.",
        "empty_selection_request": "Empty selection cannot default to all.",
        "duplicate_external_input": "External input may be supplied once.",
        "command_structure_override_forbidden": "Module and flags are registry-owned.",
        "unknown_external_input": "External input is not registered.",
        "unsafe_external_input_path": "External path must be absolute and safe.",
        "missing_output_root": "Output root is required.",
        "output_root_escape_forbidden": "Output root must be absolute and safe.",
        "direct_entry_not_current_selectable": "Direct accepts current active direct only.",
        "trigger_has_no_active_direct_entry": "Trigger has no current direct entry.",
        "domain_filter_empty_selection": "Domain removed all selected entries.",
        "catalog_trigger_selection_forbidden": "Catalog requires exact IDs.",
        "catalog_exact_id_required": "Catalog requires exact IDs.",
        "catalog_heavy_plan_confirmation_required": "Catalog requires heavy confirmation.",
        "catalog_entry_not_catalog_audit": "Entry is not a current catalog audit.",
        "unused_external_input": "Input is unused by selected entries.",
        "missing_required_cli_input": "Required typed CLI input is missing.",
        "validator_output_directory_collision": "Output directories collide.",
    }
    return SelectionIssue(
        code,
        messages[code],
        tuple(entry_ids),
        tuple(fields),
    )


def _request_issues(
    registry: ValidationRegistry, request: SelectionRequest
) -> list[SelectionIssue]:
    issues: list[SelectionIssue] = []
    if request.intent not in SELECTION_INTENTS:
        issues.append(
            _issue(
                "unknown_selection_intent",
                fields=(("intent", request.intent),),
            )
        )
    for code, values, known, field in (
        ("unknown_entry_id", request.entry_ids, registry.entry_ids, "entry_id"),
        ("unknown_trigger", request.triggers, registry.triggers, "trigger"),
        ("unknown_domain", request.domains, registry.domains, "domain"),
    ):
        unknown = sorted(set(values) - set(known))
        if unknown:
            issues.append(
                _issue(
                    code,
                    entry_ids=unknown if field == "entry_id" else (),
                    fields=(
                        ((field, value) for value in unknown)
                        if field != "entry_id"
                        else ()
                    ),
                )
            )
    if not request.entry_ids and not request.triggers:
        issues.append(
            _issue(
                "domain_only_request_forbidden"
                if request.domains
                else "empty_selection_request"
            )
        )
    input_ids = tuple(item.input_id for item in request.external_inputs)
    duplicates = sorted(
        value for value in set(input_ids) if input_ids.count(value) > 1
    )
    if duplicates:
        issues.append(
            _issue(
                "duplicate_external_input",
                fields=(("input_id", value) for value in duplicates),
            )
        )
    supplied = {item.input_id: item.value for item in request.external_inputs}
    known_inputs = {
        spec.input_id for entry in registry.entries for spec in entry.cli_inputs
    }
    unknown_inputs = sorted(set(supplied) - known_inputs)
    if unknown_inputs:
        override = any(
            value.startswith("-")
            or value in {"module", "argv", "shell", "shell_string"}
            for value in unknown_inputs
        )
        issues.append(
            _issue(
                "command_structure_override_forbidden"
                if override
                else "unknown_external_input",
                fields=(("input_id", value) for value in unknown_inputs),
            )
        )
    unsafe = sorted(
        input_id
        for input_id, value in supplied.items()
        if not _safe_path(value)
    )
    if unsafe:
        issues.append(
            _issue(
                "unsafe_external_input_path",
                fields=(("input_id", value) for value in unsafe),
            )
        )
    if not request.output_root:
        issues.append(_issue("missing_output_root"))
    elif not _safe_path(request.output_root):
        issues.append(
            _issue(
                "output_root_escape_forbidden",
                fields=(("output_root", request.output_root),),
            )
        )
    return issues


def _direct_candidates(
    registry: ValidationRegistry,
    request: SelectionRequest,
) -> tuple[tuple[ValidatorEntry, ...], list[SelectionIssue]]:
    issues: list[SelectionIssue] = []
    ids: set[str] = set()
    for entry_id in request.entry_ids:
        entry = registry.get(entry_id)
        if not (
            entry.lifecycle_classification == "active_contract"
            and entry.tier == "direct"
            and entry.current_selectable
        ):
            issues.append(
                _issue(
                    "direct_entry_not_current_selectable",
                    entry_ids=(entry_id,),
                )
            )
        else:
            ids.add(entry_id)
    for trigger in request.triggers:
        matches = tuple(
            entry
            for entry in registry.entries
            if trigger in entry.triggers
            and entry.lifecycle_classification == "active_contract"
            and entry.tier == "direct"
            and entry.current_selectable
        )
        if not matches:
            issues.append(
                _issue(
                    "trigger_has_no_active_direct_entry",
                    fields=(("trigger", trigger),),
                )
            )
        ids.update(entry.entry_id for entry in matches)
    entries = tuple(entry for entry in registry.entries if entry.entry_id in ids)
    entries = _filter_domains(entries, request.domains)
    if not issues and not entries:
        issues.append(_issue("domain_filter_empty_selection"))
    return entries, issues


def _catalog_candidates(
    registry: ValidationRegistry,
    request: SelectionRequest,
) -> tuple[tuple[ValidatorEntry, ...], list[SelectionIssue]]:
    issues: list[SelectionIssue] = []
    if request.triggers:
        issues.append(_issue("catalog_trigger_selection_forbidden"))
    if not request.entry_ids:
        issues.append(_issue("catalog_exact_id_required"))
    if not request.heavy_plan_confirmed:
        issues.append(_issue("catalog_heavy_plan_confirmation_required"))
    entries = []
    for entry_id in request.entry_ids:
        entry = registry.get(entry_id)
        if not (
            entry.lifecycle_classification == "catalog_audit"
            and entry.tier in {"catalog", "full"}
        ):
            issues.append(
                _issue("catalog_entry_not_catalog_audit", entry_ids=(entry_id,))
            )
        else:
            entries.append(entry)
    filtered = _filter_domains(tuple(entries), request.domains)
    if not issues and not filtered:
        issues.append(_issue("domain_filter_empty_selection"))
    return filtered, issues


def _filter_domains(
    entries: tuple[ValidatorEntry, ...],
    domains: tuple[str, ...],
) -> tuple[ValidatorEntry, ...]:
    if not domains:
        return entries
    requested = set(domains)
    return tuple(
        entry for entry in entries if requested.intersection(entry.domains)
    )


def _render(
    entry: ValidatorEntry,
    output_root: str,
    supplied: dict[str, str],
) -> SelectedEntryPlan:
    output = (PurePosixPath(output_root) / entry.output_subdir).as_posix()
    argv = list(entry.fixed_argv)
    inputs = []
    for spec in entry.cli_inputs:
        value = supplied[spec.input_id]
        argv.extend((spec.flag, value))
        inputs.append(
            RenderedCliInput(
                spec.input_id,
                spec.flag,
                spec.cli_required,
                spec.semantic_required,
                value,
            )
        )
    argv.extend((entry.output_flag, output))
    resource = entry.resources
    return SelectedEntryPlan(
        entry.entry_id,
        entry.module,
        tuple(argv),
        entry.lifecycle_classification,
        entry.tier,
        entry.domains,
        entry.triggers,
        resource.build_requirement,
        resource.reads_tbgd,
        resource.full_lowering_required,
        resource.rulebook_build_kind,
        resource.source_identity,
        resource.builder_identity,
        resource.artifact_identity,
        resource.shared_build_key,
        output,
        (PurePosixPath(output) / entry.summary_relative_path).as_posix(),
        tuple(inputs),
    )


def _build_groups(
    plans: tuple[SelectedEntryPlan, ...],
) -> tuple[CandidateBuildGroup, ...]:
    buckets: dict[tuple[str, str], list[SelectedEntryPlan]] = {}
    for plan in plans:
        if plan.build_requirement == "none":
            key = ("no_build", "none")
        elif plan.shared_build_key:
            key = ("registry_declared", plan.shared_build_key)
        else:
            key = ("entry", plan.entry_id)
        buckets.setdefault(key, []).append(plan)
    groups = []
    for key in sorted(buckets):
        members = buckets[key]
        first = members[0]
        identity_payload = json.dumps(
            {
                "key": key,
                "source": first.source_identity,
                "builder": first.builder_identity,
                "artifact": first.artifact_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        groups.append(
            CandidateBuildGroup(
                group_id=hashlib.sha256(identity_payload.encode()).hexdigest()[:16],
                build_requirement=first.build_requirement,
                source_identity=first.source_identity,
                builder_identity=first.builder_identity,
                artifact_identity=first.artifact_identity,
                rulebook_build_kind=first.rulebook_build_kind,
                full_lowering_required=first.full_lowering_required,
                entry_ids=tuple(member.entry_id for member in members),
                shareability_status=(
                    "no_build"
                    if key[0] == "no_build"
                    else "registry_declared"
                    if key[0] == "registry_declared"
                    else "unproven"
                ),
            )
        )
    return tuple(groups)
