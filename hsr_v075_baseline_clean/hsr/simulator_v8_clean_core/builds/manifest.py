from __future__ import annotations

import hashlib
import json
import math
import threading
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any, cast

from ..build_types import canonical_json_fingerprint, require_sha256, require_text
from ..core.immutable_json import FrozenJSONDict, freeze_json, thaw_json
from ..core.model import BattleState, JSONValue, Mutation
from ..core.reducer import MutationReducer, ReplayResult
from ..rules.engine_rule_registry import ENGINE_RULE_REGISTRY_VERSION
from ..rules.ir import CanonicalIR, IRSource
from ..rules.rulebook import RuleBook
from ..systems.ability_provider import ability_provider_payload
from .character_assembler import assemble_character_build
from .models import CharacterBuildAssemblyResult, CharacterBuildInput


BUILD_MANIFEST_SCHEMA_VERSION = "p8_s19_formal_build_manifest_v1"
FORMAL_BUILD_MANIFEST_FLAG = "formal_build_manifest"

_PROTECTED_BUILD_UNIT_FLAGS = frozenset(
    {
        "build_mode",
        "character_build_id",
        "character_build_input_fingerprint",
        "character_build_result_fingerprint",
        "equipment_build_fingerprint",
        "equipment_result_fingerprint",
        "ability_providers",
    }
)

_SOURCE_FINGERPRINT_METADATA_KEYS = (
    "light_cone_source_content_fingerprint",
    "relic_source_content_fingerprint",
)
_IDENTITY_CACHE_LOCK = threading.Lock()
_IDENTITY_CACHE: dict[
    int,
    tuple[weakref.ReferenceType[RuleBook], "BuildRuleIdentity"],
] = {}


def _closed_mapping(
    value: object,
    field_name: str,
    allowed: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a JSON object")
    extra = sorted(set(value).difference(allowed))
    if extra:
        raise ValueError(f"{field_name} contains unsupported fields: {extra}")
    return cast(Mapping[str, object], value)


@dataclass(frozen=True)
class BuildRuleIdentity:
    source_fingerprint: str
    canonical_ir_fingerprint: str
    engine_rule_version: str

    def __post_init__(self) -> None:
        require_sha256(self.source_fingerprint, "source_fingerprint")
        require_sha256(self.canonical_ir_fingerprint, "canonical_ir_fingerprint")
        require_text(self.engine_rule_version, "engine_rule_version")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_fingerprint": self.source_fingerprint,
            "canonical_ir_fingerprint": self.canonical_ir_fingerprint,
            "engine_rule_version": self.engine_rule_version,
        }

    @classmethod
    def from_json(cls, value: object) -> "BuildRuleIdentity":
        row = _closed_mapping(
            value,
            "build_rule_identity",
            {
                "source_fingerprint",
                "canonical_ir_fingerprint",
                "engine_rule_version",
            },
        )
        return cls(
            source_fingerprint=require_sha256(
                row.get("source_fingerprint"),
                "source_fingerprint",
            ),
            canonical_ir_fingerprint=require_sha256(
                row.get("canonical_ir_fingerprint"),
                "canonical_ir_fingerprint",
            ),
            engine_rule_version=require_text(
                row.get("engine_rule_version"),
                "engine_rule_version",
            ),
        )


