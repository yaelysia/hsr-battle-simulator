from __future__ import annotations

import argparse
import copy
import inspect
import json
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..build_types import BuildSourceRef
from ..builds.character_assembler import (
    assemble_character_build,
    validate_character_build_admission,
)
from ..builds.equipment_assembler import (
    assemble_equipment_build,
    validate_equipment_assembly_admission,
    validate_equipment_instance_uniqueness,
)
from ..builds.models import CharacterBuildAssemblyResult, CharacterBuildInput
from ..equipment.models import (
    DynamicMechanismSelection,
    EquipmentAssemblyDiagnostic,
    EquipmentAssemblyResult,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    LightConeDefinitionIR,
    LightConeInstanceInput,
    LightConeRankParameterBasis,
)
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR, IRSource, RuleEntity, StandaloneAbilityGraphIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.identity import IdentityResolver
from ..scenarios.loader import ScenarioLoader
from ..tbgd.character_cards import build_character_card_ir
from ..tbgd.light_cone_cards import (
    LightConeCatalogBuildResult,
    LightConeCatalogSourceBundle,
    build_light_cone_catalog_from_documents,
    load_light_cone_catalog_sources,
)
from ..tbgd.lowering import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    _standalone_ability_source_admitted,
    build_character_action_definition_ir,
)
from .io import write_json


VALIDATION_VERSION = "p8_s4_light_cone_instance_assembly"
SUMMARY_SCHEMA_VERSION = "p8_s4_light_cone_instance_assembly_summary_v2"
_ENEMY_ENTITY_ID = "monster:p8_s4_validation_target"


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    sources = load_light_cone_catalog_sources(tbgd_root)
    catalog = _build_catalog(sources)
    if not catalog.catalog_complete:
        raise ValueError("P8-S4 requires the atomically complete P8-S3 catalog")

    card_result = build_character_card_ir(
        tbgd_root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
    )
    action_definitions = build_character_action_definition_ir(tbgd_root)
    ir = _focused_ir(catalog, card_result, action_definitions)
    rules = RuleBook(ir)
    cases = _select_formal_cases(rules, ir)

    positive = _formal_positive_checks(rules, cases)
    growth_oracle = _growth_oracle_checks(rules, catalog, sources, cases)
    source_and_gap = _source_and_gap_checks(rules, catalog, cases)
    scenario = _scenario_and_uniqueness_checks(rules, cases)
    negative = _negative_matrix(rules, ir, cases)
    model_contract = _model_contract_checks(cases)
    sections = {
        "formal_positive_cases": positive,
        "independent_decimal_growth_oracle": growth_oracle,
        "source_and_gap_classification": source_and_gap,
        "scenario_and_team_uniqueness": scenario,
        "negative_matrix": negative,
        "model_contract": model_contract,
    }
    checks = {
        key: {
            "ok": value.get("ok") is True,
            "failed": sorted(
                name
                for name, item in value.items()
                if name != "ok" and isinstance(item, bool) and item is not True
            ),
        }
        for key, value in sections.items()
    }
    ok = all(value["ok"] is True for value in checks.values())

    matrix = {
        "schema_version": "p8_s4_light_cone_instance_assembly_matrix_v1",
        **sections,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / "p8_s4_light_cone_instance_assembly_matrix.json"
    write_json(matrix_path, matrix)
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checklist_modified": False,
        "git_commit_created": False,
        "validation_scope": {
            "historical_stage": "P8-S4",
            "asserts_current_p8_s5_or_later_state": False,
        },
        "checks": checks,
        "formal_cases": {
            "character_card_id": cases["card"].card_id,
            "empty_equipment_battle_admission": cases["empty_result"].battle_admission_status,
            "cross_path_activation": _activation_status(cases["cross_result"]),
            "cross_path_battle_admission": cases["cross_result"].battle_admission_status,
            "same_path_activation": _activation_status(cases["same_result"]),
            "same_path_battle_admission": cases["same_result"].battle_admission_status,
        },
        "historical_s4_fixture_gap_classification": {
            blocker.channel: blocker.gap_classification
            for blocker in cases["same_equipment_result"].battle_admission_blockers
        },
        "resource_budget": {
            "light_cone_source_scan_count": 1,
            "semantic_light_cone_table_parse_count": catalog.semantic_table_parse_count,
            "equipment_ability_file_parse_count": catalog.ability_file_parse_count,
            "character_card_build_count": 1,
            "character_action_definition_build_count": 1,
            "focused_rulebook_build_count": negative["rulebook_build_count"] + 1,
            "full_tbgd_lowering_build_count": 0,
            "formal_scenario_build_count": scenario["formal_scenario_build_count"],
            "full_canonical_ir_written": False,
            "full_rulebook_written": False,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
            "artifact_bytes_before_summary": matrix_path.stat().st_size,
            "serial_execution": True,
        },
        "scope": {
            "implemented": (
                "typed light-cone instance progression, exact base-stat assembly, derived path activation, "
                "typed battle admission, character-build propagation, and team instance uniqueness"
            ),
            "deferred": (
                "equipment ability gameplay-family execution (P8-S7/P8-S8), "
                "and every relic stage"
            ),
            "not_asserted_by_this_regression": (
                "current P8-S5 static-passive completeness or P8-S6 graph/binding/startup state; "
                "their own validators are authoritative"
            ),
        },
    }
    write_json(
        output_dir / "validation_summary_p8_s4_light_cone_instance_assembly.json",
        summary,
    )
    return summary


def _build_catalog(sources: LightConeCatalogSourceBundle) -> LightConeCatalogBuildResult:
    return build_light_cone_catalog_from_documents(
        equipment_rows=sources.equipment_rows,
        promotion_rows=sources.promotion_rows,
        skill_rows=sources.skill_rows,
        ability_documents=sources.ability_documents,
        source_content_fingerprint=sources.source_content_fingerprint,
        source_kind="tbgd",
        prerequisite_issues=sources.prerequisite_issues,
        source_integrity_ok=sources.source_integrity_ok,
        semantic_table_parse_count=3,
        ability_file_parse_count=len(sources.ability_documents),
    )


