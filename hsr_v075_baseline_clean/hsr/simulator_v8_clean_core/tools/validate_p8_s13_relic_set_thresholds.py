from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ..build_types import StatCalculation
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.relic_set_assembler import assemble_relic_set_activations
from ..equipment.models import (
    EquipmentAssemblyResult,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    RelicAssemblySelection,
    RelicInstanceInput,
    RelicMainAffixComputation,
    RelicSetDefinitionIR,
    RelicSetStaticPropertyIR,
    RelicSetThresholdIR,
    RelicTemplateDefinitionIR,
    make_equipment_source,
)
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.relic_cards import build_relic_catalog, require_complete_relic_catalog


def run_validation(tbgd_root: Path) -> dict[str, object]:
    started = perf_counter()
    catalog_result = build_relic_catalog(tbgd_root)
    catalog = require_complete_relic_catalog(catalog_result)
    rules, fixture_templates, unpublished_fixture_templates = _rules_with_non_2_4_fixture(
        catalog,
        dict(thaw_json(catalog_result.source_content_fingerprint)),
    )
    templates = tuple(
        item
        for item in catalog.template_definitions
        if item.publication_status == "published" and item.mode == "BASIC"
    )
    sets = {item.definition_key: item for item in catalog.set_definitions}
    groups = {item.definition_key: item for item in catalog.main_affix_group_definitions}
    slots = {item.definition_key: item for item in catalog.slot_definitions}
    affixes = {item.definition_key: item for item in catalog.main_affix_definitions}

    outer_sets = _templates_by_set(templates, sets, "outer")
    planar_sets = _templates_by_set(templates, sets, "planar")
    outer_four_key, outer_four = _find_set(outer_sets, 4)
    outer_two_a_key, outer_two_a = _find_set(
        outer_sets, 2, excluded={outer_four_key}
    )
    outer_two_b_key, outer_two_b = _find_set(
        outer_sets, 2, excluded={outer_four_key, outer_two_a_key}
    )
    planar_pair_key, planar_pair = _find_set(planar_sets, 2)
    planar_other_key, planar_other = _find_set(
        planar_sets, 1, excluded={planar_pair_key}
    )

    cases: dict[str, object] = {}
    empty = _assemble(rules, (), groups, "empty")
    cases["empty"] = empty
    outer_four_result = _assemble(rules, outer_four[:4], groups, "outer-four")
    cases["outer_four"] = outer_four_result
    outer_two_plus_two = _assemble(
        rules,
        (*outer_two_a[:2], *_distinct_templates(outer_two_b, outer_two_a[:2], 2)),
        groups,
        "outer-two-plus-two",
    )
    cases["outer_two_plus_two"] = outer_two_plus_two
    outer_two_plus_one_plus_one = _assemble(
        rules,
        (
            *outer_two_a[:2],
            *_distinct_templates(outer_two_b, outer_two_a[:2], 1),
            *_distinct_templates(
                outer_four,
                (*outer_two_a[:2], *_distinct_templates(outer_two_b, outer_two_a[:2], 1)),
                1,
            ),
        ),
        groups,
        "outer-two-plus-one-plus-one",
    )
    cases["outer_two_plus_one_plus_one"] = outer_two_plus_one_plus_one
    planar_pair_result = _assemble(rules, planar_pair[:2], groups, "planar-pair")
    cases["planar_pair"] = planar_pair_result
    planar_mismatch = _assemble(
        rules,
        (planar_pair[0], planar_other[0]),
        groups,
        "planar-mismatch",
    )
    cases["planar_mismatch"] = planar_mismatch
    planar_partial = _assemble(rules, planar_pair[:1], groups, "planar-partial")
    cases["planar_partial"] = planar_partial
    isolated = _assemble(
        rules,
        (outer_two_a[0], planar_pair[0]),
        groups,
        "domain-isolation",
    )
    cases["domain_isolation"] = isolated
    replacement_baseline_templates = (
        *outer_two_a[:2],
        *_distinct_templates(outer_two_b, outer_two_a[:2], 2),
    )
    replacement_baseline = _assemble(
        rules,
        replacement_baseline_templates,
        groups,
        "controlled-replacement",
    )
    replacement = _assemble(
        rules,
        (
            _template_for_slot(outer_four, outer_two_a[0].slot_key),
            outer_two_a[1],
            *replacement_baseline_templates[2:],
        ),
        groups,
        "controlled-replacement",
    )
    cases["replacement"] = replacement
    permutation_input = _build_input(outer_four[:4], groups, "outer-four")
    permuted = _result_case(
        assemble_equipment_build(
            rules,
            replace(permutation_input, relics=tuple(reversed(permutation_input.relics))),
        )
    )
    cases["permuted"] = permuted
    duplicate_input = _build_input((outer_four[0],), groups, "duplicate-instance")
    duplicate = _result_case(
        assemble_equipment_build(
            rules,
            replace(duplicate_input, relics=(duplicate_input.relics[0],) * 2),
        )
    )
    cases["duplicate"] = duplicate

    outer_four_input = _build_input(outer_four[:4], groups, "outer-four")
    outer_four_assembly = assemble_equipment_build(rules, outer_four_input)
    missing_activation_payload = outer_four_assembly.to_json()
    missing_activation_payload["relic_set_activation_decisions"] = []
    missing_activation_channel_rejected = _rejects(
        lambda: EquipmentAssemblyResult.from_json(missing_activation_payload)
    ) and _rejects(
        lambda: replace(outer_four_assembly, relic_set_activation_decisions=())
    )
    forged_decision_rejected = _rejects(
        lambda: replace(
            outer_four_assembly.relic_set_activation_decisions[0],
            decision_id="forged",
        )
    )

    fixture_selections = tuple(
        _fixture_selection(template, index, groups, slots, affixes)
        for index, template in enumerate(fixture_templates)
    )
    fixture_decisions, fixture_diagnostics = assemble_relic_set_activations(
        rules,
        fixture_selections,
    )
    unpublished_decisions, unpublished_diagnostics = assemble_relic_set_activations(
        rules,
        tuple(
            _fixture_selection(template, index, groups, slots, affixes)
            for index, template in enumerate(unpublished_fixture_templates)
        ),
    )
    ui_payload = _build_input(outer_two_a[:2], groups, "ui-negative").to_json()
    ui_payload["active_set_counts"] = {"forged": 99}
    try:
        EquipmentBuildInput.from_json(ui_payload)
        ui_input_rejected = False
    except (TypeError, ValueError):
        ui_input_rejected = True

    expected_outer_set = outer_four_key
    active_outer_four = _active_requirements(outer_four_result, expected_outer_set)
    active_two_plus_two = {
        key: _active_requirements(outer_two_plus_two, key)
        for key in (outer_two_a_key, outer_two_b_key)
    }
    predicates = {
        "only_admitted_relics_counted": duplicate["assembly_status"] == "blocked"
        and not duplicate["decisions"],
        "thresholds_loaded_from_definition": _threshold_keys_match_definitions(
            outer_four_result, sets[outer_four_key]
        ),
        "higher_threshold_retains_lower_threshold": active_outer_four == {2, 4},
        "outer_four_piece_correct": active_outer_four == {2, 4},
        "outer_two_plus_two_correct": active_two_plus_two == {
            outer_two_a_key: {2}, outer_two_b_key: {2}
        },
        "outer_two_plus_one_plus_one_correct": _active_requirements(
            outer_two_plus_one_plus_one, outer_two_a_key
        ) == {2} and len(_all_active_sets(outer_two_plus_one_plus_one)) == 1,
        "planar_matching_pair_correct": _active_requirements(
            planar_pair_result, planar_pair_key
        ) == {2},
        "planar_mismatched_pair_inactive": not _all_active(planar_mismatch),
        "planar_partial_inactive": not _all_active(planar_partial),
        "outer_planar_counts_isolated": not _all_active(isolated),
        "duplicate_instance_not_counted": duplicate["assembly_status"] == "blocked"
        and any("equipment_instance_id_reused" in item for item in duplicate["diagnostics"]),
        "invalid_relic_blocks_before_counting": duplicate["assembly_status"] == "blocked"
        and not duplicate["decisions"],
        "ui_set_active_input_rejected": ui_input_rejected,
        "activation_sources_complete": _sources_complete(outer_four_result),
        "activation_channel_complete": missing_activation_channel_rejected,
        "decision_id_derived": forged_decision_rejected,
        "input_order_deterministic": (
            outer_four_result["build_fingerprint"] == permuted["build_fingerprint"]
            and outer_four_result["decisions"] == permuted["decisions"]
            and outer_four_result["result_fingerprint"] == permuted["result_fingerprint"]
        ),
        "non_2_4_threshold_fixture": not fixture_diagnostics
        and [item.required_count for item in fixture_decisions] == [1, 3]
        and all(item.activation_status == "active" for item in fixture_decisions),
        "unpublished_set_blocks_atomically": not unpublished_decisions
        and any(
            item.reason == "relic_set_publication_status_not_admitted"
            for item in unpublished_diagnostics
        ),
        "controlled_replacement_isolated": (
            replacement_baseline["build_fingerprint"] != replacement["build_fingerprint"]
            and replacement_baseline["result_fingerprint"] != replacement["result_fingerprint"]
            and _decisions_for_set(replacement_baseline, outer_two_b_key)
            == _decisions_for_set(replacement, outer_two_b_key)
        ),
        "static_effects_not_applied": not outer_four_result["static_contributions"]
        and not outer_four_result["dynamic_mechanisms"],
        "blocker_narrowed_to_static_contributions": set(
            outer_four_result["blocker_reasons"]
        ) == {"relic_static_contributions_not_assembled"},
    }
    return {
        "ok": all(predicates.values()),
        "predicates": predicates,
        "resource": {
            "catalog_build_count": 1,
            "rulebook_build_count": 1,
            "case_count": len(cases) + 1,
            "wall_seconds": round(perf_counter() - started, 6),
        },
        "cases": cases,
        "fixture_decisions": [item.to_json() for item in fixture_decisions],
    }