@dataclass(frozen=True)
class BuildManifestEntry:
    unit_id: str
    build_input: CharacterBuildInput
    result_fingerprint: str
    equipment_result_fingerprint: str

    def __post_init__(self) -> None:
        require_text(self.unit_id, "unit_id")
        if not isinstance(self.build_input, CharacterBuildInput):
            raise TypeError("build_input must be CharacterBuildInput")
        require_sha256(self.result_fingerprint, "result_fingerprint")
        require_sha256(
            self.equipment_result_fingerprint,
            "equipment_result_fingerprint",
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "unit_id": self.unit_id,
            "build_input": self.build_input.to_json(),
            "result_fingerprint": self.result_fingerprint,
            "equipment_result_fingerprint": self.equipment_result_fingerprint,
        }

    @classmethod
    def from_assembly(
        cls,
        unit_id: str,
        build_input: CharacterBuildInput,
        assembly_result: CharacterBuildAssemblyResult,
    ) -> "BuildManifestEntry":
        if not isinstance(assembly_result, CharacterBuildAssemblyResult):
            raise TypeError("assembly_result must be CharacterBuildAssemblyResult")
        if (
            assembly_result.assembly_status != "assembled"
            or assembly_result.battle_admission_status != "admitted"
        ):
            raise ValueError(
                "formal build manifest only admits battle-ready assembly results"
            )
        if (
            assembly_result.build_id != build_input.build_id
            or assembly_result.input_fingerprint != build_input.input_fingerprint
        ):
            raise ValueError("build manifest input and assembly identity mismatch")
        equipment = assembly_result.equipment_assembly_result
        if (
            equipment is None
            or equipment.build_fingerprint
            != build_input.equipment_build.build_fingerprint
        ):
            raise ValueError("build manifest equipment identity mismatch")
        return cls(
            unit_id=unit_id,
            build_input=build_input,
            result_fingerprint=assembly_result.result_fingerprint,
            equipment_result_fingerprint=equipment.result_fingerprint,
        )

    @classmethod
    def from_json(cls, value: object) -> "BuildManifestEntry":
        row = _closed_mapping(
            value,
            "build_manifest_entry",
            {
                "unit_id",
                "build_input",
                "result_fingerprint",
                "equipment_result_fingerprint",
            },
        )
        return cls(
            unit_id=cast(str, row.get("unit_id")),
            build_input=CharacterBuildInput.from_json(row.get("build_input")),
            result_fingerprint=require_sha256(
                row.get("result_fingerprint"),
                "result_fingerprint",
            ),
            equipment_result_fingerprint=require_sha256(
                row.get("equipment_result_fingerprint"),
                "equipment_result_fingerprint",
            ),
        )


@dataclass(frozen=True)
class FormalBuildManifest:
    rule_identity: BuildRuleIdentity
    entries: tuple[BuildManifestEntry, ...]
    schema_version: str = BUILD_MANIFEST_SCHEMA_VERSION
    manifest_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != BUILD_MANIFEST_SCHEMA_VERSION:
            raise ValueError("build_manifest_schema_version_unsupported")
        if not isinstance(self.rule_identity, BuildRuleIdentity):
            raise TypeError("rule_identity must be BuildRuleIdentity")
        if not isinstance(self.entries, (list, tuple)) or not all(
            isinstance(item, BuildManifestEntry) for item in self.entries
        ):
            raise TypeError("build manifest entries must contain BuildManifestEntry")
        entries = tuple(sorted(self.entries, key=lambda item: item.unit_id))
        unit_ids = tuple(item.unit_id for item in entries)
        if not entries or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("build manifest requires unique non-empty unit entries")
        object.__setattr__(self, "entries", entries)
        expected = canonical_json_fingerprint(self._fingerprint_payload())
        if self.manifest_fingerprint:
            require_sha256(self.manifest_fingerprint, "manifest_fingerprint")
            if self.manifest_fingerprint != expected:
                raise ValueError("build_manifest_fingerprint_mismatch")
        object.__setattr__(self, "manifest_fingerprint", expected)

    def _fingerprint_payload(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "rule_identity": self.rule_identity.to_json(),
            "entries": [entry.to_json() for entry in self.entries],
        }

    def to_json(self) -> dict[str, JSONValue]:
        return {
            **self._fingerprint_payload(),
            "manifest_fingerprint": self.manifest_fingerprint,
        }

    @classmethod
    def create(
        cls,
        rules: RuleBook,
        entries: Sequence[BuildManifestEntry],
    ) -> "FormalBuildManifest":
        return cls(
            rule_identity=current_build_rule_identity(rules),
            entries=tuple(entries),
        )

    @classmethod
    def from_json(cls, value: object) -> "FormalBuildManifest":
        row = _closed_mapping(
            value,
            "formal_build_manifest",
            {
                "schema_version",
                "rule_identity",
                "entries",
                "manifest_fingerprint",
            },
        )
        raw_entries = row.get("entries")
        if not isinstance(raw_entries, (list, tuple)):
            raise TypeError("formal build manifest entries must be a JSON array")
        return cls(
            schema_version=cast(str, row.get("schema_version")),
            rule_identity=BuildRuleIdentity.from_json(row.get("rule_identity")),
            entries=tuple(BuildManifestEntry.from_json(item) for item in raw_entries),
            manifest_fingerprint=require_sha256(
                row.get("manifest_fingerprint"),
                "manifest_fingerprint",
            ),
        )

    @classmethod
    def from_state(cls, state: BattleState) -> "FormalBuildManifest":
        value = state.global_flags.get(FORMAL_BUILD_MANIFEST_FLAG)
        if value is None:
            raise ValueError("formal_build_manifest_missing")
        return cls.from_json(value)