def _focused_ir(
    catalog: LightConeCatalogBuildResult,
    card_result: Any,
    action_definitions: tuple[Any, ...],
) -> CanonicalIR:
    entities_by_id = {
        card.entity_ref: RuleEntity(
            entity_id=card.entity_ref,
            entity_type="avatar",
            fields={"profile_id": card.profile_id},
            source=card.source,
            coverage_status="audit_only",
        )
        for card in card_result.character_data_cards
    }
    for action in sorted(
        action_definitions,
        key=lambda item: (item.action_id, item.level, item.definition_id),
    ):
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
    enemy_source = IRSource(
        source_path="validation/p8_s4_enemy.json",
        raw_type="P8S4ValidationEnemy",
        raw_id=_ENEMY_ENTITY_ID,
        evidence={"fixture": True},
    )
    entities_by_id[_ENEMY_ENTITY_ID] = RuleEntity(
        entity_id=_ENEMY_ENTITY_ID,
        entity_type="monster",
        fields={},
        source=enemy_source,
        coverage_status="audit_only",
    )
    return CanonicalIR(
        version=BASELINE_VERSION,
        entities=tuple(entities_by_id[key] for key in sorted(entities_by_id)),
        avatar_profiles=tuple(card_result.avatar_profiles),
        character_data_cards=tuple(card_result.character_data_cards),
        character_equipment_eligibilities=tuple(
            card_result.character_equipment_eligibilities
        ),
        character_mechanism_slots=tuple(card_result.character_mechanism_slots),
        character_trace_nodes=tuple(card_result.character_trace_nodes),
        character_eidolon_slots=tuple(card_result.character_eidolon_slots),
        action_definitions=tuple(action_definitions),
        light_cone_definitions=catalog.canonical_definitions,
    )


def _select_formal_cases(rules: RuleBook, ir: CanonicalIR) -> dict[str, Any]:
    definitions = tuple(
        definition
        for definition in ir.light_cone_definitions
        if definition.publication_status == "published"
    )
    for card in sorted(ir.character_data_cards, key=lambda item: item.card_id):
        if card.coverage_status != "executable":
            continue
        eligibility = rules.character_equipment_eligibility_for_card(card.card_id)
        if eligibility.resolution_status != "resolved" or eligibility.value is None:
            continue
        empty_build = _character_build(card.card_id, "empty")
        empty_result = assemble_character_build(rules, empty_build)
        action = next(
            (
                (item.action_id, item.effective_level)
                for item in empty_result.effective_skill_levels
                if rules.action_definition(item.action_id, item.effective_level)
                is not None
            ),
            None,
        )
        if (
            empty_result.assembly_status != "assembled"
            or empty_result.battle_admission_status != "admitted"
            or action is None
        ):
            continue
        same_candidates = tuple(
            definition
            for definition in definitions
            if definition.path_type == eligibility.value.character_path_type
        )
        cross_candidates = tuple(
            definition
            for definition in definitions
            if definition.path_type != eligibility.value.character_path_type
        )
        if not same_candidates or not cross_candidates:
            continue
        same_definition = sorted(
            same_candidates,
            key=lambda item: (
                not bool(item.superimposition_levels[0].static_properties),
                item.definition_key.stable_id,
            ),
        )[0]
        cross_definition = sorted(
            cross_candidates,
            key=lambda item: item.definition_key.stable_id,
        )[0]
        same_build = _character_build(
            card.card_id,
            "same",
            _equipment_build(card.card_id, same_definition, "same"),
        )
        cross_build = _character_build(
            card.card_id,
            "cross",
            _equipment_build(card.card_id, cross_definition, "cross"),
        )
        same_result = assemble_character_build(rules, same_build)
        cross_result = assemble_character_build(rules, cross_build)
        if (
            same_result.assembly_status == "assembled"
            and same_result.battle_admission_status == "blocked"
            and cross_result.assembly_status == "assembled"
            and cross_result.battle_admission_status == "admitted"
            and same_result.equipment_assembly_result is not None
            and cross_result.equipment_assembly_result is not None
        ):
            return {
                "card": card,
                "eligibility": eligibility.value,
                "action": action,
                "empty_build": empty_build,
                "empty_result": empty_result,
                "same_definition": same_definition,
                "same_build": same_build,
                "same_result": same_result,
                "same_equipment_result": same_result.equipment_assembly_result,
                "cross_definition": cross_definition,
                "cross_build": cross_build,
                "cross_result": cross_result,
                "cross_equipment_result": cross_result.equipment_assembly_result,
            }
    raise RuntimeError("no structurally selected S4 formal light-cone cases exist")


def _equipment_build(
    card_id: str,
    definition: LightConeDefinitionIR,
    suffix: str,
    *,
    level: int = 1,
    promotion: int = 0,
    superimposition: int = 1,
    instance_id: str | None = None,
) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=f"validation:p8_s4:equipment:{suffix}",
        character_card_id=card_id,
        light_cone=LightConeInstanceInput(
            instance_id=instance_id or f"validation:p8_s4:light_cone:{suffix}",
            definition_key=definition.definition_key,
            level=level,
            promotion=promotion,
            superimposition=superimposition,
        ),
    )


def _character_build(
    card_id: str,
    suffix: str,
    equipment: EquipmentBuildInput | None = None,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:p8_s4:character:{suffix}",
        character_card_id=card_id,
        level=1,
        promotion=0,
        eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=equipment
        or EquipmentBuildInput(
            build_id=f"validation:p8_s4:equipment:{suffix}",
            character_card_id=card_id,
        ),
    )


