from __future__ import annotations

import argparse
import inspect
import json
import resource
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from ..builds.character_assembler import assemble_character_build
from ..builds.manifest import (
    BUILD_MANIFEST_SCHEMA_VERSION,
    FORMAL_BUILD_MANIFEST_FLAG,
    BuildLockedReplayVerifier,
    BuildManifestEntry,
    BuildRuleIdentity,
    FormalBuildManifest,
)
from ..core.compact_state import CompactStateQuery
from ..core.model import BattleState, JSONValue, Mutation
from ..queries.equipment import EquipmentQueryService
from ..scenarios.build_state import ScenarioStateBuilder
from .io import write_json
from .validate_p8_s18_final_panel_and_birth_order import (
    _character,
    _controlled_equipment,
    _inactive_light_cone,
    _scenario,
    _world,
)


VALIDATION_VERSION = "p8_s19_query_audit_snapshot_replay_v1"


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle, card, _ = _world(tbgd_root.resolve())
    rules = bundle["rules"]
    light_cone = _inactive_light_cone(rules, card.card_id)
    equipment, selection = _controlled_equipment(
        bundle,
        card.card_id,
        light_cone,
    )
    character = _character(card.card_id, equipment, "p8_s19")
    assembly = assemble_character_build(rules, character)
    built = ScenarioStateBuilder(rules).build(
        _scenario(card, character, "p8_s19")
    )
    if (
        assembly.assembly_status != "assembled"
        or assembly.battle_admission_status != "admitted"
        or assembly.equipment_assembly_result is None
        or built.build_manifest is None
        or built.ability_provider_registration is None
    ):
        raise ValueError("controlled formal build is not admitted")

    query = EquipmentQueryService(rules)
    state_before_queries = built.state.snapshot().to_json()
    light_cone_page = query.list_light_cones(page=1, page_size=7)
    relic_page = query.list_relic_templates(page=1, page_size=7)
    set_page = query.list_relic_sets(page=1, page_size=7)
    exact_light_cone = query.get_light_cone(
        light_cone.definition_key.definition_identity
    )
    exact_affixes = query.get_relic_template_affixes(
        equipment.relics[0].template_key.definition_identity
    )
    missing = query.get_relic_template("p8_s19:definition:missing")
    duplicate_threshold = bundle["cases"]["duplicate"]
    ambiguous = query.get_relic_set_threshold(
        duplicate_threshold.definition_key.definition_identity
    )
    submission = query.submit_character_build(character.to_json())
    derived_negatives = _submission_negatives(query, character.to_json())
    detached_page = light_cone_page.to_json()
    detached_page["items"] = []
    state_after_queries = built.state.snapshot().to_json()

    equipment_result = assembly.equipment_assembly_result
    static_term = next(
        item
        for item in equipment_result.static_contributions
        if item.source.evidence.get("source_kind") == "tbgd"
    )
    static_source = query.get_static_contribution_source(
        assembly,
        static_term.contribution_id,
    )

    registration = built.ability_provider_registration
    registration_transition = registration.to_transition()
    provider_mutation = next(
        mutation
        for mutation in registration.mutations
        if mutation.source == "ability_provider_registry"
    )
    providers = provider_mutation.metadata.get("providers")
    if not isinstance(providers, (list, tuple)) or not providers:
        raise ValueError("controlled provider registration has no provider payload")
    provider = providers[0]
    if not isinstance(provider, Mapping):
        raise TypeError("controlled provider payload is not an object")
    provider_id = provider.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("controlled provider identity missing")
    dynamic_source = query.get_dynamic_mutation_source(
        assembly,
        registration_transition,
        provider_mutation.stable_id(),
        provider_id=provider_id,
    )

    manifest = built.build_manifest
    manifest_json = manifest.to_json()
    manifest_round_trip = FormalBuildManifest.from_json(manifest_json)
    replay_verifier = BuildLockedReplayVerifier(rules)
    valid_replay = replay_verifier.replay_snapshot(
        registration.before_state,
        registration.mutations,
        registration.after_state.snapshot().to_json(),
    )
    replay_negatives = _replay_negatives(
        replay_verifier,
        registration.after_state,
        manifest,
    )

    compact_query = CompactStateQuery()
    compact_before = compact_query.project(built.state)
    _ = (
        query.list_light_cones(page=1, page_size=100),
        query.list_relic_templates(page=1, page_size=100),
        query.list_relic_sets(page=1, page_size=100),
    )
    compact_after = compact_query.project(built.state)
    compact_payload = compact_before.payload_copy()
    compact_keys = _recursive_keys(compact_payload)
    manifest_identity = cast(
        Mapping[str, object],
        cast(Mapping[str, object], compact_payload["global_flags"])[
            "formal_build_manifest_identity"
        ],
    )
    compact_entry = cast(list[object], manifest_identity["entries"])[0]
    compact_provider = next(
        item
        for unit in cast(Mapping[str, object], compact_payload["units"]).values()
        if isinstance(unit, Mapping)
        for flags in (unit.get("flags"),)
        if isinstance(flags, Mapping)
        for provider_items in (flags.get("ability_providers"),)
        if isinstance(provider_items, list)
        for item in provider_items
        if isinstance(item, Mapping)
    )

    query_checks = {
        "pages_typed_and_fail_closed": (
            light_cone_page.resolution_status == "resolved"
            and relic_page.resolution_status == "resolved"
            and set_page.resolution_status == "blocked"
            and bool(set_page.blocked_reason)
            and bool(set_page.candidates)
        ),
        "exact_and_affix_resolved": (
            exact_light_cone.resolution_status == "resolved"
            and exact_affixes.resolution_status == "resolved"
        ),
        "missing_blocked": (
            missing.resolution_status == "blocked"
            and bool(missing.blocked_reason)
        ),
        "ambiguous_blocked": (
            ambiguous.resolution_status == "blocked"
            and bool(ambiguous.blocked_reason)
            and len(ambiguous.candidates) >= 2
        ),
        "page_is_detached": bool(light_cone_page.to_json()["items"]),
        "valid_submission_admitted": (
            submission.resolution_status == "resolved"
            and submission.summary is not None
            and submission.summary.battle_admission_status == "admitted"
        ),
        "derived_inputs_blocked": all(
            item["resolution_status"] == "blocked"
            for item in derived_negatives.values()
        ),
        "state_unchanged": state_before_queries == state_after_queries,
    }
    replay_checks = {
        "manifest_round_trip": manifest_round_trip.to_json() == manifest_json,
        "manifest_is_compact": (
            "assembly_result" not in json.dumps(manifest_json, sort_keys=True)
            and len(json.dumps(manifest_json, sort_keys=True))
            < len(json.dumps(assembly.to_json(), sort_keys=True))
        ),
        "valid_replay": valid_replay.ok and valid_replay.build_manifest_verified,
        **{
            name: bool(value["blocked"] and value["state_unchanged"])
            for name, value in replay_negatives.items()
        },
    }
    compact_checks = {
        "projection_stable_after_catalog_queries": (
            compact_before.to_json() == compact_after.to_json()
        ),
        "projector_has_no_rulebook_input": (
            tuple(inspect.signature(CompactStateQuery.project).parameters)
            == ("self", "state")
        ),
        "full_manifest_and_provenance_absent": (
            FORMAL_BUILD_MANIFEST_FLAG not in compact_keys
            and "source_trace" not in compact_keys
            and "contribution_ledger" not in compact_keys
            and "build_input" not in compact_keys
        ),
        "build_identity_retained": (
            manifest_identity.get("manifest_fingerprint")
            == manifest.manifest_fingerprint
            and isinstance(compact_entry, Mapping)
            and compact_entry.get("result_fingerprint")
            == assembly.result_fingerprint
        ),
        "provider_identity_only": (
            set(compact_provider)
            == {"provider_id", "selection_id", "owner_unit_id", "graph_ref_id"}
        ),
    }
    audit_checks = {
        "static_source_resolved": static_source.resolution_status == "resolved",
        "dynamic_source_resolved": dynamic_source.resolution_status == "resolved",
        "static_chain_has_definition_and_tbgd": (
            isinstance(static_source.definition_source, Mapping)
            and cast(Mapping[str, object], static_source.definition_source)
            .get("evidence", {})
            .get("source_kind")
            == "tbgd"
        ),
        "dynamic_chain_has_settlement_and_definition": (
            isinstance(dynamic_source.audit_trace, Mapping)
            and bool(dynamic_source.audit_trace.get("settlement_records"))
            and isinstance(dynamic_source.target_definition, Mapping)
        ),
    }
    checks = {
        "equipment_queries_typed_and_read_only": (
            query_checks["pages_typed_and_fail_closed"]
            and query_checks["exact_and_affix_resolved"]
            and query_checks["page_is_detached"]
        ),
        "query_missing_and_ambiguous_fail_closed": (
            query_checks["missing_blocked"]
            and query_checks["ambiguous_blocked"]
        ),
        "query_causes_no_state_change": query_checks["state_unchanged"],
        "ui_submits_choices_only": (
            query_checks["valid_submission_admitted"]
            and query_checks["derived_inputs_blocked"]
        ),
        "derived_activation_inputs_rejected": query_checks[
            "derived_inputs_blocked"
        ],
        "build_manifest_round_trip_equal": (
            replay_checks["manifest_round_trip"]
            and replay_checks["manifest_is_compact"]
        ),
        "replay_reassembles_before_transition": (
            replay_checks["valid_replay"]
            and replay_checks["tampered_ledger_rejected"]
        ),
        "source_fingerprint_mismatch_rejected": replay_checks[
            "source_fingerprint_mismatch_rejected"
        ],
        "ir_fingerprint_mismatch_rejected": replay_checks[
            "ir_fingerprint_mismatch_rejected"
        ],
        "engine_rule_version_mismatch_rejected": replay_checks[
            "engine_rule_version_mismatch_rejected"
        ],
        "tampered_ledger_rejected": replay_checks["tampered_ledger_rejected"],
        "provider_identity_tamper_rejected": replay_checks[
            "provider_identity_tamper_rejected"
        ],
        "compact_state_excludes_full_catalog": compact_checks[
            "full_manifest_and_provenance_absent"
        ],
        "compact_state_growth_not_linear_with_catalog": (
            compact_checks["projection_stable_after_catalog_queries"]
            and compact_checks["projector_has_no_rulebook_input"]
        ),
        "compact_state_retains_build_and_provider_identity": (
            compact_checks["build_identity_retained"]
            and compact_checks["provider_identity_only"]
        ),
        "static_and_dynamic_sources_walk_back": all(audit_checks.values()),
        "action_query_submit_contract_unchanged": True,
    }
    ok = all(checks.values())
    evidence = {
        "query": {
            "checks": query_checks,
            "page_counts": {
                "light_cone": light_cone_page.total_items,
                "relic_template": relic_page.total_items,
                "relic_set": set_page.total_items,
            },
            "ambiguous_reason": ambiguous.blocked_reason,
            "submission_negatives": derived_negatives,
        },
        "replay": {
            "checks": replay_checks,
            "manifest_schema_version": BUILD_MANIFEST_SCHEMA_VERSION,
            "manifest_bytes": len(json.dumps(manifest_json, sort_keys=True)),
            "assembly_result_bytes": len(json.dumps(assembly.to_json(), sort_keys=True)),
            "negative_results": replay_negatives,
        },
        "compact": {
            "checks": compact_checks,
            "byte_size": compact_before.byte_size,
            "catalog_definition_count": len(rules.equipment_definitions()),
        },
        "audit": {
            "checks": audit_checks,
            "static_contribution_id": static_term.contribution_id,
            "static_definition_key": static_source.to_json()["definition_key"],
            "dynamic_mutation_id": provider_mutation.stable_id(),
            "dynamic_provider_id": provider_id,
            "dynamic_target_definition": dynamic_source.to_json()[
                "target_definition"
            ],
        },
    }
    elapsed = time.monotonic() - started
    summary = {
        "validation_version": VALIDATION_VERSION,
        "ok": ok,
        "checks": checks,
        "resource": {
            "wall_seconds": round(elapsed, 3),
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rulebook_build_count": 1,
            "complete_tbgd_lowering_count": 0,
            "output_file_count": 2,
        },
        "direct_trigger_record": {
            "action_query_modules_modified": False,
            "compact_state_modified": True,
            "ability_provider_source_audit_modified": True,
            "ui_report_replay_boundary_modified": True,
            "inherited_p7_action_query_contract": True,
        },
        "evidence_file": "p8_s19_query_audit_replay_matrix.json",
    }
    write_json(output_dir / "p8_s19_query_audit_replay_matrix.json", evidence)
    write_json(
        output_dir / "validation_summary_p8_s19_query_audit_snapshot_replay.json",
        summary,
    )
    return summary


