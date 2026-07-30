from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from ..build_types import BuildSourceRef, StatCalculation, static_property_binding
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.equipment_assembler import validate_equipment_assembly_admission
from ..equipment.models import EquipmentAssemblyResult, EquipmentBuildInput
from ..equipment.models import EquipmentDefinitionKey
from ..equipment.models import LightConeInstanceInput, RelicInstanceInput
from ..equipment.models import RelicSubAffixRollInput, make_equipment_source
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.relic_cards import build_relic_catalog, require_complete_relic_catalog
from .validate_p8_s1_equipment_type_contract import _build_definition_fixture


VALIDATION_VERSION = "p8_s14_relic_static_contributions_v1"
UNKNOWN_PROPERTY = "P8S14UnknownRelicProperty"


def _index(items: Any) -> dict[Any, Any]:
    return {item.definition_key: item for item in items}


def _assembly_light_cone(definition: Any, fingerprint: dict[str, Any]) -> Any:
    equipment_id = definition.definition_key.definition_identity

    def source(raw_type: str, raw_id: str) -> Any:
        return make_equipment_source(
            source_path=f"validation/p8_s14/{raw_type.removesuffix('Value')}.json",
            raw_type=raw_type, raw_id=raw_id, json_path="$[0]",
            source_fingerprint=fingerprint, source_kind="validation_fixture",
        )

    tier = definition.promotion_tiers[0]
    promotion_id = f"{equipment_id}:{tier.promotion_stage}"
    values = tuple(
        replace(item, source=source("EquipmentPromotionConfigValue",
                                    f"{promotion_id}:{item.field_name}"))
        for item in tier.stat_values
    )
    tier = replace(tier, stat_values=values,
                   source=source("EquipmentPromotionConfig", promotion_id))
    rank = replace(definition.superimposition_levels[0], parameters=(), static_properties=())
    return replace(
        definition, path_type="P8S14FixtureOtherPath",
        promotion_tiers=(tier,),
        superimposition_levels=(rank,),
        source=source("EquipmentConfig", equipment_id),
    )