def _formal_positive_checks(rules: RuleBook, cases: dict[str, Any]) -> dict[str, Any]:
    empty = cases["empty_result"]
    cross = cases["cross_result"]
    same = cases["same_result"]
    cross_equipment = cases["cross_equipment_result"]
    same_equipment = cases["same_equipment_result"]
    empty_equipment = empty.equipment_assembly_result
    cross_selection = cross_equipment.light_cone_selection
    same_selection = same_equipment.light_cone_selection
    checks = {
        "empty_equipment_assembled_and_battle_admitted": empty.assembly_status
        == "assembled"
        and empty.battle_admission_status == "admitted"
        and empty_equipment is not None
        and empty_equipment.assembly_status == "assembled"
        and empty_equipment.battle_admission_status == "admitted"
        and empty_equipment.light_cone_selection is None,
        "cross_path_assembled_base_applied_passive_inactive_and_admitted": cross.assembly_status
        == "assembled"
        and cross.battle_admission_status == "admitted"
        and _activation_status(cross) == "inactive"
        and cross_selection is not None
        and len(cross_selection.base_contribution_ids) == 6
        and not cross_selection.passive_contribution_ids
        and len(cross_equipment.static_contributions) == 6
        and not cross_equipment.battle_admission_blockers,
        "same_path_assembled_base_applied_passive_active_and_battle_blocked": same.assembly_status
        == "assembled"
        and same.battle_admission_status == "blocked"
        and _activation_status(same) == "active"
        and same_selection is not None
        and len(same_selection.base_contribution_ids) == 6
        and len(same_equipment.static_contributions)
        == 6 + len(same_selection.passive_contribution_ids)
        and bool(same_equipment.battle_admission_blockers),
        "cross_path_formal_character_admission_rebuild_passes": not validate_character_build_admission(
            rules, cases["cross_build"], cross
        ),
        "same_path_read_only_panel_cannot_enter_formal_battle": bool(
            validate_character_build_admission(rules, cases["same_build"], same)
        ),
        "character_panel_contains_each_equipment_contribution_once": all(
            sum(
                item.contribution_id == contribution.contribution_id
                for item in cross.contribution_ledger
            )
            == 1
            for contribution in cross_equipment.static_contributions
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _growth_oracle_checks(
    rules: RuleBook,
    catalog: LightConeCatalogBuildResult,
    sources: LightConeCatalogSourceBundle,
    cases: dict[str, Any],
) -> dict[str, Any]:
    promotion_index: dict[tuple[str, int], list[tuple[int, Mapping[str, object]]]] = {}
    if not isinstance(sources.promotion_rows, list):
        return {"raw_promotion_source_is_array": False, "ok": False}
    for row_index, row in enumerate(sources.promotion_rows):
        if not isinstance(row, Mapping):
            continue
        equipment_id = _raw_int(row.get("EquipmentID"))
        stage = _raw_int(row.get("Promotion")) if "Promotion" in row else 0
        if equipment_id is not None and stage is not None:
            promotion_index.setdefault((str(equipment_id), stage), []).append(
                (row_index, row)
            )
    skill_index: dict[tuple[str, int], list[Mapping[str, object]]] = {}
    if not isinstance(sources.skill_rows, list):
        return {"raw_skill_source_is_array": False, "ok": False}
    for row in sources.skill_rows:
        if not isinstance(row, Mapping):
            continue
        skill_id = _raw_int(row.get("SkillID"))
        rank = _raw_int(row.get("Level"))
        if skill_id is not None and rank is not None:
            skill_index.setdefault((str(skill_id), rank), []).append(row)

    card_by_path: dict[str, str] = {}
    playable_by_path: dict[
        str,
        tuple[str, CharacterBuildAssemblyResult],
    ] = {}
    for card in sorted(rules.ir.character_data_cards, key=lambda item: item.card_id):
        resolution = rules.character_equipment_eligibility_for_card(card.card_id)
        if resolution.resolution_status == "resolved" and resolution.value is not None:
            path_type = resolution.value.character_path_type
            card_by_path.setdefault(path_type, card.card_id)
            if path_type not in playable_by_path:
                empty_result = assemble_character_build(
                    rules,
                    _character_build(
                        card.card_id,
                        f"oracle-empty:{path_type}",
                    ),
                )
                if (
                    empty_result.assembly_status == "assembled"
                    and empty_result.battle_admission_status == "admitted"
                    and empty_result.base_panel is not None
                ):
                    playable_by_path[path_type] = (card.card_id, empty_result)

    differences: list[dict[str, Any]] = []
    comparison_count = 0
    boundary_case_count = 0
    rank_case_count = 0
    character_panel_case_count = 0

    def compare(label: str, actual: object, expected: object) -> None:
        nonlocal comparison_count
        comparison_count += 1
        if actual != expected and len(differences) < 16:
            differences.append({"label": label, "actual": actual, "expected": expected})

    property_fields = (
        ("max_hp", "BaseHP", "BaseHPAdd"),
        ("attack", "BaseAttack", "BaseAttackAdd"),
        ("defense", "BaseDefence", "BaseDefenceAdd"),
    )
    for definition in catalog.canonical_definitions:
        playable_candidates = tuple(
            value
            for path_type, value in sorted(playable_by_path.items())
            if path_type != definition.path_type
        )
        if not playable_candidates:
            playable_candidates = tuple(playable_by_path.values())
        if not playable_candidates:
            compare("playable_character_for_final_panel", False, True)
            continue
        card_id, empty_character_result = playable_candidates[0]
        tiers = tuple(sorted(definition.promotion_tiers, key=lambda item: item.promotion_stage))
        for tier_index, tier in enumerate(tiers):
            candidates = promotion_index.get(
                (definition.raw_equipment_id, tier.promotion_stage), ()
            )
            compare("promotion_raw_row_count", len(candidates), 1)
            if len(candidates) != 1:
                continue
            row_index, raw_row = candidates[0]
            minimum_level = 1 if tier_index == 0 else tiers[tier_index - 1].max_level
            for level in sorted({minimum_level, tier.max_level}):
                boundary_case_count += 1
                build = _equipment_build(
                    card_id,
                    definition,
                    f"oracle:{definition.raw_equipment_id}:{tier.promotion_stage}:{level}",
                    level=level,
                    promotion=tier.promotion_stage,
                )
                result = assemble_equipment_build(rules, build)
                boundary_selection = result.light_cone_selection
                compare("boundary_assembly_status", result.assembly_status, "assembled")
                compare(
                    "boundary_admission_rebuild",
                    validate_equipment_assembly_admission(rules, build, result),
                    (),
                )
                character_panel_case_count += 1
                character_result = assemble_character_build(
                    rules,
                    _character_build(
                        card_id,
                        (
                            f"oracle-panel:{definition.raw_equipment_id}:"
                            f"{tier.promotion_stage}:{level}"
                        ),
                        build,
                    ),
                )
                compare(
                    "character_boundary_assembly_status",
                    character_result.assembly_status,
                    "assembled",
                )
                compare(
                    "cross_path_character_boundary_battle_admission",
                    character_result.battle_admission_status,
                    "admitted",
                )
                compare(
                    "character_boundary_panel_present",
                    character_result.base_panel is not None,
                    True,
                )
                by_property = {
                    property_type: tuple(
                        item
                        for item in result.static_contributions
                        if boundary_selection is not None
                        and item.contribution_id
                        in boundary_selection.base_contribution_ids
                        if item.property_type == property_type
                    )
                    for property_type, _, _ in property_fields
                }
                for property_type, base_field, add_field in property_fields:
                    rows = by_property[property_type]
                    compare("base_growth_contribution_count", len(rows), 2)
                    if len(rows) != 2:
                        continue
                    base = next(
                        (item for item in rows if item.calculation.calculation_kind == "constant"),
                        None,
                    )
                    growth = next(
                        (
                            item
                            for item in rows
                            if item.calculation.calculation_kind == "linear_growth"
                        ),
                        None,
                    )
                    compare("base_operand_present", base is not None, True)
                    compare("growth_operand_present", growth is not None, True)
                    if base is None or growth is None:
                        continue
                    raw_base = _raw_decimal_container(raw_row.get(base_field))
                    raw_add = _raw_decimal_container(raw_row.get(add_field))
                    expected = raw_base + raw_add * Decimal(level - 1)
                    actual = sum(Decimal(item.exact_value) for item in rows)
                    compare("exact_boundary_value", actual, expected)
                    if (
                        character_result.base_panel is not None
                        and empty_character_result.base_panel is not None
                    ):
                        compare(
                            "character_final_panel_value",
                            Decimal(
                                getattr(character_result.base_panel, property_type)
                            ),
                            Decimal(
                                getattr(
                                    empty_character_result.base_panel,
                                    property_type,
                                )
                            )
                            + expected,
                        )
                    compare("base_operand", Decimal(base.calculation.base_value), raw_base)
                    compare("growth_operand", Decimal(growth.calculation.per_level_value), raw_add)
                    compare("growth_level_offset", growth.calculation.level_offset, level - 1)
                    compare(
                        "base_source_json_path",
                        base.source.evidence.get("json_path"),
                        f"$[{row_index}].{base_field}.Value",
                    )
                    compare(
                        "growth_source_json_path",
                        growth.source.evidence.get("json_path"),
                        f"$[{row_index}].{add_field}.Value",
                    )
                compare(
                    "character_ledger_contains_each_equipment_term_once",
                    all(
                        sum(
                            ledger_item.contribution_id
                            == equipment_item.contribution_id
                            for ledger_item in character_result.contribution_ledger
                        )
                        == 1
                        for equipment_item in result.static_contributions
                    ),
                    True,
                )

        base_signature: tuple[dict[str, Any], ...] | None = None
        for rank in definition.superimposition_levels:
            rank_case_count += 1
            build = _equipment_build(
                card_id,
                definition,
                f"rank:{definition.raw_equipment_id}:{rank.level}",
                superimposition=rank.level,
                instance_id=f"validation:p8_s4:rank:{definition.raw_equipment_id}",
            )
            result = assemble_equipment_build(rules, build)
            selection = result.light_cone_selection
            compare("rank_assembly_status", result.assembly_status, "assembled")
            compare("rank_selection_present", selection is not None, True)
            candidates = skill_index.get((definition.skill_id, rank.level), ())
            compare("rank_raw_row_count", len(candidates), 1)
            if selection is not None and len(candidates) == 1:
                raw_row = candidates[0]
                raw_parameters = raw_row.get("ParamList")
                raw_properties = raw_row.get("AbilityProperty")
                compare(
                    "rank_parameter_indices",
                    selection.parameter_indices,
                    tuple(range(len(raw_parameters))) if isinstance(raw_parameters, list) else (),
                )
                compare(
                    "rank_property_indices",
                    selection.static_property_indices,
                    tuple(range(len(raw_properties))) if isinstance(raw_properties, list) else (),
                )
            signature = tuple(
                item.to_json()
                for item in result.static_contributions
                if selection is not None
                and item.contribution_id in selection.base_contribution_ids
            )
            if base_signature is None:
                base_signature = signature
            compare("base_stats_independent_of_superimposition", signature, base_signature)

    checks = {
        "all_published_paths_have_real_character_eligibility": all(
            definition.path_type in card_by_path
            for definition in catalog.canonical_definitions
        ),
        "every_light_cone_path_has_cross_path_playable_character_oracle": all(
            any(path_type != definition.path_type for path_type in playable_by_path)
            for definition in catalog.canonical_definitions
        ),
        "all_growth_boundaries_and_rank_rows_match_raw_decimal_oracle": not differences,
        "all_growth_boundaries_merge_into_character_final_panel": character_panel_case_count
        == boundary_case_count
        and not differences,
        "shared_promotion_boundary_was_exercised": any(
            len(definition.promotion_tiers) > 1
            for definition in catalog.canonical_definitions
        ),
        "raw_numeric_documents_contain_no_float": not _contains_float(
            sources.promotion_rows
        )
        and not _contains_float(sources.skill_rows),
        "oracle_exercised_without_fixed_catalog_count": boundary_case_count > 0
        and rank_case_count > 0
        and comparison_count > boundary_case_count,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        **checks,
        "comparison_count": comparison_count,
        "boundary_case_count": boundary_case_count,
        "character_panel_case_count": character_panel_case_count,
        "rank_case_count": rank_case_count,
        "differences": differences,
    }


def _source_and_gap_checks(
    rules: RuleBook,
    catalog: LightConeCatalogBuildResult,
    cases: dict[str, Any],
) -> dict[str, Any]:
    same_result = cases["same_equipment_result"]
    same_definition = cases["same_definition"]
    selection = same_result.light_cone_selection
    activation = same_result.activation_decisions[0]
    blockers = {item.channel: item for item in same_result.battle_admission_blockers}
    dynamic = blockers.get("dynamic_ability")
    assembler_source = inspect.getsource(
        __import__(
            "simulator_v8_clean_core.builds.equipment_assembler",
            fromlist=["assemble_equipment_build"],
        )
    )
    checks = {
        "selection_contains_only_stable_references_not_definition_payloads": selection
        is not None
        and set(selection.to_json()).isdisjoint(
            {
                "promotion_tiers",
                "superimposition_levels",
                "stat_values",
                "parameters",
                "static_properties",
                "mechanism_payload",
            }
        ),
        "base_and_growth_operands_have_separate_real_sources": selection
        is not None
        and all(
            len(
                {
                    item.source.evidence.get("json_path")
                    for item in same_result.static_contributions
                    if item.contribution_id in selection.base_contribution_ids
                    if item.property_type == property_type
                }
            )
            == 2
            for property_type in ("max_hp", "attack", "defense")
        ),
        "activation_basis_preserves_both_raw_sources_and_derived_policy": activation.basis.character_path_source
        == cases["eligibility"].source
        and activation.basis.light_cone_path_source == same_definition.source
        and activation.basis.policy_origin == "build_assembly_rule"
        and activation.basis.comparison_policy
        == "exact_internal_path_identity_equality",
        "s4_regression_does_not_require_retired_static_passive_blocker": "static_passive"
        not in blockers,
        "s4_fixture_without_s6_catalog_reports_lowering_gap": dynamic is not None
        and dynamic.gap_classification == "lowering_gap"
        and same_definition.ability_source is not None
        and not rules.standalone_ability_graphs_by_name(
            same_definition.ability_source.ability_name
        ),
        "pre_s6_generic_graph_admission_excludes_equipment_sources": all(
            definition.ability_source is not None
            and not _standalone_ability_source_admitted(
                definition.ability_source.source.source_path
            )
            for definition in catalog.canonical_definitions
        ),
        "production_gap_classifier_has_no_equipment_path_hardcode": "Config/ConfigAbility/Equip/"
        not in assembler_source,
        "s4_creates_no_equipment_graph_reference_or_dynamic_selection": all(
            not definition.mechanism_ref_ids
            for definition in catalog.canonical_definitions
        )
        and not same_result.dynamic_mechanisms,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _scenario_and_uniqueness_checks(
    rules: RuleBook,
    cases: dict[str, Any],
) -> dict[str, Any]:
    cross_payload = _scenario_payload(
        cases,
        (("ally:cross", cases["cross_build"]),),
    )
    cross_scenario = ScenarioLoader().load_dict(cross_payload)
    cross_identity = IdentityResolver(rules).validate(cross_scenario)
    built = ScenarioStateBuilder(rules).build(cross_scenario) if cross_identity.ok else None

    shared_instance_id = "validation:p8_s4:shared-team-instance"
    definition = cases["cross_definition"]
    card_id = cases["card"].card_id
    duplicate_equipment_a = _equipment_build(
        card_id,
        definition,
        "duplicate:a",
        instance_id=shared_instance_id,
    )
    duplicate_equipment_b = _equipment_build(
        card_id,
        definition,
        "duplicate:b",
        instance_id=shared_instance_id,
    )
    duplicate_builds = (
        _character_build(card_id, "duplicate:a", duplicate_equipment_a),
        _character_build(card_id, "duplicate:b", duplicate_equipment_b),
    )
    duplicate_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            cases,
            (("ally:duplicate:a", duplicate_builds[0]), ("ally:duplicate:b", duplicate_builds[1])),
        )
    )
    duplicate_identity = IdentityResolver(rules).validate(duplicate_scenario)

    distinct_equipment = (
        _equipment_build(card_id, definition, "distinct:a", instance_id="validation:p8_s4:distinct:a"),
        _equipment_build(card_id, definition, "distinct:b", instance_id="validation:p8_s4:distinct:b"),
    )
    distinct_builds = (
        _character_build(card_id, "distinct:a", distinct_equipment[0]),
        _character_build(card_id, "distinct:b", distinct_equipment[1]),
    )
    distinct_scenario = ScenarioLoader().load_dict(
        _scenario_payload(
            cases,
            (("ally:distinct:a", distinct_builds[0]), ("ally:distinct:b", distinct_builds[1])),
        )
    )
    distinct_identity = IdentityResolver(rules).validate(distinct_scenario)
    checks = {
        "cross_path_formal_scenario_identity_and_state_build_pass": cross_identity.ok
        and built is not None
        and "ally:cross" in built.state.units,
        "same_instance_reuse_is_rejected_by_team_identity": any(
            error == f"equipment_instance_id_reused:{shared_instance_id}"
            for error in duplicate_identity.errors
        ),
        "same_definition_with_distinct_instance_ids_is_legal": not validate_equipment_instance_uniqueness(
            list(distinct_equipment)
        )
        and distinct_identity.ok,
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        **checks,
        "formal_scenario_build_count": 1,
        "duplicate_identity_errors": list(duplicate_identity.errors),
        "distinct_identity_errors": list(distinct_identity.errors),
    }


def _scenario_payload(
    cases: dict[str, Any],
    allies: tuple[tuple[str, CharacterBuildInput], ...],
) -> dict[str, Any]:
    units = [
        {
            "unit_id": unit_id,
            "side": "ally",
            "entity_ref": cases["card"].entity_ref,
            "level": build.level,
            "eidolon_level": build.eidolon_level,
            "position": index + 1,
            "build_mode": "assembled_character_build",
            "panel": None,
            "character_build": build.to_json(),
            "initial_condition": {"hp_mode": "full", "initial_energy": "0"},
        }
        for index, (unit_id, build) in enumerate(allies)
    ]
    units.append(
        {
            "unit_id": "enemy:fixture",
            "side": "enemy",
            "entity_ref": _ENEMY_ENTITY_ID,
            "level": 1,
            "position": 1,
            "build_mode": "kernel_fixture",
            "panel": {
                "max_hp": 1000,
                "hp": 1000,
                "attack": 100,
                "defense": 100,
                "speed": 100,
                "toughness": 60,
                "max_toughness": 60,
            },
        }
    )
    return {
        "scenario_id": f"validation:p8_s4:{allies[0][0]}",
        "version": VALIDATION_VERSION,
        "units": units,
        "route": [
            {
                "actor_id": allies[0][0],
                "action_ref": cases["action"][0],
                "action_level": cases["action"][1],
                "target_ids": ["enemy:fixture"],
                "source": "manual",
            }
        ],
        "battle_setup": {"timeline": {"mode": "runtime_initialize"}},
    }


def _negative_matrix(
    rules: RuleBook,
    ir: CanonicalIR,
    cases: dict[str, Any],
) -> dict[str, Any]:
    card_id = cases["card"].card_id
    definition = cases["same_definition"]
    first_tier = min(definition.promotion_tiers, key=lambda item: item.promotion_stage)
    invalid_builds = {
        "light_cone_level_zero": _equipment_build(
            card_id,
            definition,
            "level-zero",
            level=0,
        ),
        "level_outside_selected_promotion": _equipment_build(
            card_id,
            definition,
            "invalid-level",
            level=first_tier.max_level + 1,
        ),
        "promotion_outside_definition": _equipment_build(
            card_id,
            definition,
            "invalid-promotion",
            promotion=definition.max_promotion + 1,
        ),
        "superimposition_level_zero": _equipment_build(
            card_id,
            definition,
            "rank-zero",
            superimposition=0,
        ),
        "superimposition_outside_definition": _equipment_build(
            card_id,
            definition,
            "invalid-rank",
            superimposition=definition.max_superimposition + 1,
        ),
        "unknown_light_cone_definition": EquipmentBuildInput(
            build_id="validation:p8_s4:unknown-definition",
            character_card_id=card_id,
            light_cone=LightConeInstanceInput(
                instance_id="validation:p8_s4:unknown-definition",
                definition_key=EquipmentDefinitionKey(
                    "light_cone", "validation:p8_s4:unknown"
                ),
                level=1,
                promotion=0,
                superimposition=1,
            ),
        ),
        "missing_character_equipment_eligibility": _equipment_build(
            "validation:p8_s4:missing-character-card",
            definition,
            "missing-character-eligibility",
        ),
    }
    rows = {
        name: assemble_equipment_build(rules, build).assembly_status == "blocked"
        for name, build in invalid_builds.items()
    }

    unpublished = replace(definition, publication_status="unpublished")
    unpublished_rules = RuleBook(replace(ir, light_cone_definitions=(unpublished,)))
    rows["unpublished_definition"] = assemble_equipment_build(
        unpublished_rules,
        _equipment_build(card_id, unpublished, "unpublished"),
    ).assembly_status == "blocked"

    status_unknown = replace(
        definition,
        publication_status="status_unknown",
        release_field_present=False,
    )
    status_unknown_rules = RuleBook(
        replace(ir, light_cone_definitions=(status_unknown,))
    )
    rows["status_unknown_definition"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            status_unknown_rules,
            _equipment_build(card_id, status_unknown, "status-unknown"),
        ),
        "light_cone_publication_status_not_admitted:status_unknown",
    )

    incomplete = replace(
        definition,
        coverage_status="blocked",
        blocked_reason="validation_light_cone_projection_incomplete",
    )
    incomplete_rules = RuleBook(replace(ir, light_cone_definitions=(incomplete,)))
    rows["incomplete_projection_definition"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            incomplete_rules,
            _equipment_build(card_id, incomplete, "incomplete-projection"),
        ),
        "equipment_definition_not_lowered",
    )

    duplicate_rules = RuleBook(
        replace(ir, light_cone_definitions=(definition, definition))
    )
    rows["duplicate_definition_identity"] = assemble_equipment_build(
        duplicate_rules,
        _equipment_build(card_id, definition, "duplicate-definition"),
    ).assembly_status == "blocked"
    rows["superimposition_level_missing"] = _raises(
        lambda: replace(
            definition,
            superimposition_levels=definition.superimposition_levels[1:],
        )
    )
    rows["superimposition_level_duplicate"] = _raises(
        lambda: replace(
            definition,
            superimposition_levels=(
                definition.superimposition_levels[0],
                *definition.superimposition_levels,
            ),
        )
    )

    eligibility = cases["eligibility"]
    other_eligibility = next(
        item
        for item in ir.character_equipment_eligibilities
        if item.character_card_id != eligibility.character_card_id
        and item.character_path_type != eligibility.character_path_type
    )
    owner_mismatch_card = replace(
        cases["card"],
        equipment_eligibility_id=other_eligibility.definition_key.definition_identity,
    )
    owner_mismatch_rules = RuleBook(
        replace(
            ir,
            character_data_cards=tuple(
                owner_mismatch_card
                if item.card_id == cases["card"].card_id
                else item
                for item in ir.character_data_cards
            ),
        )
    )
    rows["eligibility_character_owner_mismatch"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            owner_mismatch_rules,
            cases["same_build"].equipment_build,
        ),
        "character_equipment_eligibility_owner_mismatch",
    )

    profile_mismatch = replace(
        eligibility,
        character_profile_id=other_eligibility.character_profile_id,
    )
    profile_mismatch_rules = RuleBook(
        replace(ir, character_equipment_eligibilities=(profile_mismatch,))
    )
    rows["eligibility_profile_mismatch"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            profile_mismatch_rules,
            cases["same_build"].equipment_build,
        ),
        "character_equipment_eligibility_profile_mismatch",
    )

    path_mismatch = replace(
        eligibility,
        character_path_type=other_eligibility.character_path_type,
        passive_activation_path_types=(other_eligibility.character_path_type,),
    )
    path_mismatch_rules = RuleBook(
        replace(ir, character_equipment_eligibilities=(path_mismatch,))
    )
    rows["eligibility_path_mismatch"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            path_mismatch_rules,
            cases["same_build"].equipment_build,
        ),
        "character_equipment_eligibility_path_mismatch",
    )

    source_mismatch = replace(
        eligibility,
        source=other_eligibility.source,
    )
    source_mismatch_rules = RuleBook(
        replace(ir, character_equipment_eligibilities=(source_mismatch,))
    )
    rows["eligibility_source_mismatch"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            source_mismatch_rules,
            cases["same_build"].equipment_build,
        ),
        "character_equipment_eligibility_source_mismatch",
    )

    foreign_definition = next(
        item
        for item in ir.light_cone_definitions
        if item.definition_key != definition.definition_key
    )
    selected_tier = min(
        definition.promotion_tiers,
        key=lambda item: item.promotion_stage,
    )
    foreign_tier = min(
        foreign_definition.promotion_tiers,
        key=lambda item: item.promotion_stage,
    )
    wrong_promotion_source = replace(
        definition,
        promotion_tiers=(
            replace(selected_tier, source=foreign_tier.source),
            *tuple(
                item
                for item in definition.promotion_tiers
                if item.promotion_stage != selected_tier.promotion_stage
            ),
        ),
    )
    wrong_promotion_rules = RuleBook(
        replace(ir, light_cone_definitions=(wrong_promotion_source,))
    )
    rows["promotion_source_mismatch"] = _assembly_blocked_with_reason(
        assemble_equipment_build(
            wrong_promotion_rules,
            _equipment_build(card_id, wrong_promotion_source, "wrong-promotion-source"),
        ),
        "light_cone_promotion_source_binding_mismatch",
    )

    selected_rank = min(
        definition.superimposition_levels,
        key=lambda item: item.level,
    )
    foreign_rank = min(
        foreign_definition.superimposition_levels,
        key=lambda item: item.level,
    )
    rows["superimposition_source_mismatch"] = _raises(
        lambda: replace(selected_rank, source=foreign_rank.source)
    )

    ability_source = definition.ability_source
    if ability_source is None:
        rows["unrelated_same_name_graph_cannot_change_gap_classification"] = False
    else:
        unrelated_graph = StandaloneAbilityGraphIR(
            standalone_ability_graph_id="validation:p8_s4:unrelated-same-name-graph",
            ability_name=ability_source.ability_name,
            source_mode="validation_fixture",
            phase_ids=(),
            task_ids=(),
            executable_task_ids=(),
            source=IRSource(
                source_path="validation/unrelated_ability.json",
                raw_type="StandaloneAbilityList",
                raw_id=ability_source.ability_name,
                evidence={"ability_index": ability_source.record_index},
            ),
            coverage_status="blocked",
            blocked_reason="validation_unrelated_graph",
        )
        unrelated_rules = RuleBook(
            replace(ir, standalone_ability_graphs=(unrelated_graph,))
        )
        unrelated_result = assemble_equipment_build(
            unrelated_rules,
            cases["same_build"].equipment_build,
        )
        rows["unrelated_same_name_graph_cannot_change_gap_classification"] = any(
            blocker.channel == "dynamic_ability"
            and blocker.gap_classification == "lowering_gap"
            for blocker in unrelated_result.battle_admission_blockers
        )

    same_result = cases["same_equipment_result"]
    same_activation = same_result.activation_decisions[0]
    rows["opposite_activation_status_forgery"] = _raises(
        lambda: replace(
            same_activation,
            activation_status="inactive",
            reason_code="light_cone_path_mismatch",
        )
    )
    rows["forged_active_admitted_result_rejected_by_canonical_rebuild"] = _raises(
        lambda: replace(
            same_result,
            battle_admission_status="admitted",
            battle_admission_blockers=(),
        )
    )
    damaged_instance = thaw_json(
        cases["same_build"].equipment_build.light_cone.to_json()
    )
    damaged_instance["instance_fingerprint"] = "0" * 64
    rows["damaged_instance_fingerprint"] = _raises(
        lambda: LightConeInstanceInput.from_json(damaged_instance)
    )
    rows["foreign_equipment_type_cannot_masquerade_as_light_cone"] = _raises(
        lambda: LightConeInstanceInput(
            instance_id="validation:p8_s4:relic-masquerading-as-light-cone",
            definition_key=EquipmentDefinitionKey(
                "relic_template",
                definition.definition_key.definition_identity,
            ),
            level=1,
            promotion=0,
            superimposition=1,
        )
    )
    damaged_build = thaw_json(cases["same_build"].equipment_build.to_json())
    damaged_build["build_fingerprint"] = "0" * 64
    rows["damaged_build_fingerprint"] = _raises(
        lambda: EquipmentBuildInput.from_json(damaged_build)
    )
    damaged_result_fingerprint = thaw_json(same_result.to_json())
    damaged_result_fingerprint["result_fingerprint"] = "0" * 64
    rows["damaged_assembly_result_fingerprint"] = _raises(
        lambda: EquipmentAssemblyResult.from_json(damaged_result_fingerprint)
    )
    damaged_result = thaw_json(same_result.to_json())
    damaged_result["unexpected_legacy_payload"] = {}
    rows["assembly_result_unknown_field"] = _raises(
        lambda: EquipmentAssemblyResult.from_json(damaged_result)
    )
    damaged_selection = thaw_json(same_result.to_json())
    damaged_selection["light_cone_selection"]["promotion_tier"] = {}
    rows["selection_cannot_copy_definition_payload"] = _raises(
        lambda: EquipmentAssemblyResult.from_json(damaged_selection)
    )
    damaged_ledger = thaw_json(same_result.to_json())
    damaged_ledger["source_ledger"][0]["legacy_effect_payload"] = {}
    rows["source_ledger_cannot_carry_legacy_payload"] = _raises(
        lambda: EquipmentAssemblyResult.from_json(damaged_ledger)
    )
    foreign_contribution = replace(
        same_result.static_contributions[0],
        source_ref=BuildSourceRef("light_cone", "validation:p8_s4:foreign"),
    )
    rows["base_contribution_cannot_claim_foreign_definition"] = _raises(
        lambda: replace(
            same_result,
            static_contributions=(
                foreign_contribution,
                *same_result.static_contributions[1:],
            ),
        )
    )
    rows["blocked_result_cannot_carry_selection"] = _raises(
        lambda: EquipmentAssemblyResult(
            assembly_id="validation:p8_s4:blocked-with-selection",
            build_fingerprint=cases["same_build"].equipment_build.build_fingerprint,
            assembly_status="blocked",
            battle_admission_status="blocked",
            light_cone_selection=same_result.light_cone_selection,
            diagnostics=(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id="validation:p8_s4:blocked-with-selection",
                    reason="validation_blocked_result",
                ),
            ),
        )
    )
    rows["blocked_result_cannot_carry_contribution"] = _raises(
        lambda: EquipmentAssemblyResult(
            assembly_id="validation:p8_s4:blocked-with-contribution",
            build_fingerprint=cases["same_build"].equipment_build.build_fingerprint,
            assembly_status="blocked",
            battle_admission_status="blocked",
            static_contributions=(same_result.static_contributions[0],),
            diagnostics=(
                EquipmentAssemblyDiagnostic(
                    diagnostic_id="validation:p8_s4:blocked-with-contribution",
                    reason="validation_blocked_result",
                ),
            ),
        )
    )

    cross_result = cases["cross_equipment_result"]
    extra_passive_contribution = replace(
        cross_result.static_contributions[0],
        contribution_id="validation:p8_s4:cross-path-static-passive",
    )
    rows["cross_path_cannot_carry_static_passive_contribution"] = _raises(
        lambda: replace(
            cross_result,
            static_contributions=(
                *cross_result.static_contributions,
                extra_passive_contribution,
            ),
        )
    )
    cross_dynamic = DynamicMechanismSelection(
        selection_id="validation:p8_s4:cross-path-dynamic",
        mechanism_key=EquipmentDefinitionKey(
            "equipment_mechanism",
            "validation:p8_s4:cross-path-dynamic",
        ),
        target_definition_key=cross_result.light_cone_selection.definition_key,
        graph_ref_id="validation:p8_s4:cross-path-graph",
        provider_source_id=cross_result.light_cone_selection.instance_id,
        wearer_character_card_id=cases["cross_build"].character_card_id,
        parameter_basis=LightConeRankParameterBasis(
            definition_key=cross_result.light_cone_selection.definition_key,
            skill_id=cross_result.light_cone_selection.skill_id,
            superimposition_level=(
                cross_result.light_cone_selection.superimposition_level
            ),
            source=cross_result.light_cone_selection.superimposition_source,
        ),
        parameter_bindings=(),
        source=cases["cross_definition"].ability_source.source,
        coverage_status="lowered",
        blocked_reason="",
    )
    rows["cross_path_cannot_carry_dynamic_passive_selection"] = _raises(
        lambda: replace(
            cross_result,
            dynamic_mechanisms=(cross_dynamic,),
        )
    )
    rows["cross_path_cannot_carry_passive_blocker"] = _raises(
        lambda: replace(
            cross_result,
            battle_admission_status="blocked",
            battle_admission_blockers=(
                replace(
                    same_result.battle_admission_blockers[0],
                    target_definition_key=cases[
                        "cross_definition"
                    ].definition_key,
                ),
            ),
        )
    )
    required_rows = frozenset(
        {
            "eligibility_character_owner_mismatch",
            "eligibility_profile_mismatch",
            "eligibility_path_mismatch",
            "eligibility_source_mismatch",
            "light_cone_level_zero",
            "superimposition_level_zero",
            "superimposition_level_missing",
            "superimposition_level_duplicate",
            "foreign_equipment_type_cannot_masquerade_as_light_cone",
            "damaged_assembly_result_fingerprint",
            "unpublished_definition",
            "status_unknown_definition",
            "incomplete_projection_definition",
            "promotion_source_mismatch",
            "superimposition_source_mismatch",
            "opposite_activation_status_forgery",
            "blocked_result_cannot_carry_selection",
            "blocked_result_cannot_carry_contribution",
            "cross_path_cannot_carry_static_passive_contribution",
            "cross_path_cannot_carry_dynamic_passive_selection",
            "cross_path_cannot_carry_passive_blocker",
        }
    )
    checks = {
        "all_negative_rows_blocked_or_rejected": all(rows.values()),
        "all_required_negative_categories_are_explicitly_present": required_rows.issubset(
            rows
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return {
        **checks,
        "rows": rows,
        "required_rows": sorted(required_rows),
        "rulebook_build_count": 10,
    }


def _model_contract_checks(cases: dict[str, Any]) -> dict[str, Any]:
    result = cases["same_equipment_result"]
    ordinary_json = copy.deepcopy(result.to_json())
    parsed = EquipmentAssemblyResult.from_json(ordinary_json)
    parsed_before = parsed.to_json()
    ordinary_json["activation_decisions"][0]["basis"]["character_path_type"] = (
        "late-mutation"
    )
    ordinary_json["static_contributions"].clear()
    selection = result.light_cone_selection
    source_keys = {
        item.source.evidence.get("json_path")
        for item in result.static_contributions
        if selection is not None
        and item.contribution_id in selection.base_contribution_ids
    }
    checks = {
        "ordinary_json_dicts_and_lists_are_accepted": parsed.to_json()
        == result.to_json(),
        "parsed_result_is_recursively_detached_from_input": parsed.to_json()
        == parsed_before,
        "result_fingerprint_is_stable_after_external_json_mutation": parsed.result_fingerprint
        == result.result_fingerprint,
        "every_static_contribution_has_real_distinct_field_source": len(source_keys)
        == 6
        and all(item.source.source_path for item in result.static_contributions),
        "every_battle_blocker_has_real_source": all(
            blocker.source_refs
            and all(source.source_path for source in blocker.source_refs)
            for blocker in result.battle_admission_blockers
        ),
    }
    checks["ok"] = all(value is True for value in checks.values())
    return checks


def _activation_status(result: CharacterBuildAssemblyResult) -> str:
    equipment = result.equipment_assembly_result
    if equipment is None or len(equipment.activation_decisions) != 1:
        return "missing"
    return equipment.activation_decisions[0].activation_status


def _assembly_blocked_with_reason(
    result: EquipmentAssemblyResult,
    reason: str,
) -> bool:
    return bool(
        result.assembly_status == "blocked"
        and result.battle_admission_status == "blocked"
        and any(diagnostic.reason == reason for diagnostic in result.diagnostics)
    )


def _raw_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _raw_decimal_container(value: object) -> Decimal:
    if not isinstance(value, Mapping):
        raise TypeError("raw stat field must be an object")
    raw = value.get("Value")
    if isinstance(raw, bool) or not isinstance(raw, (int, Decimal)):
        raise TypeError("raw stat value must be int or Decimal")
    result = Decimal(raw)
    if not result.is_finite():
        raise ValueError("raw stat value must be finite")
    return result


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_float(item) for item in value)
    return False


def _raises(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate P8-S4 light-cone instance assembly"
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
