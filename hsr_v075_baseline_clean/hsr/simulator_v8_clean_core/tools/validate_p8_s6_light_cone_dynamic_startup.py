from __future__ import annotations

import argparse
import inspect
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..build_types import immutable_ir_source
from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterBuildInput, CharacterInitialConditionInput
from ..builds.equipment_assembler import assemble_equipment_build
from ..core.model import BattleState, UnitState
from ..core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from ..equipment.models import (
    DynamicMechanismSelection,
    EquipmentBuildInput,
    EquipmentDynamicParameterBinding,
    LightConeDefinitionIR,
    LightConeInstanceInput,
)
from ..rules.ir import CanonicalIR, RuleEntity
from ..rules.rulebook import RuleBook
from ..rules.value_binding import ExactEquipmentValueBindingRequest, ValueResolver
from ..systems import ability_provider as provider_module
from ..systems.ability_provider import register_dynamic_ability_providers
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import (
    BattleSetupSpec,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..tbgd.character_cards import build_character_card_ir
from ..tbgd.light_cone_cards import build_light_cone_catalog
from ..tbgd.lowering import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    TBGDLowering,
    _attach_light_cone_equipment_mechanism_refs,
    build_character_action_definition_ir,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "p8_s6_light_cone_dynamic_startup"
SUMMARY_SCHEMA_VERSION = "p8_s6_light_cone_dynamic_startup_summary_v2"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _focused_bundle(tbgd_root)
    graph_matrix = _graph_linkage_matrix(bundle)
    raw_parameter_oracle = _raw_parameter_read_oracle(tbgd_root, bundle)
    parameter_matrix = _parameter_binding_matrix(bundle)
    sample = _sample_context(bundle)
    startup_matrix = _startup_matrix(bundle, sample)
    negative_matrix = _negative_matrix(bundle, sample)
    family_matrix = _family_gap_matrix(bundle)
    source_walkback = _source_walkback(bundle, startup_matrix)
    runtime_boundary = _runtime_boundary()

    predicates = {
        "equipment_ability_graphs_are_canonical": graph_matrix["ok"],
        "graph_identity_not_derived_from_name": graph_matrix["checks"][
            "graph_identity_not_derived_from_ability_name"
        ],
        "superimposition_parameters_bound_exactly": parameter_matrix["ok"],
        "raw_parameter_reads_match_canonical_ir": raw_parameter_oracle["ok"],
        "rank_changes_values_not_graph_identity": startup_matrix["checks"][
            "rank_pair_changes_values_not_graph_identity"
        ],
        "startup_registers_once": startup_matrix["checks"][
            "startup_registers_once"
        ],
        "startup_snapshot_preserves_provider": startup_matrix["checks"][
            "startup_snapshot_preserves_provider"
        ],
        "formal_scenario_startup_chain_verified": all(
            startup_matrix["checks"][key]
            for key in (
                "formal_scenario_registers_after_unit_creation",
                "formal_snapshot_restore_is_idempotent",
                "formal_scenario_rebuild_has_one_provider",
            )
        ),
        "path_mismatch_registers_zero_dynamic_mechanisms": startup_matrix[
            "checks"
        ]["path_mismatch_registers_zero_dynamic"],
        "selected_partial_graph_blocks_battle": startup_matrix["checks"][
            "selected_partial_graph_blocks_battle"
        ],
        "blocked_startup_state_unchanged": startup_matrix["checks"][
            "blocked_startup_state_unchanged"
        ],
        "multi_wearer_provider_identity_isolated": startup_matrix["checks"][
            "multi_wearer_provider_identity_isolated"
        ],
        "runtime_reads_raw_equipment": runtime_boundary["runtime_reads_raw_equipment"],
        "equipment_specific_event_loop_created": runtime_boundary[
            "equipment_specific_event_loop_created"
        ],
        "all_dynamic_sources_walk_back": source_walkback["ok"],
        "negative_matrix_complete": negative_matrix["ok"],
        "current_graph_admission_states_preserved": family_matrix["ok"],
    }
    predicates["ok"] = all(
        value is True
        for key, value in predicates.items()
        if key
        not in {
            "runtime_reads_raw_equipment",
            "equipment_specific_event_loop_created",
        }
    ) and predicates["runtime_reads_raw_equipment"] is False and predicates[
        "equipment_specific_event_loop_created"
    ] is False

    artifacts = {
        "graph_linkage_matrix_p8_s6.json": graph_matrix,
        "raw_parameter_read_oracle_p8_s6.json": raw_parameter_oracle,
        "parameter_binding_matrix_p8_s6.json": parameter_matrix,
        "startup_matrix_p8_s6.json": startup_matrix,
        "negative_matrix_p8_s6.json": negative_matrix,
        "family_gap_matrix_p8_s6.json": family_matrix,
        "source_walkback_p8_s6.json": source_walkback,
        "runtime_boundary_p8_s6.json": runtime_boundary,
    }
    for filename, payload in artifacts.items():
        write_json(output_dir / filename, payload)
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": predicates["ok"],
        "ready_for_review": predicates["ok"],
        "checklist_modified": False,
        "git_commit_created": False,
        "predicates": predicates,
        "counts": {
            "published_light_cone_count": len(bundle["definitions"]),
            "equipment_graph_count": len(bundle["graphs"]),
            "equipment_parameter_read_count": len(bundle["parameter_reads"]),
            "raw_parameter_read_count": raw_parameter_oracle["expected_count"],
            "equipment_mechanism_ref_count": len(bundle["mechanism_refs"]),
            "production_executable_graph_count": sum(
                graph.coverage_status == "executable"
                for graph in bundle["graphs"]
            ),
            "production_partial_graph_count": sum(
                graph.coverage_status != "executable"
                for graph in bundle["graphs"]
            ),
            "exact_rank_binding_comparison_count": parameter_matrix[
                "comparison_count"
            ],
            "negative_case_count": len(negative_matrix["rows"]),
        },
        "resource_scope": {
            "focused_rulebook_build_count": negative_matrix[
                "focused_rulebook_build_count"
            ],
            "full_canonical_ir_serialized": False,
            "transition_dump_written": False,
            "artifacts": sorted(artifacts),
        },
        "deferred": {
            "stage": "P8-S8",
            "classification": "implementation_missing",
            "reason": "remaining equipment ability graphs keep explicit blocked reasons after the P8-S7 closure",
        },
    }
    write_json(
        output_dir / "validation_summary_p8_s6_light_cone_dynamic_startup.json",
        summary,
    )
    return summary