def run_validation(tbgd_root: Path) -> dict[str, Any]:
    started = perf_counter()
    catalog_result = build_relic_catalog(tbgd_root)
    catalog = require_complete_relic_catalog(catalog_result)
    fingerprint = dict(thaw_json(catalog_result.source_content_fingerprint))
    context = _build_context(catalog, fingerprint)
    rules = context["rules"]
    empty_build = EquipmentBuildInput(
        build_id="p8-s14-empty", character_card_id=context["character_card_id"]
    )
    empty_result = assemble_equipment_build(rules, empty_build)
    scattered_templates = _scattered_six_templates(catalog)
    scattered_build, scattered_result = _case(context, scattered_templates, "p8-s14-scattered", True)
    excluded = context["unknown_threshold"].definition_key
    static_threshold, static_templates = _threshold_sample(catalog, "static_only", excluded)
    dynamic_threshold, dynamic_templates = _threshold_sample(catalog, "dynamic_only", excluded)
    both_threshold, both_templates = _threshold_sample(catalog, "both", excluded)
    static_build, static_result = _case(context, static_templates, "p8-s14-static-only", True)
    _, dynamic_result = _case(context, dynamic_templates, "p8-s14-dynamic-only", False)
    _, both_result = _case(context, both_templates, "p8-s14-both", False)
    light_cone_build = replace(
        scattered_build,
        build_id="p8-s14-light-cone-plus-relic",
        light_cone=LightConeInstanceInput(
            instance_id="p8-s14-fixture-light-cone-instance",
            definition_key=context["light_cone"].definition_key,
            level=1,
            promotion=0,
            superimposition=1,
        ),
    )
    light_cone_result = assemble_equipment_build(rules, light_cone_build)
    _, unknown_result = _case(
        context, context["unknown_templates"], "p8-s14-unknown-property", False
    )
    permuted_result = assemble_equipment_build(
        rules, replace(scattered_build, relics=tuple(reversed(scattered_build.relics)))
    )
    reordered_result = replace(
        scattered_result,
        static_contributions=tuple(reversed(scattered_result.static_contributions)),
        source_ledger=tuple(reversed(scattered_result.source_ledger)),
    )
    static_matrix = _static_matrix(
        static_result, static_threshold, dynamic_result, dynamic_threshold, both_result, both_threshold
    )
    negative_matrix = _negative_matrix(rules, scattered_result, static_build, static_result)
    reconstruction = _decimal_reconstruction(scattered_result)
    walkback = _walkback(rules, scattered_result, static_result)
    property_types = sorted({
        *(item.property_type for item in catalog.main_affix_definitions),
        *(item.property_type for item in catalog.sub_affix_definitions),
        *(prop.property_type for threshold in catalog.set_thresholds for prop in threshold.static_properties),
    })
    contribution_kinds = Counter(
        item.source_ref.definition_kind for item in light_cone_result.static_contributions
    )
    scattered_affix_count = sum(1 + len(item.sub_affixes) for item in scattered_result.relic_selections)
    scattered_relic_terms = tuple(
        item for item in scattered_result.static_contributions
        if item.source_ref.definition_kind != "light_cone"
    )
    same_property_counts = Counter(
        (item.contribution_pool, item.property_type)
        for item in scattered_relic_terms
    )
    main_count = sum(item.contribution_id.startswith("relic_main_affix:") for item in scattered_relic_terms)
    sub_count = sum(item.contribution_id.startswith("relic_sub_affix:") for item in scattered_relic_terms)
    inactive_zero = all(
        not _terms_for_decision(scattered_result, decision.decision_id)
        for decision in scattered_result.relic_set_activation_decisions
        if decision.activation_status == "inactive"
    )
    unknown_blocked = (
        unknown_result.assembly_status == "blocked"
        and not unknown_result.static_contributions
        and not unknown_result.source_ledger
        and any(item.reason.startswith("relic_static_property_type_not_admitted:")
                for item in unknown_result.diagnostics)
    )
    combined_relic_count = sum(contribution_kinds[kind] for kind in (
        "relic_main_affix", "relic_sub_affix", "relic_set_threshold"
    ))
    predicates = {
        **{key: value for key, value in static_matrix.items() if key != "cases"},
        **negative_matrix,
        "main_affix_terms_one_to_one": main_count
        == len(scattered_result.relic_selections),
        "sub_affix_terms_one_to_one": sub_count
        == scattered_affix_count - len(scattered_result.relic_selections),
        "inactive_threshold_contributes_zero": inactive_zero,
        "same_property_terms_not_preaggregated": any(
            count > 1 for count in same_property_counts.values()
        )
        and len(scattered_relic_terms) == scattered_affix_count,
        "decimal_ledger_reconstructs_totals": reconstruction["ok"],
        "unknown_property_type_blocks_assembly": unknown_blocked,
        "all_terms_source_backed": walkback["ok"],
        "dynamic_runtime_effects_started": bool(dynamic_result.dynamic_mechanisms
                                                or both_result.dynamic_mechanisms),
        "input_order_deterministic": (
            scattered_result.result_fingerprint
            == permuted_result.result_fingerprint
            == reordered_result.result_fingerprint
        ),
        "actual_property_binding_coverage_complete": all(
            static_property_binding(item) is not None for item in property_types
        ),
        "empty_relic_build_valid": (
            empty_result.assembly_status == "assembled"
            and empty_result.battle_admission_status == "admitted"
            and not empty_result.static_contributions
            and not empty_result.source_ledger
        ),
        "no_light_cone_relic_build_valid": (
            scattered_result.assembly_status == "assembled"
            and scattered_result.battle_admission_status == "admitted"
            and len(scattered_result.relic_selections) == 6
            and len(scattered_relic_terms) == scattered_affix_count
        ),
        "light_cone_and_relic_channels_partitioned": (
            light_cone_result.assembly_status == "assembled"
            and light_cone_result.battle_admission_status == "admitted"
            and contribution_kinds["light_cone"] == 6
            and combined_relic_count == scattered_affix_count
        ),
    }
    positive = (
        value for key, value in predicates.items() if key != "dynamic_runtime_effects_started"
    )
    ok = all(value is True for value in positive) and not predicates["dynamic_runtime_effects_started"]
    inventory = catalog_result.source_inventory
    return {
        "validation_version": VALIDATION_VERSION,
        "ok": ok,
        "predicates": predicates,
        "property_binding": {
            "actual_property_types": property_types,
            "unmapped": [
                item for item in property_types if static_property_binding(item) is None
            ],
        },
        "static_matrix": static_matrix,
        "negative_matrix": negative_matrix,
        "decimal_reconstruction": reconstruction,
        "walkback": walkback,
        "resource": {
            "catalog_build_count": 1,
            "rulebook_build_count": 1,
            "source_file_count": len(inventory),
            "source_bytes": sum(item.byte_count for item in inventory),
            "wall_seconds": round(perf_counter() - started, 6),
            "artifact_bytes": 0,
        },
    }