def _rules_with_non_2_4_fixture(
    catalog: object,
    fingerprint: dict[str, object],
) -> tuple[
    RuleBook,
    tuple[RelicTemplateDefinitionIR, ...],
    tuple[RelicTemplateDefinitionIR, ...],
]:
    source = lambda raw_type, raw_id: make_equipment_source(
        source_path="validation/p8_s13_relic_set_thresholds.json",
        raw_type=raw_type,
        raw_id=raw_id,
        json_path=f"$.{raw_type}[{raw_id}]",
        source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )
    outer_domain = next(
        item for item in catalog.domain_definitions if item.domain == "outer"
    )
    slots = tuple(
        item
        for item in catalog.slot_definitions
        if item.definition_key in outer_domain.slot_keys
    )[:3]
    base_templates = tuple(
        next(
            item
            for item in catalog.template_definitions
            if item.slot_key == slot.definition_key
            and item.publication_status == "published"
            and item.mode == "BASIC"
        )
        for slot in slots
    )
    fixture_set_key = EquipmentDefinitionKey("relic_set", "p8_s13_fixture")
    fixture_templates = tuple(
        RelicTemplateDefinitionIR(
            definition_key=EquipmentDefinitionKey("relic_template", f"p8_s13_fixture_{index}"),
            raw_relic_id=f"p8_s13_fixture_{index}",
            publication_status="published",
            slot_key=template.slot_key,
            domain_key=outer_domain.definition_key,
            set_key=fixture_set_key,
            rarity=template.rarity,
            max_level=template.max_level,
            main_affix_group_key=template.main_affix_group_key,
            sub_affix_group_key=template.sub_affix_group_key,
            mode="BASIC",
            raw_mode="BASIC",
            source=source("RelicConfig", f"p8_s13_fixture_{index}"),
            coverage_status="lowered",
            blocked_reason="",
        )
        for index, template in enumerate(base_templates)
    )
    threshold_keys = tuple(
        EquipmentDefinitionKey("relic_set_threshold", f"p8_s13_fixture:{count}")
        for count in (1, 3)
    )
    fixture_set = RelicSetDefinitionIR(
        definition_key=fixture_set_key,
        raw_set_id="p8_s13_fixture",
        publication_status="published",
        release_field_present=True,
        domain_key=outer_domain.definition_key,
        slot_keys=tuple(item.slot_key for item in fixture_templates),
        template_keys=tuple(item.definition_key for item in fixture_templates),
        threshold_keys=threshold_keys,
        source=source("RelicSetConfig", "p8_s13_fixture"),
        coverage_status="lowered",
        blocked_reason="",
    )
    thresholds = tuple(
        RelicSetThresholdIR(
            definition_key=key,
            set_key=fixture_set_key,
            require_count=count,
            static_properties=(
                RelicSetStaticPropertyIR(
                    property_index=0,
                    property_type="HPDelta",
                    exact_value="1",
                    source=source("RelicSetSkillStaticProperty", f"p8_s13_fixture:{count}:0"),
                ),
            ),
            parameters=(),
            ability_source=None,
            source=source("RelicSetSkillConfig", f"p8_s13_fixture:{count}"),
            coverage_status="lowered",
            blocked_reason="",
        )
        for key, count in zip(threshold_keys, (1, 3), strict=True)
    )
    unpublished_set_key = EquipmentDefinitionKey(
        "relic_set",
        "p8_s13_unpublished_fixture",
    )
    unpublished_template = RelicTemplateDefinitionIR(
        definition_key=EquipmentDefinitionKey(
            "relic_template",
            "p8_s13_unpublished_fixture_0",
        ),
        raw_relic_id="p8_s13_unpublished_fixture_0",
        publication_status="published",
        slot_key=base_templates[0].slot_key,
        domain_key=outer_domain.definition_key,
        set_key=unpublished_set_key,
        rarity=base_templates[0].rarity,
        max_level=base_templates[0].max_level,
        main_affix_group_key=base_templates[0].main_affix_group_key,
        sub_affix_group_key=base_templates[0].sub_affix_group_key,
        mode="BASIC",
        raw_mode="BASIC",
        source=source("RelicConfig", "p8_s13_unpublished_fixture_0"),
        coverage_status="lowered",
        blocked_reason="",
    )
    unpublished_threshold_key = EquipmentDefinitionKey(
        "relic_set_threshold",
        "p8_s13_unpublished_fixture:1",
    )
    unpublished_set = RelicSetDefinitionIR(
        definition_key=unpublished_set_key,
        raw_set_id="p8_s13_unpublished_fixture",
        publication_status="unpublished",
        release_field_present=True,
        domain_key=outer_domain.definition_key,
        slot_keys=(unpublished_template.slot_key,),
        template_keys=(unpublished_template.definition_key,),
        threshold_keys=(unpublished_threshold_key,),
        source=source("RelicSetConfig", "p8_s13_unpublished_fixture"),
        coverage_status="lowered",
        blocked_reason="",
    )
    unpublished_threshold = RelicSetThresholdIR(
        definition_key=unpublished_threshold_key,
        set_key=unpublished_set_key,
        require_count=1,
        static_properties=(
            RelicSetStaticPropertyIR(
                property_index=0,
                property_type="HPDelta",
                exact_value="1",
                source=source(
                    "RelicSetSkillStaticProperty",
                    "p8_s13_unpublished_fixture:1:0",
                ),
            ),
        ),
        parameters=(),
        ability_source=None,
        source=source("RelicSetSkillConfig", "p8_s13_unpublished_fixture:1"),
        coverage_status="lowered",
        blocked_reason="",
    )
    fixture_domain = replace(
        outer_domain,
        set_keys=(
            *outer_domain.set_keys,
            fixture_set_key,
            unpublished_set_key,
        ),
    )
    domains = tuple(
        fixture_domain if item.definition_key == outer_domain.definition_key else item
        for item in catalog.domain_definitions
    )
    ir = CanonicalIR(
        version="p8-s13-validation",
        relic_domain_definitions=domains,
        relic_slot_definitions=catalog.slot_definitions,
        relic_main_affix_group_definitions=catalog.main_affix_group_definitions,
        relic_main_affix_definitions=catalog.main_affix_definitions,
        relic_sub_affix_group_definitions=catalog.sub_affix_group_definitions,
        relic_sub_affix_definitions=catalog.sub_affix_definitions,
        relic_template_definitions=(
            *catalog.template_definitions,
            *fixture_templates,
            unpublished_template,
        ),
        relic_set_definitions=(
            *catalog.set_definitions,
            fixture_set,
            unpublished_set,
        ),
        relic_set_thresholds=(
            *catalog.set_thresholds,
            *thresholds,
            unpublished_threshold,
        ),
    )
    return RuleBook(ir), fixture_templates, (unpublished_template,)


