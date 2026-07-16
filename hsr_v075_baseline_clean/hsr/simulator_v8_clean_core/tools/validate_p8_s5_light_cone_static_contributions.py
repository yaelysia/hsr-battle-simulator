from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..build_types import BuildSourceRef, StaticStatContribution
from ..builds.character_assembler import assemble_character_build
from ..builds.equipment_assembler import (
    assemble_equipment_build,
)
from ..equipment.models import (
    EquipmentAssemblyResult,
    EquipmentDefinitionKey,
    LightConeStaticPropertyIR,
)
from ..immutable_json import thaw_json
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.character_cards import build_character_card_ir
from ..tbgd.light_cone_cards import (
    LIGHT_CONE_CATALOG_SCHEMA_VERSION,
    LightConeCatalogBuildResult,
    LightConeCatalogSourceBundle,
    load_light_cone_catalog_sources,
)
from ..tbgd.lowering import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    build_character_action_definition_ir,
)
from .io import write_json
from .validate_p8_s4_light_cone_instance_assembly import (
    _build_catalog,
    _character_build,
    _equipment_build,
    _focused_ir,
    _scenario_payload,
)


VALIDATION_VERSION = "p8_s5_light_cone_static_contributions"
SUMMARY_SCHEMA_VERSION = "p8_s5_light_cone_static_contributions_summary_v2"

_EXPECTED_STATIC_PROPERTY_BINDINGS: dict[str, tuple[str, str, str]] = {
    "AttackAddedRatio": ("percentage", "attack", "ratio"),
    "HPAddedRatio": ("percentage", "max_hp", "ratio"),
    "DefenceAddedRatio": ("percentage", "defense", "ratio"),
    "SpeedAddedRatio": ("percentage", "speed", "ratio"),
    "BaseSpeed": ("flat", "speed", "flat"),
    "CriticalChanceBase": ("resource", "critical_chance", "resource"),
    "CriticalDamageBase": ("resource", "critical_damage", "resource"),
    "BreakDamageAddedRatioBase": (
        "resource",
        "break_damage_added_ratio",
        "resource",
    ),
    "StatusProbabilityBase": ("resource", "effect_hit_rate", "resource"),
    "StatusResistanceBase": ("resource", "effect_resistance", "resource"),
    "AllDamageTypeAddedRatio": ("resource", "damage_added_ratio", "resource"),
    "SPRatioBase": ("resource", "energy_regeneration_rate", "resource"),
    "HealRatioBase": ("resource", "outgoing_healing_ratio", "resource"),
    "HealTakenRatio": ("resource", "incoming_healing_ratio", "resource"),
    "ElationDamageAddedRatioBase": (
        "resource",
        "elation_damage_added_ratio",
        "resource",
    ),
}


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    sources = load_light_cone_catalog_sources(tbgd_root)
    catalog = _build_catalog(sources)
    if not catalog.catalog_complete:
        raise ValueError("P8-S5 requires the atomically complete P8-S3 catalog")

    card_result = build_character_card_ir(
        tbgd_root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
    )
    action_definitions = build_character_action_definition_ir(tbgd_root)
    ir = _focused_ir(catalog, card_result, action_definitions)
    rules = RuleBook(ir)
    playable = _playable_characters_by_path(rules)

    source_matrix = _source_class_matrix(catalog, sources)
    static_matrix, sample_context = _static_contribution_matrix(
        rules,
        catalog,
        sources,
        playable,
    )
    source_integrity, catalog_rebuild_count = _source_integrity_matrix(
        catalog,
        sources,
    )
    negative_matrix = _negative_matrix(
        rules,
        catalog,
        sources,
        sample_context,
        source_integrity,
    )
    runtime_probe = _formal_runtime_boundary_probe(rules, sample_context)
    runtime_matrix = _runtime_unchanged_matrix(static_matrix, runtime_probe)
    walkback = _source_walkback(sample_context)

    predicates = {
        "catalog_schema_version_v2": catalog.to_summary_json()["schema_version"]
        == LIGHT_CONE_CATALOG_SCHEMA_VERSION
        == "p8.light_cone_catalog.v2",
        "source_class_partition_complete": source_matrix[
            "source_class_partition_complete"
        ],
        "source_class_counts_match_discovered_rows": source_matrix[
            "source_class_counts_match_discovered_rows"
        ],
        "no_static_with_ability_source_class_non_empty": source_matrix[
            "no_static_with_ability_source_class_non_empty"
        ],
        "static_with_ability_source_class_non_empty": source_matrix[
            "static_with_ability_source_class_non_empty"
        ],
        "current_static_only_source_absent": source_matrix[
            "current_static_only_source_absent"
        ],
        "absent_source_class_has_no_synthetic_positive": source_matrix[
            "absent_source_class_has_no_synthetic_positive"
        ],
        "all_discovered_ranks_have_unique_ability_source": source_matrix[
            "all_discovered_ranks_have_unique_ability_source"
        ],
        "base_and_passive_channels_separate": static_matrix[
            "base_and_passive_channels_separate"
        ],
        "path_match_static_properties_applied_once": static_matrix[
            "path_match_static_properties_applied_once"
        ],
        "path_mismatch_base_stats_retained": static_matrix[
            "path_mismatch_base_stats_retained"
        ],
        "path_mismatch_passive_stats_absent": static_matrix[
            "path_mismatch_passive_stats_absent"
        ],
        "empty_static_property_set_is_valid": static_matrix[
            "empty_static_property_set_is_valid"
        ],
        "unknown_static_property_blocks_assembly": negative_matrix[
            "rows"
        ]["unknown_static_property_blocks_assembly"],
        "duplicate_static_source_rejected": negative_matrix["rows"][
            "duplicate_static_source_rejected"
        ],
        "all_static_terms_source_backed": static_matrix[
            "all_static_terms_source_backed"
        ],
        "dynamic_ability_executed": runtime_matrix["dynamic_ability_executed"],
        "input_order_deterministic": static_matrix["input_order_deterministic"],
        "runtime_behavior_changed": runtime_matrix["runtime_behavior_changed"],
    }
    positive_predicates = {
        key: value
        for key, value in predicates.items()
        if key not in {"dynamic_ability_executed", "runtime_behavior_changed"}
    }
    ok = (
        all(value is True for value in positive_predicates.values())
        and predicates["dynamic_ability_executed"] is False
        and predicates["runtime_behavior_changed"] is False
        and source_matrix["ok"] is True
        and static_matrix["ok"] is True
        and source_integrity["ok"] is True
        and negative_matrix["ok"] is True
        and runtime_matrix["ok"] is True
        and walkback["ok"] is True
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = {
        "source_class_matrix": output_dir / "source_class_matrix.json",
        "static_contribution_matrix": output_dir / "static_contribution_matrix.json",
        "source_integrity_matrix": output_dir / "source_integrity_matrix.json",
        "negative_matrix": output_dir / "negative_matrix.json",
        "runtime_unchanged_matrix": output_dir / "runtime_unchanged_matrix.json",
        "source_walkback_sample": output_dir / "source_walkback_sample.json",
    }
    for name, path in artifact_paths.items():
        write_json(
            path,
            {
                "source_class_matrix": source_matrix,
                "static_contribution_matrix": static_matrix,
                "source_integrity_matrix": source_integrity,
                "negative_matrix": negative_matrix,
                "runtime_unchanged_matrix": runtime_matrix,
                "source_walkback_sample": walkback,
            }[name],
        )

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checklist_modified": False,
        "git_commit_created": False,
        "p8_s6_or_later_started": False,
        "predicates": predicates,
        "checks": {
            "source_class_matrix": source_matrix["ok"],
            "static_contribution_matrix": static_matrix["ok"],
            "source_integrity_matrix": source_integrity["ok"],
            "negative_matrix": negative_matrix["ok"],
            "runtime_unchanged": runtime_matrix["ok"],
            "source_walkback": walkback["ok"],
        },
        "observations": {
            "published_light_cone_count": len(catalog.canonical_definitions),
            "discovered_rank_count": source_matrix["discovered_rank_count"],
            "static_property_item_count": static_matrix[
                "static_property_item_count"
            ],
            "source_class_counts": source_matrix["class_counts"],
            "source_content_fingerprint": thaw_json(
                catalog.source_content_fingerprint
            ),
        },
        "resource_budget": {
            "primary_source_load_count": 1,
            "semantic_light_cone_table_parse_count": 3,
            "equipment_ability_file_parse_count": catalog.ability_file_parse_count,
            "focused_character_card_build_count": 1,
            "focused_character_action_definition_build_count": 1,
            "focused_rulebook_build_count": 1,
            "in_memory_catalog_negative_rebuild_count": catalog_rebuild_count,
            "full_tbgd_lowering_build_count": 0,
            "full_canonical_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "artifact_bytes_before_summary": sum(
                path.stat().st_size for path in artifact_paths.values()
            ),
            "serial_execution": True,
        },
        "scope": {
            "implemented": (
                "source-backed light-cone static properties mapped into the shared contribution ledger, "
                "path-gated passive admission, character-panel consumption, and canonical source validation"
            ),
            "deferred": (
                "equipment ability graph lowering, startup, conditions, modifiers, callbacks, and execution (P8-S6-S8)"
            ),
        },
    }
    write_json(
        output_dir / "validation_summary_p8_s5_light_cone_static_contributions.json",
        summary,
    )
    return summary


