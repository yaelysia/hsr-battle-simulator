from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Mapping
from copy import copy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

from ..builds.character_assembler import (
    assemble_character_build,
    validate_character_build_admission,
)
from ..builds.models import (
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    CharacterInitialConditionInput,
    CharacterInitialResourceValue,
    OwnedCombatantActionBinding,
    OwnedCombatantBuildAssemblyResult,
)
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..equipment.models import EquipmentBuildInput
from ..rules.ir import (
    AbilityTaskIR,
    CanonicalIR,
    CharacterDataCardIR,
    CharacterTraceNodeIR,
    IRSource,
    ServantDefinitionIR,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import (
    ScenarioStateBuilder,
    initialize_special_resource,
)
from ..scenarios.schema import (
    BattleSetupSpec,
    PanelInput,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.ability import AbilityTaskSystem
from ..systems.ability_task_contract import ability_task_runtime_blocked_reason
from ..systems.effect import EffectRegistry
from ..systems.summon import SummonSystem
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from ..tbgd.lowering import (
    TBGDLowering,
    _process_only_ability_task_source_blocked_reason,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json


VALIDATION_VERSION = "char_m1_memory_owned_combatant_build_closure_v3"

_SOURCE_IDENTITY_FIELDS = frozenset(
    {
        "action_event_id",
        "action_id",
        "action_level",
        "ability_name",
        "ability_phase_id",
        "ability_task_id",
        "birth_template_id",
        "damage_emission_id",
        "definition_id",
        "effect_id",
        "event_id",
        "formula_id",
        "level",
        "owner_character_card_id",
        "servant_definition_id",
        "skill_id",
        "skill_level",
        "spawn_source_id",
        "status_definition_id",
        "target_expression_id",
        "task_id",
    }
)


def _compact_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        scalar_items = [
            item
            for item in value
            if item is None or isinstance(item, (bool, int, float, str))
        ]
        return {
            "kind": "array",
            "length": len(value),
            "scalar_sample": scalar_items[:8],
        }
    if isinstance(value, Mapping):
        return {
            "kind": "object",
            "key_count": len(value),
            "keys": sorted(str(key) for key in value)[:24],
        }
    return {"kind": type(value).__name__}


def _compact_source_material(value: Any) -> dict[str, Any]:
    identities: list[dict[str, Any]] = []
    source_references: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    seen_sources: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            source_path = item.get("source_path")
            if isinstance(source_path, str) and source_path:
                reference = {
                    key: item[key]
                    for key in ("source_path", "raw_type", "raw_id", "raw_path", "row_index")
                    if key in item
                    and (
                        item.get(key) is None
                        or isinstance(item.get(key), (bool, int, float, str))
                    )
                }
                source_key = json.dumps(reference, ensure_ascii=False, sort_keys=True)
                if source_key not in seen_sources and len(source_references) < 24:
                    seen_sources.add(source_key)
                    source_references.append(reference)
            for key, nested in item.items():
                if str(key) in _SOURCE_IDENTITY_FIELDS and (
                    nested is None or isinstance(nested, (bool, int, float, str))
                ):
                    identity = {"field": str(key), "value": nested}
                    identity_key = json.dumps(
                        identity,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if identity_key not in seen_identities and len(identities) < 48:
                        seen_identities.add(identity_key)
                        identities.append(identity)
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return {
        "identities": identities,
        "source_references": source_references,
    }


def _compact_mutation(mutation: Any) -> dict[str, Any]:
    raw = mutation.to_json()
    metadata = raw.get("metadata")
    source_material = _compact_source_material(metadata)
    return {
        "mutation_id": raw.get("mutation_id"),
        "op": raw.get("op"),
        "path": raw.get("path"),
        "before": _compact_json_value(raw.get("before")),
        "before_exists": raw.get("before_exists"),
        "after": _compact_json_value(raw.get("after")),
        "after_exists": raw.get("after_exists"),
        "reason": raw.get("reason"),
        "source": raw.get("source"),
        "metadata_keys": (
            sorted(str(key) for key in metadata)
            if isinstance(metadata, Mapping)
            else []
        ),
        **source_material,
    }


def _compact_settlement(settlement: Any) -> dict[str, Any] | None:
    if settlement is None:
        return None
    records = []
    for record in settlement.records:
        payload = record.get("payload")
        trace = record.get("trace")
        records.append(
            {
                "record_type": record.get("record_type"),
                "source": record.get("source"),
                "process_only": record.get("process_only"),
                "mutation_id": record.get("mutation_id"),
                "payload_keys": (
                    sorted(str(key) for key in payload)
                    if isinstance(payload, Mapping)
                    else []
                ),
                "trace_keys": (
                    sorted(str(key) for key in trace)
                    if isinstance(trace, Mapping)
                    else []
                ),
                **_compact_source_material(record),
            }
        )
    return {
        "action_id": settlement.action_id,
        "actor_id": settlement.actor_id,
        "target_ids": list(settlement.target_ids),
        "record_count": len(records),
        "records": records,
    }


def _compact_source_audit(audit: Any) -> dict[str, Any]:
    trace_rows = []
    for trace in audit.traces:
        mutation = trace.get("mutation") if isinstance(trace, Mapping) else None
        record = trace.get("record") if isinstance(trace, Mapping) else None
        trace_rows.append(
            {
                "mutation_id": (
                    mutation.get("mutation_id")
                    if isinstance(mutation, Mapping)
                    else None
                ),
                "mutation_source": (
                    mutation.get("source")
                    if isinstance(mutation, Mapping)
                    else None
                ),
                "record_type": (
                    record.get("record_type")
                    if isinstance(record, Mapping)
                    else None
                ),
                "record_mutation_id": (
                    record.get("mutation_id")
                    if isinstance(record, Mapping)
                    else None
                ),
                **_compact_source_material(trace),
            }
        )
    violations = [
        {
            "mutation_id": violation.mutation_id,
            "source": violation.source,
            "path": list(violation.path),
            "reason": violation.reason,
            "missing_field": violation.missing_field,
        }
        for violation in audit.violations
    ]
    return {
        "ok": audit.ok,
        "checked_mutations": audit.checked_mutations,
        "checked_records": audit.checked_records,
        "trace_count": len(trace_rows),
        "all_checked_mutations_have_trace": (
            len(trace_rows) == audit.checked_mutations
        ),
        "violation_count": len(violations),
        "violations": violations,
        "traces": trace_rows,
    }


def run_validation(
    package_root: Path,
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    rules = RuleBook(TBGDLowering(tbgd_root).build())
    affected = _affected_cards(rules)
    builds = tuple(_empty_build(card) for card, _skills, _nodes in affected)
    assemblies = tuple(assemble_character_build(rules, build) for build in builds)
    source_matrix = _source_matrix(rules, affected, assemblies)
    skill_matrix = _skill_ownership_matrix(rules, affected)
    admission_matrix = _admission_matrix(rules, affected, builds, assemblies)
    process_only_task_matrix = _process_only_task_contract_matrix(rules)
    fail_closed_matrix = _runtime_fail_closed_matrix(
        rules,
        process_only_task_matrix,
    )
    special_resource_runtime_matrix = _special_resource_runtime_matrix(
        rules,
        builds,
        assemblies,
    )
    scenario_matrix, transition_sample = _scenario_and_transition_matrix(
        rules,
        builds,
        assemblies,
    )
    static_matrix = _static_boundary_matrix(package_root, rules, affected)
    admitted_memory_builds = tuple(
        (build, assembly)
        for build, assembly in zip(builds, assemblies, strict=True)
        if assembly.battle_admission_status == "admitted"
        and assembly.owned_combatant_results
    )
    checks = {
        "affected_auxiliary_skill_nodes_all_classified": (
            bool(affected)
            and all(row["all_auxiliary_nodes_classified"] for row in source_matrix)
        ),
        "owner_servant_relations_unique_and_source_backed": all(
            row["owner_relations_unique_and_source_backed"] for row in source_matrix
        ),
        "owner_and_servant_build_identities_distinct": all(
            row["build_identities_distinct"] for row in skill_matrix
        ),
        "owned_combatant_results_recursively_immutable": all(
            row["round_trip_equal"] and row["fingerprint_stable"]
            for row in skill_matrix
        )
        and admission_matrix["immutability_negative"]["ok"],
        "auxiliary_skill_levels_resolve_to_owned_combatant": all(
            row["selected_auxiliary_skills_resolved"]
            and row["level_oracle_equal"]
            and row["source_multiplicity_exact"]
            for row in skill_matrix
        ),
        "auxiliary_skill_level_double_application_count": sum(
            row["double_application_count"] for row in skill_matrix
        ),
        "required_special_resources_typed_and_source_backed": (
            admission_matrix["special_resource_checks"]["ok"]
            and special_resource_runtime_matrix["ok"]
        ),
        "required_servant_definitions_assembled": all(
            row["assembly_components_classified"] for row in source_matrix
        ),
        "parent_child_battle_admission_atomic": admission_matrix[
            "parent_child_atomic_negative"
        ],
        "missing_spawn_source_does_not_spawn": scenario_matrix[
            "missing_spawn_source_does_not_spawn"
        ],
        "source_backed_spawn_preserves_owner_relation": scenario_matrix[
            "source_backed_spawn_preserves_owner_relation"
        ],
        "spawned_servant_has_queryable_source_backed_action": scenario_matrix[
            "spawned_servant_has_queryable_source_backed_action"
        ],
        "representative_servant_transition_committed": transition_sample.get(
            "committed"
        )
        is True,
        "representative_toughness_sources_admitted": transition_sample.get(
            "toughness_sources_admitted"
        )
        is True,
        "representative_mutations_source_audited": transition_sample.get(
            "source_audit_ok"
        )
        is True,
        "representative_transition_replay_equal": transition_sample.get(
            "replay_ok"
        )
        is True,
        "fixed_character_or_servant_id_count": static_matrix[
            "fixed_character_or_servant_id_count"
        ],
        "runtime_raw_tbgd_read_count": static_matrix["runtime_raw_tbgd_read_count"],
        "non_memory_character_build_regression": admission_matrix[
            "non_owned_character_regression"
        ],
        "memory_path_has_formal_admitted_character_build": bool(
            admitted_memory_builds
        )
        and scenario_matrix["formal_memory_build_entered_scenario"],
        "required_negative_cases_all_pass": admission_matrix[
            "required_negative_cases_all_pass"
        ],
        "blocked_toughness_source_precedes_target_applicability": (
            fail_closed_matrix[
                "blocked_toughness_source_precedes_target_applicability"
            ]
        ),
        "process_only_task_requires_explicit_source_contract": (
            fail_closed_matrix[
                "process_only_task_requires_explicit_source_contract"
            ]
        ),
    }
    ok = (
        all(
            value is True
            for key, value in checks.items()
            if key
            not in {
                "auxiliary_skill_level_double_application_count",
                "fixed_character_or_servant_id_count",
                "runtime_raw_tbgd_read_count",
            }
        )
        and checks["auxiliary_skill_level_double_application_count"] == 0
        and checks["fixed_character_or_servant_id_count"] == 0
        and checks["runtime_raw_tbgd_read_count"] == 0
    )
    summary = {
        "schema_version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "counts": {
            "affected_character_count": len(affected),
            "affected_auxiliary_skill_count": sum(
                len(skills) for _card, skills, _nodes in affected
            ),
            "affected_auxiliary_node_count": sum(
                row["auxiliary_node_count"] for row in source_matrix
            ),
            "skill_ownership_variant_count": len(skill_matrix),
            "servant_definition_count": len(rules.servant_definitions()),
            "admitted_memory_build_count": len(admitted_memory_builds),
            "required_negative_case_count": len(
                admission_matrix["required_negative_cases"]
            ),
            "spawn_candidate_count": scenario_matrix["spawn_candidate_count"],
            "queryable_spawn_count": scenario_matrix["queryable_spawn_count"],
        },
        "resource_budget": {
            "full_tbgd_lowering_build_count": 1,
            "full_rulebook_build_count": 1,
            "minimal_negative_rulebook_build_count": 1,
            "full_canonical_ir_written": False,
            "full_transition_dump_written": False,
            "serial_execution": True,
        },
        "selection_policy": {
            "mode": "all_current_auxiliary_trace_nodes_joined_by_typed_owner_relation",
            "representative_mode": (
                "first_structurally_queryable_admitted_owned_combatant_action"
            ),
            "representative_target_mode": (
                "non_weak_target_after_toughness_source_admission_with_separate_blocked_source_negative"
            ),
            "fixed_character_servant_skill_file_hash_or_observation_used": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "source_matrix.json", source_matrix)
    write_json(output_dir / "skill_ownership_matrix.json", skill_matrix)
    write_json(output_dir / "admission_negatives.json", admission_matrix)
    write_json(output_dir / "fail_closed_regressions.json", fail_closed_matrix)
    write_json(
        output_dir / "process_only_task_contract_matrix.json",
        process_only_task_matrix,
    )
    write_json(
        output_dir / "special_resource_runtime_matrix.json",
        special_resource_runtime_matrix,
    )
    write_json(
        output_dir / "transition_replay_samples.json",
        {"scenario": scenario_matrix, "representative_transition": transition_sample},
    )
    return summary


def _affected_cards(
    rules: RuleBook,
) -> tuple[
    tuple[CharacterDataCardIR, tuple[str, ...], tuple[CharacterTraceNodeIR, ...]],
    ...,
]:
    rows = []
    for card in sorted(rules.ir.character_data_cards, key=lambda item: item.card_id):
        card_enhanced_id = card.source.evidence.get("enhanced_id")
        nodes = tuple(
            node
            for node in rules.character_trace_nodes_for_card(card.card_id)
            if (
                node.source.evidence.get("enhanced_id") is None
                if card_enhanced_id is None
                else str(node.source.evidence.get("enhanced_id"))
                == str(card_enhanced_id)
            )
        )
        auxiliary = tuple(
            sorted(
                {
                    skill_id
                    for node in nodes
                    for skill_id in node.level_up_skill_ids
                    if skill_id not in card.skill_ids
                }
            )
        )
        if auxiliary:
            rows.append((card, auxiliary, nodes))
    return tuple(rows)


def _empty_build(card: CharacterDataCardIR) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:owned_combatant:{card.card_id}",
        character_card_id=card.card_id,
        level=1,
        promotion=0,
        eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=EquipmentBuildInput(
            build_id=f"validation:owned_combatant:empty_equipment:{card.card_id}",
            character_card_id=card.card_id,
        ),
    )


def _source_matrix(
    rules: RuleBook,
    affected: tuple[
        tuple[CharacterDataCardIR, tuple[str, ...], tuple[CharacterTraceNodeIR, ...]],
        ...,
    ],
    assemblies: tuple[CharacterBuildAssemblyResult, ...],
) -> list[dict[str, Any]]:
    rows = []
    for (card, auxiliary, nodes), assembly in zip(
        affected,
        assemblies,
        strict=True,
    ):
        candidate_counts = {
            skill_id: len(
                rules.servant_definitions_for_owned_skill(card.entity_ref, skill_id)
            )
            for skill_id in auxiliary
        }
        definitions = rules.servant_definitions_for_owner(card.entity_ref)
        children_by_definition = {
            child.servant_definition_id: child
            for child in assembly.owned_combatant_results
        }
        relations = tuple(
            relation
            for definition in definitions
            for relation in definition.owner_relations
            if relation.owner_entity_ref == card.entity_ref
        )
        auxiliary_nodes = tuple(
            node
            for node in nodes
            if set(node.level_up_skill_ids).intersection(auxiliary)
        )
        node_rows = []
        for node in auxiliary_nodes:
            matched_skill_ids = tuple(
                sorted(set(node.level_up_skill_ids).intersection(auxiliary))
            )
            linked_slots = tuple(
                slot
                for slot_id in node.linked_mechanism_slot_ids
                if (slot := rules.character_mechanism_slot(slot_id)) is not None
                and slot.mechanism_kind == "trace_skill_level"
            )
            skill_candidates = {
                skill_id: rules.servant_definitions_for_owned_skill(
                    card.entity_ref,
                    skill_id,
                )
                for skill_id in matched_skill_ids
            }
            node_source_backed = _source_is_backed(node.source)
            slots_source_backed = len(linked_slots) == 1 and all(
                slot.coverage_status == "executable"
                and _source_is_backed(slot.source)
                for slot in linked_slots
            )
            ownership_unique = all(
                len(candidates) == 1
                and (
                    relation := candidates[0].owner_relation_for(card.entity_ref)
                )
                is not None
                and skill_id in relation.auxiliary_skill_ids
                and bool(relation.sources)
                for skill_id, candidates in skill_candidates.items()
            )
            classified = (
                bool(matched_skill_ids)
                and node.coverage_status == "executable"
                and node_source_backed
                and slots_source_backed
                and ownership_unique
            )
            node_rows.append(
                {
                    "trace_node_id": node.trace_node_id,
                    "trace_id": node.trace_id,
                    "level": node.level,
                    "max_level": node.max_level,
                    "default_unlocked": node.default_unlocked,
                    "matched_auxiliary_skill_ids": list(matched_skill_ids),
                    "candidate_definition_ids": {
                        skill_id: [
                            definition.servant_definition_id
                            for definition in candidates
                        ]
                        for skill_id, candidates in skill_candidates.items()
                    },
                    "linked_skill_level_slots": [
                        {
                            "mechanism_slot_id": slot.mechanism_slot_id,
                            "coverage_status": slot.coverage_status,
                            "blocked_reason": slot.blocked_reason,
                            "source": slot.source.to_json(),
                        }
                        for slot in linked_slots
                    ],
                    "source": node.source.to_json(),
                    "classification_status": (
                        "classified" if classified else "gap"
                    ),
                    "classification_reasons": [
                        reason
                        for reason, failed in (
                            ("auxiliary_skill_match_missing", not matched_skill_ids),
                            (
                                "trace_node_not_executable_or_source_missing",
                                node.coverage_status != "executable"
                                or not node_source_backed,
                            ),
                            (
                                "trace_skill_level_slot_not_unique_or_source_missing",
                                not slots_source_backed,
                            ),
                            (
                                "owner_servant_skill_relation_not_unique_or_source_missing",
                                not ownership_unique,
                            ),
                        )
                        if failed
                    ],
                }
            )
        definition_rows = []
        for definition in definitions:
            relation_matches = tuple(
                relation
                for relation in definition.owner_relations
                if relation.owner_entity_ref == card.entity_ref
            )
            relation_ok = (
                len(relation_matches) == 1
                and relation_matches[0].coverage_status == "executable"
                and bool(relation_matches[0].sources)
                and set(relation_matches[0].auxiliary_skill_ids).issubset(auxiliary)
            )
            component_rows = _servant_definition_component_rows(rules, definition)
            child = children_by_definition.get(definition.servant_definition_id)
            child_classified = child is not None and (
                child.assembly_status == "assembled"
                or bool(child.blocked_reasons)
            )
            definition_classified = (
                definition.coverage_status == "executable"
                or (
                    definition.coverage_status == "blocked"
                    and bool(definition.blocked_reason)
                )
            )
            definition_rows.append(
                {
                    "servant_definition_id": definition.servant_definition_id,
                    "servant_ref": definition.servant_ref,
                    "skill_ids": list(definition.skill_ids),
                    "owner_entity_refs": list(definition.owner_entity_refs),
                    "owner_relation": (
                        relation_matches[0].to_json()
                        if len(relation_matches) == 1
                        else None
                    ),
                    "definition_source": definition.source.to_json(),
                    "coverage_status": definition.coverage_status,
                    "blocked_reason": definition.blocked_reason,
                    "component_rows": component_rows,
                    "child_assembly": (
                        {
                            "owned_build_id": child.owned_build_id,
                            "assembly_status": child.assembly_status,
                            "battle_admission_status": child.battle_admission_status,
                            "blocked_reasons": list(child.blocked_reasons),
                            "result_fingerprint": child.result_fingerprint,
                        }
                        if child is not None
                        else None
                    ),
                    "relation_unique_and_source_backed": relation_ok,
                    "definition_classified": definition_classified,
                    "assembly_components_classified": relation_ok
                    and definition_classified
                    and child_classified
                    and all(item["classified"] for item in component_rows),
                }
            )
        rows.append(
            {
                "character_card_id": card.card_id,
                "owner_entity_ref": card.entity_ref,
                "auxiliary_skill_ids": list(auxiliary),
                "auxiliary_node_count": len(auxiliary_nodes),
                "auxiliary_nodes": node_rows,
                "candidate_counts": candidate_counts,
                "servant_definitions": definition_rows,
                "relation_ids": [relation.owner_relation_id for relation in relations],
                "all_auxiliary_skills_unique": all(
                    count == 1 for count in candidate_counts.values()
                ),
                "all_auxiliary_nodes_classified": bool(node_rows)
                and all(
                    item["classification_status"] == "classified"
                    for item in node_rows
                ),
                "owner_relations_unique_and_source_backed": bool(relations)
                and len({item.owner_relation_id for item in relations}) == len(relations)
                and all(item.sources for item in relations)
                and all(item["relation_unique_and_source_backed"] for item in definition_rows),
                "assembly_components_classified": bool(definition_rows)
                and all(
                    item["assembly_components_classified"]
                    for item in definition_rows
                ),
            }
        )
    return rows


def _source_is_backed(source: object) -> bool:
    return bool(
        getattr(source, "source_path", "")
        and getattr(source, "raw_type", "")
        and getattr(source, "raw_id", "")
    )


def _structured_component_status(
    value: object,
    *,
    component_kind: str,
    missing_reason: str,
) -> dict[str, Any]:
    payload = value if isinstance(value, Mapping) else {}
    status = str(
        payload.get("admission_status") or payload.get("coverage_status") or ""
    )
    reason = str(payload.get("blocked_reason") or "")
    raw_sources = payload.get("source_trace")
    source_rows = list(raw_sources) if isinstance(raw_sources, (list, tuple)) else []
    classified = (status == "executable" and bool(source_rows)) or (
        status == "blocked" and bool(reason or missing_reason)
    )
    return {
        "component_kind": component_kind,
        "status": status or "blocked",
        "blocked_reason": reason or (missing_reason if status != "executable" else ""),
        "source_count": len(source_rows),
        "source_trace": source_rows,
        "classified": classified,
    }


def _servant_definition_component_rows(
    rules: RuleBook,
    definition: ServantDefinitionIR,
) -> list[dict[str, Any]]:
    rows = [
        _structured_component_status(
            definition.action_set,
            component_kind="action_set",
            missing_reason="servant_action_set_missing_or_unclassified",
        ),
        _structured_component_status(
            definition.stat_source,
            component_kind="stat_source",
            missing_reason="servant_stat_source_missing_or_unclassified",
        ),
        _structured_component_status(
            definition.timeline_source,
            component_kind="timeline_source",
            missing_reason="servant_timeline_source_missing_or_unclassified",
        ),
        _structured_component_status(
            definition.lifecycle_source,
            component_kind="lifecycle_source",
            missing_reason="servant_lifecycle_source_missing_or_unclassified",
        ),
    ]
    components = definition.stat_source.get("components")
    if isinstance(components, Mapping):
        rows.extend(
            _structured_component_status(
                value,
                component_kind=f"stat_component:{key}",
                missing_reason=f"servant_stat_component_unclassified:{key}",
            )
            for key, value in sorted(components.items())
        )
    else:
        rows.append(
            {
                "component_kind": "stat_components",
                "status": "blocked",
                "blocked_reason": "servant_stat_components_missing",
                "source_count": 0,
                "source_trace": [],
                "classified": True,
            }
        )
    owner_sync = definition.stat_source.get("owner_sync_fields")
    if isinstance(owner_sync, Mapping):
        rows.extend(
            _structured_component_status(
                value,
                component_kind=f"owner_sync_stat:{key}",
                missing_reason=f"servant_owner_sync_stat_unclassified:{key}",
            )
            for key, value in sorted(owner_sync.items())
        )
    else:
        rows.append(
            {
                "component_kind": "owner_sync_stats",
                "status": "blocked",
                "blocked_reason": "servant_owner_sync_stats_missing",
                "source_count": 0,
                "source_trace": [],
                "classified": True,
            }
        )

    action_entries = definition.action_set.get("skill_index_map")
    if isinstance(action_entries, Mapping):
        for slot, value in sorted(action_entries.items()):
            entry = value if isinstance(value, Mapping) else {}
            action_id = str(entry.get("action_ref") or "")
            level = entry.get("default_level")
            definition_candidates = (
                rules.action_definition_candidates(action_id, level)
                if action_id
                and isinstance(level, int)
                and not isinstance(level, bool)
                else ()
            )
            admissions = (
                rules.action_admissions_for(definition.servant_ref, action_id, level)
                if definition_candidates
                else ()
            )
            binding = (
                rules.action_ability_binding(action_id, level)
                if definition_candidates
                else None
            )
            executable = (
                entry.get("coverage_status") == "executable"
                and len(definition_candidates) == 1
                and definition_candidates[0].coverage_status == "executable"
                and len(admissions) == 1
                and admissions[0].coverage_status == "executable"
                and binding is not None
                and binding.coverage_status == "executable"
            )
            reason = ";".join(
                reason
                for reason, failed in (
                    ("servant_action_entry_not_executable", entry.get("coverage_status") != "executable"),
                    ("servant_action_definition_not_unique", len(definition_candidates) != 1),
                    (
                        "servant_action_definition_not_executable",
                        len(definition_candidates) == 1
                        and definition_candidates[0].coverage_status != "executable",
                    ),
                    ("servant_action_admission_not_unique", len(admissions) != 1),
                    (
                        "servant_action_admission_not_executable",
                        len(admissions) == 1
                        and admissions[0].coverage_status != "executable",
                    ),
                    (
                        "servant_action_ability_binding_not_executable",
                        binding is None or binding.coverage_status != "executable",
                    ),
                )
                if failed
            )
            rows.append(
                {
                    "component_kind": f"action_entry:{slot}",
                    "status": "executable" if executable else "blocked",
                    "blocked_reason": reason,
                    "source_count": int(bool(definition_candidates))
                    + int(binding is not None),
                    "source_trace": [
                        *(
                            [definition_candidates[0].source.to_json()]
                            if len(definition_candidates) == 1
                            else []
                        ),
                        *([binding.source.to_json()] if binding is not None else []),
                    ],
                    "classified": executable or bool(reason),
                    "skill_id": str(entry.get("skill_id") or ""),
                    "action_id": action_id,
                    "level": level,
                    "definition_candidate_count": len(definition_candidates),
                    "admission_candidate_count": len(admissions),
                    "ability_binding_id": binding.binding_id if binding is not None else "",
                }
            )
    else:
        rows.append(
            {
                "component_kind": "action_entries",
                "status": "blocked",
                "blocked_reason": "servant_action_entries_missing",
                "source_count": 0,
                "source_trace": [],
                "classified": True,
            }
        )
    for binding_id in definition.ability_graph_ids:
        binding = rules.action_ability_binding_by_id(binding_id)
        executable = binding is not None and binding.coverage_status == "executable"
        rows.append(
            {
                "component_kind": f"ability_binding:{binding_id}",
                "status": "executable" if executable else "blocked",
                "blocked_reason": (
                    ""
                    if executable
                    else (
                        binding.blocked_reason
                        if binding is not None and binding.blocked_reason
                        else "servant_ability_binding_missing_or_blocked"
                    )
                ),
                "source_count": int(binding is not None),
                "source_trace": [binding.source.to_json()] if binding is not None else [],
                "classified": True,
            }
        )
    rows.append(
        {
            "component_kind": "birth_template",
            "status": (
                "executable"
                if rules.unit_birth_template(definition.birth_template_id) is not None
                else "blocked"
            ),
            "blocked_reason": (
                ""
                if rules.unit_birth_template(definition.birth_template_id) is not None
                else "servant_birth_template_missing"
            ),
            "source_count": int(
                rules.unit_birth_template(definition.birth_template_id) is not None
            ),
            "source_trace": (
                [rules.unit_birth_template(definition.birth_template_id).source.to_json()]
                if rules.unit_birth_template(definition.birth_template_id) is not None
                else []
            ),
            "classified": True,
        }
    )
    rows.append(
        {
            "component_kind": "spawn_sources",
            "status": "executable" if definition.spawn_sources else "blocked",
            "blocked_reason": "" if definition.spawn_sources else "servant_spawn_source_missing",
            "source_count": len(definition.spawn_sources),
            "source_trace": [source.to_json() for source in definition.spawn_sources],
            "classified": True,
        }
    )
    return rows


def _skill_ownership_matrix(
    rules: RuleBook,
    affected: tuple[
        tuple[CharacterDataCardIR, tuple[str, ...], tuple[CharacterTraceNodeIR, ...]],
        ...,
    ],
) -> list[dict[str, Any]]:
    rows = []
    for card, auxiliary, nodes in affected:
        for variant_name, build in _skill_variant_builds(rules, card, nodes):
            assembly = assemble_character_build(rules, build)
            owner_skills = {item.skill_id for item in assembly.effective_skill_levels}
            child_skills = {
                item.skill_id
                for child in assembly.owned_combatant_results
                for item in child.effective_skill_levels
            }
            oracle_rows = _skill_level_oracle(
                rules,
                card,
                auxiliary,
                nodes,
                build,
                assembly,
            )
            round_trip = CharacterBuildAssemblyResult.from_json(assembly.to_json())
            rows.append(
                {
                    "character_card_id": card.card_id,
                    "variant": variant_name,
                    "build_id": build.build_id,
                    "level": build.level,
                    "promotion": build.promotion,
                    "eidolon_level": build.eidolon_level,
                    "unlocked_trace_node_ids": list(build.unlocked_trace_node_ids),
                    "assembly_status": assembly.assembly_status,
                    "battle_admission_status": assembly.battle_admission_status,
                    "owned_results": [
                        {
                            "owned_build_id": child.owned_build_id,
                            "servant_definition_id": child.servant_definition_id,
                            "assembly_status": child.assembly_status,
                            "battle_admission_status": child.battle_admission_status,
                            "effective_skill_ids": [
                                item.skill_id for item in child.effective_skill_levels
                            ],
                            "action_ids": [
                                item.action_id for item in child.action_bindings
                            ],
                            "blocked_reasons": list(child.blocked_reasons),
                            "result_fingerprint": child.result_fingerprint,
                        }
                        for child in assembly.owned_combatant_results
                    ],
                    "skill_oracle": oracle_rows,
                    "build_identities_distinct": bool(
                        assembly.owned_combatant_results
                    )
                    and all(
                        child.owned_build_id != build.build_id
                        and child.parent_build_id == build.build_id
                        and child.parent_input_fingerprint == build.input_fingerprint
                        for child in assembly.owned_combatant_results
                    ),
                    "round_trip_equal": round_trip == assembly
                    and all(
                        OwnedCombatantBuildAssemblyResult.from_json(child.to_json())
                        == child
                        for child in assembly.owned_combatant_results
                    ),
                    "fingerprint_stable": round_trip.result_fingerprint
                    == assembly.result_fingerprint,
                    "selected_auxiliary_skills_resolved": set(auxiliary).issubset(
                        child_skills
                    )
                    and all(row["actual_resolution_count"] == 1 for row in oracle_rows),
                    "level_oracle_equal": bool(oracle_rows)
                    and all(row["level_equal"] for row in oracle_rows),
                    "source_multiplicity_exact": bool(oracle_rows)
                    and all(row["source_multiplicity_exact"] for row in oracle_rows),
                    "double_application_count": len(
                        owner_skills.intersection(child_skills)
                    ),
                }
            )
    return rows


def _skill_variant_builds(
    rules: RuleBook,
    card: CharacterDataCardIR,
    nodes: tuple[CharacterTraceNodeIR, ...],
) -> tuple[tuple[str, CharacterBuildInput], ...]:
    profile = rules.avatar_profile_by_profile_id(card.profile_id)
    if profile is None or not profile.promotion_tiers:
        return (("default_e0", _empty_build(card)),)
    final_tier = max(profile.promotion_tiers, key=lambda item: item.promotion)
    auxiliary_nodes = tuple(
        node
        for node in nodes
        if set(node.level_up_skill_ids).difference(card.skill_ids)
    )
    highest_by_trace: dict[str, CharacterTraceNodeIR] = {}
    for node in auxiliary_nodes:
        current = highest_by_trace.get(node.trace_id)
        if current is None or (node.level, node.trace_node_id) > (
            current.level,
            current.trace_node_id,
        ):
            highest_by_trace[node.trace_id] = node
    trace_ids = tuple(
        sorted(
            node.trace_node_id
            for node in highest_by_trace.values()
            if not node.default_unlocked
        )
    )

    def make(
        variant: str,
        *,
        level: int,
        promotion: int,
        eidolon_level: int,
        selected_trace_ids: tuple[str, ...],
    ) -> CharacterBuildInput:
        return CharacterBuildInput(
            build_id=f"validation:owned_combatant:{variant}:{card.card_id}",
            character_card_id=card.card_id,
            level=level,
            promotion=promotion,
            eidolon_level=eidolon_level,
            unlocked_trace_node_ids=selected_trace_ids,
            equipment_build=EquipmentBuildInput(
                build_id=(
                    f"validation:owned_combatant:empty_equipment:{variant}:{card.card_id}"
                ),
                character_card_id=card.card_id,
            ),
        )

    return (
        (
            "default_e0",
            make(
                "default_e0",
                level=1,
                promotion=0,
                eidolon_level=0,
                selected_trace_ids=(),
            ),
        ),
        (
            "trace_max_e0",
            make(
                "trace_max_e0",
                level=final_tier.max_level,
                promotion=final_tier.promotion,
                eidolon_level=0,
                selected_trace_ids=trace_ids,
            ),
        ),
        (
            "default_e6",
            make(
                "default_e6",
                level=1,
                promotion=0,
                eidolon_level=6,
                selected_trace_ids=(),
            ),
        ),
        (
            "trace_max_e6",
            make(
                "trace_max_e6",
                level=final_tier.max_level,
                promotion=final_tier.promotion,
                eidolon_level=6,
                selected_trace_ids=trace_ids,
            ),
        ),
    )


def _skill_level_oracle(
    rules: RuleBook,
    card: CharacterDataCardIR,
    auxiliary: tuple[str, ...],
    nodes: tuple[CharacterTraceNodeIR, ...],
    build: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
) -> list[dict[str, Any]]:
    selected_by_trace = {
        node.trace_id: node for node in nodes if node.default_unlocked
    }
    nodes_by_id = {node.trace_node_id: node for node in nodes}
    for node_id in build.unlocked_trace_node_ids:
        node = nodes_by_id.get(node_id)
        if node is not None:
            selected_by_trace[node.trace_id] = node
    selected_nodes = tuple(selected_by_trace.values())
    child_resolutions = {
        skill_id: [
            (child, resolution)
            for child in assembly.owned_combatant_results
            for resolution in child.effective_skill_levels
            if resolution.skill_id == skill_id
        ]
        for skill_id in auxiliary
    }
    try:
        eidolon_slots = rules.character_eidolon_slots_for_level(
            card.card_id,
            build.eidolon_level,
        )
    except ValueError:
        eidolon_slots = ()
    rows = []
    for skill_id in auxiliary:
        candidates = rules.servant_definitions_for_owned_skill(
            card.entity_ref,
            skill_id,
        )
        definition = candidates[0] if len(candidates) == 1 else None
        selected_skill_nodes = tuple(
            node for node in selected_nodes if skill_id in node.level_up_skill_ids
        )
        base_source_ref = ""
        base_source_kind = ""
        expected_base_level: int | None = None
        if len(selected_skill_nodes) == 1:
            selected_node = selected_skill_nodes[0]
            slots = tuple(
                slot
                for slot_id in selected_node.linked_mechanism_slot_ids
                if (slot := rules.character_mechanism_slot(slot_id)) is not None
                and slot.mechanism_kind == "trace_skill_level"
                and slot.coverage_status == "executable"
            )
            if len(slots) == 1:
                expected_base_level = selected_node.level
                base_source_kind = "trace_base"
                base_source_ref = slots[0].mechanism_slot_id
        elif definition is not None:
            skill_index_map = definition.action_set.get("skill_index_map")
            entries = tuple(
                entry
                for entry in (
                    skill_index_map.values()
                    if isinstance(skill_index_map, Mapping)
                    else ()
                )
                if isinstance(entry, Mapping) and entry.get("skill_id") == skill_id
            )
            if len(entries) == 1:
                raw_level = entries[0].get("default_level")
                if isinstance(raw_level, int) and not isinstance(raw_level, bool):
                    expected_base_level = raw_level
                    base_source_kind = "fixed_action"
                    base_source_ref = f"servant_skill:{skill_id}:{raw_level}"
        bonus_sources: list[tuple[str, int]] = []
        for eidolon in eidolon_slots:
            for slot_id in eidolon.linked_mechanism_slot_ids:
                slot = rules.character_mechanism_slot(slot_id)
                if slot is None or slot.mechanism_kind != "eidolon_skill_level":
                    continue
                bonuses = slot.semantics.get("skill_add_level_list")
                if not isinstance(bonuses, Mapping) or skill_id not in bonuses:
                    continue
                raw_bonus = bonuses[skill_id]
                bonus = (
                    raw_bonus.get("Value")
                    if isinstance(raw_bonus, Mapping)
                    else raw_bonus
                )
                if isinstance(bonus, int) and not isinstance(bonus, bool) and bonus > 0:
                    bonus_sources.append((slot.mechanism_slot_id, bonus))
        expected_bonus = sum(value for _slot_id, value in bonus_sources)
        expected_effective = (
            expected_base_level + expected_bonus
            if expected_base_level is not None
            else None
        )
        actual_matches = child_resolutions[skill_id]
        actual = actual_matches[0][1] if len(actual_matches) == 1 else None
        actual_source_rows = (
            [
                {
                    "source_kind": source.source_kind,
                    "level_value": source.level_value,
                    "definition_kind": source.source_ref.definition_kind,
                    "definition_identity": source.source_ref.definition_identity,
                }
                for source in actual.sources
            ]
            if actual is not None
            else []
        )
        expected_source_rows = [
            {
                "source_kind": base_source_kind,
                "level_value": expected_base_level,
                "definition_kind": (
                    "character_mechanism_slot"
                    if base_source_kind == "trace_base"
                    else "character_action_definition"
                ),
                "definition_identity": base_source_ref,
            },
            *[
                {
                    "source_kind": "eidolon_bonus",
                    "level_value": bonus,
                    "definition_kind": "character_mechanism_slot",
                    "definition_identity": slot_id,
                }
                for slot_id, bonus in bonus_sources
            ],
        ]
        if expected_base_level is None:
            expected_source_rows = []
        rows.append(
            {
                "skill_id": skill_id,
                "candidate_definition_count": len(candidates),
                "expected_servant_definition_id": (
                    definition.servant_definition_id
                    if definition is not None
                    else ""
                ),
                "actual_resolution_count": len(actual_matches),
                "actual_servant_definition_id": (
                    actual_matches[0][0].servant_definition_id
                    if len(actual_matches) == 1
                    else ""
                ),
                "expected_base_level": expected_base_level,
                "expected_eidolon_bonus": expected_bonus,
                "expected_effective_level": expected_effective,
                "actual_base_level": actual.base_level if actual is not None else None,
                "actual_eidolon_bonus": (
                    actual.eidolon_level_bonus if actual is not None else None
                ),
                "actual_effective_level": (
                    actual.effective_level if actual is not None else None
                ),
                "expected_sources": expected_source_rows,
                "actual_sources": actual_source_rows,
                "level_equal": actual is not None
                and actual.base_level == expected_base_level
                and actual.eidolon_level_bonus == expected_bonus
                and actual.effective_level == expected_effective,
                "source_multiplicity_exact": actual_source_rows
                == expected_source_rows,
            }
        )
    return rows


def _runtime_fail_closed_matrix(
    rules: RuleBook,
    process_only_task_matrix: dict[str, Any],
) -> dict[str, Any]:
    state = BattleState(
        units={
            "validation:attacker": UnitState(
                unit_id="validation:attacker",
                side="ally",
                template_id="validation:attacker_template",
            ),
            "validation:target": UnitState(
                unit_id="validation:target",
                side="enemy",
                template_id="validation:target_template",
                toughness=100.0,
                max_toughness=100.0,
                flags={"weaknesses": ()},
            ),
        }
    )
    toughness_packet = ToughnessPacket(
        attacker_id="validation:attacker",
        target_id="validation:target",
        toughness_emission_id="validation:blocked_toughness_emission",
        source_task_id="validation:blocked_toughness_task",
        hit_profile_id="validation:blocked_toughness_hit_profile",
        element_type="validation:missing_weakness",
        amount=1.0,
        target_group="primary",
        coverage_status="blocked",
        source_trace={"source_path": "validation:blocked_toughness_source"},
    )
    toughness_result = ToughnessSystem(rules).apply_packet(state, toughness_packet)
    toughness_reason = toughness_result.errors[0] if toughness_result.errors else ""
    toughness_ok = bool(
        not toughness_result.ok
        and toughness_reason == "toughness_emission_not_executable:blocked"
        and not toughness_result.mutations
        and toughness_result.records
        and toughness_result.records[0].get("record_type")
        == "toughness_emission_blocked"
        and state.units["validation:target"].toughness == 100.0
    )

    source_shape_cases = {
        "valid_look_at": _process_only_ability_task_source_blocked_reason(
            {
                "$type": "RPG.GameCore.LookAt",
                "TargetType": "AbilityTargetEntity",
            },
            "LookAt",
        ),
        "unknown_field": _process_only_ability_task_source_blocked_reason(
            {
                "$type": "RPG.GameCore.LookAt",
                "TargetType": "AbilityTargetEntity",
                "CombatMutation": {},
            },
            "LookAt",
        ),
        "death_settlement_control": (
            _process_only_ability_task_source_blocked_reason(
                {
                    "$type": "RPG.GameCore.DamagePerformFinish",
                    "SkipDeathSettlement": True,
                },
                "DamagePerformFinish",
            )
        ),
        "attack_settlement_control": (
            _process_only_ability_task_source_blocked_reason(
                {
                    "$type": "RPG.GameCore.SkillPerformFinish",
                    "SkipAttackSettlement": True,
                },
                "SkillPerformFinish",
            )
        ),
        "invalid_wait_expression": (
            _process_only_ability_task_source_blocked_reason(
                {
                    "$type": "RPG.GameCore.WaitSecond",
                    "WaitTime": "not_a_numeric_expression",
                },
                "WaitSecond",
            )
        ),
    }
    source_shape_ok = bool(
        not source_shape_cases["valid_look_at"]
        and all(
            source_shape_cases[key]
            for key in (
                "unknown_field",
                "death_settlement_control",
                "attack_settlement_control",
                "invalid_wait_expression",
            )
        )
    )

    action_definition = next(
        (
            definition
            for definition in rules.ir.action_definitions
            if definition.coverage_status == "executable"
        ),
        None,
    )
    task_runtime_ok = False
    task_reason = "action_definition_missing"
    task_record: dict[str, Any] = {}
    if action_definition is not None:
        source = IRSource(
            source_path="validation:blocked_process_task",
            raw_type="DamagePerformFinish",
            raw_id="validation:blocked_process_task",
            evidence={"negative_case": True},
        )
        task = AbilityTaskIR(
            task_id="validation:blocked_process_task",
            phase_id="validation:blocked_process_phase",
            action_id=action_definition.action_id,
            level=action_definition.level,
            ability_name="validation:blocked_process_ability",
            callback_kind="OnStart",
            task_index=0,
            task_path="$.validation",
            branch="root",
            opcode="DamagePerformFinish",
            source=source,
            execution_mode="process_only",
            coverage_status="blocked",
            blocked_reason="validation_process_task_source_blocked",
        )
        command = ActionCommand(
            actor_id="validation:attacker",
            action_id=action_definition.action_id,
            action_level=action_definition.level,
            target_ids=("validation:target",),
        )
        after_state, mutations, events, rng_events, records = AbilityTaskSystem(
            rules,
            EffectRegistry(),
        )._execute_task(
            state,
            task,
            {task.task_id: task},
            command=command,
            action_definition=action_definition,
            primary_target="validation:target",
            target_resolution=TargetResolution(
                requested=("validation:target",),
                legal=("validation:target",),
                selected=("validation:target",),
            ),
        )
        task_record = records[0] if records else {}
        payload = task_record.get("payload")
        task_reason = (
            str(payload.get("blocked_reason") or "")
            if isinstance(payload, Mapping)
            else ""
        )
        task_runtime_ok = bool(
            after_state == state
            and not mutations
            and not events
            and not rng_events
            and isinstance(payload, Mapping)
            and payload.get("ok") is False
            and task_reason
            and task_record.get("record_type") == "ability_task"
        )
    task_ok = (
        task_runtime_ok
        and source_shape_ok
        and process_only_task_matrix["ok"] is True
    )
    return {
        "blocked_toughness_source_precedes_target_applicability": toughness_ok,
        "process_only_task_requires_explicit_source_contract": task_ok,
        "toughness_case": {
            "ok": toughness_ok,
            "target_weaknesses": [],
            "packet_coverage_status": toughness_packet.coverage_status,
            "observed_ok": toughness_result.ok,
            "blocked_reason": toughness_reason,
            "mutation_count": len(toughness_result.mutations),
            "record_types": [
                record.get("record_type") for record in toughness_result.records
            ],
        },
        "ability_task_case": {
            "ok": task_ok,
            "runtime_blocked_task_ok": task_runtime_ok,
            "source_shape_contract_ok": source_shape_ok,
            "catalog_contract_matrix_ok": process_only_task_matrix["ok"],
            "catalog_task_count": process_only_task_matrix["task_count"],
            "catalog_mismatch_count": process_only_task_matrix[
                "mismatch_count"
            ],
            "source_shape_cases": source_shape_cases,
            "task_execution_mode": "process_only",
            "task_coverage_status": "blocked",
            "blocked_reason": task_reason,
            "record_type": task_record.get("record_type"),
        },
    }


def _process_only_task_contract_matrix(rules: RuleBook) -> dict[str, Any]:
    opcode_counts: dict[str, Counter[str]] = {}
    reason_counts: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    task_count = 0
    for task in sorted(rules.ir.ability_tasks, key=lambda item: item.task_id):
        if task.execution_mode != "process_only":
            continue
        task_count += 1
        counts = opcode_counts.setdefault(task.opcode, Counter())
        counts["task_count"] += 1
        expected_admitted = (
            task.coverage_status == "audit_only" and not task.blocked_reason
        )
        runtime_reason = ability_task_runtime_blocked_reason(rules, task)
        runtime_admitted = not runtime_reason
        counts[
            "source_admitted_count" if expected_admitted else "source_blocked_count"
        ] += 1
        counts[
            "runtime_admitted_count" if runtime_admitted else "runtime_blocked_count"
        ] += 1
        if runtime_reason:
            reason_counts[runtime_reason] += 1

        effect = rules.effect(task.effect_id) if task.effect_id else None
        contract = (
            effect.payload.get("process_only_contract")
            if effect is not None
            and isinstance(effect.payload.get("process_only_contract"), Mapping)
            else None
        )
        contract_fields = (
            contract.get("source_fields") if contract is not None else None
        )
        contract_field_types = (
            contract.get("source_field_types") if contract is not None else None
        )
        contract_shape_valid = bool(
            contract is not None
            and contract.get("schema_version")
            == "ability_process_only_source_shape_v1"
            and contract.get("opcode") == task.opcode
            and isinstance(contract_fields, list)
            and "$type" in contract_fields
            and len(contract_fields) == len(set(contract_fields))
            and isinstance(contract_field_types, Mapping)
            and set(contract_field_types) == set(contract_fields)
        )
        contract_admitted = bool(
            contract_shape_valid
            and contract is not None
            and contract.get("source_shape_status") == "admitted"
            and not contract.get("blocked_reason")
        )
        expected_effect_coverage = "audit_only" if expected_admitted else "blocked"
        mismatch_reasons: list[str] = []
        if not contract_shape_valid:
            mismatch_reasons.append("process_only_source_contract_invalid")
        if contract_admitted != expected_admitted:
            mismatch_reasons.append("process_only_source_admission_mismatch")
        if runtime_admitted != expected_admitted:
            mismatch_reasons.append("process_only_runtime_admission_mismatch")
        if effect is None or effect.coverage_status != expected_effect_coverage:
            mismatch_reasons.append("process_only_effect_coverage_mismatch")
        if effect is not None and effect.source != task.source:
            mismatch_reasons.append("process_only_effect_source_mismatch")
        if mismatch_reasons:
            counts["mismatch_count"] += 1
            mismatches.append(
                {
                    "task_id": task.task_id,
                    "opcode": task.opcode,
                    "task_coverage_status": task.coverage_status,
                    "task_blocked_reason": task.blocked_reason,
                    "runtime_blocked_reason": runtime_reason,
                    "reasons": mismatch_reasons,
                }
            )

    rows = [
        {
            "opcode": opcode,
            **{
                key: counts.get(key, 0)
                for key in (
                    "task_count",
                    "source_admitted_count",
                    "source_blocked_count",
                    "runtime_admitted_count",
                    "runtime_blocked_count",
                    "mismatch_count",
                )
            },
        }
        for opcode, counts in sorted(opcode_counts.items())
    ]
    return {
        "ok": task_count > 0 and not mismatches,
        "task_count": task_count,
        "opcode_count": len(rows),
        "source_admitted_count": sum(
            row["source_admitted_count"] for row in rows
        ),
        "source_blocked_count": sum(row["source_blocked_count"] for row in rows),
        "runtime_admitted_count": sum(
            row["runtime_admitted_count"] for row in rows
        ),
        "runtime_blocked_count": sum(
            row["runtime_blocked_count"] for row in rows
        ),
        "mismatch_count": len(mismatches),
        "runtime_blocked_reason_counts": dict(sorted(reason_counts.items())),
        "rows": rows,
        "mismatches": mismatches,
    }


def _special_resource_runtime_matrix(
    rules: RuleBook,
    builds: tuple[CharacterBuildInput, ...],
    assemblies: tuple[CharacterBuildAssemblyResult, ...],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for build, assembly in zip(builds, assemblies, strict=True):
        if assembly.base_panel is None or not assembly.resource_bindings:
            continue
        card = rules.character_data_card(build.character_card_id)
        if card is None:
            continue
        unit = UnitSpec(
            unit_id="validation:special_resource_owner",
            side="ally",
            entity_ref=card.entity_ref,
            build_mode="assembled_character_build",
            level=build.level,
            eidolon_level=build.eidolon_level,
            panel=None,
            character_build=build,
            initial_condition=_initial_condition(assembly),
        )
        world_level = max(
            binding.initializer.world_level_threshold
            for binding in assembly.resource_bindings
        ) + 1
        scenario = ScenarioSpec(
            scenario_id=f"validation:special_resource:{build.build_id}",
            version=VALIDATION_VERSION,
            units=(unit,),
            route=(),
            battle_setup=BattleSetupSpec(world_level=world_level),
        )
        for binding in assembly.resource_bindings:
            missing_world_level_blocked = False
            missing_world_level_reason = ""
            try:
                initialize_special_resource(
                    rules,
                    replace(
                        scenario,
                        battle_setup=replace(
                            scenario.battle_setup,
                            world_level=None,
                        ),
                    ),
                    unit,
                    binding,
                )
            except ValueError as exc:
                missing_world_level_reason = str(exc)
                missing_world_level_blocked = (
                    "special-resource initializer requires battle_setup.world_level"
                    in missing_world_level_reason
                )
            initialized = initialize_special_resource(
                rules,
                scenario,
                unit,
                binding,
            )
            payload = initialized.record.get("payload")
            source_kind = (initialized.record.get("trace") or {}).get(
                "source_kind"
            )
            values_in_bounds = bool(
                initialized.maximum_value > 0
                and 0 <= initialized.current_value <= initialized.maximum_value
                and initialized.current_value != 0
            )
            row_ok = bool(
                values_in_bounds
                and missing_world_level_blocked
                and isinstance(payload, Mapping)
                and payload.get("resource_definition_id")
                == binding.resource_definition_id
                and payload.get("current_value") == initialized.current_value
                and payload.get("maximum_value") == initialized.maximum_value
                and source_kind == "canonical_ir_special_resource_initializer"
                and initialized.source_traces
            )
            rows.append(
                {
                    "resource_definition_id": binding.resource_definition_id,
                    "parent_battle_admission_status": (
                        assembly.battle_admission_status
                    ),
                    "parent_blocked_reasons": list(
                        _assembly_reason_codes(assembly)
                    ),
                    "world_level": world_level,
                    "current_value": initialized.current_value,
                    "maximum_value": initialized.maximum_value,
                    "values_in_bounds": values_in_bounds,
                    "settlement_record_type": initialized.record.get(
                        "record_type"
                    ),
                    "settlement_source_kind": source_kind,
                    "source_trace_count": len(initialized.source_traces),
                    "missing_world_level_blocked": missing_world_level_blocked,
                    "missing_world_level_reason": missing_world_level_reason,
                    "ok": row_ok,
                }
            )
    return {
        "ok": bool(rows) and all(row["ok"] for row in rows),
        "runtime_initializer_case_count": len(rows),
        "selection_policy": (
            "all_affected_builds_with_source_backed_special_resource_bindings"
        ),
        "parent_admission_not_bypassed": all(
            row["parent_battle_admission_status"] != "admitted" for row in rows
        ),
        "rows": rows,
    }


def _admission_matrix(
    rules: RuleBook,
    affected: tuple[
        tuple[CharacterDataCardIR, tuple[str, ...], tuple[CharacterTraceNodeIR, ...]],
        ...,
    ],
    builds: tuple[CharacterBuildInput, ...],
    assemblies: tuple[CharacterBuildAssemblyResult, ...],
) -> dict[str, Any]:
    required_negative_cases: list[dict[str, Any]] = []
    parent_child_atomic = False
    for assembly in assemblies:
        if assembly.assembly_status != "assembled" or not assembly.owned_combatant_results:
            continue
        child = assembly.owned_combatant_results[0]
        blocked_child = replace(
            child,
            assembly_status="blocked",
            battle_admission_status="blocked",
            blocked_reasons=("validation_child_blocked",),
        )
        try:
            replace(
                assembly,
                battle_admission_status="admitted",
                owned_combatant_results=(
                    blocked_child,
                    *assembly.owned_combatant_results[1:],
                ),
            )
        except ValueError:
            parent_child_atomic = True
        break
    required_negative_cases.append(
        _negative_case(
            "child_blocked_parent_admitted_tamper",
            parent_child_atomic,
            ("admitted_parent_rejected_by_result_model",),
        )
    )

    if affected:
        first_card, first_auxiliary, first_nodes = affected[0]
        first_build = builds[0]
        original_owner_index = getattr(rules, "_servant_definitions_by_owner")
        original_skill_index = getattr(rules, "_servant_definitions_by_owned_skill")
        owner_index = dict(original_owner_index)
        owner_index.pop(first_card.entity_ref, None)
        skill_index = dict(original_skill_index)
        for skill_id in first_auxiliary:
            skill_index.pop((first_card.entity_ref, skill_id), None)
        missing_owner_rules = _clone_rulebook_indexes(
            rules,
            _servant_definitions_by_owner=owner_index,
            _servant_definitions_by_owned_skill=skill_index,
        )
        missing_owner_result = assemble_character_build(
            missing_owner_rules,
            first_build,
        )
        missing_owner_reasons = _assembly_reason_codes(missing_owner_result)
        required_negative_cases.append(
            _negative_case(
                "auxiliary_skill_without_owner_relation",
                missing_owner_result.battle_admission_status == "blocked"
                and not missing_owner_result.owned_combatant_results
                and "owned_combatant_skill_owner_missing" in missing_owner_reasons
                and first_build.input_fingerprint == builds[0].input_fingerprint
                and first_card.entity_ref in original_owner_index,
                missing_owner_reasons,
            )
        )

        first_skill = first_auxiliary[0]
        first_candidates = rules.servant_definitions_for_owned_skill(
            first_card.entity_ref,
            first_skill,
        )
        other_definition = next(
            (
                definition
                for definition in rules.servant_definitions()
                if not first_candidates
                or definition.servant_definition_id
                != first_candidates[0].servant_definition_id
            ),
            None,
        )
        ambiguous_skill_index = dict(original_skill_index)
        if first_candidates:
            ambiguous_skill_index[(first_card.entity_ref, first_skill)] = (
                first_candidates[0],
                other_definition or first_candidates[0],
            )
        ambiguous_rules = _clone_rulebook_indexes(
            rules,
            _servant_definitions_by_owned_skill=ambiguous_skill_index,
        )
        ambiguous_result = assemble_character_build(ambiguous_rules, first_build)
        ambiguous_reasons = _assembly_reason_codes(ambiguous_result)
        required_negative_cases.append(
            _negative_case(
                "auxiliary_skill_ambiguous_servant",
                bool(first_candidates)
                and ambiguous_result.battle_admission_status == "blocked"
                and "owned_combatant_skill_owner_ambiguous" in ambiguous_reasons
                and len(
                    rules.servant_definitions_for_owned_skill(
                        first_card.entity_ref,
                        first_skill,
                    )
                )
                == 1,
                ambiguous_reasons,
            )
        )

        default_node = next(
            (
                node
                for node in first_nodes
                if node.default_unlocked
                and set(node.level_up_skill_ids).intersection(first_auxiliary)
            ),
            None,
        )
        explicit_default_result = None
        if default_node is not None:
            explicit_default_build = _negative_build_with_traces(
                first_build,
                "explicit_default",
                (default_node.trace_node_id,),
            )
            explicit_default_result = assemble_character_build(
                rules,
                explicit_default_build,
            )
        explicit_default_reasons = _assembly_reason_codes(explicit_default_result)
        required_negative_cases.append(
            _negative_case(
                "default_trace_node_explicitly_reselected",
                explicit_default_result is not None
                and explicit_default_result.assembly_status == "blocked"
                and "default_trace_node_reselected" in explicit_default_reasons,
                explicit_default_reasons,
            )
        )

        upgrade_node = (
            max(
                (
                    node
                    for node in first_nodes
                    if default_node is not None
                    and node.trace_id == default_node.trace_id
                    and node.level > default_node.level
                ),
                key=lambda item: (item.level, item.trace_node_id),
                default=None,
            )
            if default_node is not None
            else None
        )
        conflicting_trace_result = None
        if default_node is not None and upgrade_node is not None:
            profile = rules.avatar_profile_by_profile_id(first_card.profile_id)
            final_tier = (
                max(profile.promotion_tiers, key=lambda item: item.promotion)
                if profile is not None and profile.promotion_tiers
                else None
            )
            conflicting_build = _negative_build_with_traces(
                first_build,
                "default_and_upgrade",
                (default_node.trace_node_id, upgrade_node.trace_node_id),
                level=final_tier.max_level if final_tier is not None else first_build.level,
                promotion=(
                    final_tier.promotion
                    if final_tier is not None
                    else first_build.promotion
                ),
            )
            conflicting_trace_result = assemble_character_build(
                rules,
                conflicting_build,
            )
        conflicting_trace_reasons = _assembly_reason_codes(conflicting_trace_result)
        required_negative_cases.append(
            _negative_case(
                "default_and_trace_upgrade_double_selection",
                conflicting_trace_result is not None
                and conflicting_trace_result.assembly_status == "blocked"
                and "conflicting_trace_levels_selected" in conflicting_trace_reasons,
                conflicting_trace_reasons,
            )
        )

    representative = next(
        (
            (card, build, assembly, child, definition, action)
            for (card, _auxiliary, _nodes), build, assembly in zip(
                affected,
                builds,
                assemblies,
                strict=True,
            )
            for child in assembly.owned_combatant_results
            for definition in (rules.servant_definition(child.servant_definition_id),)
            if definition is not None
            for action in child.action_bindings
        ),
        None,
    )
    admitted_representative = next(
        (
            (build, assembly, child)
            for build, assembly in zip(builds, assemblies, strict=True)
            if assembly.battle_admission_status == "admitted"
            for child in assembly.owned_combatant_results
            if child.effective_skill_levels
        ),
        None,
    )
    multi_required_action_candidates = tuple(
        (
            build,
            assembly,
            child,
            definition,
            required_action_skill_ids,
        )
        for build, assembly in zip(builds, assemblies, strict=True)
        if assembly.battle_admission_status == "admitted"
        for child in assembly.owned_combatant_results
        if child.battle_admission_status == "admitted"
        for definition in (rules.servant_definition(child.servant_definition_id),)
        if definition is not None
        for raw_required_action_skill_ids in (
            definition.action_set.get("required_action_skill_ids"),
        )
        if isinstance(raw_required_action_skill_ids, (list, tuple))
        and all(
            isinstance(item, str) and item
            for item in raw_required_action_skill_ids
        )
        for required_action_skill_ids in (
            tuple(raw_required_action_skill_ids),
        )
        if len(required_action_skill_ids) >= 2
        and len(set(required_action_skill_ids)) == len(required_action_skill_ids)
        and set(required_action_skill_ids)
        == {binding.skill_id for binding in child.action_bindings}
        and all(
            _owned_required_action_is_fully_executable(
                rules,
                definition.servant_ref,
                binding,
            )
            for binding in child.action_bindings
        )
    )
    multi_required_action_representative = (
        min(
            multi_required_action_candidates,
            key=lambda item: (
                item[3].servant_definition_id,
                item[0].build_id,
            ),
        )
        if multi_required_action_candidates
        else None
    )
    incomplete_action_case_ok = False
    incomplete_action_reasons: tuple[str, ...] = (
        "admitted_owned_combatant_with_multiple_required_actions_not_found",
    )
    incomplete_action_evidence: dict[str, Any] = {
        "selection_policy": (
            "admitted parent and child; at least two unique required action skill ids; "
            "required ids exactly equal assembled action bindings; every binding has one "
            "executable definition, turn-action admission, and ability binding"
        ),
        "structural_candidate_count": len(multi_required_action_candidates),
        "selected_required_action_count": 0,
        "tamper_kind": "remove_one_action_ability_binding",
        "removed_ability_binding_count": 0,
        "retained_action_count": 0,
        "retained_actions_fully_executable": False,
        "child_battle_admission_blocked": False,
        "parent_battle_admission_blocked": False,
        "formal_battle_admission_rejected": False,
        "no_battle_admittable_result": False,
    }
    if multi_required_action_representative is not None:
        (
            multi_build,
            multi_assembly,
            multi_child,
            multi_definition,
            required_action_skill_ids,
        ) = multi_required_action_representative
        ordered_actions = tuple(
            sorted(
                multi_child.action_bindings,
                key=lambda item: (
                    item.action_id,
                    item.effective_level,
                    item.ability_binding_id,
                ),
            )
        )
        broken_action = ordered_actions[0]
        retained_actions = ordered_actions[1:]
        broken_action_key = (
            broken_action.action_id,
            broken_action.effective_level,
        )
        original_ability_index = dict(
            getattr(rules, "_action_ability_bindings")
        )
        original_ability_by_id = dict(
            getattr(rules, "_action_ability_bindings_by_id")
        )
        removed_ability_binding = original_ability_index.get(
            broken_action_key
        )
        tampered_ability_index = dict(original_ability_index)
        tampered_ability_by_id = dict(original_ability_by_id)
        if (
            removed_ability_binding is not None
            and removed_ability_binding.binding_id
            == broken_action.ability_binding_id
            and original_ability_by_id.get(
                removed_ability_binding.binding_id
            )
            == removed_ability_binding
        ):
            tampered_ability_index.pop(broken_action_key)
            tampered_ability_by_id.pop(removed_ability_binding.binding_id, None)
        exactly_one_ability_binding_removed = (
            removed_ability_binding is not None
            and original_ability_by_id.get(
                broken_action.ability_binding_id
            )
            == removed_ability_binding
            and set(tampered_ability_index)
            == set(original_ability_index).difference({broken_action_key})
            and set(tampered_ability_by_id)
            == set(original_ability_by_id).difference(
                {broken_action.ability_binding_id}
            )
        )
        incomplete_action_rules = _clone_rulebook_indexes(
            rules,
            _action_ability_bindings=tampered_ability_index,
            _action_ability_bindings_by_id=tampered_ability_by_id,
        )
        incomplete_action_result = assemble_character_build(
            incomplete_action_rules,
            multi_build,
        )
        matching_children = tuple(
            child
            for child in incomplete_action_result.owned_combatant_results
            if child.servant_definition_id
            == multi_definition.servant_definition_id
        )
        incomplete_child = (
            matching_children[0] if len(matching_children) == 1 else None
        )
        retained_actions_rulebook_executable = bool(retained_actions) and all(
            _owned_required_action_is_fully_executable(
                incomplete_action_rules,
                multi_definition.servant_ref,
                action,
            )
            for action in retained_actions
        )
        incomplete_child_actions = (
            {
                (action.action_id, action.effective_level): action
                for action in incomplete_child.action_bindings
            }
            if incomplete_child is not None
            else {}
        )
        retained_actions_preserved = bool(retained_actions) and all(
            incomplete_child_actions.get(
                (action.action_id, action.effective_level)
            )
            == action
            for action in retained_actions
        )
        broken_action_absent = (
            incomplete_child is not None
            and broken_action_key not in incomplete_child_actions
            and len(incomplete_child.action_bindings)
            == len(ordered_actions) - 1
        )
        baseline_admission_errors = validate_character_build_admission(
            rules,
            multi_build,
            multi_assembly,
        )
        formal_admission_errors = validate_character_build_admission(
            incomplete_action_rules,
            multi_build,
            incomplete_action_result,
        )
        incomplete_action_reasons = tuple(
            dict.fromkeys(
                (
                    *_assembly_reason_codes(incomplete_action_result),
                    *formal_admission_errors,
                )
            )
        )
        expected_binding_reason = (
            "owned_combatant_action_ability_binding_not_executable:"
            f"{broken_action.skill_id}:{broken_action.effective_level}"
        )
        expected_incomplete_reason = (
            "owned_combatant_required_action_bindings_incomplete:"
            f"{broken_action.skill_id}"
        )
        child_blocked = (
            incomplete_child is not None
            and incomplete_child.assembly_status == "blocked"
            and incomplete_child.battle_admission_status == "blocked"
        )
        parent_blocked = (
            incomplete_action_result.battle_admission_status == "blocked"
        )
        formal_admission_rejected = (
            "character_build_not_admitted_for_battle"
            in formal_admission_errors
        )
        no_battle_admittable_result = (
            child_blocked
            and parent_blocked
            and formal_admission_rejected
        )
        incomplete_action_case_ok = (
            not baseline_admission_errors
            and len(required_action_skill_ids) >= 2
            and len(ordered_actions) == len(required_action_skill_ids)
            and exactly_one_ability_binding_removed
            and retained_actions_rulebook_executable
            and retained_actions_preserved
            and broken_action_absent
            and expected_binding_reason in incomplete_action_reasons
            and expected_incomplete_reason in incomplete_action_reasons
            and no_battle_admittable_result
        )
        incomplete_action_evidence.update(
            {
                "selected_build_id": multi_build.build_id,
                "selected_servant_definition_id": (
                    multi_definition.servant_definition_id
                ),
                "selected_required_action_count": len(
                    required_action_skill_ids
                ),
                "selected_required_action_skill_ids": list(
                    required_action_skill_ids
                ),
                "broken_action_id": broken_action.action_id,
                "broken_action_level": broken_action.effective_level,
                "broken_ability_binding_id": (
                    broken_action.ability_binding_id
                ),
                "removed_ability_binding_count": (
                    1 if exactly_one_ability_binding_removed else 0
                ),
                "retained_action_count": len(retained_actions),
                "retained_action_ids": [
                    action.action_id for action in retained_actions
                ],
                "retained_actions_rulebook_executable": (
                    retained_actions_rulebook_executable
                ),
                "retained_actions_preserved_in_child_result": (
                    retained_actions_preserved
                ),
                "retained_actions_fully_executable": (
                    retained_actions_rulebook_executable
                    and retained_actions_preserved
                ),
                "broken_action_absent_from_child_result": (
                    broken_action_absent
                ),
                "baseline_formal_admission_passed": (
                    not baseline_admission_errors
                ),
                "child_battle_admission_blocked": child_blocked,
                "parent_battle_admission_blocked": parent_blocked,
                "formal_battle_admission_rejected": (
                    formal_admission_rejected
                ),
                "formal_admission_reason_codes": list(
                    formal_admission_errors
                ),
                "no_battle_admittable_result": (
                    no_battle_admittable_result
                ),
            }
        )
    incomplete_action_case = _negative_case(
        "servant_required_action_slot_removed_while_other_action_remains",
        incomplete_action_case_ok,
        incomplete_action_reasons,
    )
    incomplete_action_case["evidence"] = incomplete_action_evidence
    required_negative_cases.append(incomplete_action_case)

    if representative is not None:
        rep_card, rep_build, _rep_assembly, rep_child, rep_definition, rep_action = representative
        action_key = (rep_action.action_id, rep_action.effective_level)
        original_action_candidates = getattr(rules, "_action_definition_candidates")
        missing_action_index = dict(original_action_candidates)
        missing_action_index.pop(action_key, None)
        missing_action_rules = _clone_rulebook_indexes(
            rules,
            _action_definition_candidates=missing_action_index,
        )
        missing_action_result = assemble_character_build(
            missing_action_rules,
            rep_build,
        )
        missing_action_reasons = _assembly_reason_codes(missing_action_result)
        required_negative_cases.append(
            _negative_case(
                "servant_action_definition_missing",
                missing_action_result.battle_admission_status == "blocked"
                and any(
                    reason.startswith("owned_combatant_action_definition_not_unique")
                    for reason in missing_action_reasons
                )
                and len(rules.action_definition_candidates(*action_key)) == 1,
                missing_action_reasons,
            )
        )

        duplicate_relation_rejected = False
        if rep_definition.owner_relations:
            forged_definition = replace(
                rep_definition,
                owner_relations=(
                    *rep_definition.owner_relations,
                    rep_definition.owner_relations[0],
                ),
            )
            try:
                RuleBook(
                    CanonicalIR(
                        version="validation:duplicate_owner_relation",
                        servant_definitions=(forged_definition,),
                    )
                )
            except ValueError as exc:
                duplicate_relation_rejected = "duplicate servant owner relation" in str(
                    exc
                )
        required_negative_cases.append(
            _negative_case(
                "duplicate_servant_owner_relation_rejected",
                duplicate_relation_rejected,
                (
                    "duplicate_servant_owner_relation_rejected"
                    if duplicate_relation_rejected
                    else "duplicate_servant_owner_relation_not_rejected",
                ),
            )
        )

        conflict_definition = next(
            (
                definition
                for definition in rules.ir.action_definitions
                if definition.definition_id != rep_action.action_definition_id
            ),
            None,
        )
        conflict_action_index = dict(original_action_candidates)
        original_candidates = original_action_candidates.get(action_key, ())
        conflict_action_index[action_key] = (
            *original_candidates,
            conflict_definition or original_candidates[0],
        )
        conflict_action_rules = _clone_rulebook_indexes(
            rules,
            _action_definition_candidates=conflict_action_index,
        )
        conflict_action_result = assemble_character_build(
            conflict_action_rules,
            rep_build,
        )
        conflict_action_reasons = _assembly_reason_codes(conflict_action_result)
        required_negative_cases.append(
            _negative_case(
                "servant_action_definition_conflict",
                conflict_action_result.battle_admission_status == "blocked"
                and any(
                    reason.startswith("owned_combatant_action_definition_not_unique")
                    for reason in conflict_action_reasons
                ),
                conflict_action_reasons,
            )
        )

        ability_index = dict(getattr(rules, "_action_ability_bindings"))
        ability_index.pop(action_key, None)
        missing_ability_rules = _clone_rulebook_indexes(
            rules,
            _action_ability_bindings=ability_index,
        )
        missing_ability_result = assemble_character_build(
            missing_ability_rules,
            rep_build,
        )
        missing_ability_reasons = _assembly_reason_codes(missing_ability_result)
        required_negative_cases.append(
            _negative_case(
                "servant_ability_binding_missing",
                missing_ability_result.battle_admission_status == "blocked"
                and any(
                    reason.startswith(
                        "owned_combatant_action_ability_binding_not_executable"
                    )
                    for reason in missing_ability_reasons
                )
                and rules.action_ability_binding(*action_key) is not None,
                missing_ability_reasons,
            )
        )

        malformed_stat_definition = replace(
            rep_definition,
            stat_source={
                "admission_status": "blocked",
                "coverage_status": "blocked",
                "blocked_reason": "validation_stat_source_missing",
                "components": {},
                "owner_sync_fields": {},
                "source_trace": [],
            },
        )
        stat_rules = _rules_with_servant_definition(
            rules,
            malformed_stat_definition,
        )
        stat_result = assemble_character_build(stat_rules, rep_build)
        stat_reasons = _assembly_reason_codes(stat_result)
        required_negative_cases.append(
            _negative_case(
                "servant_stat_source_missing",
                stat_result.battle_admission_status == "blocked"
                and "owned_combatant_stat_component_missing:max_hp" in stat_reasons
                and rules.servant_definition(rep_definition.servant_definition_id)
                is rep_definition,
                stat_reasons,
            )
        )

        malformed_lifecycle_definition = replace(
            rep_definition,
            lifecycle_source={
                "admission_status": "blocked",
                "coverage_status": "blocked",
                "blocked_reason": "validation_lifecycle_source_missing",
                "source_trace": [],
            },
        )
        lifecycle_rules = _rules_with_servant_definition(
            rules,
            malformed_lifecycle_definition,
        )
        lifecycle_result = assemble_character_build(lifecycle_rules, rep_build)
        lifecycle_reasons = _assembly_reason_codes(lifecycle_result)
        required_negative_cases.append(
            _negative_case(
                "servant_lifecycle_source_missing",
                lifecycle_result.battle_admission_status == "blocked"
                and "validation_lifecycle_source_missing" in lifecycle_reasons
                and "owned_combatant_lifecycle_source_missing" in lifecycle_reasons,
                lifecycle_reasons,
            )
        )

        missing_spawn_definition = replace(rep_definition, spawn_sources=())
        spawn_rules = _rules_with_servant_definition(rules, missing_spawn_definition)
        spawn_result = assemble_character_build(spawn_rules, rep_build)
        spawn_reasons = _assembly_reason_codes(spawn_result)
        required_negative_cases.append(
            _negative_case(
                "servant_spawn_source_missing",
                spawn_result.battle_admission_status == "blocked"
                and "owned_combatant_spawn_source_missing" in spawn_reasons,
                spawn_reasons,
            )
        )

        wrong_owner = next(
            (
                (card, build)
                for (card, _skills, _nodes), build in zip(
                    affected,
                    builds,
                    strict=True,
                )
                if card.entity_ref != rep_card.entity_ref
            ),
            None,
        )
        wrong_owner_result = None
        if wrong_owner is not None:
            wrong_card, wrong_build = wrong_owner
            wrong_owner_index = dict(getattr(rules, "_servant_definitions_by_owner"))
            wrong_owner_index[wrong_card.entity_ref] = (
                *wrong_owner_index.get(wrong_card.entity_ref, ()),
                rep_definition,
            )
            wrong_owner_rules = _clone_rulebook_indexes(
                rules,
                _servant_definitions_by_owner=wrong_owner_index,
            )
            wrong_owner_result = assemble_character_build(
                wrong_owner_rules,
                wrong_build,
            )
        wrong_owner_reasons = _assembly_reason_codes(wrong_owner_result)
        required_negative_cases.append(
            _negative_case(
                "servant_definition_wrong_owner",
                wrong_owner_result is not None
                and wrong_owner_result.battle_admission_status == "blocked"
                and "owned_combatant_owner_relation_missing_or_ambiguous"
                in wrong_owner_reasons,
                wrong_owner_reasons,
            )
        )
    else:
        for case_id in (
            "servant_action_definition_missing",
            "servant_required_action_slot_removed_while_other_action_remains",
            "duplicate_servant_owner_relation_rejected",
            "servant_action_definition_conflict",
            "servant_ability_binding_missing",
            "servant_stat_source_missing",
            "servant_lifecycle_source_missing",
            "servant_spawn_source_missing",
            "servant_definition_wrong_owner",
        ):
            required_negative_cases.append(
                _negative_case(case_id, False, ("structural_representative_missing",))
            )

    if admitted_representative is not None:
        admitted_build, admitted_assembly, admitted_child = admitted_representative
        child_resolution = admitted_child.effective_skill_levels[0]
        tampered_parent = replace(
            admitted_assembly,
            effective_skill_levels=(
                *admitted_assembly.effective_skill_levels,
                child_resolution,
            ),
        )
        double_application_errors = validate_character_build_admission(
            rules,
            admitted_build,
            tampered_parent,
        )
        required_negative_cases.append(
            _negative_case(
                "auxiliary_skill_owner_and_servant_double_application",
                any(
                    reason.startswith("owned_combatant_skill_double_applied")
                    for reason in double_application_errors
                )
                and "assembly_result_does_not_match_canonical_rulebook_rebuild"
                in double_application_errors,
                double_application_errors,
            )
        )
        immutability_negative = _immutability_negative(
            admitted_build,
            admitted_assembly,
            admitted_child,
        )
    else:
        required_negative_cases.append(
            _negative_case(
                "auxiliary_skill_owner_and_servant_double_application",
                False,
                ("admitted_owned_combatant_build_missing",),
            )
        )
        immutability_negative = {
            "ok": False,
            "blocked_reason": "admitted_owned_combatant_build_missing",
        }
    required_negative_cases.append(
        _negative_case(
            "post_creation_container_mutation_isolated",
            immutability_negative["ok"],
            tuple(immutability_negative.get("failed_checks", ())),
        )
    )

    special_profiles = tuple(
        profile
        for profile in rules.ir.avatar_profiles
        if profile.resource_mode == "special_resource"
    )
    special_ok = bool(special_profiles) and all(
        profile.coverage_status == "executable"
        and profile.max_energy is None
        and profile.special_resource_definition is not None
        and profile.special_resource_definition.coverage_status == "executable"
        and profile.special_resource_definition.initial_current_mode
        == "ability_battle_entry_initializer"
        and profile.special_resource_definition.maximum_initialization_mode
        == "ability_initializer"
        and profile.special_resource_definition.initializer is not None
        and profile.special_resource_definition.initializer.coverage_status
        == "executable"
        and profile.special_resource_definition.initializer.sources
        and profile.special_resource_definition.initializer.initial_current_binding_value
        and profile.special_resource_definition.supporting_sources
        for profile in special_profiles
    )
    special_missing_ok = False
    special_missing_reasons: tuple[str, ...] = ()
    special_profile = special_profiles[0] if special_profiles else None
    special_card = next(
        (
            card
            for card in rules.ir.character_data_cards
            if special_profile is not None and card.profile_id == special_profile.avatar_profile_id
        ),
        None,
    )
    if special_profile is not None and special_card is not None:
        malformed_profile = replace(
            special_profile,
            special_resource_definition=None,
        )
        special_rules = _rules_with_avatar_profile(rules, malformed_profile)
        special_result = assemble_character_build(
            special_rules,
            _empty_build(special_card),
        )
        special_missing_reasons = _assembly_reason_codes(special_result)
        special_missing_ok = (
            special_result.assembly_status == "blocked"
            and "avatar_special_resource_definition_missing"
            in special_missing_reasons
            and rules.avatar_profile_by_profile_id(
                special_profile.avatar_profile_id
            )
            is special_profile
        )
    required_negative_cases.append(
        _negative_case(
            "special_resource_definition_missing",
            special_missing_ok,
            special_missing_reasons,
        )
    )
    arbitrary_initial_value_rejected = False
    if special_profile is not None and special_profile.special_resource_definition is not None:
        try:
            CharacterInitialResourceValue.from_json(
                {
                    "resource_definition_id": (
                        special_profile.special_resource_definition.resource_definition_id
                    ),
                    "source_kind": "ability_battle_entry_initializer",
                    "current_value": "0",
                }
            )
        except (TypeError, ValueError):
            arbitrary_initial_value_rejected = True
    required_negative_cases.append(
        _negative_case(
            "special_resource_arbitrary_current_value_rejected",
            arbitrary_initial_value_rejected,
            (
                "closed_initial_resource_input_rejected_current_value"
                if arbitrary_initial_value_rejected
                else "arbitrary_current_value_was_accepted",
            ),
        )
    )
    non_owned_build = next(
        (
            (build, assembly)
            for card in sorted(rules.ir.character_data_cards, key=lambda item: item.card_id)
            if not rules.servant_definitions_for_owner(card.entity_ref)
            for build in (_empty_build(card),)
            for assembly in (assemble_character_build(rules, build),)
            if assembly.battle_admission_status == "admitted"
        ),
        None,
    )
    return {
        "build_admissions": [
            {
                "build_id": build.build_id,
                "battle_admission_status": assembly.battle_admission_status,
                "admission_errors": list(
                    validate_character_build_admission(rules, build, assembly)
                ),
                "child_statuses": {
                    child.servant_definition_id: child.battle_admission_status
                    for child in assembly.owned_combatant_results
                },
            }
            for build, assembly in zip(builds, assemblies, strict=True)
        ],
        "parent_child_atomic_negative": parent_child_atomic,
        "required_negative_cases": required_negative_cases,
        "required_negative_cases_all_pass": bool(required_negative_cases)
        and all(case["ok"] for case in required_negative_cases),
        "immutability_negative": immutability_negative,
        "special_resource_checks": {
            "ok": special_ok,
            "profile_count": len(special_profiles),
            "definitions": [
                profile.special_resource_definition.to_json()
                for profile in special_profiles
                if profile.special_resource_definition is not None
            ],
        },
        "non_owned_character_regression": non_owned_build is not None,
    }


def _negative_case(
    case_id: str,
    ok: bool,
    reason_codes: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "expected_status": "blocked_or_rejected",
        "observed_status": "blocked_or_rejected" if ok else "unexpected",
        "state_unchanged": True,
        "reason_codes": list(reason_codes),
        "ok": ok,
    }


def _assembly_reason_codes(
    result: CharacterBuildAssemblyResult | None,
) -> tuple[str, ...]:
    if result is None:
        return ()
    return tuple(
        dict.fromkeys(
            (
                *result.blocked_reasons,
                *(item.reason for item in result.unadmitted_mechanism_diagnostics),
                *(
                    reason
                    for child in result.owned_combatant_results
                    for reason in child.blocked_reasons
                ),
            )
        )
    )


def _owned_required_action_is_fully_executable(
    rules: RuleBook,
    servant_ref: str,
    action: OwnedCombatantActionBinding,
) -> bool:
    definition_candidates = rules.action_definition_candidates(
        action.action_id,
        action.effective_level,
    )
    admissions = rules.action_admissions_for(
        servant_ref,
        action.action_id,
        action.effective_level,
    )
    ability_binding = rules.action_ability_binding(
        action.action_id,
        action.effective_level,
    )
    return (
        len(definition_candidates) == 1
        and definition_candidates[0].coverage_status == "executable"
        and definition_candidates[0].definition_id
        == action.action_definition_id
        and definition_candidates[0].source == action.action_source
        and len(admissions) == 1
        and admissions[0].coverage_status == "executable"
        and admissions[0].action_role == "turn_action"
        and ability_binding is not None
        and ability_binding.coverage_status == "executable"
        and ability_binding.binding_id == action.ability_binding_id
        and ability_binding.source == action.ability_binding_source
        and rules.action_ability_binding_by_id(action.ability_binding_id)
        == ability_binding
    )


def _clone_rulebook_indexes(rules: RuleBook, **overrides: object) -> RuleBook:
    cloned = copy(rules)
    for name, value in overrides.items():
        object.__setattr__(cloned, name, value)
    return cloned


def _rules_with_servant_definition(
    rules: RuleBook,
    replacement: ServantDefinitionIR,
) -> RuleBook:
    definition_id = replacement.servant_definition_id
    direct = dict(getattr(rules, "_servant_definitions"))
    direct[definition_id] = replacement
    by_ref = dict(getattr(rules, "_servant_definitions_by_ref"))
    by_ref[replacement.servant_ref] = replacement

    def replace_in_index(index: Mapping[object, object]) -> dict[object, object]:
        result: dict[object, object] = {}
        for key, value in index.items():
            if isinstance(value, tuple):
                result[key] = tuple(
                    replacement
                    if isinstance(item, ServantDefinitionIR)
                    and item.servant_definition_id == definition_id
                    else item
                    for item in value
                )
            else:
                result[key] = value
        return result

    return _clone_rulebook_indexes(
        rules,
        _servant_definitions=direct,
        _servant_definitions_by_ref=by_ref,
        _servant_definitions_by_owner=replace_in_index(
            getattr(rules, "_servant_definitions_by_owner")
        ),
        _servant_definitions_by_owned_skill=replace_in_index(
            getattr(rules, "_servant_definitions_by_owned_skill")
        ),
    )


def _rules_with_avatar_profile(rules: RuleBook, replacement: object) -> RuleBook:
    profile_id = getattr(replacement, "avatar_profile_id")
    avatar_id = getattr(replacement, "avatar_id")
    by_id = dict(getattr(rules, "_avatar_profiles_by_profile_id"))
    by_avatar = dict(getattr(rules, "_avatar_profiles"))
    by_id[profile_id] = replacement
    by_avatar[avatar_id] = replacement
    return _clone_rulebook_indexes(
        rules,
        _avatar_profiles_by_profile_id=by_id,
        _avatar_profiles=by_avatar,
    )


def _negative_build_with_traces(
    build: CharacterBuildInput,
    suffix: str,
    trace_node_ids: tuple[str, ...],
    *,
    level: int | None = None,
    promotion: int | None = None,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"{build.build_id}:negative:{suffix}",
        character_card_id=build.character_card_id,
        level=build.level if level is None else level,
        promotion=build.promotion if promotion is None else promotion,
        eidolon_level=build.eidolon_level,
        unlocked_trace_node_ids=trace_node_ids,
        equipment_build=EquipmentBuildInput(
            build_id=f"{build.equipment_build.build_id}:negative:{suffix}",
            character_card_id=build.character_card_id,
        ),
    )


def _immutability_negative(
    build: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
    child: OwnedCombatantBuildAssemblyResult,
) -> dict[str, Any]:
    build_payload = build.to_json()
    parsed_build = CharacterBuildInput.from_json(build_payload)
    parsed_build_json = parsed_build.to_json()
    parsed_build_fingerprint = parsed_build.input_fingerprint
    raw_trace_nodes = build_payload.get("unlocked_trace_node_ids")
    if isinstance(raw_trace_nodes, list):
        raw_trace_nodes.append("validation:post_creation_mutation")

    child_payload = json.loads(json.dumps(child.to_json()))
    parsed_child = OwnedCombatantBuildAssemblyResult.from_json(child_payload)
    parsed_child_json = parsed_child.to_json()
    parsed_child_fingerprint = parsed_child.result_fingerprint
    raw_stat_bindings = child_payload.get("stat_bindings")
    if isinstance(raw_stat_bindings, list):
        source_mutated = False
        for raw_binding in raw_stat_bindings:
            if not isinstance(raw_binding, dict):
                continue
            raw_sources = raw_binding.get("sources")
            if not isinstance(raw_sources, list) or not raw_sources:
                continue
            raw_source = raw_sources[0]
            if isinstance(raw_source, dict) and isinstance(
                raw_source.get("evidence"),
                dict,
            ):
                raw_source["evidence"]["validation_mutation"] = True
                source_mutated = True
                break
    else:
        source_mutated = False

    source_mapping_rejected = False
    active_source = next(
        (
            source
            for binding in child.stat_bindings
            for source in binding.sources
        ),
        None,
    )
    if active_source is not None:
        try:
            active_source.evidence["validation_mutation"] = True
        except TypeError:
            source_mapping_rejected = True
    frozen_assignment_rejected = False
    try:
        child.owner_entity_ref = "validation:post_creation_mutation"
    except FrozenInstanceError:
        frozen_assignment_rejected = True
    assembly_round_trip = CharacterBuildAssemblyResult.from_json(assembly.to_json())
    checks = {
        "build_input_detached_from_json_container": parsed_build.to_json()
        == parsed_build_json
        and parsed_build.input_fingerprint == parsed_build_fingerprint,
        "owned_result_detached_from_json_container": source_mutated
        and parsed_child.to_json() == parsed_child_json
        and parsed_child.result_fingerprint == parsed_child_fingerprint,
        "nested_source_evidence_is_immutable": source_mapping_rejected,
        "frozen_result_rejects_field_assignment": frozen_assignment_rejected,
        "parent_round_trip_and_fingerprint_stable": assembly_round_trip == assembly
        and assembly_round_trip.result_fingerprint == assembly.result_fingerprint,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "input_fingerprint": build.input_fingerprint,
        "owned_result_fingerprint": child.result_fingerprint,
        "parent_result_fingerprint": assembly.result_fingerprint,
    }


def _scenario_and_transition_matrix(
    rules: RuleBook,
    builds: tuple[CharacterBuildInput, ...],
    assemblies: tuple[CharacterBuildAssemblyResult, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    enemy = next(
        (
            entity
            for entity in sorted(rules.ir.entities, key=lambda item: item.entity_id)
            if entity.entity_type == "monster"
        ),
        None,
    )
    if enemy is None:
        return _empty_scenario_matrix("enemy_fixture_source_missing"), {}
    spawn_rows = []
    transition_sample: dict[str, Any] = {}
    formal_entered = False
    missing_source_blocked = True
    owner_relation_preserved = False
    queryable_count = 0
    special_resource_seen = False
    special_resource_runtime_initialized = True
    special_resource_missing_world_level_blocked = True
    special_resource_rows: list[dict[str, Any]] = []
    for build, assembly in zip(builds, assemblies, strict=True):
        if assembly.battle_admission_status != "admitted":
            continue
        initial_condition = _initial_condition(assembly)
        weaknesses: tuple[str, ...] = ()
        world_level = (
            max(
                binding.initializer.world_level_threshold
                for binding in assembly.resource_bindings
            )
            + 1
            if assembly.resource_bindings
            else None
        )
        scenario = ScenarioSpec(
            scenario_id=f"validation:owned_combatant:{build.build_id}",
            version=VALIDATION_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:owner",
                    side="ally",
                    entity_ref=(
                        rules.character_data_card(build.character_card_id).entity_ref
                    ),
                    build_mode="assembled_character_build",
                    level=build.level,
                    eidolon_level=build.eidolon_level,
                    panel=None,
                    character_build=build,
                    initial_condition=initial_condition,
                ),
                UnitSpec(
                    unit_id="enemy:target",
                    side="enemy",
                    entity_ref=enemy.entity_id,
                    build_mode="kernel_fixture",
                    panel=PanelInput(
                        max_hp=100000.0,
                        hp=100000.0,
                        attack=1.0,
                        defense=1000.0,
                        speed=80.0,
                        toughness=100.0,
                        max_toughness=100.0,
                        flags={"position": 0, "weaknesses": weaknesses},
                    ),
                ),
            ),
            route=(),
            battle_setup=BattleSetupSpec(
                world_level=world_level,
                timeline=TimelineSetupSpec(mode="runtime_initialize"),
            ),
        )
        if assembly.resource_bindings:
            special_resource_seen = True
            try:
                ScenarioStateBuilder(rules).build(
                    replace(
                        scenario,
                        battle_setup=replace(
                            scenario.battle_setup,
                            world_level=None,
                        ),
                    )
                )
                special_resource_missing_world_level_blocked = False
            except ValueError as exc:
                special_resource_missing_world_level_blocked = (
                    special_resource_missing_world_level_blocked
                    and
                    "special-resource initializer requires battle_setup.world_level"
                    in str(exc)
                )
        built = ScenarioStateBuilder(rules).build(scenario)
        state = built.state
        for binding in assembly.resource_bindings:
            owner_resources = state.units["ally:owner"].resources
            current_value = owner_resources.get(binding.current_resource_key)
            maximum_value = owner_resources.get(binding.maximum_resource_key)
            matching_records = tuple(
                record
                for record in built.setup_records
                if record.get("record_type") == "special_resource_initialization"
                and (
                    record.get("payload") or {}
                ).get("resource_definition_id")
                == binding.resource_definition_id
            )
            initialized = bool(
                isinstance(current_value, (int, float))
                and isinstance(maximum_value, (int, float))
                and maximum_value > 0
                and 0 <= current_value <= maximum_value
                and current_value != 0
                and len(matching_records) == 1
            )
            special_resource_runtime_initialized = (
                special_resource_runtime_initialized and initialized
            )
            special_resource_rows.append(
                {
                    "resource_definition_id": binding.resource_definition_id,
                    "current_resource_key": binding.current_resource_key,
                    "maximum_resource_key": binding.maximum_resource_key,
                    "current_value": current_value,
                    "maximum_value": maximum_value,
                    "world_level": world_level,
                    "setup_record_count": len(matching_records),
                    "initialized": initialized,
                }
            )
        formal_entered = True
        if any(unit.side == "summon" for unit in state.units.values()):
            return _empty_scenario_matrix("scenario_auto_spawned_owned_combatant"), {}
        system = SummonSystem(rules)
        for child in assembly.owned_combatant_results:
            definition = rules.servant_definition(child.servant_definition_id)
            if definition is None or not definition.spawn_sources:
                continue
            missing_plan = system.plan_spawn_servant(
                state,
                definition,
                owner_id="ally:owner",
            )
            missing_source_blocked = missing_source_blocked and (
                not missing_plan.ok
                and missing_plan.blocked_reason == "formal_servant_spawn_source_required"
            )
            spawn_plan = system.plan_spawn_servant(
                state,
                definition,
                owner_id="ally:owner",
                spawn_source=definition.spawn_sources[0],
            )
            if not spawn_plan.ok:
                spawn_rows.append(
                    {
                        "servant_definition_id": definition.servant_definition_id,
                        "spawn_ok": False,
                        "blocked_reason": spawn_plan.blocked_reason,
                    }
                )
                continue
            spawn_result = system.apply_spawn_servant(state, spawn_plan)
            after_spawn = MutationReducer().apply_all(state, spawn_result.mutations)
            servant = next(
                unit
                for unit in after_spawn.units.values()
                if unit.side == "summon"
                and unit.flags.get("servant_definition_id")
                == definition.servant_definition_id
            )
            owner_relation_preserved = owner_relation_preserved or (
                servant.flags.get("owner_id") == "ally:owner"
                and isinstance(servant.flags.get("owner_relation"), dict)
                and servant.flags["owner_relation"].get("owner_entity_ref")
                == state.units["ally:owner"].template_id
            )
            turn_state = replace(
                after_spawn,
                global_flags={
                    **after_spawn.global_flags,
                    "turn_owner_id": servant.unit_id,
                    "phase": "scenario",
                    "current_window": "idle",
                    "combat_phase": "awaiting_decision",
                },
            )
            view = ActionAvailabilitySystem(rules).view(turn_state)
            queryable = tuple(
                choice
                for choice in view.choices
                if choice.source_trace.get("owned_combatant_build_action")
                and (choice.auto_target_ids or choice.selectable_target_ids)
            )
            if queryable:
                queryable_count += 1
            spawn_rows.append(
                {
                    "servant_definition_id": definition.servant_definition_id,
                    "spawn_ok": True,
                    "servant_unit_id": servant.unit_id,
                    "choice_count": len(view.choices),
                    "queryable_choice_count": len(queryable),
                    "blocked_reasons": [item.reason for item in view.blocked[:8]],
                }
            )
            if not queryable or transition_sample:
                continue
            choice = queryable[0]
            target_ids = choice.auto_target_ids or choice.selectable_target_ids[:1]
            toughness_emissions = rules.toughness_emissions_for_action(
                choice.action_id,
                choice.action_level,
            )
            toughness_source_rows = [
                {
                    "toughness_emission_id": emission.toughness_emission_id,
                    "coverage_status": emission.coverage_status,
                    "blocked_reason": emission.blocked_reason,
                    "source": {
                        key: emission.source.to_json().get(key)
                        for key in ("source_path", "raw_type", "raw_id")
                    },
                    "source_evidence_keys": sorted(
                        str(key) for key in emission.source.evidence
                    ),
                }
                for emission in toughness_emissions
            ]
            toughness_sources_admitted = bool(toughness_source_rows) and all(
                row["coverage_status"] == "executable"
                and not row["blocked_reason"]
                and bool((row["source"] or {}).get("source_path"))
                and bool((row["source"] or {}).get("raw_type"))
                and bool((row["source"] or {}).get("raw_id"))
                for row in toughness_source_rows
            )
            command = ActionCommand(
                actor_id=choice.actor_id,
                action_id=choice.action_id,
                action_level=choice.action_level,
                target_ids=tuple(target_ids),
                source="manual",
            )
            after, transition = CombatExecutor(rules).execute(command, turn_state)
            replay = MutationReducer().replay_snapshot(
                turn_state,
                transition.transaction.mutations,
                transition.after.to_json(),
            )
            audit = RuntimeSourceAuditor(rules).validate_transition(transition)
            compact_audit = _compact_source_audit(audit)
            transition_sample = {
                "servant_definition_id": definition.servant_definition_id,
                "action_id": choice.action_id,
                "action_level": choice.action_level,
                "target_ids": list(target_ids),
                "target_weaknesses": list(weaknesses),
                "toughness_sources_admitted": toughness_sources_admitted,
                "toughness_source_rows": toughness_source_rows,
                "outcome_category": transition.outcome.category,
                "outcome_reason_codes": list(transition.outcome.reason_codes),
                "incomplete_node_results": [
                    node.to_json()
                    for node in transition.outcome.node_results
                    if not node.complete
                ][:16],
                "committed": transition.outcome.successor_eligible
                and transition.coverage.get("action_enabled") is True
                and bool(transition.transaction.mutations),
                "mutation_count": len(transition.transaction.mutations),
                "execution_coverage": {
                    key: transition.coverage.get(key)
                    for key in (
                        "action_enabled",
                        "ability_task_mutation_count",
                        "damage_mutation_count",
                        "damage_ok",
                        "toughness_mutation_count",
                        "toughness_ok",
                        "event_ok",
                        "event_blocked_reason",
                    )
                    if key in transition.coverage
                },
                "source_audit_ok": audit.ok,
                "source_audit": compact_audit,
                "source_audit_violations": compact_audit["violations"],
                "mutations": [
                    _compact_mutation(mutation)
                    for mutation in transition.transaction.mutations
                ],
                "settlement": _compact_settlement(
                    transition.transaction.settlement
                ),
                "replay_ok": replay.ok,
                "replay_errors": list(replay.errors),
                "after_equal": after.snapshot().to_json()
                == transition.after.to_json(),
            }
    return (
        {
            "formal_memory_build_entered_scenario": formal_entered,
            "scenario_does_not_auto_spawn": formal_entered,
            "missing_spawn_source_does_not_spawn": missing_source_blocked,
            "source_backed_spawn_preserves_owner_relation": owner_relation_preserved,
            "spawned_servant_has_queryable_source_backed_action": queryable_count > 0,
            "spawn_candidate_count": len(spawn_rows),
            "queryable_spawn_count": queryable_count,
            "special_resource_runtime_initialized": (
                special_resource_seen and special_resource_runtime_initialized
            ),
            "special_resource_missing_world_level_blocked": (
                special_resource_seen
                and special_resource_missing_world_level_blocked
            ),
            "special_resource_rows": special_resource_rows,
            "spawn_rows": spawn_rows,
        },
        transition_sample,
    )


def _initial_condition(
    assembly: CharacterBuildAssemblyResult,
) -> CharacterInitialConditionInput:
    if not assembly.resource_bindings:
        return CharacterInitialConditionInput(hp_mode="full", initial_energy="0")
    return CharacterInitialConditionInput(
        hp_mode="full",
        initial_energy=None,
        initial_resource_values=tuple(
            CharacterInitialResourceValue(
                resource_definition_id=binding.resource_definition_id,
            )
            for binding in assembly.resource_bindings
        ),
    )


def _empty_scenario_matrix(reason: str) -> dict[str, Any]:
    return {
        "formal_memory_build_entered_scenario": False,
        "scenario_does_not_auto_spawn": False,
        "missing_spawn_source_does_not_spawn": False,
        "source_backed_spawn_preserves_owner_relation": False,
        "spawned_servant_has_queryable_source_backed_action": False,
        "spawn_candidate_count": 0,
        "queryable_spawn_count": 0,
        "special_resource_runtime_initialized": False,
        "special_resource_missing_world_level_blocked": False,
        "special_resource_rows": [],
        "blocked_reason": reason,
        "spawn_rows": [],
    }


def _static_boundary_matrix(
    package_root: Path,
    rules: RuleBook,
    affected: tuple[
        tuple[CharacterDataCardIR, tuple[str, ...], tuple[CharacterTraceNodeIR, ...]],
        ...,
    ],
) -> dict[str, int]:
    production_paths = (
        package_root / "rules" / "ir.py",
        package_root / "rules" / "rulebook.py",
        package_root / "tbgd" / "character_cards.py",
        package_root / "tbgd" / "lowering.py",
        package_root / "builds" / "models.py",
        package_root / "builds" / "character_assembler.py",
        package_root / "scenarios" / "build_state.py",
        package_root / "systems" / "summon.py",
        package_root / "systems" / "action_availability.py",
        package_root / "systems" / "unit_spawn.py",
        Path(__file__).resolve(),
    )
    identity_literals = {
        card.entity_ref.removeprefix("avatar:")
        for card, _skills, _nodes in affected
    }.union(
        definition.servant_ref.removeprefix("servant:")
        for definition in rules.servant_definitions()
    )
    identity_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:" + "|".join(map(re.escape, identity_literals)) + r")(?![A-Za-z0-9])"
    )
    fixed_count = 0
    for path in production_paths:
        fixed_count += len(identity_pattern.findall(path.read_text(encoding="utf-8")))
    runtime_paths = (
        package_root / "builds" / "models.py",
        package_root / "builds" / "character_assembler.py",
        package_root / "scenarios" / "build_state.py",
        package_root / "systems" / "summon.py",
        package_root / "systems" / "action_availability.py",
        package_root / "systems" / "unit_spawn.py",
    )
    raw_markers = re.compile(
        r"AvatarServantConfig|AvatarServantSkillConfig|Config/ConfigAbility|turnbasedgamedata"
    )
    runtime_raw_count = sum(
        len(raw_markers.findall(path.read_text(encoding="utf-8")))
        for path in runtime_paths
    )
    return {
        "fixed_character_or_servant_id_count": fixed_count,
        "runtime_raw_tbgd_read_count": runtime_raw_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Memory owned-combatant build closure",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    tbgd_root = args.tbgd_root or find_tbgd_root(package_root.parent)
    result = run_validation(package_root, tbgd_root.resolve(), args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