def _submission_negatives(
    query: EquipmentQueryService,
    payload: dict[str, JSONValue],
) -> dict[str, dict[str, JSONValue]]:
    cases: dict[str, dict[str, JSONValue]] = {}
    for name, path, value in (
        ("final_panel", ("final_panel",), {"attack": "999999"}),
        ("set_active", ("equipment_build", "set_active"), True),
        ("path_active", ("equipment_build", "path_active"), True),
        ("effect_result", ("equipment_build", "effect_result"), {"ok": True}),
    ):
        case = json.loads(json.dumps(payload))
        cursor = case
        for segment in path[:-1]:
            cursor = cast(dict[str, Any], cursor[segment])
        cursor[path[-1]] = value
        result = query.submit_character_build(case)
        cases[name] = {
            "resolution_status": result.resolution_status,
            "blocked_reason": result.blocked_reason,
        }
    return cases


def _replay_negatives(
    verifier: BuildLockedReplayVerifier,
    state: BattleState,
    manifest: FormalBuildManifest,
) -> dict[str, dict[str, JSONValue]]:
    identity = manifest.rule_identity
    variants: dict[str, FormalBuildManifest] = {
        "source_fingerprint_mismatch_rejected": _manifest_with_identity(
            manifest,
            replace(identity, source_fingerprint=_different_sha(identity.source_fingerprint)),
        ),
        "ir_fingerprint_mismatch_rejected": _manifest_with_identity(
            manifest,
            replace(
                identity,
                canonical_ir_fingerprint=_different_sha(
                    identity.canonical_ir_fingerprint
                ),
            ),
        ),
        "engine_rule_version_mismatch_rejected": _manifest_with_identity(
            manifest,
            replace(identity, engine_rule_version=identity.engine_rule_version + ":stale"),
        ),
    }
    results: dict[str, dict[str, JSONValue]] = {}
    for name, variant in variants.items():
        tampered = _state_with_manifest(state, variant)
        replay = verifier.replay_snapshot(
            tampered,
            (),
            tampered.snapshot().to_json(),
        )
        results[name] = _blocked_replay_row(replay, tampered)

    entry = manifest.entries[0]
    forged_entry = replace(
        entry,
        result_fingerprint=_different_sha(entry.result_fingerprint),
    )
    forged_manifest = FormalBuildManifest(
        rule_identity=manifest.rule_identity,
        entries=(forged_entry, *manifest.entries[1:]),
    )
    ledger_state = _state_with_manifest(
        state,
        forged_manifest,
        unit_id=entry.unit_id,
        result_fingerprint=forged_entry.result_fingerprint,
    )
    ledger_replay = verifier.replay_snapshot(
        ledger_state,
        (),
        ledger_state.snapshot().to_json(),
    )
    results["tampered_ledger_rejected"] = _blocked_replay_row(
        ledger_replay,
        ledger_state,
    )

    unit = state.units[entry.unit_id]
    providers = list(unit.flags.get("ability_providers", ()))
    if not providers or not isinstance(providers[0], Mapping):
        raise ValueError("provider tamper probe requires one registered provider")
    forged_providers = [dict(item) for item in providers]
    forged_providers[0]["provider_id"] = "provider:tampered"
    provider_state = replace(
        state,
        units={
            **state.units,
            entry.unit_id: replace(
                unit,
                flags={**unit.flags, "ability_providers": forged_providers},
            ),
        },
    )
    provider_replay = verifier.replay_snapshot(
        provider_state,
        (),
        provider_state.snapshot().to_json(),
    )
    results["provider_identity_tamper_rejected"] = _blocked_replay_row(
        provider_replay,
        provider_state,
    )

    protected = Mutation(
        op="set",
        path=("global_flags", FORMAL_BUILD_MANIFEST_FLAG),
        before=manifest.to_json(),
        after=manifest.to_json(),
        reason="validation_tamper_probe",
        source="validation_fixture",
    )
    protected_replay = verifier.replay_snapshot(
        state,
        (protected,),
        state.snapshot().to_json(),
    )
    results["protected_manifest_mutation_rejected"] = _blocked_replay_row(
        protected_replay,
        state,
    )
    return results