def _build_context(catalog: Any, fingerprint: dict[str, Any]) -> dict[str, Any]:
    unknown_threshold = next(item for item in reversed(catalog.set_thresholds)
                             if item.static_properties)
    changed_property = replace(unknown_threshold.static_properties[0],
                               property_type=UNKNOWN_PROPERTY)
    changed_threshold = replace(
        unknown_threshold,
        static_properties=(changed_property, *unknown_threshold.static_properties[1:])
    )
    equipment_ir, equipment_fixture = _build_definition_fixture(fingerprint)
    light_cone = _assembly_light_cone(equipment_fixture["light_cone"], fingerprint)
    eligibility = equipment_fixture["eligibility"]
    ir = CanonicalIR(
        version=VALIDATION_VERSION,
        avatar_profiles=equipment_ir.avatar_profiles,
        character_data_cards=equipment_ir.character_data_cards,
        character_equipment_eligibilities=(eligibility,),
        light_cone_definitions=(light_cone,),
        equipment_ability_parameter_reads=equipment_ir.equipment_ability_parameter_reads,
        equipment_mechanism_refs=equipment_ir.equipment_mechanism_refs,
        standalone_ability_graphs=equipment_ir.standalone_ability_graphs,
        relic_domain_definitions=catalog.domain_definitions,
        relic_slot_definitions=catalog.slot_definitions,
        relic_main_affix_group_definitions=catalog.main_affix_group_definitions,
        relic_main_affix_definitions=catalog.main_affix_definitions,
        relic_sub_affix_group_definitions=catalog.sub_affix_group_definitions,
        relic_sub_affix_definitions=catalog.sub_affix_definitions,
        relic_template_definitions=catalog.template_definitions,
        relic_set_definitions=catalog.set_definitions,
        relic_set_thresholds=tuple(
            changed_threshold if item.definition_key == changed_threshold.definition_key else item
            for item in catalog.set_thresholds
        ),
    )
    return {
        "rules": RuleBook(ir),
        "character_card_id": eligibility.character_card_id,
        "light_cone": light_cone,
        "main_groups": _index(catalog.main_affix_group_definitions),
        "main_affixes": _index(catalog.main_affix_definitions),
        "sub_groups": _index(catalog.sub_affix_group_definitions),
        "sub_affixes": _index(catalog.sub_affix_definitions),
        "unknown_threshold": unknown_threshold,
        "unknown_templates": _templates_for_threshold(catalog, unknown_threshold),
    }


def _case(
    context: dict[str, Any], templates: tuple[Any, ...],
    build_id: str, with_sub_affixes: bool,
) -> tuple[EquipmentBuildInput, EquipmentAssemblyResult]:
    build = _build_input(context, templates, build_id, with_sub_affixes=with_sub_affixes)
    return build, assemble_equipment_build(context["rules"], build)


def _build_input(
    context: dict[str, Any], templates: tuple[Any, ...], build_id: str,
    *, with_sub_affixes: bool,
) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=build_id,
        character_card_id=context["character_card_id"],
        relics=tuple(
            _instance(context, template, f"{build_id}:{index}", with_sub_affixes=with_sub_affixes)
            for index, template in enumerate(templates)
        ),
    )


def _instance(
    context: dict[str, Any], template: Any, instance_id: str,
    *, with_sub_affixes: bool,
) -> RelicInstanceInput:
    main_group = context["main_groups"][template.main_affix_group_key]
    main_affix_key = next(
        key
        for key in main_group.affix_keys
        if static_property_binding(context["main_affixes"][key].property_type) is not None
    )
    main_property = context["main_affixes"][main_affix_key].property_type
    sub_rolls: tuple[RelicSubAffixRollInput, ...] = ()
    if with_sub_affixes:
        sub_group = context["sub_groups"][template.sub_affix_group_key]
        sub_affix_key = next(
            key
            for key in sub_group.affix_keys
            if context["sub_affixes"][key].property_type
            != main_property
            and static_property_binding(context["sub_affixes"][key].property_type) is not None
        )
        sub_rolls = (
            RelicSubAffixRollInput(affix_key=sub_affix_key, count=1, step=0),
        )
    return RelicInstanceInput(
        instance_id=instance_id,
        template_key=template.definition_key,
        slot_key=template.slot_key,
        level=0, main_affix_key=main_affix_key,
        sub_affix_rolls=sub_rolls,
    )