def _templates_by_set(templates: tuple[object, ...], sets: dict[object, object], domain: str) -> dict[object, tuple[object, ...]]:
    grouped: dict[object, list[object]] = {}
    for template in templates:
        if sets[template.set_key].domain_key.definition_identity == domain:
            grouped.setdefault(template.set_key, []).append(template)
    return {
        key: tuple(_unique_slots(items))
        for key, items in grouped.items()
    }


def _find_set(grouped: dict[object, tuple[object, ...]], count: int, excluded: set[object] = frozenset()) -> tuple[object, tuple[object, ...]]:
    for key, templates in sorted(grouped.items(), key=lambda item: item[0].stable_id):
        if key not in excluded and len(templates) >= count:
            return key, templates
    raise ValueError(f"no source-backed set with {count} unique slots")


def _unique_slots(templates: list[object]) -> tuple[object, ...]:
    selected: list[object] = []
    slots: set[object] = set()
    for template in sorted(templates, key=lambda item: item.definition_key.stable_id):
        if template.slot_key not in slots:
            selected.append(template)
            slots.add(template.slot_key)
    return tuple(selected)


def _distinct_templates(
    candidates: tuple[object, ...],
    occupied: tuple[object, ...],
    count: int,
) -> tuple[object, ...]:
    occupied_slots = {item.slot_key for item in occupied}
    result = tuple(
        item for item in candidates if item.slot_key not in occupied_slots
    )[:count]
    if len(result) != count:
        raise ValueError("source-backed set lacks the requested distinct slots")
    return result