def _focused_bundle(tbgd_root: Path) -> dict[str, Any]:
    catalog = build_light_cone_catalog(tbgd_root)
    if not catalog.catalog_complete:
        raise ValueError("P8-S6 requires the complete P8-S3 light-cone catalog")
    lowering = TBGDLowering(tbgd_root)
    lowered = lowering._lower_equipment_ability_graphs(catalog.canonical_definitions)
    graphs, phases, tasks, effects, conditions, formulas, targets, parameter_reads = lowered
    definitions, mechanism_refs = _attach_light_cone_equipment_mechanism_refs(
        catalog.canonical_definitions,
        graphs,
        parameter_reads,
    )
    characters = build_character_card_ir(
        tbgd_root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
    )
    action_definitions = build_character_action_definition_ir(tbgd_root)
    entities_by_id = {
        card.entity_ref: RuleEntity(
            entity_id=card.entity_ref,
            entity_type="avatar",
            fields={"profile_id": card.profile_id},
            source=card.source,
            coverage_status="audit_only",
        )
        for card in characters.character_data_cards
    }
    for action in action_definitions:
        entities_by_id.setdefault(
            action.action_id,
            RuleEntity(
                entity_id=action.action_id,
                entity_type=action.action_id.split(":", 1)[0],
                fields={"source_kind": "typed_action_definition"},
                source=action.source,
                coverage_status="audit_only",
            ),
        )
    ir = CanonicalIR(
        version=BASELINE_VERSION,
        entities=tuple(entities_by_id[key] for key in sorted(entities_by_id)),
        avatar_profiles=characters.avatar_profiles,
        character_data_cards=characters.character_data_cards,
        character_equipment_eligibilities=characters.character_equipment_eligibilities,
        character_mechanism_slots=tuple(characters.character_mechanism_slots),
        character_trace_nodes=tuple(characters.character_trace_nodes),
        character_eidolon_slots=tuple(characters.character_eidolon_slots),
        action_definitions=tuple(action_definitions),
        light_cone_definitions=definitions,
        equipment_ability_parameter_reads=tuple(parameter_reads),
        equipment_mechanism_refs=mechanism_refs,
        standalone_ability_graphs=tuple(graphs),
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        effects=tuple(effects),
        conditions=tuple(conditions),
        formulas=tuple(formulas),
        target_expressions=tuple(targets),
        metadata={"validation_scope": "p8_s6_focused_equipment_ability"},
    )
    return {
        "catalog": catalog,
        "characters": characters,
        "definitions": definitions,
        "graphs": tuple(graphs),
        "phases": tuple(phases),
        "tasks": tuple(tasks),
        "effects": tuple(effects),
        "conditions": tuple(conditions),
        "formulas": tuple(formulas),
        "targets": tuple(targets),
        "parameter_reads": tuple(parameter_reads),
        "mechanism_refs": mechanism_refs,
        "ir": ir,
        "rules": RuleBook(ir),
        "tbgd_root": tbgd_root,
    }