def _scattered_six_templates(catalog: Any) -> tuple[Any, ...]:
    selected: list[Any] = []
    slots: set[Any] = set()
    sets: set[Any] = set()
    for template in sorted(catalog.template_definitions, key=lambda item: item.definition_key.stable_id):
        if (
            template.publication_status == "published"
            and template.mode == "BASIC"
            and template.slot_key not in slots
            and template.set_key not in sets
        ):
            selected.append(template)
            slots.add(template.slot_key)
            sets.add(template.set_key)
    if len(selected) != 6:
        raise ValueError("source catalog lacks six scattered unique slots")
    return tuple(selected)


def _templates_for_threshold(catalog: Any, threshold: Any) -> tuple[Any, ...]:
    relic_set = _index(catalog.set_definitions)[threshold.set_key]
    templates = _index(item for item in catalog.template_definitions
                       if item.publication_status == "published" and item.mode == "BASIC")
    selected: list[Any] = []
    slots: set[Any] = set()
    for key in relic_set.template_keys:
        template = templates.get(key)
        if template is not None and template.slot_key not in slots:
            selected.append(template)
            slots.add(template.slot_key)
    if len(selected) < threshold.require_count:
        raise ValueError("source set lacks required unique slots")
    return tuple(selected[: threshold.require_count])


def _threshold_sample(
    catalog: Any,
    payload_class: str,
    excluded_key: EquipmentDefinitionKey,
) -> tuple[Any, tuple[Any, ...]]:
    thresholds_by_set: dict[Any, list[Any]] = {}
    for item in catalog.set_thresholds:
        thresholds_by_set.setdefault(item.set_key, []).append(item)
    candidates = sorted(catalog.set_thresholds,
                        key=lambda item: (item.require_count, item.definition_key.stable_id))
    for threshold in candidates:
        if threshold.definition_key == excluded_key:
            continue
        has_static = bool(threshold.static_properties)
        has_dynamic = threshold.ability_source is not None
        actual_class = "both" if has_static and has_dynamic else (
            "static_only" if has_static else "dynamic_only" if has_dynamic else "empty"
        )
        if actual_class != payload_class:
            continue
        active_thresholds = tuple(item for item in thresholds_by_set[threshold.set_key]
                                  if item.require_count <= threshold.require_count)
        if payload_class == "static_only" and any(item.ability_source is not None
                                                  for item in active_thresholds):
            continue
        if payload_class == "both" and not any(item.require_count < threshold.require_count
                                               and item.static_properties
                                               for item in active_thresholds):
            continue
        try:
            return threshold, _templates_for_threshold(catalog, threshold)
        except ValueError:
            continue
    raise ValueError(f"source catalog lacks payload class {payload_class}")


def _terms_for_decision(result: EquipmentAssemblyResult, decision_id: str) -> tuple[Any, ...]:
    prefix = f"relic_set_static:{decision_id}:"
    return tuple(
        item for item in result.static_contributions
        if item.contribution_id.startswith(prefix)
    )