def _playable_characters_by_path(
    rules: RuleBook,
) -> dict[str, tuple[str, Any]]:
    result: dict[str, tuple[str, Any]] = {}
    fallback_card_ids: dict[str, str] = {}
    for card in sorted(rules.ir.character_data_cards, key=lambda item: item.card_id):
        resolution = rules.character_equipment_eligibility_for_card(card.card_id)
        if resolution.resolution_status != "resolved" or resolution.value is None:
            continue
        path_type = resolution.value.character_path_type
        fallback_card_ids.setdefault(path_type, card.card_id)
        if path_type in result:
            continue
        empty = assemble_character_build(
            rules,
            _character_build(card.card_id, f"s5-empty:{path_type}"),
        )
        if (
            empty.assembly_status == "assembled"
            and empty.battle_admission_status == "admitted"
            and empty.base_panel is not None
        ):
            result[path_type] = (card.card_id, empty)
    for path_type, card_id in fallback_card_ids.items():
        result.setdefault(path_type, (card_id, None))
    return result


def _ability_index(
    ability_documents: tuple[tuple[str, object], ...],
) -> dict[str, tuple[tuple[str, int], ...]]:
    result: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for source_path, document in ability_documents:
        if not isinstance(document, Mapping):
            continue
        ability_list = document.get("AbilityList")
        if not isinstance(ability_list, list):
            continue
        for index, row in enumerate(ability_list):
            name = row.get("Name") if isinstance(row, Mapping) else None
            if isinstance(name, str) and name:
                result[name].append((source_path, index))
    return {
        name: tuple(sorted(items))
        for name, items in sorted(result.items())
    }


def _source_class_matrix(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
) -> dict[str, Any]:
    ability_index = _ability_index(sources.ability_documents)
    rows: list[dict[str, Any]] = []
    ability_errors: list[dict[str, Any]] = []
    for definition in sorted(
        catalog.canonical_definitions,
        key=lambda item: item.definition_key.stable_id,
    ):
        for rank in definition.superimposition_levels:
            candidates = ability_index.get(rank.ability_name, ())
            ability = definition.ability_source
            unique_ability = bool(
                len(candidates) == 1
                and ability is not None
                and ability.ability_name == rank.ability_name
                and (ability.source.source_path, ability.record_index) == candidates[0]
            )
            if rank.static_properties and unique_ability:
                source_class = "static_with_ability_source"
            elif not rank.static_properties and unique_ability:
                source_class = "no_static_with_ability_source"
            elif rank.static_properties and not unique_ability:
                source_class = "static_only_without_ability_source"
            else:
                source_class = "invalid_no_static_or_unique_ability_source"
            row = {
                "definition_key": definition.definition_key.stable_id,
                "skill_id": rank.skill_id,
                "rank": rank.level,
                "static_property_count": len(rank.static_properties),
                "ability_name": rank.ability_name,
                "ability_candidate_count": len(candidates),
                "source_class": source_class,
            }
            rows.append(row)
            if not unique_ability:
                ability_errors.append(row)
    class_counts = Counter(row["source_class"] for row in rows)
    expected_classes = (
        "no_static_with_ability_source",
        "static_with_ability_source",
        "static_only_without_ability_source",
    )
    samples = {
        source_class: next(
            (row for row in rows if row["source_class"] == source_class),
            None,
        )
        for source_class in expected_classes
    }
    discovered_raw_rows = len(sources.skill_rows) if isinstance(sources.skill_rows, list) else -1
    classified_count = sum(class_counts.get(name, 0) for name in expected_classes)
    checks = {
        "source_class_partition_complete": classified_count == len(rows)
        and not ability_errors,
        "source_class_counts_match_discovered_rows": len(rows)
        == discovered_raw_rows
        == classified_count,
        "no_static_with_ability_source_class_non_empty": class_counts[
            "no_static_with_ability_source"
        ]
        > 0,
        "static_with_ability_source_class_non_empty": class_counts[
            "static_with_ability_source"
        ]
        > 0,
        "current_static_only_source_absent": class_counts[
            "static_only_without_ability_source"
        ]
        == 0,
        "absent_source_class_has_no_synthetic_positive": samples[
            "static_only_without_ability_source"
        ]
        is None,
        "all_discovered_ranks_have_unique_ability_source": not ability_errors,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "schema_version": "p8_s5_source_class_matrix_v1",
        **checks,
        "discovered_rank_count": len(rows),
        "class_counts": {
            name: class_counts.get(name, 0)
            for name in expected_classes
        },
        "samples": samples,
        "ability_source_errors": ability_errors[:16],
        "selection_policy": (
            "stable definition key and rank order; class membership uses only static-property presence "
            "and unique raw ability-record binding"
        ),
        "fixed_definition_ids_used": False,
        "synthetic_positive_count": 0,
    }