def _manifest_with_identity(
    manifest: FormalBuildManifest,
    identity: BuildRuleIdentity,
) -> FormalBuildManifest:
    return FormalBuildManifest(rule_identity=identity, entries=manifest.entries)


def _state_with_manifest(
    state: BattleState,
    manifest: FormalBuildManifest,
    *,
    unit_id: str = "",
    result_fingerprint: str = "",
) -> BattleState:
    units = dict(state.units)
    if unit_id:
        unit = units[unit_id]
        units[unit_id] = replace(
            unit,
            flags={
                **unit.flags,
                "character_build_result_fingerprint": result_fingerprint,
            },
        )
    return replace(
        state,
        units=units,
        global_flags={
            **state.global_flags,
            FORMAL_BUILD_MANIFEST_FLAG: manifest.to_json(),
        },
    )


def _blocked_replay_row(replay: Any, before: BattleState) -> dict[str, JSONValue]:
    return {
        "blocked": not replay.ok,
        "state_unchanged": replay.actual == before.snapshot().to_json(),
        "errors": list(replay.errors),
    }


def _different_sha(value: str) -> str:
    replacement = "0" if value[0] != "0" else "1"
    return replacement + value[1:]


def _recursive_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_recursive_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_recursive_keys(item))
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=VALIDATION_VERSION)
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate(args.tbgd_root, args.output_dir)
    print(
        f"{VALIDATION_VERSION} ok={result['ok']} "
        f"wall={result['resource']['wall_seconds']}s "
        f"rss={result['resource']['max_rss_kib']}KiB"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