def _static_matrix(
    static_result: EquipmentAssemblyResult, static_threshold: Any,
    dynamic_result: EquipmentAssemblyResult, dynamic_threshold: Any,
    both_result: EquipmentAssemblyResult, both_threshold: Any,
) -> dict[str, Any]:
    def measure(result: EquipmentAssemblyResult, threshold: Any) -> dict[str, Any]:
        decision = next(
            item for item in result.relic_set_activation_decisions
            if item.threshold_key == threshold.definition_key
        )
        return {
            "property_count": len(threshold.static_properties),
            "term_count": len(_terms_for_decision(result, decision.decision_id)),
            "blocker_count": sum(item.target_definition_key == threshold.definition_key
                                 for item in result.battle_admission_blockers),
            "battle_admission_status": result.battle_admission_status,
        }

    cases = {
        "static_only": measure(static_result, static_threshold),
        "dynamic_only": measure(dynamic_result, dynamic_threshold),
        "both": measure(both_result, both_threshold),
    }
    active = tuple(
        item for item in both_result.relic_set_activation_decisions
        if item.activation_status == "active"
        and item.set_key == both_threshold.set_key
        and item.static_property_indices
    )
    retained = len(active) >= 2 and all(
        len(_terms_for_decision(both_result, item.decision_id))
        == len(item.static_property_indices)
        for item in active
    )
    blockers = (
        *dynamic_result.battle_admission_blockers,
        *both_result.battle_admission_blockers,
    )
    return {
        "cases": cases,
        "active_set_property_terms_one_to_one": (
            cases["static_only"]["term_count"] == cases["static_only"]["property_count"]
            and cases["dynamic_only"]["term_count"] == 0
            and cases["both"]["term_count"] == cases["both"]["property_count"]
        ),
        "high_threshold_retains_lower_terms": retained,
        "static_dynamic_payloads_separate": (
            cases["static_only"]["blocker_count"] == 0
            and cases["static_only"]["battle_admission_status"] == "admitted"
            and cases["dynamic_only"]["blocker_count"] == 1
            and cases["both"]["blocker_count"] == 1
            and not dynamic_result.dynamic_mechanisms
            and not both_result.dynamic_mechanisms
        ),
        "light_cone_and_relic_blockers_independent": all(
            blocker.gap_classification == "lowering_gap"
            and blocker.reason_code
            == "relic_set_dynamic_ability_graph_not_lowered"
            and blocker.target_definition_key.definition_kind == "relic_set_threshold"
            for blocker in blockers
        ),
    }


def _negative_matrix(
    rules: RuleBook, scattered_result: EquipmentAssemblyResult,
    static_build: EquipmentBuildInput, static_result: EquipmentAssemblyResult,
) -> dict[str, bool]:
    first = scattered_result.static_contributions[0]
    first_ledger = next(
        item for item in scattered_result.source_ledger
        if item.ledger_entry_id == f"equipment_source:{first.contribution_id}"
    )
    missing_rejected = _rejects(
        lambda: replace(
            scattered_result,
            static_contributions=tuple(item for item in scattered_result.static_contributions
                                       if item != first),
            source_ledger=tuple(item for item in scattered_result.source_ledger
                                if item != first_ledger),
        )
    )
    duplicate = replace(first, contribution_id=f"{first.contribution_id}:duplicate")
    duplicate_ledger = replace(
        first_ledger, ledger_entry_id=f"equipment_source:{duplicate.contribution_id}"
    )
    duplicate_source_rejected = _rejects(
        lambda: replace(
            scattered_result,
            static_contributions=(*scattered_result.static_contributions, duplicate),
            source_ledger=(*scattered_result.source_ledger, duplicate_ledger),
        )
    )
    set_term = next(
        item for item in static_result.static_contributions
        if item.contribution_id.startswith("relic_set_static:")
    )
    alternate_threshold_key = next(
        item.threshold_key for item in static_result.relic_set_activation_decisions
        if item.threshold_key.definition_identity != set_term.source_ref.definition_identity
    )
    wrong_term = replace(
        set_term,
        source_ref=BuildSourceRef(
            "relic_set_threshold", alternate_threshold_key.definition_identity
        ),
    )
    wrong_threshold_rejected = _rejects(
        lambda: replace(
            static_result,
            static_contributions=tuple(wrong_term if item == set_term else item
                                       for item in static_result.static_contributions),
        )
    )
    altered_exact = str(Decimal(set_term.exact_value) + Decimal(1))
    altered_set_term = replace(
        set_term,
        exact_value=altered_exact,
        calculation=StatCalculation(
            set_term.calculation.calculation_kind, altered_exact
        ),
    )
    structurally_valid_tamper = replace(
        static_result,
        static_contributions=tuple(altered_set_term if item == set_term else item
                                   for item in static_result.static_contributions),
    )
    rebuild_errors = validate_equipment_assembly_admission(
        rules, static_build, structurally_valid_tamper
    )
    return {
        "duplicate_source_consumption_rejected": duplicate_source_rejected,
        "forged_missing_or_misattached_terms_rejected": (
            missing_rejected and wrong_threshold_rejected
        ),
        "canonical_rebuild_is_stronger_boundary": rebuild_errors == (
            "equipment_assembly_result_does_not_match_canonical_rebuild",
        ),
    }