def _raw_skill_index(
    skill_rows: object,
) -> dict[tuple[str, int], tuple[int, Mapping[str, object]]]:
    result: dict[tuple[str, int], tuple[int, Mapping[str, object]]] = {}
    if not isinstance(skill_rows, list):
        return result
    duplicates: set[tuple[str, int]] = set()
    for index, row in enumerate(skill_rows):
        if not isinstance(row, Mapping):
            continue
        skill_id = row.get("SkillID")
        level = row.get("Level")
        if (
            not isinstance(skill_id, int)
            or isinstance(skill_id, bool)
            or not isinstance(level, int)
            or isinstance(level, bool)
        ):
            continue
        key = (str(skill_id), level)
        if key in result:
            duplicates.add(key)
        result[key] = (index, row)
    for key in duplicates:
        result.pop(key, None)
    return result


def _static_contribution_matrix(
    rules: RuleBook,
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
    playable: dict[str, tuple[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_index = _raw_skill_index(sources.skill_rows)
    differences: list[dict[str, Any]] = []
    rank_count = 0
    static_property_item_count = 0
    no_static_case_count = 0
    path_match_case_count = 0
    path_mismatch_case_count = 0
    panel_case_count = 0
    panel_unavailable_case_count = 0
    dynamic_mechanism_selection_count = 0
    same_path_dynamic_blocked_case_count = 0
    cross_path_inactive_admitted_case_count = 0
    all_static_source_backed = True
    base_and_passive_separate = True
    path_match_once = True
    path_mismatch_base_retained = True
    path_mismatch_passive_absent = True
    empty_static_valid = True
    sample_context: dict[str, Any] = {}
    deterministic_rows: list[tuple[str, int, str]] = []
    deterministic_cases: list[tuple[str, int, Any]] = []

    def difference(label: str, actual: object, expected: object, identity: str) -> None:
        if actual != expected and len(differences) < 32:
            differences.append(
                {
                    "label": label,
                    "identity": identity,
                    "actual": actual,
                    "expected": expected,
                }
            )

    for definition in sorted(
        catalog.canonical_definitions,
        key=lambda item: item.definition_key.stable_id,
    ):
        same_entry = playable.get(definition.path_type)
        cross_entries = tuple(
            entry
            for path_type, entry in sorted(playable.items())
            if path_type != definition.path_type and entry[1] is not None
        )
        difference(
            "same_path_real_character_eligibility_present",
            same_entry is not None,
            True,
            definition.definition_key.stable_id,
        )
        difference(
            "cross_path_playable_character_present",
            bool(cross_entries),
            True,
            definition.definition_key.stable_id,
        )
        if same_entry is None or not cross_entries:
            continue
        same_card_id, empty_character = same_entry
        cross_card_id, cross_empty_character = cross_entries[0]
        for rank in definition.superimposition_levels:
            identity = f"{definition.definition_key.stable_id}:rank:{rank.level}"
            rank_count += 1
            static_property_item_count += len(rank.static_properties)
            raw_candidate = raw_index.get((rank.skill_id, rank.level))
            difference("raw_rank_row_unique", raw_candidate is not None, True, identity)
            raw_properties: object = None
            if raw_candidate is not None:
                raw_properties = raw_candidate[1].get("AbilityProperty")
                difference(
                    "raw_static_property_list_is_array",
                    isinstance(raw_properties, list),
                    True,
                    identity,
                )
                difference(
                    "typed_static_property_count_matches_raw",
                    len(rank.static_properties),
                    len(raw_properties) if isinstance(raw_properties, list) else -1,
                    identity,
                )

            same_build = _equipment_build(
                same_card_id,
                definition,
                f"s5:same:{definition.raw_equipment_id}:{rank.level}",
                superimposition=rank.level,
                instance_id=(
                    f"validation:p8_s5:same:{definition.raw_equipment_id}:{rank.level}"
                ),
            )
            cross_build = _equipment_build(
                cross_card_id,
                definition,
                f"s5:cross:{definition.raw_equipment_id}:{rank.level}",
                superimposition=rank.level,
                instance_id=(
                    f"validation:p8_s5:cross:{definition.raw_equipment_id}:{rank.level}"
                ),
            )
            same_result = assemble_equipment_build(rules, same_build)
            cross_result = assemble_equipment_build(rules, cross_build)
            dynamic_mechanism_selection_count += len(
                same_result.dynamic_mechanisms
            ) + len(cross_result.dynamic_mechanisms)
            path_match_case_count += 1
            path_mismatch_case_count += 1
            same_selection = same_result.light_cone_selection
            cross_selection = cross_result.light_cone_selection
            difference("same_path_assembled", same_result.assembly_status, "assembled", identity)
            difference("cross_path_assembled", cross_result.assembly_status, "assembled", identity)
            difference("same_path_selection_present", same_selection is not None, True, identity)
            difference("cross_path_selection_present", cross_selection is not None, True, identity)
            if same_selection is None or cross_selection is None:
                continue

            same_by_id = {
                item.contribution_id: item
                for item in same_result.static_contributions
            }
            passive_terms = tuple(
                same_by_id[item]
                for item in same_selection.passive_contribution_ids
                if item in same_by_id
            )
            base_terms = tuple(
                same_by_id[item]
                for item in same_selection.base_contribution_ids
                if item in same_by_id
            )
            base_and_passive_separate = base_and_passive_separate and bool(
                len(base_terms) == 6
                and all(item.contribution_pool == "base" for item in base_terms)
                and all(item.contribution_pool != "base" for item in passive_terms)
                and set(same_selection.base_contribution_ids).isdisjoint(
                    same_selection.passive_contribution_ids
                )
            )
            path_match_once = path_match_once and bool(
                len(passive_terms) == len(rank.static_properties)
                and tuple(item.contribution_id for item in passive_terms)
                == same_selection.passive_contribution_ids
            )

            for index, property_ir in enumerate(rank.static_properties):
                item_identity = f"{identity}:property:{index}"
                raw_item = (
                    raw_properties[index]
                    if isinstance(raw_properties, list)
                    and index < len(raw_properties)
                    and isinstance(raw_properties[index], Mapping)
                    else None
                )
                raw_value = _raw_static_decimal(raw_item)
                expected_binding = _EXPECTED_STATIC_PROPERTY_BINDINGS.get(
                    property_ir.property_type
                )
                difference(
                    "static_property_type_has_independent_expected_binding",
                    expected_binding is not None,
                    True,
                    item_identity,
                )
                if index >= len(passive_terms) or expected_binding is None:
                    path_match_once = False
                    continue
                contribution = passive_terms[index]
                expected_pool, expected_property_type, expected_calculation = (
                    expected_binding
                )
                expected_id = (
                    f"light_cone_passive:{same_build.light_cone.instance_id}:"
                    f"rank:{rank.level}:property:{property_ir.property_index}"
                )
                expected = (
                    expected_id,
                    expected_pool,
                    expected_property_type,
                    expected_calculation,
                    raw_value,
                    property_ir.source,
                )
                actual = (
                    contribution.contribution_id,
                    contribution.contribution_pool,
                    contribution.property_type,
                    contribution.calculation.calculation_kind,
                    Decimal(contribution.exact_value),
                    contribution.source,
                )
                difference("static_contribution_matches_raw_oracle", actual, expected, item_identity)
                ledger_matches = tuple(
                    item
                    for item in same_result.source_ledger
                    if item.ledger_entry_id
                    == f"equipment_source:{contribution.contribution_id}"
                    and item.source == property_ir.source
                )
                source_backed = bool(
                    contribution.source_ref.definition_kind == "light_cone"
                    and contribution.source_ref.definition_identity
                    == definition.definition_key.definition_identity
                    and len(ledger_matches) == 1
                )
                all_static_source_backed = all_static_source_backed and source_backed
                if not sample_context and empty_character is not None:
                    sample_context = {
                        "definition": definition,
                        "rank": rank,
                        "property": property_ir,
                        "same_build": same_build,
                        "same_result": same_result,
                        "cross_build": cross_build,
                        "cross_result": cross_result,
                        "contribution": contribution,
                        "same_card_id": same_card_id,
                        "same_empty_character": empty_character,
                        "cross_card_id": cross_card_id,
                        "cross_empty_character": cross_empty_character,
                    }

            cross_by_id = {
                item.contribution_id: item
                for item in cross_result.static_contributions
            }
            cross_base_terms = tuple(
                cross_by_id[item]
                for item in cross_selection.base_contribution_ids
                if item in cross_by_id
            )
            path_mismatch_base_retained = path_mismatch_base_retained and (
                _contribution_signature(base_terms)
                == _contribution_signature(cross_base_terms)
            )
            path_mismatch_passive_absent = path_mismatch_passive_absent and bool(
                not cross_selection.passive_contribution_ids
                and len(cross_result.static_contributions) == 6
                and not cross_result.dynamic_mechanisms
                and not cross_result.battle_admission_blockers
                and cross_result.battle_admission_status == "admitted"
            )
            if not rank.static_properties:
                no_static_case_count += 1
                empty_static_valid = empty_static_valid and bool(
                    not same_selection.passive_contribution_ids
                    and len(same_result.static_contributions) == 6
                    and all(
                        blocker.channel != "static_passive"
                        for blocker in same_result.battle_admission_blockers
                    )
                )
            difference(
                "same_path_only_dynamic_ability_blocks_battle",
                tuple(item.channel for item in same_result.battle_admission_blockers),
                ("dynamic_ability",),
                identity,
            )
            if (
                same_result.battle_admission_status == "blocked"
                and tuple(
                    item.channel for item in same_result.battle_admission_blockers
                )
                == ("dynamic_ability",)
            ):
                same_path_dynamic_blocked_case_count += 1
            difference(
                "dynamic_mechanism_not_selected",
                same_result.dynamic_mechanisms,
                (),
                identity,
            )
            if (
                cross_result.battle_admission_status == "admitted"
                and not cross_result.dynamic_mechanisms
                and cross_result.activation_decisions
                and cross_result.activation_decisions[0].activation_status == "inactive"
            ):
                cross_path_inactive_admitted_case_count += 1

            if empty_character is None:
                panel_unavailable_case_count += 1
            else:
                character_result = assemble_character_build(
                    rules,
                    _character_build(
                        same_card_id,
                        f"s5-panel:{definition.raw_equipment_id}:{rank.level}",
                        same_build,
                    ),
                )
                panel_case_count += 1
                difference(
                    "character_panel_assembled",
                    character_result.assembly_status,
                    "assembled",
                    identity,
                )
                expected_ledger = (
                    *empty_character.contribution_ledger,
                    *same_result.static_contributions,
                )
                difference(
                    "character_ledger_consumes_each_equipment_term_once",
                    Counter(
                        item.contribution_id
                        for item in character_result.contribution_ledger
                    ),
                    Counter(item.contribution_id for item in expected_ledger),
                    identity,
                )
                difference(
                    "character_final_panel_matches_independent_pool_fold",
                    _panel_values(character_result.base_panel),
                    _oracle_panel_values(expected_ledger),
                    identity,
                )
            deterministic_rows.append(
                (
                    definition.definition_key.stable_id,
                    rank.level,
                    same_result.result_fingerprint,
                )
            )
            deterministic_cases.append(
                (definition.definition_key.stable_id, rank.level, same_build)
            )

    ordered_digest = _row_digest(deterministic_rows)
    reverse_digest = _row_digest(
        (
            definition_key,
            rank_level,
            assemble_equipment_build(rules, build).result_fingerprint,
        )
        for definition_key, rank_level, build in reversed(deterministic_cases)
    )
    checks = {
        "base_and_passive_channels_separate": base_and_passive_separate,
        "path_match_static_properties_applied_once": path_match_once
        and static_property_item_count > 0,
        "path_mismatch_base_stats_retained": path_mismatch_base_retained,
        "path_mismatch_passive_stats_absent": path_mismatch_passive_absent,
        "empty_static_property_set_is_valid": empty_static_valid
        and no_static_case_count > 0,
        "all_static_terms_source_backed": all_static_source_backed
        and static_property_item_count > 0,
        "input_order_deterministic": ordered_digest == reverse_digest,
        "every_rank_and_panel_case_exercised": rank_count > 0
        and path_match_case_count == rank_count
        and path_mismatch_case_count == rank_count
        and panel_case_count > 0
        and panel_case_count + panel_unavailable_case_count == rank_count,
        "independent_static_oracle_has_no_differences": not differences,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return (
        {
            "schema_version": "p8_s5_static_contribution_matrix_v1",
            **checks,
            "rank_case_count": rank_count,
            "path_match_case_count": path_match_case_count,
            "path_mismatch_case_count": path_mismatch_case_count,
            "panel_case_count": panel_case_count,
            "panel_unavailable_due_preexisting_character_admission_count": panel_unavailable_case_count,
            "no_static_case_count": no_static_case_count,
            "static_property_item_count": static_property_item_count,
            "dynamic_mechanism_selection_count": dynamic_mechanism_selection_count,
            "same_path_dynamic_blocked_case_count": same_path_dynamic_blocked_case_count,
            "cross_path_inactive_admitted_case_count": cross_path_inactive_admitted_case_count,
            "property_type_counts": dict(
                sorted(
                    Counter(
                        item.property_type
                        for definition in catalog.canonical_definitions
                        for rank in definition.superimposition_levels
                        for item in rank.static_properties
                    ).items()
                )
            ),
            "deterministic_result_digest": ordered_digest,
            "differences": differences,
        },
        sample_context,
    )


def _source_integrity_matrix(
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
) -> tuple[dict[str, Any], int]:
    definition = next(
        item
        for item in catalog.canonical_definitions
        if any(rank.static_properties for rank in item.superimposition_levels)
    )
    ability_name = definition.ability_source.ability_name
    missing_documents = _mutate_ability_documents(
        sources.ability_documents,
        ability_name,
        mode="remove",
    )
    duplicate_documents = _mutate_ability_documents(
        sources.ability_documents,
        ability_name,
        mode="duplicate",
    )
    wrong_skill_rows = copy.deepcopy(sources.skill_rows)
    other_ability_name = next(
        name
        for name in sorted(_ability_index(sources.ability_documents))
        if name != ability_name
    )
    changed = False
    for row in wrong_skill_rows:
        if (
            isinstance(row, dict)
            and str(row.get("SkillID")) == definition.skill_id
            and not changed
        ):
            row["AbilityName"] = other_ability_name
            changed = True
    missing_catalog = _build_catalog(
        replace(sources, ability_documents=missing_documents)
    )
    duplicate_catalog = _build_catalog(
        replace(sources, ability_documents=duplicate_documents)
    )
    wrong_binding_catalog = _build_catalog(
        replace(sources, skill_rows=wrong_skill_rows)
    )
    rows = {
        "missing_ability_source_blocks_catalog": not missing_catalog.catalog_complete,
        "ambiguous_ability_source_blocks_catalog": not duplicate_catalog.catalog_complete,
        "wrong_ability_binding_blocks_catalog": changed
        and not wrong_binding_catalog.catalog_complete,
    }
    issue_codes = {
        "missing": sorted({item.issue_code for item in missing_catalog.issues}),
        "ambiguous": sorted(
            {item.issue_code for item in duplicate_catalog.issues}
        ),
        "wrong_binding": sorted(
            {item.issue_code for item in wrong_binding_catalog.issues}
        ),
    }
    return (
        {
            "schema_version": "p8_s5_source_integrity_matrix_v1",
            "ok": all(rows.values()),
            "rows": rows,
            "issue_codes": issue_codes,
            "catalog_negative_rebuilds_use_in_memory_documents": True,
        },
        3,
    )


def _negative_matrix(
    rules: RuleBook,
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
    context: dict[str, Any],
    source_integrity: dict[str, Any],
) -> dict[str, Any]:
    if not context:
        return {"ok": False, "rows": {}, "reason": "real static-property sample missing"}
    property_ir = context["property"]
    rank = context["rank"]
    result = context["same_result"]
    contribution = context["contribution"]
    cross_result = context["cross_result"]

    unknown_json = property_ir.to_json()
    unknown_json["property_type"] = "ValidationUnknownStaticProperty"
    malformed_json = property_ir.to_json()
    malformed_json["exact_value"] = "NaN"
    wrong_binding_json = property_ir.to_json()
    wrong_binding_json["canonical_property_type"] = (
        "defense" if property_ir.canonical_property_type != "defense" else "attack"
    )

    foreign_property = next(
        item
        for definition in catalog.canonical_definitions
        for candidate_rank in definition.superimposition_levels
        for item in candidate_rank.static_properties
        if item.property_index == property_ir.property_index
        and item.source.raw_id != property_ir.source.raw_id
    )
    wrong_source_property = replace(property_ir, source=foreign_property.source)
    rank_properties = tuple(
        wrong_source_property if item.property_index == property_ir.property_index else item
        for item in rank.static_properties
    )

    multi_property_rank = next(
        candidate_rank
        for definition in catalog.canonical_definitions
        for candidate_rank in definition.superimposition_levels
        if len(candidate_rank.static_properties) >= 2
    )
    first, second, *remaining = multi_property_rank.static_properties
    duplicated_source_second = replace(second, source=first.source)

    duplicate_result_term = _raises(
        lambda: replace(
            result,
            static_contributions=(
                *result.static_contributions,
                contribution,
            ),
        )
    )
    missing_result_term = _raises(
        lambda: replace(
            result,
            static_contributions=tuple(
                item
                for item in result.static_contributions
                if item.contribution_id != contribution.contribution_id
            ),
        )
    )
    forged_source_contribution = replace(
        contribution,
        source=foreign_property.source,
    )
    forged_source_result_rejected = _raises(
        lambda: replace(
            result,
            static_contributions=tuple(
                forged_source_contribution
                if item.contribution_id == contribution.contribution_id
                else item
                for item in result.static_contributions
            ),
        )
    )
    other_rank_property = next(
        item
        for candidate_rank in context["definition"].superimposition_levels
        if candidate_rank.level != rank.level
        for item in candidate_rank.static_properties
        if item.property_index == property_ir.property_index
    )
    def jointly_forged_source_rejected(forged_source: Any) -> bool:
        forged_contribution = replace(contribution, source=forged_source)
        return _raises(
            lambda: replace(
                result,
                static_contributions=tuple(
                    forged_contribution
                    if item.contribution_id == contribution.contribution_id
                    else item
                    for item in result.static_contributions
                ),
                source_ledger=tuple(
                    replace(item, source=forged_source)
                    if item.ledger_entry_id
                    == f"equipment_source:{contribution.contribution_id}"
                    else item
                    for item in result.source_ledger
                ),
            )
        )

    wrong_json_path_evidence = thaw_json(contribution.source.evidence)
    wrong_json_path_evidence["json_path"] = (
        f"{rank.source.evidence['json_path']}.AbilityProperty["
        f"{property_ir.property_index + 1}].Value.Value"
    )
    wrong_json_path_source = replace(
        contribution.source,
        evidence=wrong_json_path_evidence,
    )
    wrong_fingerprint_evidence = thaw_json(contribution.source.evidence)
    wrong_fingerprint_evidence["source_fingerprint"]["sha256"] = "0" * 64
    wrong_fingerprint_source = replace(
        contribution.source,
        evidence=wrong_fingerprint_evidence,
    )
    damaged_passive_identity_rejected = _raises(
        lambda: replace(
            result.light_cone_selection,
            passive_contribution_ids=(
                f"light_cone_passive:{result.light_cone_selection.instance_id}:"
                f"rank:{rank.level}:property:{property_ir.property_index + 1}",
            ),
        )
    )
    jointly_forged_contribution_and_ledger_rejected = (
        jointly_forged_source_rejected(other_rank_property.source)
    )
    jointly_forged_json_path_rejected = jointly_forged_source_rejected(
        wrong_json_path_source
    )
    jointly_forged_fingerprint_rejected = jointly_forged_source_rejected(
        wrong_fingerprint_source
    )
    other_definition = next(
        item
        for item in catalog.canonical_definitions
        if item.definition_key != context["definition"].definition_key
    )
    jointly_forged_owner_contribution = replace(
        contribution,
        source_ref=BuildSourceRef(
            "light_cone",
            other_definition.definition_key.definition_identity,
        ),
    )
    jointly_forged_contribution_and_ledger_owner_rejected = _raises(
        lambda: replace(
            result,
            static_contributions=tuple(
                jointly_forged_owner_contribution
                if item.contribution_id == contribution.contribution_id
                else item
                for item in result.static_contributions
            ),
            source_ledger=tuple(
                replace(
                    item,
                    definition_key=EquipmentDefinitionKey(
                        "light_cone",
                        other_definition.definition_key.definition_identity,
                    ),
                )
                if item.ledger_entry_id
                == f"equipment_source:{contribution.contribution_id}"
                else item
                for item in result.source_ledger
            ),
        )
    )
    cross_selection = cross_result.light_cone_selection
    forged_cross_rejected = False
    if cross_selection is not None:
        def forge_inactive_cross_result() -> EquipmentAssemblyResult:
            forged_cross_selection = replace(
                cross_selection,
                passive_contribution_ids=(contribution.contribution_id,),
            )
            return replace(
                cross_result,
                light_cone_selection=forged_cross_selection,
                static_contributions=(
                    *cross_result.static_contributions,
                    contribution,
                ),
            )

        forged_cross_rejected = _raises(forge_inactive_cross_result)

    character_result = assemble_character_build(
        rules,
        _character_build(
            context["same_card_id"],
            "s5-negative-double-consumption",
            context["same_build"],
        ),
    )
    damaged_result_json = result.to_json()
    damaged_result_json["result_fingerprint"] = "0" * 64
    rows = {
        "unknown_static_property_blocks_assembly": _raises(
            lambda: LightConeStaticPropertyIR.from_json(unknown_json)
        ),
        "noncanonical_static_decimal_rejected": _raises(
            lambda: LightConeStaticPropertyIR.from_json(malformed_json)
        ),
        "damaged_canonical_property_binding_rejected": _raises(
            lambda: LightConeStaticPropertyIR.from_json(wrong_binding_json)
        ),
        "foreign_static_property_source_rejected": _raises(
            lambda: replace(rank, static_properties=rank_properties)
        ),
        "duplicate_static_source_rejected": _raises(
            lambda: replace(
                multi_property_rank,
                static_properties=(first, duplicated_source_second, *remaining),
            )
        ),
        "duplicate_static_contribution_identity_rejected": duplicate_result_term,
        "missing_selected_passive_contribution_rejected": missing_result_term,
        "forged_contribution_source_rejected_by_result_model": forged_source_result_rejected,
        "jointly_forged_contribution_and_ledger_source_rejected": (
            jointly_forged_contribution_and_ledger_rejected
        ),
        "jointly_forged_contribution_and_ledger_json_path_rejected": (
            jointly_forged_json_path_rejected
        ),
        "jointly_forged_contribution_and_ledger_fingerprint_rejected": (
            jointly_forged_fingerprint_rejected
        ),
        "jointly_forged_contribution_and_ledger_owner_rejected": (
            jointly_forged_contribution_and_ledger_owner_rejected
        ),
        "damaged_passive_contribution_identity_rejected": (
            damaged_passive_identity_rejected
        ),
        "inactive_path_cannot_carry_passive_contribution": forged_cross_rejected,
        "character_legacy_double_consumption_rejected": _raises(
            lambda: replace(
                character_result,
                contribution_ledger=(
                    *character_result.contribution_ledger,
                    contribution,
                ),
            )
        ),
        "damaged_equipment_result_fingerprint_rejected": _raises(
            lambda: EquipmentAssemblyResult.from_json(damaged_result_json)
        ),
        "missing_ability_source_blocks_catalog": source_integrity["rows"][
            "missing_ability_source_blocks_catalog"
        ],
        "ambiguous_ability_source_blocks_catalog": source_integrity["rows"][
            "ambiguous_ability_source_blocks_catalog"
        ],
        "wrong_ability_binding_blocks_catalog": source_integrity["rows"][
            "wrong_ability_binding_blocks_catalog"
        ],
    }
    required_rows = frozenset(
        {
            "unknown_static_property_blocks_assembly",
            "noncanonical_static_decimal_rejected",
            "damaged_canonical_property_binding_rejected",
            "foreign_static_property_source_rejected",
            "duplicate_static_source_rejected",
            "duplicate_static_contribution_identity_rejected",
            "missing_selected_passive_contribution_rejected",
            "forged_contribution_source_rejected_by_result_model",
            "jointly_forged_contribution_and_ledger_source_rejected",
            "jointly_forged_contribution_and_ledger_json_path_rejected",
            "jointly_forged_contribution_and_ledger_fingerprint_rejected",
            "jointly_forged_contribution_and_ledger_owner_rejected",
            "damaged_passive_contribution_identity_rejected",
            "inactive_path_cannot_carry_passive_contribution",
            "character_legacy_double_consumption_rejected",
            "damaged_equipment_result_fingerprint_rejected",
            "missing_ability_source_blocks_catalog",
            "ambiguous_ability_source_blocks_catalog",
            "wrong_ability_binding_blocks_catalog",
        }
    )
    return {
        "schema_version": "p8_s5_negative_matrix_v2",
        "ok": all(rows.values()) and required_rows.issubset(rows),
        "all_required_negative_rows_present": required_rows.issubset(rows),
        "rows": rows,
        "required_rows": sorted(required_rows),
        "raw_source_documents_reused": bool(sources.ability_documents),
    }


def _formal_runtime_boundary_probe(
    rules: RuleBook,
    context: dict[str, Any],
) -> dict[str, Any]:
    if not context:
        return {
            "ok": False,
            "reason": "real formal runtime boundary sample missing",
        }

    def card(card_id: str) -> Any:
        return next(
            item for item in rules.ir.character_data_cards if item.card_id == card_id
        )

    def artifact_payload(result: Any) -> dict[str, list[Any]]:
        def encode(item: Any) -> Any:
            method = getattr(item, "to_json", None)
            return method() if callable(method) else item

        return {
            "mutations": [encode(item) for item in result.setup_mutations],
            "events": [encode(item) for item in result.setup_events],
            "rng_events": [encode(item) for item in result.setup_rng_events],
        }

    same_character_input = _character_build(
        context["same_card_id"],
        "s5-runtime-probe-active",
        context["same_build"],
    )
    same_character_result = assemble_character_build(rules, same_character_input)
    if not same_character_result.effective_skill_levels:
        return {"ok": False, "reason": "active probe has no effective skill level"}
    same_skill = same_character_result.effective_skill_levels[0]
    same_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            {
                "card": card(context["same_card_id"]),
                "action": (same_skill.action_id, same_skill.effective_level),
            },
            (("ally:s5-active-probe", same_character_input),),
        )
    )
    same_identity = IdentityResolver(rules).validate(same_scenario)
    same_state_build_error = ""
    same_built = None
    if same_identity.ok:
        try:
            same_built = ScenarioStateBuilder(rules).build(same_scenario)
        except ValueError as exc:
            same_state_build_error = str(exc)

    cross_character_input = _character_build(
        context["cross_card_id"],
        "s5-runtime-probe-cross",
        context["cross_build"],
    )
    empty_character_input = _character_build(
        context["cross_card_id"],
        "s5-runtime-probe-empty",
    )
    cross_character_result = assemble_character_build(rules, cross_character_input)
    empty_character_result = assemble_character_build(rules, empty_character_input)
    if (
        not cross_character_result.effective_skill_levels
        or not empty_character_result.effective_skill_levels
    ):
        return {"ok": False, "reason": "admitted probe has no effective skill level"}
    cross_skill = cross_character_result.effective_skill_levels[0]
    empty_skill = empty_character_result.effective_skill_levels[0]
    cross_cases = {
        "card": card(context["cross_card_id"]),
        "action": (cross_skill.action_id, cross_skill.effective_level),
    }
    empty_cases = {
        "card": card(context["cross_card_id"]),
        "action": (empty_skill.action_id, empty_skill.effective_level),
    }
    cross_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            cross_cases,
            (("ally:s5-runtime-probe", cross_character_input),),
        )
    )
    empty_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            empty_cases,
            (("ally:s5-runtime-probe", empty_character_input),),
        )
    )
    cross_identity = IdentityResolver(rules).validate(cross_scenario)
    empty_identity = IdentityResolver(rules).validate(empty_scenario)
    cross_built = (
        ScenarioStateBuilder(rules).build(cross_scenario)
        if cross_identity.ok
        else None
    )
    empty_built = (
        ScenarioStateBuilder(rules).build(empty_scenario)
        if empty_identity.ok
        else None
    )
    cross_artifacts = artifact_payload(cross_built) if cross_built is not None else {}
    empty_artifacts = artifact_payload(empty_built) if empty_built is not None else {}
    artifact_delta_channels = tuple(
        name
        for name in ("mutations", "events", "rng_events")
        if cross_artifacts.get(name) != empty_artifacts.get(name)
    )
    same_equipment_result = same_character_result.equipment_assembly_result
    cross_equipment_result = cross_character_result.equipment_assembly_result
    checks = {
        "same_path_active_build_rejected_by_formal_state_boundary": bool(
            same_character_result.assembly_status == "assembled"
            and same_character_result.battle_admission_status == "blocked"
            and same_equipment_result is not None
            and same_equipment_result.battle_admission_status == "blocked"
            and tuple(
                item.channel
                for item in same_equipment_result.battle_admission_blockers
            )
            == ("dynamic_ability",)
            and same_identity.ok
            and same_built is None
            and same_state_build_error
        ),
        "cross_path_inactive_formal_state_build_succeeds": bool(
            cross_character_result.battle_admission_status == "admitted"
            and cross_equipment_result is not None
            and cross_equipment_result.battle_admission_status == "admitted"
            and cross_equipment_result.activation_decisions
            and cross_equipment_result.activation_decisions[0].activation_status
            == "inactive"
            and cross_identity.ok
            and cross_built is not None
        ),
        "empty_formal_state_build_succeeds": bool(
            empty_character_result.battle_admission_status == "admitted"
            and empty_identity.ok
            and empty_built is not None
        ),
        "cross_path_equipment_creates_no_dynamic_setup_artifact_delta": not artifact_delta_channels,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "schema_version": "p8_s5_formal_runtime_boundary_probe_v1",
        **checks,
        "same_identity_errors": list(same_identity.errors),
        "same_state_build_error": same_state_build_error,
        "cross_identity_errors": list(cross_identity.errors),
        "empty_identity_errors": list(empty_identity.errors),
        "cross_setup_artifact_counts": {
            key: len(value) for key, value in cross_artifacts.items()
        },
        "empty_setup_artifact_counts": {
            key: len(value) for key, value in empty_artifacts.items()
        },
        "setup_artifact_delta_channels": list(artifact_delta_channels),
    }


