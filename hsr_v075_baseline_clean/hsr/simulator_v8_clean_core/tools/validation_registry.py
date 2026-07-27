from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


REGISTRY_SCHEMA_VERSION = "vg-s3.validator-registry.v2"

LIFECYCLE_CLASSIFICATIONS = frozenset(
    {
        "active_contract",
        "catalog_audit",
        "historical_evidence",
        "superseded",
        "invalid",
    }
)
VALIDATION_TIERS = frozenset({"direct", "catalog", "full"})
BUILD_REQUIREMENTS = frozenset(
    {
        "none",
        "small_fixture_rulebook",
        "source_inventory",
        "full_lowering_rulebook",
    }
)
RULEBOOK_BUILD_KINDS = frozenset(
    {"none", "small_fixture", "focused_source", "full_lowering"}
)
REPLACEMENT_STATUSES = frozenset(
    {"not_applicable", "incomplete", "complete"}
)
INPUT_KINDS = frozenset({"tbgd_root", "validation_summary"})
KNOWN_INPUT_IDS = frozenset({"tbgd_root", "s0_summary"})
KNOWN_DOMAINS = frozenset(
    {
        "character_build",
        "character_card_source",
        "committed_integrity",
        "committed_state",
        "equipment",
        "full_pipeline",
        "halo",
        "lifecycle",
        "light_cone",
        "lowering",
        "mutation_reducer",
        "replay",
        "rng",
        "selected_graph",
        "source_inventory",
        "status",
        "summon",
    }
)
KNOWN_TRIGGERS = frozenset(
    {
        "character_build_changed",
        "character_card_source_changed",
        "character_catalog_changed",
        "committed_integrity_changed",
        "committed_state_changed",
        "equipment_type_changed",
        "lifecycle_contract_changed",
        "light_cone_catalog_changed",
        "mutation_reducer_changed",
        "rng_or_replay_changed",
        "selected_graph_commit_changed",
        "summon_halo_runtime_changed",
        "summon_halo_source_changed",
    }
)

_ID = re.compile(r"^[a-z0-9][a-z0-9_.:+-]*$")
_MODULE = re.compile(
    r"^simulator_v8_clean_core\.tools\.validate_[a-z0-9_]+$"
)
_FLAG = re.compile(r"^--[a-z0-9][a-z0-9-]*$")
_PATH_PART = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class RegistryContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise RegistryContractError(code, message)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value:
        _fail("invalid_type", f"{field} must be a non-empty plain string")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        _fail("invalid_type", f"{field} must be bool")
    return value