def _decimal_reconstruction(result: EquipmentAssemblyResult) -> dict[str, Any]:
    def aggregate(terms: Any) -> dict[tuple[str, str], Decimal]:
        totals: dict[tuple[str, str], Decimal] = {}
        for item in terms:
            key = (item.contribution_pool, item.property_type)
            totals[key] = totals.get(key, Decimal(0)) + Decimal(item.exact_value)
        return totals

    totals = aggregate(result.static_contributions)
    ledger_ids = {item.ledger_entry_id for item in result.source_ledger}
    return {
        "ok": totals == aggregate(reversed(result.static_contributions))
        and all(f"equipment_source:{item.contribution_id}" in ledger_ids
                for item in result.static_contributions),
        "group_count": len(totals),
        "term_count": len(result.static_contributions),
    }


def _resolved(resolution: Any) -> Any:
    return resolution.value if resolution.resolution_status == "resolved" else None


def _term_matches(
    result: EquipmentAssemblyResult,
    term: Any,
    definition_key: EquipmentDefinitionKey,
    raw_property_type: str,
    exact_value: str,
    source: Any,
) -> bool:
    if term is None:
        return False
    binding = static_property_binding(raw_property_type)
    ledger = next(
        (item for item in result.source_ledger
         if item.ledger_entry_id == f"equipment_source:{term.contribution_id}"),
        None,
    )
    return (
        binding is not None
        and term.source_ref == BuildSourceRef(
            definition_key.definition_kind, definition_key.definition_identity
        )
        and term.contribution_pool == binding.contribution_pool
        and term.property_type == binding.canonical_property_type
        and term.exact_value == exact_value
        and term.calculation.calculation_kind == binding.calculation_kind
        and term.calculation.exact_value == exact_value
        and term.source == source
        and source.evidence.get("source_kind") == "tbgd"
        and ledger is not None
        and ledger.channel == "static"
        and ledger.definition_key == definition_key
        and ledger.source == source
    )


def _source_evidence(source: Any) -> dict[str, Any]:
    return {
        "source_path": source.source_path, "json_path": source.evidence.get("json_path"),
        "raw_type": source.raw_type, "raw_id": source.raw_id,
    }