def _graph_linkage_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    graphs = bundle["graphs"]
    rows = []
    for definition in bundle["definitions"]:
        source = definition.ability_source
        matching = tuple(graph for graph in graphs if source and graph.source == source.source)
        mechanism_resolutions = tuple(
            rules.equipment_mechanism_ref(key.definition_identity)
            for key in definition.mechanism_ref_ids
        )
        mechanism = (
            mechanism_resolutions[0].value
            if len(mechanism_resolutions) == 1
            and mechanism_resolutions[0].resolution_status == "resolved"
            else None
        )
        parameter_reads = (
            tuple(
                rules.equipment_ability_parameter_read(binding_id)
                for binding_id in mechanism.parameter_binding_ids
            )
            if mechanism is not None
            else ()
        )
        graph = matching[0] if len(matching) == 1 else None
        row = {
            "definition_identity": definition.definition_key.definition_identity,
            "ability_name": source.ability_name if source else "",
            "ability_record_index": source.record_index if source else None,
            "graph_ref_id": graph.standalone_ability_graph_id if graph else "",
            "graph_count": len(matching),
            "mechanism_ref_count": len(mechanism_resolutions),
            "parameter_read_count": len(parameter_reads),
            "graph_status": graph.coverage_status if graph else "missing",
            "graph_blocked_reason": graph.blocked_reason if graph else "graph_missing",
            "source_matches": bool(graph and source and graph.source == source.source),
            "graph_identity_uses_source_row": bool(
                graph
                and source
                and graph.standalone_ability_graph_id.endswith(
                    f"ability_list_row:{source.record_index}"
                )
                and source.ability_name not in graph.standalone_ability_graph_id
            ),
            "parameter_reads_resolved": all(item is not None for item in parameter_reads),
        }
        row["ok"] = all(
            (
                row["graph_count"] == 1,
                row["mechanism_ref_count"] == 1,
                row["source_matches"],
                row["graph_identity_uses_source_row"],
                row["parameter_reads_resolved"],
            )
        )
        rows.append(row)
    checks = {
        "every_definition_has_one_canonical_graph": all(row["ok"] for row in rows),
        "graph_identities_unique": len({row["graph_ref_id"] for row in rows})
        == len(rows),
        "graph_identity_not_derived_from_ability_name": all(
            row["graph_identity_uses_source_row"] for row in rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {"schema_version": "p8_s6_graph_linkage_matrix_v1", "ok": checks["ok"], "checks": checks, "rows": rows}


def _raw_parameter_read_oracle(
    tbgd_root: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    documents: dict[str, dict[str, Any]] = {}
    expected_rows: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_records: set[tuple[str, int]] = set()
    for definition in bundle["definitions"]:
        ability_source = definition.ability_source
        if ability_source is None:
            problems.append(
                f"{definition.definition_key.stable_id}:ability_source_missing"
            )
            continue
        record_key = (
            ability_source.source.source_path,
            ability_source.record_index,
        )
        if record_key in seen_records:
            continue
        seen_records.add(record_key)
        relative, record_index = record_key
        document = documents.get(relative)
        if document is None:
            parsed = json.loads((tbgd_root / relative).read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                problems.append(f"{relative}:document_not_object")
                continue
            document = parsed
            documents[relative] = document
        ability_list = document.get("AbilityList")
        if (
            not isinstance(ability_list, list)
            or record_index < 0
            or record_index >= len(ability_list)
            or not isinstance(ability_list[record_index], dict)
        ):
            problems.append(f"{relative}:ability_list_row:{record_index}:missing")
            continue
        ability = ability_list[record_index]
        dynamic_values = ability.get("DynamicValues")
        if dynamic_values is None:
            continue
        if not isinstance(dynamic_values, dict):
            problems.append(
                f"{relative}:ability_list_row:{record_index}:dynamic_values_invalid"
            )
            continue
        for value_type, values in sorted(
            dynamic_values.items(), key=lambda item: str(item[0])
        ):
            if not isinstance(value_type, str) or not isinstance(values, dict):
                problems.append(
                    f"{relative}:ability_list_row:{record_index}:dynamic_bucket_invalid"
                )
                continue
            for dynamic_hash, value_definition in sorted(
                values.items(), key=lambda item: str(item[0])
            ):
                if not isinstance(value_definition, dict):
                    continue
                read_info = value_definition.get("ReadInfo")
                if not isinstance(read_info, dict) or read_info.get("Type") != "SkillEquip":
                    continue
                parameter_index = read_info.get("Index")
                if (
                    not isinstance(parameter_index, int)
                    or isinstance(parameter_index, bool)
                    or parameter_index < 0
                ):
                    problems.append(
                        f"{relative}:ability_list_row:{record_index}:"
                        f"dynamic_hash:{dynamic_hash}:index_invalid"
                    )
                    continue
                expected_rows.append(
                    {
                        "parameter_read_id": (
                            f"equipment_parameter_read:{relative}:"
                            f"json_path:$.AbilityList[{record_index}]:"
                            f"value_type:{value_type}:dynamic_hash:{dynamic_hash}:"
                            f"parameter_index:{parameter_index}"
                        ),
                        "source_path": relative,
                        "json_path": (
                            f"$.AbilityList[{record_index}].DynamicValues."
                            f"{value_type}.{dynamic_hash}.ReadInfo"
                        ),
                        "value_type": value_type,
                        "dynamic_hash": str(dynamic_hash),
                        "parameter_index": parameter_index,
                        "source_fingerprint": ability_source.source.evidence.get(
                            "source_fingerprint"
                        ),
                    }
                )

    actual_rows = [
        {
            "parameter_read_id": item.parameter_read_id,
            "source_path": item.source.source_path,
            "json_path": item.source.evidence.get("json_path"),
            "value_type": item.value_type,
            "dynamic_hash": item.dynamic_hash,
            "parameter_index": item.parameter_index,
            "source_fingerprint": item.source.evidence.get("source_fingerprint"),
        }
        for item in bundle["parameter_reads"]
    ]
    key = lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True)
    expected_keys = tuple(sorted(key(row) for row in expected_rows))
    actual_keys = tuple(sorted(key(row) for row in actual_rows))
    checks = {
        "raw_skill_equip_reads_nonempty": bool(expected_rows),
        "raw_skill_equip_reads_have_valid_indices": not problems,
        "canonical_reads_match_raw_rows_exactly": actual_keys == expected_keys,
        "canonical_read_identities_unique": len(actual_keys) == len(set(actual_keys)),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s6_raw_parameter_read_oracle_v1",
        "ok": checks["ok"],
        "checks": checks,
        "expected_count": len(expected_rows),
        "actual_count": len(actual_rows),
        "problems": problems,
        "rows": expected_rows,
    }


def _parameter_binding_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    resolver = ValueResolver(rules)
    rows = []
    comparison_count = 0
    for definition in bundle["definitions"]:
        mechanism_resolution = rules.equipment_mechanism_ref(
            definition.mechanism_ref_ids[0].definition_identity
        )
        mechanism = mechanism_resolution.value
        if mechanism is None:
            rows.append({"definition_identity": definition.raw_equipment_id, "ok": False, "reason": "mechanism_unresolved"})
            continue
        reads = tuple(
            rules.equipment_ability_parameter_read(binding_id)
            for binding_id in mechanism.parameter_binding_ids
        )
        for rank in definition.superimposition_levels:
            resolved_values = []
            ok = True
            for parameter_read in reads:
                if parameter_read is None or parameter_read.parameter_index >= len(rank.parameters):
                    ok = False
                    continue
                parameter = rank.parameters[parameter_read.parameter_index]
                result = resolver.resolve_equipment_rank_parameter(
                    ExactEquipmentValueBindingRequest(
                        binding_kind="equipment_rank_parameter",
                        binding_id=(
                            f"validation:{definition.raw_equipment_id}:"
                            f"rank:{rank.level}:{parameter_read.parameter_read_id}"
                        ),
                        target_definition_identity=(
                            definition.definition_key.definition_identity
                        ),
                        graph_ref_id=mechanism.graph_ref_id,
                        parameter_read_id=parameter_read.parameter_read_id,
                        value_type=parameter_read.value_type,
                        dynamic_hash=parameter_read.dynamic_hash,
                        parameter_index=parameter_read.parameter_index,
                        skill_id=rank.skill_id,
                        superimposition_level=rank.level,
                        exact_value=parameter.exact_value,
                        value_source=parameter.source,
                    )
                )
                comparison_count += 1
                ok = ok and result.ok and result.exact_value == parameter.exact_value
                resolved_values.append(
                    {
                        "parameter_read_id": parameter_read.parameter_read_id,
                        "parameter_index": parameter_read.parameter_index,
                        "dynamic_hash": parameter_read.dynamic_hash,
                        "exact_value": result.exact_value,
                        "value_source_raw_id": result.value_source.raw_id,
                    }
                )
            rows.append(
                {
                    "definition_identity": definition.raw_equipment_id,
                    "rank": rank.level,
                    "graph_ref_id": mechanism.graph_ref_id,
                    "bindings": resolved_values,
                    "ok": ok,
                }
            )
    checks = {
        "all_parameter_reads_resolve_exactly": all(row["ok"] for row in rows),
        "exact_values_are_strings": all(
            isinstance(binding["exact_value"], str)
            for row in rows
            for binding in row.get("bindings", ())
        ),
        "comparison_count_nonzero": comparison_count > 0,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s6_parameter_binding_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "comparison_count": comparison_count,
        "rows": rows,
    }


def _sample_context(bundle: dict[str, Any]) -> dict[str, Any]:
    definitions: tuple[LightConeDefinitionIR, ...] = bundle["definitions"]
    eligibilities = bundle["characters"].character_equipment_eligibilities
    cards = {card.card_id: card for card in bundle["characters"].character_data_cards}
    candidates = []
    rules: RuleBook = bundle["rules"]
    empty_admitted_cards = {
        eligibility.character_card_id
        for eligibility in eligibilities
        if assemble_character_build(
            rules,
            _character_build(
                eligibility.character_card_id,
                "sample-empty-admission",
            ),
        ).battle_admission_status
        == "admitted"
    }
    for eligibility in eligibilities:
        card = cards.get(eligibility.character_card_id)
        if card is None or card.card_id not in empty_admitted_cards:
            continue
        for definition in definitions:
            if eligibility.character_path_type != definition.path_type:
                continue
            mechanism = rules.equipment_mechanism_ref(
                definition.mechanism_ref_ids[0].definition_identity
            ).value
            if mechanism is None or not mechanism.parameter_binding_ids:
                continue
            read = rules.equipment_ability_parameter_read(mechanism.parameter_binding_ids[0])
            if read is None or len(definition.superimposition_levels) < 2:
                continue
            values = tuple(
                rank.parameters[read.parameter_index].exact_value
                for rank in definition.superimposition_levels
            )
            if len(set(values)) > 1:
                candidates.append((eligibility, card, definition))
    if not candidates:
        raise ValueError("no structural rank-pair sample with a changing bound value")
    eligibility, card, definition = sorted(
        candidates,
        key=lambda item: (
            item[2].ability_source.source.source_path,
            item[2].ability_source.record_index,
            item[1].card_id,
        ),
    )[0]
    cross_definition = next(
        item for item in definitions if item.path_type != eligibility.character_path_type
    )
    return {
        "eligibility": eligibility,
        "card": card,
        "definition": definition,
        "cross_definition": cross_definition,
    }


def _assembly(
    rules: RuleBook,
    card_id: str,
    definition: LightConeDefinitionIR,
    *,
    instance_id: str,
    rank: int,
) -> Any:
    build = EquipmentBuildInput(
        build_id=f"validation:p8_s6:build:{instance_id}:rank:{rank}",
        character_card_id=card_id,
        light_cone=LightConeInstanceInput(
            instance_id=instance_id,
            definition_key=definition.definition_key,
            level=1,
            promotion=0,
            superimposition=rank,
        ),
    )
    return build, assemble_equipment_build(rules, build)


def _character_build(
    card_id: str,
    suffix: str,
    equipment_build: EquipmentBuildInput | None = None,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:p8_s6:character:{suffix}",
        character_card_id=card_id,
        level=1,
        promotion=0,
        eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=equipment_build
        or EquipmentBuildInput(
            build_id=f"validation:p8_s6:empty-equipment:{suffix}",
            character_card_id=card_id,
        ),
    )


def _current_formal_startup_context(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    graph_by_id = {
        graph.standalone_ability_graph_id: graph for graph in bundle["graphs"]
    }
    cards = {
        card.card_id: card
        for card in bundle["characters"].character_data_cards
    }
    eligibilities_by_path: dict[str, list[Any]] = {}
    for eligibility in bundle["characters"].character_equipment_eligibilities:
        eligibilities_by_path.setdefault(
            eligibility.character_path_type, []
        ).append(eligibility)
    candidates: list[tuple[LightConeDefinitionIR, Any]] = []
    for definition in bundle["definitions"]:
        if not definition.mechanism_ref_ids:
            continue
        mechanism = rules.equipment_mechanism_ref(
            definition.mechanism_ref_ids[0].definition_identity
        ).value
        graph = (
            graph_by_id.get(mechanism.graph_ref_id)
            if mechanism is not None
            else None
        )
        if graph is None or graph.coverage_status != "executable":
            continue
        for eligibility in eligibilities_by_path.get(
            definition.path_type, ()
        ):
            card = cards.get(eligibility.character_card_id)
            if card is not None:
                candidates.append((definition, card))
    errors: list[str] = []
    for definition, card in sorted(
        candidates,
        key=lambda item: (
            item[0].ability_source.source.source_path,
            item[0].ability_source.record_index,
            item[1].card_id,
        ),
    ):
        equipment_build, equipment_result = _assembly(
            rules,
            card.card_id,
            definition,
            instance_id="validation:p8_s6:formal-current",
            rank=1,
        )
        character_build = _character_build(
            card.card_id,
            "formal-current",
            equipment_build,
        )
        character_result = assemble_character_build(rules, character_build)
        if (
            equipment_result.battle_admission_status != "admitted"
            or character_result.battle_admission_status != "admitted"
        ):
            continue
        scenario = ScenarioSpec(
            scenario_id="validation:p8_s6:formal-provider-startup",
            version=BASELINE_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:formal-provider",
                    side="ally",
                    entity_ref=card.entity_ref,
                    build_mode="assembled_character_build",
                    level=character_build.level,
                    eidolon_level=character_build.eidolon_level,
                    panel=None,
                    character_build=character_build,
                    initial_condition=CharacterInitialConditionInput(
                        hp_mode="full",
                        initial_energy="0",
                    ),
                ),
            ),
            route=(),
            battle_setup=BattleSetupSpec(
                timeline=TimelineSetupSpec(mode="runtime_initialize")
            ),
        )
        try:
            built = ScenarioStateBuilder(rules).build(scenario)
            rebuilt = ScenarioStateBuilder(rules).build(scenario)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        return {
            "card": card,
            "definition": definition,
            "equipment_result": equipment_result,
            "character_result": character_result,
            "scenario": scenario,
            "built": built,
            "rebuilt": rebuilt,
        }
    raise ValueError(
        "no currently executable formal equipment startup sample: "
        f"{errors[:5]}"
    )


def _startup_matrix(bundle: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    card = sample["card"]
    definition = sample["definition"]
    _, partial = _assembly(rules, card.card_id, definition, instance_id="validation:p8_s6:partial", rank=1)
    _, mismatch = _assembly(rules, card.card_id, sample["cross_definition"], instance_id="validation:p8_s6:mismatch", rank=1)
    partial_state = BattleState(
        units={
            "ally:partial": UnitState(
                unit_id="ally:partial",
                side="ally",
                template_id=card.entity_ref,
                flags={"character_data_card_id": card.card_id},
            )
        }
    )
    partial_registration = register_dynamic_ability_providers(
        partial_state,
        rules,
        (("ally:partial", partial.dynamic_mechanisms[0]),),
    )

    graph_id = partial.dynamic_mechanisms[0].graph_ref_id
    admitted_ir = replace(
        bundle["ir"],
        standalone_ability_graphs=tuple(
            replace(graph, coverage_status="executable", blocked_reason="")
            if graph.standalone_ability_graph_id == graph_id
            else graph
            for graph in bundle["graphs"]
        ),
    )
    admitted_rules = RuleBook(admitted_ir)
    _, rank_one = _assembly(admitted_rules, card.card_id, definition, instance_id="validation:p8_s6:owner-a", rank=1)
    _, rank_two = _assembly(admitted_rules, card.card_id, definition, instance_id="validation:p8_s6:owner-b", rank=2)
    initial = BattleState(
        units={
            unit_id: UnitState(
                unit_id=unit_id,
                side="ally",
                template_id=card.entity_ref,
                flags={"character_data_card_id": card.card_id},
            )
            for unit_id in ("ally:a", "ally:b")
        }
    )
    first = register_dynamic_ability_providers(
        initial,
        admitted_rules,
        (("ally:a", rank_one.dynamic_mechanisms[0]),),
    )
    second = register_dynamic_ability_providers(
        first.after_state,
        admitted_rules,
        (("ally:a", rank_one.dynamic_mechanisms[0]),),
    )
    multi = register_dynamic_ability_providers(
        initial,
        admitted_rules,
        (
            ("ally:a", rank_one.dynamic_mechanisms[0]),
            ("ally:b", rank_two.dynamic_mechanisms[0]),
        ),
    )
    provider_ids = tuple(
        provider["provider_id"]
        for unit in multi.after_state.units.values()
        for provider in unit.flags.get("ability_providers", ())
    ) if multi.ok else ()
    rank_one_values = tuple(
        binding.exact_value for binding in rank_one.dynamic_mechanisms[0].parameter_bindings
    )
    rank_two_values = tuple(
        binding.exact_value for binding in rank_two.dynamic_mechanisms[0].parameter_bindings
    )
    snapshot_units = first.after_state.snapshot().to_json().get("units", {})
    snapshot_unit = (
        snapshot_units.get("ally:a", {})
        if isinstance(snapshot_units, dict)
        else {}
    )
    snapshot_flags = (
        snapshot_unit.get("flags", {})
        if isinstance(snapshot_unit, dict)
        else {}
    )
    snapshot_providers = (
        snapshot_flags.get("ability_providers", [])
        if isinstance(snapshot_flags, dict)
        else []
    )
    mismatch_registration = register_dynamic_ability_providers(
        initial,
        admitted_rules,
        (),
    )
    from .validate_p8_s7_light_cone_status_condition_listener_closure import (
        _with_s7_status_closure,
    )

    formal_bundle = _with_s7_status_closure(bundle, bundle["tbgd_root"])
    formal_rules: RuleBook = formal_bundle["rules"]
    formal_context = _current_formal_startup_context(formal_bundle)
    formal_character_result = formal_context["character_result"]
    formal_built = formal_context["built"]
    formal_rebuilt = formal_context["rebuilt"]
    formal_selection = formal_context["equipment_result"].dynamic_mechanisms[0]
    formal_unit = formal_built.state.units["ally:formal-provider"]
    formal_providers = formal_unit.flags.get("ability_providers", ())
    rebuilt_providers = formal_rebuilt.state.units[
        "ally:formal-provider"
    ].flags.get("ability_providers", ())
    formal_provider_mutations = tuple(
        mutation
        for mutation in formal_built.setup_mutations
        if mutation.source == "ability_provider_registry"
    )
    formal_provider_records = tuple(
        record
        for record in formal_built.setup_records
        if record.get("record_type") == "ability_provider_registration"
    )
    restored_unit = unit_state_from_payload(unit_state_to_payload(formal_unit))
    restored_state = replace(
        formal_built.state,
        units={
            **formal_built.state.units,
            restored_unit.unit_id: restored_unit,
        },
    )
    restored_registration = register_dynamic_ability_providers(
        restored_state,
        formal_rules,
        (("ally:formal-provider", formal_selection),),
    )
    checks = {
        "selected_partial_graph_blocks_battle": partial.assembly_status == "assembled"
        and partial.battle_admission_status == "blocked"
        and len(partial.dynamic_mechanisms) == 1
        and partial.dynamic_mechanisms[0].coverage_status == "blocked",
        "blocked_startup_state_unchanged": not partial_registration.ok
        and partial_registration.state_unchanged
        and not partial_registration.mutations,
        "path_mismatch_registers_zero_dynamic": mismatch.assembly_status == "assembled"
        and mismatch.battle_admission_status == "admitted"
        and not mismatch.dynamic_mechanisms
        and mismatch_registration.ok
        and mismatch_registration.state_unchanged,
        "rank_pair_changes_values_not_graph_identity": rank_one_values != rank_two_values
        and rank_one.dynamic_mechanisms[0].graph_ref_id
        == rank_two.dynamic_mechanisms[0].graph_ref_id,
        "startup_registers_once": first.ok
        and len(first.mutations) == 1
        and second.ok
        and not second.mutations
        and second.state_unchanged,
        "startup_snapshot_preserves_provider": isinstance(snapshot_providers, list)
        and len(snapshot_providers) == 1
        and snapshot_providers[0].get("provider_id")
        == first.records[0].get("provider_id"),
        "multi_wearer_provider_identity_isolated": multi.ok
        and len(provider_ids) == 2
        and len(set(provider_ids)) == 2
        and all(unit.flags.get("ability_providers") for unit in multi.after_state.units.values()),
        "formal_scenario_registers_after_unit_creation": formal_character_result.battle_admission_status
        == "admitted"
        and len(formal_provider_mutations) == 1
        and formal_provider_mutations[0].path
        == ("units", "ally:formal-provider", "flags", "ability_providers")
        and len(formal_providers) == 1
        and len(formal_provider_records) == 1
        and formal_provider_records[0].get("status") == "registered",
        "formal_snapshot_restore_is_idempotent": restored_registration.ok
        and restored_registration.state_unchanged
        and not restored_registration.mutations,
        "formal_scenario_rebuild_has_one_provider": len(rebuilt_providers) == 1
        and len(
            tuple(
                mutation
                for mutation in formal_rebuilt.setup_mutations
                if mutation.source == "ability_provider_registry"
            )
        )
        == 1,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s6_startup_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "production_partial": {
            "assembly_status": partial.assembly_status,
            "battle_admission_status": partial.battle_admission_status,
            "static_contribution_count": len(partial.static_contributions),
            "dynamic_mechanism_count": len(partial.dynamic_mechanisms),
            "dynamic_statuses": [
                item.coverage_status for item in partial.dynamic_mechanisms
            ],
            "blocker_reasons": [
                item.reason_code for item in partial.battle_admission_blockers
            ],
        },
        "path_mismatch": {
            "assembly_status": mismatch.assembly_status,
            "battle_admission_status": mismatch.battle_admission_status,
            "static_contribution_count": len(mismatch.static_contributions),
            "dynamic_mechanism_count": len(mismatch.dynamic_mechanisms),
            "battle_blocker_count": len(mismatch.battle_admission_blockers),
        },
        "admitted_fixture_scope": "provider_lifecycle_only; does_not_claim_equipment_gameplay_execution",
        "rank_pair": {
            "graph_ref_id": rank_one.dynamic_mechanisms[0].graph_ref_id,
            "rank_one_values": list(rank_one_values),
            "rank_two_values": list(rank_two_values),
        },
        "first_registration": [record for record in first.records],
        "second_registration": [record for record in second.records],
        "snapshot_provider_count": len(snapshot_providers),
        "multi_owner_provider_ids": list(provider_ids),
        "formal_scenario": {
            "definition_identity": formal_context[
                "definition"
            ].definition_key.definition_identity,
            "character_battle_admission_status": formal_character_result.battle_admission_status,
            "provider_count": len(formal_providers),
            "provider_mutations": [
                mutation.to_json() for mutation in formal_provider_mutations
            ],
            "provider_records": list(formal_provider_records),
            "restored_registration_mutation_count": len(
                restored_registration.mutations
            ),
            "rebuilt_provider_count": len(rebuilt_providers),
        },
    }


def _negative_matrix(bundle: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    definition = sample["definition"]
    card = sample["card"]
    mechanism_key = definition.mechanism_ref_ids[0]
    mechanism = rules.equipment_mechanism_ref(mechanism_key.definition_identity).value
    assert mechanism is not None
    graph = rules.standalone_ability_graph(mechanism.graph_ref_id)
    assert graph is not None
    read = rules.equipment_ability_parameter_read(mechanism.parameter_binding_ids[0])
    assert read is not None

    missing_graph_rules = RuleBook(
        replace(
            bundle["ir"],
            standalone_ability_graphs=tuple(
                item for item in bundle["graphs"] if item.standalone_ability_graph_id != graph.standalone_ability_graph_id
            ),
        )
    )
    duplicate_graph_rules = RuleBook(
        replace(
            bundle["ir"],
            standalone_ability_graphs=(*bundle["graphs"], graph),
        )
    )
    wrong_source_graph = replace(
        graph,
        source=sample["cross_definition"].ability_source.source,
    )
    wrong_source_rules = RuleBook(
        replace(
            bundle["ir"],
            standalone_ability_graphs=tuple(
                wrong_source_graph
                if item.standalone_ability_graph_id == graph.standalone_ability_graph_id
                else item
                for item in bundle["graphs"]
            ),
        )
    )
    duplicate_parameter_read_rules = RuleBook(
        replace(
            bundle["ir"],
            equipment_ability_parameter_reads=(
                *bundle["parameter_reads"],
                read,
            ),
        )
    )
    wrong_parameter_read_source = replace(
        read,
        source=replace(
            read.source,
            source_path=sample["cross_definition"].ability_source.source.source_path,
        ),
    )
    wrong_parameter_read_source_rules = RuleBook(
        replace(
            bundle["ir"],
            equipment_ability_parameter_reads=tuple(
                wrong_parameter_read_source
                if item.parameter_read_id == read.parameter_read_id
                else item
                for item in bundle["parameter_reads"]
            ),
        )
    )
    graph_json_path = graph.source.evidence.get("json_path")
    assert isinstance(graph_json_path, str)
    forged_hash_source = immutable_ir_source(
        replace(
            read.source,
            evidence={
                **read.source.evidence,
                "json_path": (
                    f"{graph_json_path}.DynamicValues.{read.value_type}."
                    "forged_hash.ReadInfo"
                ),
            },
        )
    )
    forged_hash_read_rules = RuleBook(
        replace(
            bundle["ir"],
            equipment_ability_parameter_reads=tuple(
                replace(read, source=forged_hash_source)
                if item.parameter_read_id == read.parameter_read_id
                else item
                for item in bundle["parameter_reads"]
            ),
        )
    )
    forged_type_read_rules = RuleBook(
        replace(
            bundle["ir"],
            equipment_ability_parameter_reads=tuple(
                replace(
                    read,
                    value_type="ForgedType",
                    source=immutable_ir_source(
                        replace(
                            read.source,
                            evidence={
                                **read.source.evidence,
                                "json_path": (
                                    f"{graph_json_path}.DynamicValues.ForgedType."
                                    f"{read.dynamic_hash}.ReadInfo"
                                ),
                            },
                        )
                    ),
                )
                if item.parameter_read_id == read.parameter_read_id
                else item
                for item in bundle["parameter_reads"]
            ),
        )
    )
    wrong_definition_mechanism_rules = RuleBook(
        replace(
            bundle["ir"],
            light_cone_definitions=tuple(
                replace(
                    item,
                    mechanism_ref_ids=sample["cross_definition"].mechanism_ref_ids,
                )
                if item.definition_key == definition.definition_key
                else item
                for item in bundle["definitions"]
            ),
        )
    )
    rank = definition.superimposition_levels[0]
    out_of_range_read = replace(read, parameter_index=len(rank.parameters))
    out_of_range_rules = RuleBook(
        replace(
            bundle["ir"],
            equipment_ability_parameter_reads=tuple(
                out_of_range_read if item.parameter_read_id == read.parameter_read_id else item
                for item in bundle["parameter_reads"]
            ),
        )
    )
    _, out_of_range_result = _assembly(
        out_of_range_rules,
        card.card_id,
        definition,
        instance_id="validation:p8_s6:out-of-range",
        rank=1,
    )

    admitted_ir = replace(
        bundle["ir"],
        standalone_ability_graphs=tuple(
            replace(item, coverage_status="executable", blocked_reason="")
            if item.standalone_ability_graph_id == graph.standalone_ability_graph_id
            else item
            for item in bundle["graphs"]
        ),
    )
    admitted_rules = RuleBook(admitted_ir)
    parameter = rank.parameters[read.parameter_index]
    exact_request = ExactEquipmentValueBindingRequest(
        binding_kind="equipment_rank_parameter",
        binding_id="validation:p8_s6:negative:exact-binding",
        target_definition_identity=definition.definition_key.definition_identity,
        graph_ref_id=graph.standalone_ability_graph_id,
        parameter_read_id=read.parameter_read_id,
        value_type=read.value_type,
        dynamic_hash=read.dynamic_hash,
        parameter_index=read.parameter_index,
        skill_id=rank.skill_id,
        superimposition_level=rank.level,
        exact_value=parameter.exact_value,
        value_source=parameter.source,
    )
    exact_resolver = ValueResolver(admitted_rules)
    forged_value_resolution = exact_resolver.resolve_equipment_rank_parameter(
        replace(exact_request, exact_value="999")
    )
    forged_source_resolution = exact_resolver.resolve_equipment_rank_parameter(
        replace(
            exact_request,
            value_source=replace(parameter.source, raw_id="forged:rank-parameter"),
        )
    )
    _, admitted_result = _assembly(
        admitted_rules,
        card.card_id,
        definition,
        instance_id="validation:p8_s6:negative",
        rank=1,
    )
    selection = admitted_result.dynamic_mechanisms[0]
    state = BattleState(
        units={
            "ally:owner": UnitState(
                unit_id="ally:owner",
                side="ally",
                template_id=card.entity_ref,
                flags={"character_data_card_id": card.card_id},
            )
        }
    )
    wrong_owner = replace(selection, wearer_character_card_id="wrong:card")
    missing_binding = replace(selection, parameter_bindings=selection.parameter_bindings[1:])
    first_binding = selection.parameter_bindings[0]
    forged_binding = replace(first_binding, exact_value="999")
    forged_value = replace(
        selection,
        parameter_bindings=(forged_binding, *selection.parameter_bindings[1:]),
    )
    owner_result = register_dynamic_ability_providers(
        state, admitted_rules, (("ally:owner", wrong_owner),)
    )
    binding_result = register_dynamic_ability_providers(
        state, admitted_rules, (("ally:owner", missing_binding),)
    )
    forged_result = register_dynamic_ability_providers(
        state, admitted_rules, (("ally:owner", forged_value),)
    )
    registered_result = register_dynamic_ability_providers(
        state, admitted_rules, (("ally:owner", selection),)
    )
    aliased_selection = replace(
        selection,
        selection_id="validation:p8_s6:forged-selection-alias",
    )
    duplicate_existing_result = register_dynamic_ability_providers(
        registered_result.after_state,
        admitted_rules,
        (("ally:owner", aliased_selection),),
    )
    duplicate_request_result = register_dynamic_ability_providers(
        state,
        admitted_rules,
        (
            ("ally:owner", selection),
            ("ally:owner", aliased_selection),
        ),
    )
    forged_hash_binding = replace(first_binding, read_source=forged_hash_source)
    forged_hash_selection = replace(
        selection,
        parameter_bindings=(
            forged_hash_binding,
            *selection.parameter_bindings[1:],
        ),
    )
    forged_type_binding = replace(first_binding, value_type="ForgedType")
    forged_type_selection = replace(
        selection,
        parameter_bindings=(
            forged_type_binding,
            *selection.parameter_bindings[1:],
        ),
    )
    unknown_json = selection.to_json()
    unknown_json["legacy_payload"] = {}
    rows = {
        "missing_graph": missing_graph_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "duplicate_graph": duplicate_graph_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "wrong_graph_source": wrong_source_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "duplicate_parameter_read": duplicate_parameter_read_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "wrong_parameter_read_source": wrong_parameter_read_source_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "forged_dynamic_hash_json_path": forged_hash_read_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "forged_parameter_value_type": forged_type_read_rules.equipment_mechanism_ref(
            mechanism_key.definition_identity
        ).resolution_status
        == "blocked",
        "wrong_definition_mechanism_source": wrong_definition_mechanism_rules.light_cone_definition(
            definition.definition_key.definition_identity
        ).resolution_status
        == "blocked",
        "parameter_index_out_of_range": out_of_range_result.battle_admission_status
        == "blocked"
        and not out_of_range_result.dynamic_mechanisms,
        "owner_mismatch": not owner_result.ok
        and owner_result.state_unchanged
        and not owner_result.mutations,
        "parameter_read_set_mismatch": not binding_result.ok
        and binding_result.state_unchanged
        and not binding_result.mutations,
        "parameter_value_forged": not forged_result.ok
        and forged_result.state_unchanged
        and not forged_result.mutations,
        "result_model_rejects_forged_dynamic_hash_path": _raises(
            lambda: replace(
                admitted_result,
                dynamic_mechanisms=(forged_hash_selection,),
            )
        ),
        "result_model_rejects_forged_parameter_type": _raises(
            lambda: replace(
                admitted_result,
                dynamic_mechanisms=(forged_type_selection,),
            )
        ),
        "same_semantic_provider_rejects_selection_alias": not duplicate_existing_result.ok
        and duplicate_existing_result.state_unchanged
        and not duplicate_existing_result.mutations,
        "same_request_rejects_semantic_provider_duplicate": not duplicate_request_result.ok
        and duplicate_request_result.state_unchanged
        and not duplicate_request_result.mutations,
        "value_resolver_rejects_forged_exact_value": not forged_value_resolution.ok,
        "value_resolver_rejects_forged_value_source": not forged_source_resolution.ok,
        "unknown_legacy_json_field": _raises(
            lambda: DynamicMechanismSelection.from_json(unknown_json)
        ),
        "float_exact_value": _raises(
            lambda: replace(first_binding, exact_value=0.5)
        ),
    }
    required = {
        "missing_graph",
        "duplicate_graph",
        "wrong_graph_source",
        "duplicate_parameter_read",
        "wrong_parameter_read_source",
        "forged_dynamic_hash_json_path",
        "forged_parameter_value_type",
        "wrong_definition_mechanism_source",
        "parameter_index_out_of_range",
        "owner_mismatch",
        "parameter_read_set_mismatch",
        "parameter_value_forged",
        "result_model_rejects_forged_dynamic_hash_path",
        "result_model_rejects_forged_parameter_type",
        "same_semantic_provider_rejects_selection_alias",
        "same_request_rejects_semantic_provider_duplicate",
        "value_resolver_rejects_forged_exact_value",
        "value_resolver_rejects_forged_value_source",
        "unknown_legacy_json_field",
        "float_exact_value",
    }
    checks = {
        "required_rows_present": set(rows) == required,
        "all_negative_rows_rejected": all(rows.values()),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s6_negative_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "rows": rows,
        "focused_rulebook_build_count": 10,
    }


def _family_gap_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    opcode_counts: Counter[str] = Counter()
    for phase in bundle["phases"]:
        counts = phase.opcode_summary.get("opcode_counts")
        if isinstance(counts, dict):
            for opcode, count in counts.items():
                if isinstance(opcode, str) and isinstance(count, int):
                    opcode_counts[opcode] += count
    rows = [
        {
            "opcode": opcode,
            "raw_node_count": count,
            "inventory_role": "s6_raw_family_discovery",
        }
        for opcode, count in sorted(opcode_counts.items())
    ]
    production_graphs = bundle["graphs"]
    executable_graphs = tuple(
        graph for graph in production_graphs if graph.coverage_status == "executable"
    )
    blocked_graphs = tuple(
        graph for graph in production_graphs if graph.coverage_status != "executable"
    )
    checks = {
        "all_partial_graphs_have_reason": all(
            bool(graph.blocked_reason) for graph in blocked_graphs
        ),
        "current_partial_graphs_remain_blocked": bool(blocked_graphs),
        "downstream_admitted_graphs_are_explicit": bool(executable_graphs)
        and all(not graph.blocked_reason for graph in executable_graphs),
        "graph_partition_is_lossless": len(executable_graphs)
        + len(blocked_graphs)
        == len(production_graphs),
        "family_rows_nonempty": bool(rows),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s6_family_gap_matrix_v2",
        "ok": checks["ok"],
        "checks": checks,
        "current_graph_counts": {
            "executable": len(executable_graphs),
            "blocked": len(blocked_graphs),
        },
        "rows": rows,
    }


def _source_walkback(
    bundle: dict[str, Any],
    startup_matrix: dict[str, Any],
) -> dict[str, Any]:
    formal_scenario = startup_matrix.get("formal_scenario", {})
    records = (
        formal_scenario.get("provider_records", [])
        if isinstance(formal_scenario, dict)
        else []
    )
    if not records:
        records = startup_matrix.get("first_registration", [])
    record = records[0] if isinstance(records, list) and records else {}
    semantic_key = record.get("semantic_key", {}) if isinstance(record, dict) else {}
    mechanism_key = (
        semantic_key.get("mechanism_key", {})
        if isinstance(semantic_key, dict)
        else {}
    )
    mechanism_identity = (
        mechanism_key.get("definition_identity")
        if isinstance(mechanism_key, dict)
        else None
    )
    definition = next(
        (
            candidate
            for candidate in bundle["definitions"]
            if any(
                key.definition_identity == mechanism_identity
                for key in candidate.mechanism_ref_ids
            )
        ),
        None,
    )
    ability_source = definition.ability_source if definition is not None else None
    graph_ref_id = record.get("graph_ref_id") if isinstance(record, dict) else None
    graph = (
        bundle["rules"].standalone_ability_graph(graph_ref_id)
        if isinstance(graph_ref_id, str)
        else None
    )
    mechanism = (
        bundle["rules"].equipment_mechanism_ref(mechanism_identity).value
        if isinstance(mechanism_identity, str)
        else None
    )
    ok = bool(
        ability_source
        and graph
        and mechanism
        and record.get("source") == ability_source.source.to_json()
        and graph.source == ability_source.source
        and graph.standalone_ability_graph_id == mechanism.graph_ref_id
        and record.get("parameter_binding_ids")
        == list(mechanism.parameter_binding_ids)
        and ability_source.source.source_path.startswith("Config/ConfigAbility/Equip/")
        and ability_source.source.evidence.get("json_path")
        == f"$.AbilityList[{ability_source.record_index}]"
        and ability_source.source.evidence.get("source_fingerprint")
    )
    return {
        "schema_version": "p8_s6_source_walkback_v1",
        "ok": ok,
        "definition_key": definition.definition_key.to_json() if definition else {},
        "ability_name": ability_source.ability_name if ability_source else "",
        "ability_record_index": ability_source.record_index if ability_source else None,
        "provider_registration": record,
        "graph_ref_id": graph_ref_id,
        "source": ability_source.source.to_json() if ability_source else {},
    }


def _runtime_boundary() -> dict[str, Any]:
    source = inspect.getsource(provider_module)
    raw_tokens = (
        "read_text(",
        "json.loads(",
        "Config/ConfigAbility/Equip/",
        "EquipmentBuildInput",
        "LightConeInstanceInput",
    )
    event_loop_tokens = (
        "EventDispatchSystem",
        "dispatch_event(",
        "callback_kind",
        "execute_standalone(",
    )
    return {
        "schema_version": "p8_s6_runtime_boundary_v1",
        "runtime_reads_raw_equipment": any(token in source for token in raw_tokens),
        "equipment_specific_event_loop_created": any(
            token in source for token in event_loop_tokens
        ),
        "runtime_input_contract": [
            "DynamicMechanismSelection",
            "RuleBook/CanonicalIR",
            "BattleState",
        ],
    }


def _raises(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate P8-S6 light-cone dynamic startup")
    parser.add_argument("--tbgd-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    tbgd_root = args.tbgd_root.resolve() if args.tbgd_root else find_tbgd_root(Path.cwd())
    summary = run_validation(tbgd_root, args.output_dir.resolve())
    print({"ok": summary["ok"], "counts": summary["counts"], "output_dir": str(args.output_dir.resolve())})
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