@dataclass(frozen=True)
class BuildLockedReplayResult:
    ok: bool
    expected: dict[str, JSONValue]
    actual: dict[str, JSONValue]
    errors: tuple[str, ...] = ()
    replay: ReplayResult | None = None
    build_manifest_verified: bool = False

    def __post_init__(self) -> None:
        expected = freeze_json(self.expected)
        actual = freeze_json(self.actual)
        if not isinstance(expected, FrozenJSONDict) or not isinstance(
            actual,
            FrozenJSONDict,
        ):
            raise TypeError("build replay snapshots must be JSON objects")
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "actual", actual)
        if not isinstance(self.errors, (list, tuple)) or not all(
            isinstance(item, str) for item in self.errors
        ):
            raise TypeError("build replay errors must contain strings")
        errors = tuple(self.errors)
        if self.ok and (
            errors
            or not self.build_manifest_verified
            or self.replay is None
            or not self.replay.ok
        ):
            raise ValueError("successful build replay requires verified replay evidence")
        object.__setattr__(self, "errors", errors)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "expected": cast(dict[str, JSONValue], thaw_json(self.expected)),
            "actual": cast(dict[str, JSONValue], thaw_json(self.actual)),
            "errors": list(self.errors),
            "build_manifest_verified": self.build_manifest_verified,
            "replay": self.replay.to_json() if self.replay is not None else None,
        }