def _template_for_slot(
    templates: tuple[object, ...],
    slot_key: object,
) -> object:
    return next(item for item in templates if item.slot_key == slot_key)


def _build_input(templates: tuple[object, ...], groups: dict[object, object], build_id: str) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=build_id,
        character_card_id="p8-s13-validation",
        relics=tuple(
            RelicInstanceInput(
                instance_id=f"{build_id}:{index}",
                template_key=template.definition_key,
                slot_key=template.slot_key,
                level=0,
                main_affix_key=groups[template.main_affix_group_key].affix_keys[0],
            )
            for index, template in enumerate(templates)
        ),
    )


def _assemble(rules: RuleBook, templates: tuple[object, ...], groups: dict[object, object], build_id: str) -> dict[str, object]:
    return _result_case(
        assemble_equipment_build(rules, _build_input(templates, groups, build_id))
    )


def _result_case(result: object) -> dict[str, object]:
    return {
        "assembly_status": result.assembly_status,
        "battle_admission_status": result.battle_admission_status,
        "build_fingerprint": result.build_fingerprint,
        "result_fingerprint": result.result_fingerprint,
        "decisions": [item.to_json() for item in result.relic_set_activation_decisions],
        "diagnostics": [item.reason for item in result.diagnostics],
        "blocker_reasons": [item.reason_code for item in result.battle_admission_blockers],
        "static_contributions": [item.to_json() for item in result.static_contributions],
        "dynamic_mechanisms": [item.to_json() for item in result.dynamic_mechanisms],
    }