def _runtime_unchanged_matrix(
    static_matrix: dict[str, Any],
    runtime_probe: dict[str, Any],
) -> dict[str, Any]:
    from ..builds import equipment_assembler

    source = inspect.getsource(equipment_assembler)
    production_assembler_has_no_runtime_or_system_import = bool(
        "..systems" not in source
        and "Mutation" not in source
        and "Settlement" not in source
    )
    dynamic_ability_executed = bool(
        static_matrix["dynamic_mechanism_selection_count"]
        or not runtime_probe.get(
            "same_path_active_build_rejected_by_formal_state_boundary", False
        )
        or runtime_probe.get("setup_artifact_delta_channels")
    )
    runtime_behavior_changed = bool(
        not production_assembler_has_no_runtime_or_system_import
        or runtime_probe.get("setup_artifact_delta_channels")
    )
    checks = {
        "dynamic_ability_executed": dynamic_ability_executed,
        "runtime_behavior_changed": runtime_behavior_changed,
        "production_assembler_has_no_runtime_or_system_import": (
            production_assembler_has_no_runtime_or_system_import
        ),
        "all_real_rank_cases_keep_dynamic_selection_empty": bool(
            static_matrix["rank_case_count"] > 0
            and static_matrix["dynamic_mechanism_selection_count"] == 0
        ),
        "all_same_path_cases_block_dynamic_before_runtime": bool(
            static_matrix["same_path_dynamic_blocked_case_count"]
            == static_matrix["rank_case_count"]
        ),
        "all_cross_path_cases_remain_inactive_and_admitted": bool(
            static_matrix["cross_path_inactive_admitted_case_count"]
            == static_matrix["rank_case_count"]
        ),
        "formal_runtime_boundary_probe_passes": runtime_probe.get("ok") is True,
    }
    checks["ok"] = bool(
        checks["dynamic_ability_executed"] is False
        and checks["runtime_behavior_changed"] is False
        and checks["production_assembler_has_no_runtime_or_system_import"] is True
        and checks["all_real_rank_cases_keep_dynamic_selection_empty"] is True
        and checks["all_same_path_cases_block_dynamic_before_runtime"] is True
        and checks["all_cross_path_cases_remain_inactive_and_admitted"] is True
        and checks["formal_runtime_boundary_probe_passes"] is True
    )
    return {
        "schema_version": "p8_s5_runtime_unchanged_matrix_v2",
        **checks,
        "evidence_derivation": {
            "rank_case_count": static_matrix["rank_case_count"],
            "dynamic_mechanism_selection_count": static_matrix[
                "dynamic_mechanism_selection_count"
            ],
            "same_path_dynamic_blocked_case_count": static_matrix[
                "same_path_dynamic_blocked_case_count"
            ],
            "cross_path_inactive_admitted_case_count": static_matrix[
                "cross_path_inactive_admitted_case_count"
            ],
        },
        "formal_runtime_boundary_probe": runtime_probe,
    }