class BuildLockedReplayVerifier:
    """Reassemble formal builds before applying a replay mutation batch."""

    def __init__(self, rules: RuleBook):
        if not isinstance(rules, RuleBook):
            raise TypeError("rules must be RuleBook")
        self.rules = rules

    def replay_snapshot(
        self,
        before: BattleState,
        mutations: tuple[Mutation, ...],
        expected_after: dict[str, JSONValue],
    ) -> BuildLockedReplayResult:
        if not isinstance(before, BattleState):
            raise TypeError("before must be BattleState")
        if not isinstance(mutations, tuple) or not all(
            isinstance(item, Mutation) for item in mutations
        ):
            raise TypeError("mutations must be a tuple of Mutation")
        if not isinstance(expected_after, dict):
            raise TypeError("expected_after must be a snapshot JSON object")
        before_snapshot = before.snapshot().to_json()
        try:
            manifest = FormalBuildManifest.from_state(before)
        except (TypeError, ValueError) as exc:
            return _blocked_replay(
                expected_after,
                before_snapshot,
                _error_code("build_manifest_invalid", exc),
            )

        expected_flags = expected_after.get("global_flags")
        expected_manifest = (
            expected_flags.get(FORMAL_BUILD_MANIFEST_FLAG)
            if isinstance(expected_flags, Mapping)
            else None
        )
        if expected_manifest != manifest.to_json():
            return _blocked_replay(
                expected_after,
                before_snapshot,
                "build_manifest_changed_by_transition",
            )

        binding_error = _manifest_state_binding_error(before, manifest)
        if binding_error:
            return _blocked_replay(
                expected_after,
                before_snapshot,
                binding_error,
            )
        mutation_error = _protected_build_mutation_error(mutations)
        if mutation_error:
            return _blocked_replay(
                expected_after,
                before_snapshot,
                mutation_error,
            )

        try:
            current_identity = current_build_rule_identity(self.rules)
        except (TypeError, ValueError) as exc:
            return _blocked_replay(
                expected_after,
                before_snapshot,
                _error_code("current_build_rule_identity_invalid", exc),
            )
        identity_errors = _identity_errors(manifest.rule_identity, current_identity)
        if identity_errors:
            return _blocked_replay(
                expected_after,
                before_snapshot,
                *identity_errors,
            )

        for entry in manifest.entries:
            try:
                current_result = assemble_character_build(
                    self.rules,
                    entry.build_input,
                )
            except (TypeError, ValueError) as exc:
                return _blocked_replay(
                    expected_after,
                    before_snapshot,
                    _error_code(
                        f"build_reassembly_failed:{entry.unit_id}",
                        exc,
                    ),
                )
            current_equipment = current_result.equipment_assembly_result
            if (
                current_result.assembly_status != "assembled"
                or current_result.battle_admission_status != "admitted"
                or current_result.result_fingerprint != entry.result_fingerprint
                or current_equipment is None
                or current_equipment.result_fingerprint
                != entry.equipment_result_fingerprint
            ):
                return _blocked_replay(
                    expected_after,
                    before_snapshot,
                    f"build_reassembly_result_mismatch:{entry.unit_id}",
                )
            provider_error = _provider_registry_error(
                before,
                entry,
                current_result,
                mutations,
            )
            if provider_error:
                return _blocked_replay(
                    expected_after,
                    before_snapshot,
                    provider_error,
                )

        replay = MutationReducer().replay_snapshot(before, mutations, expected_after)
        return BuildLockedReplayResult(
            ok=replay.ok,
            expected=replay.expected,
            actual=replay.actual,
            errors=replay.errors,
            replay=replay,
            build_manifest_verified=True,
        )


def current_build_rule_identity(rules: RuleBook) -> BuildRuleIdentity:
    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be RuleBook")
    cache_key = id(rules)
    with _IDENTITY_CACHE_LOCK:
        cached = _IDENTITY_CACHE.get(cache_key)
        if cached is not None and cached[0]() is rules:
            return cached[1]

    identity = BuildRuleIdentity(
        source_fingerprint=_source_fingerprint(rules.ir),
        canonical_ir_fingerprint=canonical_ir_fingerprint(rules.ir),
        engine_rule_version=ENGINE_RULE_REGISTRY_VERSION,
    )

    def clear(reference: weakref.ReferenceType[RuleBook]) -> None:
        with _IDENTITY_CACHE_LOCK:
            current = _IDENTITY_CACHE.get(cache_key)
            if current is not None and current[0] is reference:
                _IDENTITY_CACHE.pop(cache_key, None)

    reference = weakref.ref(rules, clear)
    with _IDENTITY_CACHE_LOCK:
        _IDENTITY_CACHE[cache_key] = (reference, identity)
    return identity


def canonical_ir_fingerprint(ir: CanonicalIR) -> str:
    digest = hashlib.sha256()
    _update_digest(digest, ir)
    return digest.hexdigest()