def _walkback(
    rules: RuleBook,
    scattered_result: EquipmentAssemblyResult,
    static_result: EquipmentAssemblyResult,
) -> dict[str, Any]:
    affix_terms = {
        item.contribution_id: item
        for item in scattered_result.static_contributions
        if item.contribution_id.startswith(
            ("relic_main_affix:", "relic_sub_affix:")
        )
    }
    expected_affix_ids: set[str] = set()
    main_samples: list[dict[str, Any]] = []
    sub_samples: list[dict[str, Any]] = []
    for selection in scattered_result.relic_selections:
        template = _resolved(
            rules.relic_template_definition(selection.template_key.definition_identity)
        )
        main = selection.main_affix
        contribution_id = (
            f"relic_main_affix:{selection.instance_id}:"
            f"affix:{main.affix_key.definition_identity}"
        )
        expected_affix_ids.add(contribution_id)
        term = affix_terms.get(contribution_id)
        definition = _resolved(
            rules.relic_main_affix_definition(main.affix_key.definition_identity)
        )
        linked = (
            template is not None
            and definition is not None
            and main.template_key == selection.template_key
            and main.slot_key == selection.slot_key
            and main.level == selection.level
            and template.definition_key == selection.template_key
            and template.slot_key == selection.slot_key
            and template.main_affix_group_key == main.group_key
            and template.source == selection.template_source
            and definition.definition_key == main.affix_key
            and definition.group_key == main.group_key
            and definition.property_type == main.property_type
            and definition.source == main.affix_source
            and _term_matches(
                scattered_result, term, main.affix_key, main.property_type,
                main.exact_value, main.affix_source,
            )
        )
        main_samples.append(
            {
                "ok": linked,
                "contribution_id": contribution_id,
                "instance_id": selection.instance_id,
                "template_key": selection.template_key.stable_id,
                "affix_key": main.affix_key.stable_id,
                "level": main.level,
                "raw_property_type": main.property_type,
                "exact_value": main.exact_value,
                **_source_evidence(main.affix_source),
            }
        )
        for sub in selection.sub_affixes:
            contribution_id = (
                f"relic_sub_affix:{selection.instance_id}:"
                f"affix:{sub.affix_key.definition_identity}"
            )
            expected_affix_ids.add(contribution_id)
            term = affix_terms.get(contribution_id)
            definition = _resolved(
                rules.relic_sub_affix_definition(sub.affix_key.definition_identity)
            )
            linked = (
                template is not None
                and definition is not None
                and sub.template_key == selection.template_key
                and template.sub_affix_group_key == sub.group_key
                and definition.definition_key == sub.affix_key
                and definition.group_key == sub.group_key
                and definition.property_type == sub.property_type
                and definition.base_value == sub.base_value
                and definition.step_value == sub.step_value
                and definition.step_count == sub.step_count
                and definition.source == sub.affix_source
                and _term_matches(
                    scattered_result, term, sub.affix_key, sub.property_type,
                    sub.exact_value, sub.affix_source,
                )
            )
            sub_samples.append(
                {
                    "ok": linked,
                    "contribution_id": contribution_id,
                    "instance_id": selection.instance_id,
                    "template_key": selection.template_key.stable_id,
                    "affix_key": sub.affix_key.stable_id,
                    "count": sub.count,
                    "step": sub.step,
                    "raw_property_type": sub.property_type,
                    "exact_value": sub.exact_value,
                    **_source_evidence(sub.affix_source),
                }
            )

    set_terms = {
        item.contribution_id: item
        for item in static_result.static_contributions
        if item.contribution_id.startswith("relic_set_static:")
    }
    expected_set_ids: set[str] = set()
    set_samples: list[dict[str, Any]] = []
    selected_instances = {
        item.instance_id for item in static_result.relic_selections
    }
    for decision in static_result.relic_set_activation_decisions:
        if decision.activation_status != "active":
            continue
        threshold = _resolved(
            rules.relic_set_threshold(decision.threshold_key.definition_identity)
        )
        contributor_ids = {
            item.instance_id for item in decision.contributors
        }
        activation_ok = (
            threshold is not None
            and decision.threshold_key == threshold.definition_key
            and decision.set_key == threshold.set_key
            and decision.required_count == threshold.require_count
            and decision.matched_count >= decision.required_count
            and decision.missing_count == 0
            and decision.static_property_indices
            == tuple(
                item.property_index
                for item in threshold.static_properties
            )
            and decision.ability_source == threshold.ability_source
            and decision.threshold_source == threshold.source
            and len(contributor_ids) == decision.matched_count
            and contributor_ids.issubset(selected_instances)
        )
        for property_index in decision.static_property_indices:
            contribution_id = (
                f"relic_set_static:{decision.decision_id}:"
                f"property:{property_index}"
            )
            expected_set_ids.add(contribution_id)
            term = set_terms.get(contribution_id)
            prop = (
                threshold.static_properties[property_index]
                if threshold is not None
                and property_index < len(threshold.static_properties)
                else None
            )
            linked = (
                activation_ok
                and prop is not None
                and prop.property_index == property_index
                and _term_matches(
                    static_result, term, decision.threshold_key, prop.property_type,
                    prop.exact_value, prop.source,
                )
            )
            set_samples.append(
                {
                    "ok": linked,
                    "contribution_id": contribution_id,
                    "decision_id": decision.decision_id,
                    "activation_status": decision.activation_status,
                    "matched_count": decision.matched_count,
                    "required_count": decision.required_count,
                    "contributors": sorted(contributor_ids),
                    "threshold_key": decision.threshold_key.stable_id,
                    "property_index": property_index,
                    "raw_property_type": (
                        prop.property_type if prop is not None else None
                    ),
                    "exact_value": (
                        prop.exact_value if prop is not None else None
                    ),
                    **_source_evidence(
                        prop.source
                        if prop is not None
                        else decision.threshold_source
                    ),
                }
            )

    samples = {
        "main": main_samples,
        "sub": sub_samples,
        "set": set_samples,
    }
    all_samples = (*main_samples, *sub_samples, *set_samples)
    return {
        "ok": (
            expected_affix_ids == set(affix_terms)
            and expected_set_ids == set(set_terms)
            and bool(main_samples)
            and bool(sub_samples)
            and bool(set_samples)
            and all(item["ok"] is True for item in all_samples)
        ),
        "counts": {
            "main": len(main_samples),
            "sub": len(sub_samples),
            "set": len(set_samples),
        },
        "samples": samples,
    }


def _rejects(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_validation(args.tbgd_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "summary.json"
    for _ in range(3):
        text = json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True)
        encoded = (text + "\n").encode("utf-8")
        result["resource"]["artifact_bytes"] = len(encoded)
    output.write_bytes(encoded)
    print(json.dumps({
        "ok": result["ok"],
        "predicates": result["predicates"],
        "resource": result["resource"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