def _strings(
    values: Iterable[str],
    field: str,
    *,
    ordered: bool = False,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        _fail("invalid_type", f"{field} must be a string sequence")
    copied = tuple(values)
    if any(type(value) is not str or not value for value in copied):
        _fail("invalid_type", f"{field} contains a non-string value")
    if len(set(copied)) != len(copied):
        _fail("duplicate_value", f"{field} contains duplicates")
    if not allow_empty and not copied:
        _fail("missing_value", f"{field} must not be empty")
    return copied if ordered else tuple(sorted(copied))


@dataclass(frozen=True, slots=True)
class CliInputSpec:
    input_id: str
    flag: str
    input_kind: str
    cli_required: bool
    selection_required: bool
    semantic_required: bool
    description: str
    render_order: int = 10

    def __post_init__(self) -> None:
        input_id = _text(self.input_id, "input_id")
        flag = _text(self.flag, "flag")
        input_kind = _text(self.input_kind, "input_kind")
        description = _text(self.description, "description")
        _boolean(self.cli_required, "cli_required")
        _boolean(self.selection_required, "selection_required")
        _boolean(self.semantic_required, "semantic_required")
        if input_id not in KNOWN_INPUT_IDS:
            _fail("unknown_input_id", input_id)
        if input_kind not in INPUT_KINDS:
            _fail("unknown_input_kind", input_kind)
        if not _FLAG.fullmatch(flag):
            _fail("invalid_cli_flag", flag)
        if type(self.render_order) is not int or self.render_order < 0:
            _fail("invalid_type", "render_order must be a non-negative int")
        if (self.cli_required or self.semantic_required) and not self.selection_required:
            _fail(
                "input_requirement_conflict",
                f"{input_id} must be selection-required",
            )
        object.__setattr__(self, "input_id", input_id)
        object.__setattr__(self, "flag", flag)
        object.__setattr__(self, "input_kind", input_kind)
        object.__setattr__(self, "description", description)

    def to_json(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "flag": self.flag,
            "input_kind": self.input_kind,
            "cli_required": self.cli_required,
            "selection_required": self.selection_required,
            "semantic_required": self.semantic_required,
            "description": self.description,
            "render_order": self.render_order,
        }


@dataclass(frozen=True, slots=True)
class ResourceRequirement:
    build_requirement: str
    reads_tbgd: bool
    full_lowering_required: bool
    rulebook_build_kind: str
    source_identity: str
    builder_identity: str
    artifact_identity: str
    shared_build_key: str | None = None

    def __post_init__(self) -> None:
        requirement = _text(self.build_requirement, "build_requirement")
        rulebook_kind = _text(
            self.rulebook_build_kind, "rulebook_build_kind"
        )
        source = _text(self.source_identity, "source_identity")
        builder = _text(self.builder_identity, "builder_identity")
        artifact = _text(self.artifact_identity, "artifact_identity")
        _boolean(self.reads_tbgd, "reads_tbgd")
        _boolean(self.full_lowering_required, "full_lowering_required")
        if requirement not in BUILD_REQUIREMENTS:
            _fail("unknown_build_requirement", requirement)
        if rulebook_kind not in RULEBOOK_BUILD_KINDS:
            _fail("unknown_rulebook_build_kind", rulebook_kind)
        for field, value in (
            ("source_identity", source),
            ("builder_identity", builder),
            ("artifact_identity", artifact),
        ):
            if not _ID.fullmatch(value):
                _fail("invalid_resource_identity", f"{field}={value}")
        if self.shared_build_key is not None:
            key = _text(self.shared_build_key, "shared_build_key")
            if not _ID.fullmatch(key):
                _fail("invalid_resource_identity", f"shared_build_key={key}")
        if requirement == "none":
            valid = (
                not self.reads_tbgd
                and not self.full_lowering_required
                and rulebook_kind == "none"
            )
        elif requirement == "small_fixture_rulebook":
            valid = (
                not self.reads_tbgd
                and not self.full_lowering_required
                and rulebook_kind == "small_fixture"
            )
        elif requirement == "source_inventory":
            valid = (
                self.reads_tbgd
                and not self.full_lowering_required
                and rulebook_kind in {"none", "focused_source"}
            )
        else:
            valid = (
                self.reads_tbgd
                and self.full_lowering_required
                and rulebook_kind in {"focused_source", "full_lowering"}
            )
        if not valid:
            _fail(
                "resource_combination_invalid",
                (
                    f"{requirement}, reads_tbgd={self.reads_tbgd}, "
                    f"full_lowering={self.full_lowering_required}, "
                    f"rulebook={rulebook_kind}"
                ),
            )
        object.__setattr__(self, "build_requirement", requirement)
        object.__setattr__(self, "rulebook_build_kind", rulebook_kind)
        object.__setattr__(self, "source_identity", source)
        object.__setattr__(self, "builder_identity", builder)
        object.__setattr__(self, "artifact_identity", artifact)

    def to_json(self) -> dict[str, Any]:
        return {
            "build_requirement": self.build_requirement,
            "reads_tbgd": self.reads_tbgd,
            "full_lowering_required": self.full_lowering_required,
            "rulebook_build_kind": self.rulebook_build_kind,
            "source_identity": self.source_identity,
            "builder_identity": self.builder_identity,
            "artifact_identity": self.artifact_identity,
            "shared_build_key": self.shared_build_key,
        }


@dataclass(frozen=True, slots=True)
class ValidatorEntry:
    entry_id: str
    module: str
    mode_id: str
    fixed_argv: tuple[str, ...]
    lifecycle_classification: str
    tier: str
    domains: tuple[str, ...]
    triggers: tuple[str, ...]
    cli_inputs: tuple[CliInputSpec, ...]
    resources: ResourceRequirement
    output_flag: str
    output_subdir: str
    summary_relative_path: str
    replacement_status: str
    replaced_by: tuple[str, ...]
    dependencies: tuple[str, ...]
    current_selectable: bool
    current_contract_predicates: tuple[str, ...]
    classification_reason: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        entry_id = _text(self.entry_id, "entry_id")
        module = _text(self.module, "module")
        mode_id = _text(self.mode_id, "mode_id")
        lifecycle = _text(
            self.lifecycle_classification, "lifecycle_classification"
        )
        tier = _text(self.tier, "tier")
        output_flag = _text(self.output_flag, "output_flag")
        output_subdir = _text(self.output_subdir, "output_subdir")
        summary = _text(
            self.summary_relative_path, "summary_relative_path"
        )
        replacement = _text(self.replacement_status, "replacement_status")
        reason = _text(self.classification_reason, "classification_reason")
        _boolean(self.current_selectable, "current_selectable")
        if type(self.resources) is not ResourceRequirement:
            _fail("invalid_type", "resources must be ResourceRequirement")
        fixed_argv = _strings(
            self.fixed_argv, "fixed_argv", ordered=True
        )
        domains = _strings(self.domains, "domains", allow_empty=False)
        triggers = _strings(self.triggers, "triggers")
        replaced_by = _strings(self.replaced_by, "replaced_by")
        dependencies = _strings(self.dependencies, "dependencies")
        predicates = _strings(
            self.current_contract_predicates,
            "current_contract_predicates",
        )
        limitations = _strings(self.limitations, "limitations")
        if isinstance(self.cli_inputs, (str, bytes, Mapping)):
            _fail("invalid_type", "cli_inputs must be a sequence")
        cli_inputs = tuple(self.cli_inputs)
        if any(type(item) is not CliInputSpec for item in cli_inputs):
            _fail("invalid_type", "cli_inputs contains a non-CliInputSpec")
        cli_inputs = tuple(
            sorted(cli_inputs, key=lambda item: (item.render_order, item.input_id))
        )
        if not _ID.fullmatch(entry_id):
            _fail("invalid_entry_id", entry_id)
        if not _MODULE.fullmatch(module):
            _fail("invalid_module", module)
        if not _ID.fullmatch(mode_id):
            _fail("invalid_mode_id", mode_id)
        if lifecycle not in LIFECYCLE_CLASSIFICATIONS:
            _fail("unknown_lifecycle", lifecycle)
        if tier not in VALIDATION_TIERS:
            _fail("unknown_tier", tier)
        unknown_domains = set(domains) - KNOWN_DOMAINS
        unknown_triggers = set(triggers) - KNOWN_TRIGGERS
        if unknown_domains:
            _fail("unknown_domain", repr(sorted(unknown_domains)))
        if unknown_triggers:
            _fail("unknown_trigger", repr(sorted(unknown_triggers)))
        if any(not _FLAG.fullmatch(flag) for flag in fixed_argv):
            _fail("invalid_cli_flag", repr(fixed_argv))
        if not _FLAG.fullmatch(output_flag):
            _fail("invalid_cli_flag", output_flag)
        if not _PATH_PART.fullmatch(output_subdir):
            _fail("output_path_unsafe", output_subdir)
        summary_path = PurePosixPath(summary)
        if (
            summary_path.is_absolute()
            or ".." in summary_path.parts
            or summary_path.name != summary
            or summary_path.suffix != ".json"
        ):
            _fail("summary_path_invalid", summary)
        if replacement not in REPLACEMENT_STATUSES:
            _fail("unknown_replacement_status", replacement)
        if replacement == "complete" and not replaced_by:
            _fail("replacement_target_missing", entry_id)
        if replacement == "not_applicable" and replaced_by:
            _fail("replacement_status_conflict", entry_id)
        input_ids = tuple(item.input_id for item in cli_inputs)
        input_flags = tuple(item.flag for item in cli_inputs)
        if len(set(input_ids)) != len(input_ids):
            _fail("duplicate_input_id", entry_id)
        if len(set(input_flags)) != len(input_flags):
            _fail("duplicate_input_flag", entry_id)
        if set(fixed_argv) & {output_flag, *input_flags}:
            _fail("command_flag_collision", entry_id)
        if self.current_selectable and not (
            lifecycle == "active_contract" and tier == "direct"
        ):
            _fail("selectability_conflict", entry_id)
        if tier == "direct" and (
            self.resources.reads_tbgd
            or self.resources.full_lowering_required
        ):
            _fail("direct_heavy_resource_conflict", entry_id)
        if lifecycle == "catalog_audit" and tier not in {"catalog", "full"}:
            _fail("lifecycle_tier_conflict", entry_id)
        if lifecycle == "historical_evidence" and tier != "full":
            _fail("lifecycle_tier_conflict", entry_id)
        if lifecycle == "active_contract" and tier == "direct":
            if not triggers or not predicates:
                _fail("current_contract_metadata_missing", entry_id)
        elif predicates:
            _fail("historical_current_predicate", entry_id)
        tbgd_inputs = tuple(
            item for item in cli_inputs if item.input_kind == "tbgd_root"
        )
        if self.resources.reads_tbgd and not any(
            item.semantic_required for item in tbgd_inputs
        ):
            _fail("tbgd_semantic_input_missing", entry_id)
        if not self.resources.reads_tbgd and any(
            item.semantic_required for item in tbgd_inputs
        ):
            _fail("tbgd_semantic_input_conflict", entry_id)
        object.__setattr__(self, "entry_id", entry_id)
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "mode_id", mode_id)
        object.__setattr__(self, "fixed_argv", fixed_argv)
        object.__setattr__(self, "lifecycle_classification", lifecycle)
        object.__setattr__(self, "tier", tier)
        object.__setattr__(self, "domains", domains)
        object.__setattr__(self, "triggers", triggers)
        object.__setattr__(self, "cli_inputs", cli_inputs)
        object.__setattr__(self, "output_flag", output_flag)
        object.__setattr__(self, "output_subdir", output_subdir)
        object.__setattr__(self, "summary_relative_path", summary)
        object.__setattr__(self, "replacement_status", replacement)
        object.__setattr__(self, "replaced_by", replaced_by)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self, "current_contract_predicates", predicates
        )
        object.__setattr__(self, "classification_reason", reason)
        object.__setattr__(self, "limitations", limitations)

    @property
    def mode_identity(self) -> tuple[str, str]:
        return (self.module, self.mode_id)

    @property
    def command_identity(self) -> tuple[Any, ...]:
        return (
            self.module,
            self.fixed_argv,
            tuple(item.flag for item in self.cli_inputs),
            self.output_flag,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "module": self.module,
            "mode_id": self.mode_id,
            "fixed_argv": list(self.fixed_argv),
            "lifecycle_classification": self.lifecycle_classification,
            "tier": self.tier,
            "domains": list(self.domains),
            "triggers": list(self.triggers),
            "cli_inputs": [item.to_json() for item in self.cli_inputs],
            "resources": self.resources.to_json(),
            "output_flag": self.output_flag,
            "output_subdir": self.output_subdir,
            "summary_relative_path": self.summary_relative_path,
            "replacement_status": self.replacement_status,
            "replaced_by": list(self.replaced_by),
            "dependencies": list(self.dependencies),
            "current_selectable": self.current_selectable,
            "current_contract_predicates": list(
                self.current_contract_predicates
            ),
            "classification_reason": self.classification_reason,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ValidationRegistry:
    entries: tuple[ValidatorEntry, ...]
    schema_version: str = REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        schema = _text(self.schema_version, "schema_version")
        if schema != REGISTRY_SCHEMA_VERSION:
            _fail("schema_version_unsupported", schema)
        if isinstance(self.entries, (str, bytes, Mapping)):
            _fail("invalid_type", "entries must be a sequence")
        entries = tuple(self.entries)
        if not entries or any(type(item) is not ValidatorEntry for item in entries):
            _fail("invalid_type", "entries must contain ValidatorEntry values")
        entries = tuple(sorted(entries, key=lambda item: item.entry_id))
        ids = tuple(item.entry_id for item in entries)
        modes = tuple(item.mode_identity for item in entries)
        commands = tuple(item.command_identity for item in entries)
        if len(set(ids)) != len(ids):
            _fail("duplicate_entry_id", "entry IDs must be unique")
        if len(set(modes)) != len(modes):
            _fail("duplicate_mode_identity", "module + mode must be unique")
        if len(set(commands)) != len(commands):
            _fail(
                "command_identity_collision",
                "distinct entries have the same command template",
            )
        known = set(ids)
        for entry in entries:
            missing_replacements = set(entry.replaced_by) - known
            missing_dependencies = set(entry.dependencies) - known
            if missing_replacements:
                _fail(
                    "replacement_dangling",
                    f"{entry.entry_id}: {sorted(missing_replacements)}",
                )
            if missing_dependencies:
                _fail(
                    "dependency_dangling",
                    f"{entry.entry_id}: {sorted(missing_dependencies)}",
                )
        shared_identities: dict[str, set[tuple[Any, ...]]] = {}
        for entry in entries:
            resource = entry.resources
            if resource.shared_build_key is None:
                continue
            shared_identities.setdefault(
                resource.shared_build_key, set()
            ).add(
                (
                    resource.build_requirement,
                    resource.reads_tbgd,
                    resource.full_lowering_required,
                    resource.rulebook_build_kind,
                    resource.source_identity,
                    resource.builder_identity,
                    resource.artifact_identity,
                )
            )
        if any(len(identities) != 1 for identities in shared_identities.values()):
            _fail(
                "shared_build_identity_conflict",
                "one shared key describes different source/build/artifact facts",
            )
        _reject_cycles(
            {entry.entry_id: entry.replaced_by for entry in entries},
            "replacement_cycle",
        )
        _reject_cycles(
            {entry.entry_id: entry.dependencies for entry in entries},
            "dependency_cycle",
        )
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "schema_version", schema)

    def get(self, entry_id: str) -> ValidatorEntry:
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry
        raise KeyError(entry_id)

    @property
    def entry_ids(self) -> tuple[str, ...]:
        return tuple(entry.entry_id for entry in self.entries)

    @property
    def triggers(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for entry in self.entries for value in entry.triggers})
        )

    @property
    def domains(self) -> tuple[str, ...]:
        return tuple(
            sorted({value for entry in self.entries for value in entry.domains})
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_json() for entry in self.entries],
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_json(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()


def _reject_cycles(
    graph: dict[str, tuple[str, ...]], code: str
) -> None:
    active: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            _fail(code, node)
        if node in done:
            return
        active.add(node)
        for target in graph[node]:
            visit(target)
        active.remove(node)
        done.add(node)

    for node in sorted(graph):
        visit(node)


def _input(
    input_id: str,
    flag: str,
    kind: str,
    *,
    cli_required: bool,
    semantic_required: bool,
    description: str,
) -> CliInputSpec:
    return CliInputSpec(
        input_id,
        flag,
        kind,
        cli_required,
        True,
        semantic_required,
        description,
    )


TBGD_REQUIRED = _input(
    "tbgd_root",
    "--tbgd-root",
    "tbgd_root",
    cli_required=True,
    semantic_required=True,
    description="CLI and mode semantics require an explicit TBGD root.",
)
TBGD_OPTIONAL_CLI = _input(
    "tbgd_root",
    "--tbgd-root",
    "tbgd_root",
    cli_required=False,
    semantic_required=True,
    description="CLI can auto-discover TBGD; deterministic planning cannot.",
)
TBGD_CLI_ONLY = _input(
    "tbgd_root",
    "--tbgd-root",
    "tbgd_root",
    cli_required=True,
    semantic_required=False,
    description="Runtime-only argparse requires this path but does not read it.",
)
S0_SUMMARY_REQUIRED = _input(
    "s0_summary",
    "--s0-summary",
    "validation_summary",
    cli_required=True,
    semantic_required=True,
    description="P8-S1 consumes the existing S0 validation summary.",
)


def _none() -> ResourceRequirement:
    return ResourceRequirement(
        "none", False, False, "none", "none", "none", "none"
    )


def _small(builder: str, artifact: str) -> ResourceRequirement:
    return ResourceRequirement(
        "small_fixture_rulebook",
        False,
        False,
        "small_fixture",
        "in_memory_fixture",
        builder,
        artifact,
    )


def _source(
    source: str,
    builder: str,
    artifact: str,
    *,
    rulebook: str = "none",
) -> ResourceRequirement:
    return ResourceRequirement(
        "source_inventory",
        True,
        False,
        rulebook,
        source,
        builder,
        artifact,
    )


def _full(
    builder: str,
    artifact: str,
    *,
    source: str = "tbgd.full_tree",
    rulebook: str = "full_lowering",
) -> ResourceRequirement:
    return ResourceRequirement(
        "full_lowering_rulebook",
        True,
        True,
        rulebook,
        source,
        builder,
        artifact,
    )


def _entry(
    entry_id: str,
    module: str,
    mode: str,
    lifecycle: str,
    tier: str,
    resource: ResourceRequirement,
    summary: str,
    domains: tuple[str, ...],
    *,
    fixed: tuple[str, ...] = (),
    triggers: tuple[str, ...] = (),
    inputs: tuple[CliInputSpec, ...] = (),
    predicates: tuple[str, ...] = (),
    reason: str,
    limitations: tuple[str, ...] = (),
) -> ValidatorEntry:
    selectable = lifecycle == "active_contract" and tier == "direct"
    return ValidatorEntry(
        entry_id=entry_id,
        module=f"simulator_v8_clean_core.tools.{module}",
        mode_id=mode,
        fixed_argv=fixed,
        lifecycle_classification=lifecycle,
        tier=tier,
        domains=domains,
        triggers=triggers,
        cli_inputs=inputs,
        resources=resource,
        output_flag="--output-dir",
        output_subdir=entry_id.replace(".", "_"),
        summary_relative_path=summary,
        replacement_status=(
            "incomplete"
            if lifecycle == "historical_evidence"
            else "not_applicable"
        ),
        replaced_by=(),
        dependencies=(),
        current_selectable=selectable,
        current_contract_predicates=predicates,
        classification_reason=reason,
        limitations=limitations,
    )


_DEFAULT_ENTRIES = (
    _entry(
        "vg.s1.committed_state_immutability.direct",
        "validate_vg_s1_committed_state_immutability",
        "default",
        "active_contract",
        "direct",
        _none(),
        "validation_summary_vg_s1_committed_state_immutability.json",
        ("committed_state",),
        triggers=("committed_state_changed",),
        predicates=("committed_state_is_recursively_immutable",),
        reason="Current committed-state alias isolation contract.",
    ),
    _entry(
        "vg.s2.committed_integrity_lifecycle.direct",
        "validate_vg_s2_committed_integrity_lifecycle",
        "default",
        "active_contract",
        "direct",
        _small("vg_s2.small_rulebook", "committed_integrity_rulebook"),
        "validation_summary_vg_s2_committed_integrity_lifecycle.json",
        ("committed_integrity", "lifecycle", "replay", "status"),
        triggers=("committed_integrity_changed", "lifecycle_contract_changed"),
        predicates=("committed_lifecycle_integrity_is_atomic",),
        reason="Current committed-integrity lifecycle contract.",
    ),
    _entry(
        "p7.s2.mutation_reducer_contract.direct",
        "validate_p7_s2_mutation_reducer_contract",
        "default",
        "active_contract",
        "direct",
        _none(),
        "validation_summary_p7_s2_mutation_reducer_contract.json",
        ("mutation_reducer", "replay"),
        triggers=("mutation_reducer_changed",),
        predicates=("mutation_reducer_contract_holds",),
        reason="Current mutation reducer and replay contract.",
    ),
    _entry(
        "p7.s3.selected_graph_atomic_commit.direct",
        "validate_p7_s3_selected_graph_atomic_commit",
        "default",
        "active_contract",
        "direct",
        _small("p7_s3.run_validation", "selected_graph_fixture_rulebook"),
        "validation_summary_p7_s3_selected_graph_atomic_commit.json",
        ("committed_integrity", "mutation_reducer", "selected_graph"),
        triggers=("selected_graph_commit_changed",),
        predicates=("selected_graph_commit_is_atomic",),
        reason="Current selected-graph atomic commit contract.",
    ),
    _entry(
        "p7.s15.rng_identity_replay.direct",
        "validate_p7_s15_rng_identity_replay",
        "default",
        "active_contract",
        "direct",
        _none(),
        "validation_summary_p7_s15_rng_identity_replay.json",
        ("replay", "rng"),
        triggers=("rng_or_replay_changed",),
        predicates=("rng_identity_and_replay_are_stable",),
        reason="Current RNG identity and replay contract.",
    ),
    _entry(
        "p8.s1.equipment_type_contract.direct",
        "validate_p8_s1_equipment_type_contract",
        "default",
        "active_contract",
        "direct",
        _small("p8_s1.fixture_builders", "equipment_contract_rulebooks"),
        "validation_summary_p8_s1_equipment_type_contract.json",
        ("character_build", "equipment"),
        triggers=("equipment_type_changed",),
        inputs=(S0_SUMMARY_REQUIRED,),
        predicates=("equipment_type_contract_holds",),
        reason="Current equipment type contract with S0 summary input.",
        limitations=("requires_existing_s0_summary_artifact",),
    ),
    _entry(
        "p8.s2.character_build.fixture",
        "validate_p8_s2_character_build_base_panel",
        "fixture_only",
        "active_contract",
        "direct",
        _small(
            "p8_s2.run_fixture_contract_validation",
            "character_build_fixture_rulebooks",
        ),
        "validation_summary_p8_s2_fixture_contract.json",
        ("character_build",),
        fixed=("--fixture-only",),
        triggers=("character_build_changed",),
        predicates=("character_build_fixture_contract_holds",),
        reason="Current fixture-only character-build contract.",
    ),
    _entry(
        "p8.s2.character_card_source.catalog",
        "validate_p8_s2_character_build_base_panel",
        "character_card_source_only",
        "catalog_audit",
        "catalog",
        _source(
            "tbgd.character_card_tables",
            "build_character_card_ir+build_character_action_definition_ir",
            "character_card_ir+focused_character_rulebooks",
            rulebook="focused_source",
        ),
        "validation_summary_p8_s2_character_card_source.json",
        ("character_card_source", "source_inventory"),
        fixed=("--character-card-source-only",),
        triggers=("character_card_source_changed",),
        inputs=(TBGD_OPTIONAL_CLI,),
        reason="Character-card source audit with two focused RuleBooks.",
        limitations=("heavy_plan_only", "shared_build_unproven"),
    ),
    _entry(
        "p8.s2.character_build.complete_catalog",
        "validate_p8_s2_character_build_base_panel",
        "default",
        "catalog_audit",
        "full",
        _full(
            "p8_s2.tbgd_lowering_build",
            "character_build_full_canonical_ir+rulebook",
        ),
        "validation_summary_p8_s2_character_build_base_panel.json",
        ("character_build", "character_card_source", "lowering"),
        triggers=("character_catalog_changed",),
        inputs=(TBGD_OPTIONAL_CLI,),
        reason="Complete character catalog with full lowering and RuleBook.",
        limitations=("heavy_plan_only", "shared_build_unproven"),
    ),
    _entry(
        "p8.r1.summon_halo.runtime",
        "validate_p8_r1_summon_runtime_halo_lifecycle",
        "runtime_only",
        "active_contract",
        "direct",
        _small("p8_r1.runtime_validation", "summon_halo_runtime_rulebook"),
        "validation_summary_p8_r1_summon_runtime_halo_lifecycle.json",
        ("halo", "lifecycle", "status", "summon"),
        fixed=("--runtime-only",),
        triggers=("lifecycle_contract_changed", "summon_halo_runtime_changed"),
        inputs=(TBGD_CLI_ONLY,),
        predicates=("summon_halo_runtime_lifecycle_contract_holds",),
        reason="Runtime-only contract; TBGD is CLI-only and unread.",
        limitations=("tbgd_root_is_cli_only_for_runtime_mode",),
    ),
    _entry(
        "p8.r1.summon_halo.source_catalog",
        "validate_p8_r1_summon_runtime_halo_lifecycle",
        "source_catalog_only",
        "catalog_audit",
        "catalog",
        _source(
            "tbgd.light_cone_catalog_and_ability_files",
            "build_light_cone_catalog",
            "light_cone_catalog+source_hash_matrix",
        ),
        "validation_summary_p8_r1_summon_runtime_halo_lifecycle.json",
        ("halo", "source_inventory", "summon"),
        fixed=("--source-catalog-only",),
        triggers=("summon_halo_source_changed",),
        inputs=(TBGD_REQUIRED,),
        reason="Light-cone source catalog audit without RuleBook.",
        limitations=("heavy_plan_only", "shared_build_unproven"),
    ),
    _entry(
        "p8.s8.light_cone.catalog_startup",
        "validate_p8_s8_light_cone_remaining_gameplay_closure",
        "catalog_startup_only",
        "catalog_audit",
        "catalog",
        _full(
            "p8_s8.focused_bundle+owned_combatant_lowering",
            "focused_equipment_rulebook+owned_combatant_catalog",
            source="tbgd.light_cone_and_owned_combatants",
            rulebook="focused_source",
        ),
        "validation_summary_p8_s8_catalog_startup.json",
        ("light_cone", "lowering", "source_inventory"),
        fixed=("--catalog-startup-only",),
        triggers=("light_cone_catalog_changed",),
        inputs=(TBGD_REQUIRED,),
        reason="Catalog startup: full owned-combatant lowering plus focused RuleBook.",
        limitations=("heavy_plan_only", "shared_build_unproven"),
    ),
    *(
        _entry(
            entry_id,
            module,
            "default",
            "historical_evidence",
            "full",
            _full(
                f"{module}.tbgd_lowering",
                f"{entry_id}.historical_rulebook",
            ),
            summary,
            domains,
            inputs=(TBGD_OPTIONAL_CLI,),
            reason=reason,
            limitations=("no_complete_current_replacement_proven",),
        )
        for entry_id, module, summary, domains, reason in (
            (
                "p7.current_tree.shared_aggregate.history",
                "validate_p7_current_tree_shared_regressions",
                "p7_current_tree_shared_regression_manifest.json",
                ("full_pipeline", "lifecycle", "lowering", "status", "summon"),
                "Historical shared aggregate retains old P2/P3 gap gates.",
            ),
            (
                "p1.phase1.aggregate.history",
                "validate_p1_9_phase1_aggregate",
                "validation_summary_p1_9_phase1_aggregate.json",
                ("full_pipeline", "lowering"),
                "Historical P1 aggregate; current coverage is unproven.",
            ),
            (
                "p2.status.aggregate.history",
                "validate_p2_status_system_complete",
                "validation_summary_p2_status_system_complete.json",
                ("full_pipeline", "lowering", "status"),
                "Historical P2 status aggregate.",
            ),
            (
                "p3.summon.aggregate.history",
                "validate_p3_summon_assistant_servant_complete",
                "validation_summary_p3_summon_assistant_servant_complete.json",
                ("full_pipeline", "lowering", "summon"),
                "Historical P3 summon aggregate with reopened gaps.",
            ),
            (
                "v0.209.full_pipeline.history",
                "validate_v0_209",
                "validation_summary_v0_209.json",
                ("full_pipeline", "lowering"),
                "Historical v0.209 full-pipeline evidence.",
            ),
        )
    ),
)

DEFAULT_REGISTRY = ValidationRegistry(_DEFAULT_ENTRIES)


def load_default_registry() -> ValidationRegistry:
    return DEFAULT_REGISTRY