def _source_walkback(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {"ok": False, "reason": "real source walkback sample missing"}
    definition = context["definition"]
    rank = context["rank"]
    property_ir = context["property"]
    contribution = context["contribution"]
    selection = context["same_result"].light_cone_selection
    activation = context["same_result"].activation_decisions[0]
    source_matches = bool(
        selection is not None
        and contribution.contribution_id in selection.passive_contribution_ids
        and property_ir.property_index in selection.static_property_indices
        and contribution.source == property_ir.source
        and property_ir.source.raw_id
        == f"{rank.skill_id}:{rank.level}:{property_ir.property_index}"
    )
    return {
        "schema_version": "p8_s5_source_walkback_sample_v1",
        "ok": source_matches,
        "selection_policy": "first real static-property rank in stable definition/rank/property order",
        "fixed_definition_id_used": False,
        "instance": {
            "instance_id": context["same_build"].light_cone.instance_id,
            "instance_fingerprint": context["same_build"].light_cone.instance_fingerprint,
        },
        "definition_key": definition.definition_key.to_json(),
        "rank": {
            "skill_id": rank.skill_id,
            "level": rank.level,
            "source": rank.source.to_json(),
        },
        "property": property_ir.to_json(),
        "activation": activation.to_json(),
        "contribution": contribution.to_json(),
        "source_identity_matches": source_matches,
    }


def _raw_static_decimal(value: object) -> Decimal | None:
    if not isinstance(value, Mapping):
        return None
    container = value.get("Value")
    if not isinstance(container, Mapping):
        return None
    raw = container.get("Value")
    if isinstance(raw, bool) or not isinstance(raw, (int, Decimal)):
        return None
    result = Decimal(raw)
    return result if result.is_finite() else None


def _contribution_signature(
    contributions: tuple[StaticStatContribution, ...],
) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            item.contribution_pool,
            item.property_type,
            item.exact_value,
            item.calculation.to_json(),
            item.source.to_json(),
        )
        for item in contributions
    )