def _source_fingerprint(ir: CanonicalIR) -> str:
    tokens: set[str] = set()
    for key in _SOURCE_FINGERPRINT_METADATA_KEYS:
        value = ir.metadata.get(key)
        if isinstance(value, Mapping):
            tokens.add(canonical_json_fingerprint(cast(JSONValue, value)))
    _collect_source_fingerprint_tokens(ir, tokens, set())
    if not tokens:
        raise ValueError("canonical_ir_source_fingerprint_missing")
    return canonical_json_fingerprint({"source_fingerprints": sorted(tokens)})


def _collect_source_fingerprint_tokens(
    value: object,
    tokens: set[str],
    seen: set[int],
) -> None:
    if value is None or isinstance(value, (bool, int, float, Decimal, str)):
        return
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    if isinstance(value, IRSource):
        fingerprint = value.evidence.get("source_fingerprint")
        if isinstance(fingerprint, Mapping):
            tokens.add(
                canonical_json_fingerprint(cast(JSONValue, fingerprint))
            )
        return
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            _collect_source_fingerprint_tokens(
                getattr(value, item.name),
                tokens,
                seen,
            )
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_source_fingerprint_tokens(item, tokens, seen)
        return
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            _collect_source_fingerprint_tokens(item, tokens, seen)


def _identity_errors(
    expected: BuildRuleIdentity,
    actual: BuildRuleIdentity,
) -> tuple[str, ...]:
    errors: list[str] = []
    if expected.source_fingerprint != actual.source_fingerprint:
        errors.append("build_source_fingerprint_mismatch")
    if expected.canonical_ir_fingerprint != actual.canonical_ir_fingerprint:
        errors.append("build_canonical_ir_fingerprint_mismatch")
    if expected.engine_rule_version != actual.engine_rule_version:
        errors.append("build_engine_rule_version_mismatch")
    return tuple(errors)


def _provider_registry_error(
    state: BattleState,
    entry: BuildManifestEntry,
    assembly_result: CharacterBuildAssemblyResult | None = None,
    mutations: tuple[Mutation, ...] = (),
) -> str:
    unit = state.units.get(entry.unit_id)
    if unit is None:
        return f"build_manifest_unit_missing:{entry.unit_id}"
    if assembly_result is None:
        return f"build_reassembly_result_missing:{entry.unit_id}"
    equipment = assembly_result.equipment_assembly_result
    assert equipment is not None
    expected = tuple(
        ability_provider_payload(entry.unit_id, selection)
        for selection in equipment.dynamic_mechanisms
    )
    raw_actual = unit.flags.get("ability_providers", ())
    if not isinstance(raw_actual, (list, tuple)) or not all(
        isinstance(item, Mapping) for item in raw_actual
    ):
        return f"build_provider_registry_invalid:{entry.unit_id}"
    actual = tuple(
        sorted(
            (dict(item) for item in raw_actual),
            key=lambda item: str(item.get("provider_id") or ""),
        )
    )
    expected = tuple(sorted(expected, key=lambda item: str(item["provider_id"])))
    registrations = tuple(
        mutation
        for mutation in mutations
        if mutation.source == "ability_provider_registry"
        and mutation.path
        == ("units", entry.unit_id, "flags", "ability_providers")
    )
    if registrations:
        if len(registrations) != 1:
            return f"build_provider_identity_mismatch:{entry.unit_id}"
        registration = registrations[0]
        registered = registration.metadata.get("providers")
        if (
            not actual
            and (
                (
                    registration.before is None
                    and registration.before_exists is False
                )
                or (
                    registration.before_exists is True
                    and isinstance(registration.before, (list, tuple))
                    and not registration.before
                )
            )
            and isinstance(registered, (list, tuple))
            and tuple(registered) == expected
            and tuple(registration.after) == expected
            and registration.reason == "register_canonical_ability_provider"
        ):
            return ""
        return f"build_provider_identity_mismatch:{entry.unit_id}"
    if actual == expected:
        return ""
    return f"build_provider_identity_mismatch:{entry.unit_id}"