def _fixture_selection(
    template: RelicTemplateDefinitionIR,
    index: int,
    groups: dict[object, object],
    slots: dict[object, object],
    affixes: dict[object, object],
) -> RelicAssemblySelection:
    group = groups[template.main_affix_group_key]
    affix_key = group.affix_keys[0]
    affix = affixes[affix_key]
    slot = slots[template.slot_key]
    digest = hashlib.sha256(f"fixture:{index}".encode()).hexdigest()
    computation = RelicMainAffixComputation(
        template_key=template.definition_key,
        slot_key=template.slot_key,
        group_key=group.definition_key,
        affix_key=affix_key,
        property_type=affix.property_type,
        level=0,
        exact_value=affix.base_value,
        calculation=StatCalculation("linear_growth", affix.base_value),
        template_source=template.source,
        slot_source=slot.source,
        group_source=group.source,
        affix_source=affix.source,
    )
    return RelicAssemblySelection(
        instance_id=f"fixture:{index}",
        instance_fingerprint=digest,
        template_key=template.definition_key,
        slot_key=template.slot_key,
        level=0,
        publication_status="published",
        template_mode="BASIC",
        affix_validation_status="main_and_sub_affixes_validated",
        template_source=template.source,
        slot_source=computation.slot_source,
        main_affix=computation,
    )


def _active_requirements(case: dict[str, object], set_key: object) -> set[int]:
    return {
        item["required_count"]
        for item in case["decisions"]
        if item["set_key"] == set_key.to_json() and item["activation_status"] == "active"
    }


def _all_active(case: dict[str, object]) -> bool:
    return any(item["activation_status"] == "active" for item in case["decisions"])


def _all_active_sets(case: dict[str, object]) -> set[str]:
    return {
        item["set_key"]["stable_id"]
        for item in case["decisions"]
        if item["activation_status"] == "active"
    }


def _decisions_for_set(case: dict[str, object], set_key: object) -> list[object]:
    return [
        item
        for item in case["decisions"]
        if item["set_key"] == set_key.to_json()
    ]


def _rejects(callback: object) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def _threshold_keys_match_definitions(case: dict[str, object], relic_set: object) -> bool:
    return {item["threshold_key"]["stable_id"] for item in case["decisions"]} == {
        item.stable_id for item in relic_set.threshold_keys
    }


def _sources_complete(case: dict[str, object]) -> bool:
    return all(
        item["contributors"]
        and all(item[source]["raw_id"] for source in ("domain_source", "set_source", "threshold_source"))
        and all(contributor["template_source"]["raw_id"] for contributor in item["contributors"])
        for item in case["decisions"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_validation(args.tbgd_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": result["ok"], "predicates": result["predicates"], "resource": result["resource"]}, ensure_ascii=True, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