def _oracle_panel_values(
    contributions: tuple[StaticStatContribution, ...],
) -> dict[str, Decimal]:
    by_pool: dict[str, dict[str, Decimal]] = {
        "base": {},
        "percentage": {},
        "flat": {},
        "resource": {},
    }
    for item in contributions:
        pool = by_pool[item.contribution_pool]
        pool[item.property_type] = pool.get(item.property_type, Decimal(0)) + Decimal(
            item.exact_value
        )
    result: dict[str, Decimal] = {}
    for property_type in sorted(set().union(*(value for value in by_pool.values()))):
        if property_type in {"max_hp", "attack", "defense", "speed", "max_energy"}:
            result[property_type] = by_pool["base"].get(
                property_type, Decimal(0)
            ) * (Decimal(1) + by_pool["percentage"].get(property_type, Decimal(0))) + by_pool[
                "flat"
            ].get(property_type, Decimal(0))
        else:
            result[property_type] = by_pool["resource"].get(
                property_type, Decimal(0)
            )
    return result


def _panel_values(panel: Any) -> dict[str, Decimal] | None:
    if panel is None:
        return None
    result = {
        name: Decimal(getattr(panel, name))
        for name in (
            "max_hp",
            "attack",
            "defense",
            "speed",
            "max_energy",
            "critical_chance",
            "critical_damage",
            "base_aggro",
        )
    }
    result.update(
        {
            item.property_type: Decimal(item.exact_value)
            for item in panel.additional_resources
        }
    )
    return result


def _row_digest(rows: Any) -> str:
    payload = sorted(tuple(row) for row in rows)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mutate_ability_documents(
    documents: tuple[tuple[str, object], ...],
    ability_name: str,
    *,
    mode: str,
) -> tuple[tuple[str, object], ...]:
    result = copy.deepcopy(documents)
    changed = False
    for _, document in result:
        if not isinstance(document, dict):
            continue
        ability_list = document.get("AbilityList")
        if not isinstance(ability_list, list):
            continue
        matches = [
            index
            for index, row in enumerate(ability_list)
            if isinstance(row, dict) and row.get("Name") == ability_name
        ]
        if not matches:
            continue
        if mode == "remove":
            ability_list.pop(matches[0])
        elif mode == "duplicate":
            ability_list.append(copy.deepcopy(ability_list[matches[0]]))
        else:
            raise ValueError(f"unsupported ability document mutation mode {mode}")
        changed = True
        break
    if not changed:
        raise ValueError("ability mutation target was not found")
    return result


def _raises(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P8-S5 light-cone static contributions"
    )
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run_validation(args.tbgd_root, args.output_dir)
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