def _manifest_state_binding_error(
    state: BattleState,
    manifest: FormalBuildManifest,
) -> str:
    expected_unit_ids = {entry.unit_id for entry in manifest.entries}
    actual_unit_ids = {
        unit_id
        for unit_id, unit in state.units.items()
        if unit.flags.get("build_mode") == "assembled_character_build"
    }
    if actual_unit_ids != expected_unit_ids:
        return "build_manifest_formal_unit_set_mismatch"
    for entry in manifest.entries:
        unit = state.units[entry.unit_id]
        expected_flags = {
            "character_build_id": entry.build_input.build_id,
            "character_build_input_fingerprint": entry.build_input.input_fingerprint,
            "character_build_result_fingerprint": entry.result_fingerprint,
            "equipment_build_fingerprint": (
                entry.build_input.equipment_build.build_fingerprint
            ),
            "equipment_result_fingerprint": entry.equipment_result_fingerprint,
        }
        if any(
            unit.flags.get(key) != value
            for key, value in expected_flags.items()
        ):
            return f"build_manifest_unit_identity_mismatch:{entry.unit_id}"
    return ""


def _protected_build_mutation_error(mutations: tuple[Mutation, ...]) -> str:
    for mutation in mutations:
        if mutation.path == ("global_flags", FORMAL_BUILD_MANIFEST_FLAG):
            return "build_manifest_mutation_not_admitted"
        if (
            len(mutation.path) >= 3
            and mutation.path[0] == "units"
            and mutation.path[2] == "flags"
            and (
                len(mutation.path) == 3
                or mutation.path[3] in _PROTECTED_BUILD_UNIT_FLAGS
            )
        ):
            if (
                len(mutation.path) == 4
                and mutation.path[3] == "ability_providers"
                and mutation.source == "ability_provider_registry"
                and mutation.reason == "register_canonical_ability_provider"
            ):
                continue
            return f"build_identity_mutation_not_admitted:{mutation.path[1]}"
    return ""


def _blocked_replay(
    expected: dict[str, JSONValue],
    actual: dict[str, JSONValue],
    *errors: str,
) -> BuildLockedReplayResult:
    return BuildLockedReplayResult(
        ok=False,
        expected=expected,
        actual=actual,
        errors=tuple(errors),
    )


def _error_code(prefix: str, exc: Exception) -> str:
    detail = str(exc).split(":", 1)[0].strip().replace(" ", "_")
    return f"{prefix}:{detail or type(exc).__name__}"


def _update_digest(digest: Any, value: object) -> None:
    if value is None:
        digest.update(b"n;")
        return
    if isinstance(value, bool):
        digest.update(b"b1;" if value else b"b0;")
        return
    if isinstance(value, int):
        digest.update(f"i{value};".encode("ascii"))
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical IR contains a non-finite float")
        digest.update(b"f")
        digest.update(json.dumps(value, allow_nan=False).encode("ascii"))
        digest.update(b";")
        return
    if isinstance(value, Decimal):
        digest.update(f"d{value};".encode("ascii"))
        return
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        digest.update(f"s{len(encoded)}:".encode("ascii"))
        digest.update(encoded)
        digest.update(b";")
        return
    if is_dataclass(value) and not isinstance(value, type):
        digest.update(f"c{type(value).__module__}.{type(value).__qualname__}{{".encode("utf-8"))
        for item in fields(value):
            _update_digest(digest, item.name)
            _update_digest(digest, getattr(value, item.name))
        digest.update(b"};")
        return
    if isinstance(value, Mapping):
        digest.update(b"m{")
        for key in sorted(value, key=lambda item: str(item)):
            _update_digest(digest, str(key))
            _update_digest(digest, value[key])
        digest.update(b"};")
        return
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        digest.update(b"q[")
        for item in value:
            _update_digest(digest, item)
        digest.update(b"];")
        return
    raise TypeError(
        f"unsupported Canonical IR fingerprint value: {type(value).__name__}"
    )
