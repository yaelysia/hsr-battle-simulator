"""P8-S12 finished-relic sub-affix admission validation."""

from __future__ import annotations

import argparse
import json
from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from .. import BASELINE_VERSION
from ..build_types import static_property_binding
from ..builds.character_assembler import assemble_character_build
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.models import CharacterBuildInput
from ..builds.relic_affix_calculator import (
    admit_relic_main_affix, admit_relic_sub_affixes,
)
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentAssemblyResult,
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    LightConeAbilitySourceIR,
    LightConeDefinitionIR,
    LightConeInstanceInput,
    LightConePromotionTierIR,
    LightConePromotionValueIR,
    LightConeSuperimpositionLevelIR,
    RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
    RelicInstanceInput,
    RelicSubAffixDefinitionIR,
    RelicSubAffixRollInput,
    RelicTemplateDefinitionIR,
    make_equipment_source,
)
from ..immutable_json import thaw_json
from ..ir_types import IRSource, JSONValue
from ..rules.ir import (
    AvatarProfileIR, AvatarPromotionTierIR, CanonicalIR, CharacterDataCardIR,
)
from ..rules.rulebook import RuleBook
from ..tbgd.relic_cards import (
    RelicCanonicalCatalog,
    build_relic_catalog_from_source_bundle,
    load_relic_catalog_sources,
    require_complete_relic_catalog,
)
from .io import write_json


VERSION = "p8_s12_relic_sub_affix_rolls_v3"
CARD_ID = "validation:p8_s12:character-card"
LIGHT_CONE_ID = "validation:p8_s12:light-cone"


@dataclass(frozen=True)
class RawSubAffixOracle:
    base_value: Fraction
    step_value: Fraction
    step_num: int


def _oracle(raw: RawSubAffixOracle, count: int, step: int) -> str:
    value = raw.base_value * count + raw.step_value * step
    with localcontext() as context:
        context.prec = max(
            32, len(str(abs(value.numerator))) + len(str(value.denominator)) + 4
        )
        decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    text = format(decimal_value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _raw_sub_affix_oracle(value: object) -> dict[str, RawSubAffixOracle]:
    if not isinstance(value, list) or any(
        not isinstance(row, Mapping) for row in value
    ):
        raise RuntimeError("raw RelicSubAffixConfig must be an object array")
    result: dict[str, RawSubAffixOracle] = {}
    for row in cast(list[Mapping[str, object]], value):
        try:
            group_id, affix_id = row["GroupID"], row["AffixID"]
            step_num = row["StepNum"]
            base_value = cast(Mapping[str, object], row["BaseValue"])["Value"]
            step_value = cast(Mapping[str, object], row["StepValue"])["Value"]
        except (KeyError, TypeError):
            raise RuntimeError("raw sub-affix oracle fields are missing") from None
        if (
            not all(
                isinstance(item, (str, int)) and not isinstance(item, bool)
                for item in (group_id, affix_id)
            )
            or not all(
                isinstance(item, (Decimal, int)) and not isinstance(item, bool)
                for item in (base_value, step_value)
            )
            or type(step_num) is not int
            or step_num <= 0
        ):
            raise RuntimeError("raw sub-affix oracle fields are invalid")
        identity = f"{group_id}:{affix_id}"
        if identity in result:
            raise RuntimeError("raw sub-affix oracle identities must be unique")
        result[identity] = RawSubAffixOracle(
            Fraction(base_value), Fraction(step_value), step_num
        )
    return result


@dataclass(frozen=True)
class Fixture:
    template: RelicTemplateDefinitionIR
    main_key: EquipmentDefinitionKey
    affixes: tuple[RelicSubAffixDefinitionIR, ...]
    flat_ratio: tuple[RelicSubAffixDefinitionIR, RelicSubAffixDefinitionIR]
    main_conflict: RelicSubAffixDefinitionIR


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    sources = load_relic_catalog_sources(tbgd_root)
    catalog_result = build_relic_catalog_from_source_bundle(sources)
    raw_affixes = _raw_sub_affix_oracle(sources.sub_affix_rows)
    complete_catalog = require_complete_relic_catalog(catalog_result)
    catalog = _bounded_catalog(complete_catalog)
    rules = RuleBook(_focused_ir(catalog, catalog_result.source_content_fingerprint))
    fixture = _fixture(catalog)
    numeric = _numeric(rules, catalog, raw_affixes)
    constraints = _constraints(rules, catalog, fixture)
    hardening = _hardening(rules, catalog, fixture)
    integration = _integration(rules, catalog, fixture)

    negatives = {name: row["passed"] for name, row in constraints["negative_cases"].items()}
    schema_cases = hardening["schema_cases"]
    checks = {
        "raw_sub_affix_values_match_independent_oracle": numeric["ok"],
        "count_and_step_integer_bounds_enforced": (
            all(negatives[name] for name in ("count_zero", "step_negative", "step_above"))
            and schema_cases["bool_step"] and schema_cases["float_count"]
        ),
        "maximum_four_unique_properties_enforced": (
            constraints["four_upper"] and negatives["fifth_property"]
        ),
        "same_affix_rejected": negatives["same_affix"],
        "same_property_rejected": constraints["same_property"],
        "main_sub_same_property_rejected": negatives["main_conflict"],
        "distinct_flat_and_ratio_properties_can_coexist": constraints["flat_ratio"],
        "sub_affix_group_membership_enforced": negatives["wrong_group"],
        "per_affix_cumulative_step_bound_enforced": (
            constraints["step_bound"] and negatives["step_above"]
        ),
        "aggregate_upgrade_history_not_modeled": hardening["finished_schema"],
        "main_affix_identity_and_source_recomputed": all(
            hardening["canonical_input_cases"][name]
            for name in ("main_property", "main_source")
        ),
        "canonical_template_identity_and_source_recomputed": all(
            hardening["canonical_input_cases"][name]
            for name in ("template_json_path", "template_sub_affix_group")
        ),
        "bool_float_unknown_and_stale_inputs_rejected": all(schema_cases.values()),
        "input_containers_detached_and_immutable":
            all(hardening["input_isolation_cases"].values()),
        "valid_sibling_plus_invalid_relic_fails_atomically": integration["sibling"],
        "empty_relic_build_remains_battle_admitted": integration["empty"],
        "light_cone_and_no_light_cone_paths_future_blocked": integration["both_paths"],
        "character_build_cannot_admit_zero_relic_effects": integration["character"],
        "accepted_bounded_domain_reuse": (
            not catalog.reference_issues()
            and len(catalog.definitions()) < len(complete_catalog.definitions())
            and len(rules.equipment_definitions()) == len(catalog.definitions()) + 2
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "numeric_oracle_matrix.json", numeric["evidence"])
    evidence = {
        "constraints": constraints,
        "hardening": hardening,
        "integration": integration,
    }
    write_json(output_dir / "admission_evidence.json", evidence)
    summary = {
        "schema_version": VERSION,
        "ok": all(checks.values()),
        "checks": checks,
        "metrics": {
            "semantic_table_parse_count": catalog_result.semantic_table_parse_count,
            "ability_file_parse_count": catalog_result.ability_file_parse_count,
            "source_snapshot_load_count": 1,
            "raw_sub_affix_oracle_row_count": len(raw_affixes),
            "full_relic_catalog_build_count": 1, "rulebook_build_count": 1,
            "full_relic_definition_count": len(complete_catalog.definitions()),
            "rulebook_relic_definition_count": len(catalog.definitions()),
            "full_canonical_ir_build_count": 0, "full_rulebook_build_count": 0,
        },
        "downstream_battle_blockers": [{
            "classification": "implementation_missing",
            "reason_code": RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
            "missing_capabilities": ["relic_set_activation", "relic_static_contributions"],
        }],
        "gap_register": [],
    }
    write_json(output_dir / "validation_summary.json", summary)
    return summary


def _bounded_catalog(catalog: RelicCanonicalCatalog) -> RelicCanonicalCatalog:
    main_groups = {
        item.definition_key: item for item in catalog.main_affix_group_definitions
    }
    formal = _formal_templates(catalog)
    required_sub_groups = {item.sub_affix_group_key for item in formal}
    domain = min(
        (
            item for item in catalog.domain_definitions
            if required_sub_groups.issubset({
                template.sub_affix_group_key
                for template in formal
                if template.domain_key == item.definition_key
                and len(main_groups[template.main_affix_group_key].affix_keys) > 1
            })
        ),
        key=lambda item: (len(item.set_keys), item.definition_key.stable_id),
    )
    sets = _select(catalog.set_definitions, "definition_key", domain.set_keys)
    template_keys = {
        key for relic_set in sets for key in relic_set.template_keys
    }
    templates = _select(catalog.template_definitions, "definition_key", template_keys)
    main_group_keys = {item.main_affix_group_key for item in templates}
    sub_group_keys = {item.sub_affix_group_key for item in templates}
    threshold_keys = {key for item in sets for key in item.threshold_keys}
    filters = {
        "slot_definitions": ("definition_key", domain.slot_keys),
        "main_affix_group_definitions": ("definition_key", main_group_keys),
        "main_affix_definitions": ("group_key", main_group_keys),
        "sub_affix_group_definitions": ("definition_key", sub_group_keys),
        "sub_affix_definitions": ("group_key", sub_group_keys),
        "set_thresholds": ("definition_key", threshold_keys),
    }
    return replace(
        catalog,
        domain_definitions=(domain,),
        template_definitions=templates,
        set_definitions=sets,
        **{
            field: _select(getattr(catalog, field), attribute, values)
            for field, (attribute, values) in filters.items()
        },
    )


def _select(items, attribute: str, values) -> tuple:
    selected = set(values)
    return tuple(item for item in items if getattr(item, attribute) in selected)


def _focused_ir(
    catalog: RelicCanonicalCatalog, source_fingerprint: Mapping[str, JSONValue],
) -> CanonicalIR:
    fingerprint = cast(dict[str, JSONValue], thaw_json(source_fingerprint))
    character_source = IRSource(
        source_path="validation/p8_s12/character.json",
        raw_type="P8S12CharacterFixture",
        raw_id="p8_s12_avatar",
        evidence={"fixture": True, "scope": "assembly_propagation"},
    )
    tier = AvatarPromotionTierIR(
        promotion_tier_id="validation:p8_s12:promotion:0",
        avatar_id="p8_s12_avatar", promotion=0,
        promotion_field_present=True, max_level=1,
        hp_base="1000", hp_add="0",
        attack_base="500", attack_add="0",
        defense_base="300", defense_add="0",
        speed_base="100", base_aggro="100",
        critical_chance="0.05", critical_damage="0.5",
        source=character_source, coverage_status="executable",
    )
    profile = AvatarProfileIR(
        avatar_profile_id="validation:p8_s12:profile",
        avatar_id="p8_s12_avatar", base_type="ValidationCharacterPath",
        damage_type="Physical", skill_ids=(),
        promotion_tiers=(tier,), max_energy="100",
        max_energy_source=character_source,
        source=character_source, coverage_status="executable",
    )
    card = CharacterDataCardIR(
        card_id=CARD_ID, entity_ref="avatar:p8_s12_avatar",
        profile_id=profile.avatar_profile_id,
        skill_ids=(), skill_formula_binding_ids=(), bounce_policy_ids=(),
        source=character_source, coverage_status="executable",
        equipment_eligibility_id=CARD_ID, action_set={"actions": []},
    )
    eligibility = CharacterEquipmentEligibilityIR(
        definition_key=EquipmentDefinitionKey("character_equipment_eligibility", CARD_ID),
        character_card_id=CARD_ID, character_profile_id=profile.avatar_profile_id,
        character_path_type=profile.base_type,
        passive_activation_path_types=(profile.base_type,),
        source=character_source,
        coverage_status="lowered", blocked_reason="",
    )
    return CanonicalIR(
        version=BASELINE_VERSION,
        avatar_profiles=(profile,),
        character_data_cards=(card,),
        character_equipment_eligibilities=(eligibility,),
        light_cone_definitions=(_light_cone(fingerprint),),
        relic_domain_definitions=catalog.domain_definitions,
        relic_slot_definitions=catalog.slot_definitions,
        relic_main_affix_group_definitions=catalog.main_affix_group_definitions,
        relic_main_affix_definitions=catalog.main_affix_definitions,
        relic_sub_affix_group_definitions=catalog.sub_affix_group_definitions,
        relic_sub_affix_definitions=catalog.sub_affix_definitions,
        relic_template_definitions=catalog.template_definitions,
        relic_set_definitions=catalog.set_definitions,
        relic_set_thresholds=catalog.set_thresholds,
    )


def _light_cone(fingerprint: Mapping[str, JSONValue]) -> LightConeDefinitionIR:
    promotion_id = f"{LIGHT_CONE_ID}:0"
    fields = (
        ("base_hp", "10"), ("hp_per_level", "0"),
        ("base_attack", "5"), ("attack_per_level", "0"),
        ("base_defence", "4"), ("defence_per_level", "0"),
    )
    values = tuple(
        LightConePromotionValueIR(
            name, value, _source(
                fingerprint, "EquipmentPromotionConfigValue",
                f"{promotion_id}:{name}", f"$[0].{name}.Value",
            )
        )
        for name, value in fields
    )
    ability_name = "P8S12FixtureAbility"
    rank = LightConeSuperimpositionLevelIR(
        skill_id="validation:p8_s12:skill", level=1, ability_name=ability_name,
        skill_name_hash="validation:p8_s12:name",
        skill_description_hash="validation:p8_s12:description",
        parameters=(), static_properties=(),
        source=_source(
            fingerprint, "EquipmentSkillConfig",
            "validation:p8_s12:skill:1", "$[0]",
        ),
    )
    return LightConeDefinitionIR(
        definition_key=EquipmentDefinitionKey("light_cone", LIGHT_CONE_ID),
        raw_equipment_id=LIGHT_CONE_ID, publication_status="published",
        release_field_present=True,
        equipment_name_hash="validation:p8_s12:light-cone-name",
        path_type="DifferentFixturePath", rarity="validation",
        max_promotion=0, max_superimposition=1,
        skill_id=rank.skill_id,
        promotion_tiers=(LightConePromotionTierIR(
            promotion_stage=0, promotion_field_present=False,
            max_level=20, stat_values=values,
            source=_source(
                fingerprint, "EquipmentPromotionConfig", promotion_id, "$[0]"
            ),
        ),),
        superimposition_levels=(rank,),
        ability_source=LightConeAbilitySourceIR(
            ability_name=ability_name, record_index=0,
            source=_source(
                fingerprint, "AbilityList", ability_name, "$.AbilityList[0]",
                "validation/p8_s12/equipment_ability.json",
            ),
        ),
        mechanism_ref_ids=(),
        source=_source(fingerprint, "EquipmentConfig", LIGHT_CONE_ID, "$[0]"),
        coverage_status="lowered", blocked_reason="",
    )


def _source(
    fingerprint: Mapping[str, JSONValue],
    raw_type: str,
    raw_id: str,
    json_path: str,
    source_path: str = "validation/p8_s12/equipment_fixture.json",
) -> IRSource:
    return make_equipment_source(
        source_path=source_path, raw_type=raw_type, raw_id=raw_id,
        json_path=json_path, source_fingerprint=fingerprint,
        source_kind="validation_fixture",
    )


def _numeric(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    raw_affixes: Mapping[str, RawSubAffixOracle],
) -> dict[str, Any]:
    main_groups = {
        item.definition_key: item
        for item in catalog.main_affix_group_definitions
    }
    templates = {
        item.sub_affix_group_key: item
        for item in _formal_templates(catalog)
        if len(main_groups[item.main_affix_group_key].affix_keys) > 1
    }
    rows = []
    for index, affix in enumerate(catalog.sub_affix_definitions):
        raw = raw_affixes[affix.definition_key.definition_identity]
        template = templates[affix.group_key]
        main_key = _main_key(catalog, template, {affix.property_type})
        cases = [("low", 2, 0), ("mid", 2, raw.step_num)]
        cases.append(("high", 2, 2 * raw.step_num))
        if index == 0:
            count = 10**30 + 7
            cases.append(("large_integer", count, count * raw.step_num))
        for label, count, step in cases:
            roll = RelicSubAffixRollInput(affix.definition_key, count, step)
            instance = _instance(template, main_key, (roll,), f"numeric:{index}:{label}")
            slot = rules.relic_slot_definition(template.slot_key.definition_identity).value
            main, main_issues = admit_relic_main_affix(rules, template, slot, instance)
            values, issues = admit_relic_sub_affixes(rules, template, instance, main)
            expected = _oracle(raw, count, step)
            actual = values[0].exact_value if values else None
            passed = not main_issues and not issues and actual == expected
            rows.append({
                "affix": affix.definition_key.definition_identity,
                "boundary": label,
                "count": count,
                "step": step,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            })
    return {
        "ok": bool(rows) and all(row["passed"] for row in rows),
        "evidence": {"rows": rows},
    }


def _constraints(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    fixture: Fixture,
) -> dict[str, Any]:
    four_rolls = tuple(
        RelicSubAffixRollInput(item.definition_key, 1, item.step_count)
        for item in fixture.affixes[:4]
    )
    fifth = RelicSubAffixRollInput(
        fixture.affixes[4].definition_key, 1, fixture.affixes[4].step_count
    )
    first = fixture.affixes[0]
    other_group = next(
        item for item in catalog.sub_affix_definitions
        if item.group_key != fixture.template.sub_affix_group_key
    )
    roll_input = RelicSubAffixRollInput
    specs = {
        "fifth_property": ((*four_rolls, fifth), "relic_sub_affix_property_limit_exceeded"),
        "same_affix": ((four_rolls[0], four_rolls[0]), "relic_sub_affix_duplicate_affix"),
        "main_conflict": ((roll_input(fixture.main_conflict.definition_key, 1, 0),), "relic_main_sub_affix_property_conflict"),
        "wrong_group": ((roll_input(other_group.definition_key, 1, 0),), "relic_sub_affix_not_in_template_group"),
        "count_zero": ((roll_input(first.definition_key, 0, 0),), "relic_sub_affix_count_not_positive"),
        "step_negative": ((roll_input(first.definition_key, 1, -1),), "relic_sub_affix_step_negative"),
        "step_above": ((roll_input(first.definition_key, 1, first.step_count + 1),), "relic_sub_affix_step_exceeds_cumulative_bound"),
    }
    negative_rows = {}
    for name, (rolls, reason) in specs.items():
        result = _assemble(rules, fixture, rolls, name)
        actual = sorted({item.reason for item in result.diagnostics})
        negative_rows[name] = {
            "passed": _blocked_empty(result) and reason in actual,
            "expected": reason,
            "actual": actual,
        }
    four = _assemble(rules, fixture, four_rolls, "four-upper")
    pair_rolls = tuple(
        RelicSubAffixRollInput(item.definition_key, 1, 0)
        for item in fixture.flat_ratio
    )
    pair = _assemble(rules, fixture, pair_rolls, "flat-ratio")
    bound_roll = RelicSubAffixRollInput(
        first.definition_key, 3, 3 * first.step_count
    )
    at_bound = _assemble(rules, fixture, (bound_roll,), "step-bound")
    selection = pair.relic_selections[0]
    forged = replace(
        selection.sub_affixes[1],
        property_type=selection.sub_affixes[0].property_type,
    )
    same_property = _raises(
        lambda: replace(
            selection,
            sub_affixes=(selection.sub_affixes[0], forged),
        ),
        (TypeError, ValueError),
    )
    return {
        "negative_cases": negative_rows,
        "four_upper": _future_blocked(four, 1)
        and len(four.relic_selections[0].sub_affixes) == 4,
        "flat_ratio": _future_blocked(pair, 1),
        "step_bound": _future_blocked(at_bound, 1),
        "same_property": same_property,
    }


def _hardening(
    rules: RuleBook, catalog: RelicCanonicalCatalog, fixture: Fixture,
) -> dict[str, Any]:
    affix = fixture.affixes[0]
    roll = RelicSubAffixRollInput(affix.definition_key, 1, 0)
    instance = _instance(fixture.template, fixture.main_key, (roll,), "hardening")
    slot = rules.relic_slot_definition(fixture.template.slot_key.definition_identity).value
    main = admit_relic_main_affix(rules, fixture.template, slot, instance)[0]
    if main is None:
        raise RuntimeError("hardening fixture main affix must be admitted")
    fingerprint = cast(dict[str, JSONValue], thaw_json(
        fixture.template.source.evidence["source_fingerprint"]
    ))
    alternate = dict(fingerprint)
    alternate["sha256"] = "0" * 64 if alternate["sha256"] != "0" * 64 else "1" * 64
    source_main = replace(
        main,
        template_source=_resourced(main.template_source, alternate),
        slot_source=_resourced(main.slot_source, alternate),
        group_source=_resourced(main.group_source, alternate),
        affix_source=_resourced(main.affix_source, alternate),
    )
    property_main = replace(main, property_type=f"{main.property_type}:tampered")
    json_template = replace(
        fixture.template,
        source=_resourced(
            fixture.template.source, fingerprint, json_path="$[999999]"
        ),
    )
    alternate_group = next(
        item.definition_key for item in catalog.sub_affix_group_definitions
        if item.definition_key != fixture.template.sub_affix_group_key
    )
    group_template = replace(
        fixture.template, sub_affix_group_key=alternate_group
    )
    canonical_specs = {
        "main_property": (
            fixture.template, property_main, "relic_sub_affix_main_property_mismatch",
        ),
        "main_source": (
            fixture.template, source_main,
            "relic_sub_affix_main_source_fingerprint_mismatch",
        ),
        "template_json_path": (
            json_template, main, "relic_sub_affix_template_not_canonical",
        ),
        "template_sub_affix_group": (
            group_template, main, "relic_sub_affix_template_not_canonical",
        ),
    }
    canonical_checks = {}
    for name, (candidate_template, candidate_main, reason) in canonical_specs.items():
        issues = admit_relic_sub_affixes(
            rules, candidate_template, instance, candidate_main
        )[1]
        canonical_checks[name] = {item.reason for item in issues} == {reason}
    schema_specs = {
        "bool_step": (lambda: RelicSubAffixRollInput(affix.definition_key, 1, False), TypeError),
        "float_count": (lambda: RelicSubAffixRollInput(affix.definition_key, 1.0, 0), TypeError),
        "final_value": (
            lambda: RelicSubAffixRollInput.from_json(
                {**roll.to_json(), "final_value": 1.25}
            ), ValueError
        ),
        "stale_instance": (
            lambda: RelicInstanceInput.from_json(
                {**instance.to_json(), "instance_fingerprint": "0" * 64}
            ), ValueError
        ),
    }
    schema_checks = {
        name: _raises(callback, error)
        for name, (callback, error) in schema_specs.items()
    }
    source_rolls = [roll]
    detached_instance = _instance(
        fixture.template, fixture.main_key, source_rolls, "isolation"
    )
    source_rolls.clear()
    source_relics = [detached_instance]
    detached_build = EquipmentBuildInput(
        build_id="validation:p8_s12:isolation", character_card_id=CARD_ID,
        relics=source_relics,
    )
    source_relics.clear()
    isolation = {
        "rolls": len(detached_instance.sub_affix_rolls) == 1,
        "relics": len(detached_build.relics) == 1,
        "instance_frozen": _raises(
            lambda: setattr(detached_instance, "level", 0), FrozenInstanceError
        ),
    }
    excluded = {
        "rarity_roll_budget", "level_roll_budget", "upgrade_history",
        "engine_rule_version", "final_value",
    }
    return {
        "schema_cases": schema_checks,
        "canonical_input_cases": canonical_checks,
        "input_isolation_cases": isolation,
        "finished_schema": (
            set(roll.to_json()) == {"affix_key", "count", "step"}
            and not excluded.intersection(instance.to_json())
        ),
    }


def _integration(
    rules: RuleBook, catalog: RelicCanonicalCatalog, fixture: Fixture,
) -> dict[str, Any]:
    roll = RelicSubAffixRollInput(fixture.affixes[0].definition_key, 1, 0)
    legal_build = _build(fixture.template, fixture.main_key, (roll,), "legal")
    legal = legal_build.relics[0]
    empty_result = assemble_equipment_build(
        rules,
        EquipmentBuildInput(
            build_id="validation:p8_s12:empty", character_card_id=CARD_ID,
        ),
    )
    legal_result = assemble_equipment_build(rules, legal_build)
    light_cone_build = replace(
        legal_build,
        build_id="validation:p8_s12:with-light-cone",
        light_cone=LightConeInstanceInput(
            "validation:p8_s12:light-cone-instance",
            EquipmentDefinitionKey("light_cone", LIGHT_CONE_ID), 1, 0, 1,
        ),
    )
    light_cone_result = assemble_equipment_build(rules, light_cone_build)
    sibling_template = next(
        item for item in _formal_templates(catalog)
        if item.slot_key != fixture.template.slot_key
        and sum(
            definition.group_key == item.main_affix_group_key
            for definition in catalog.main_affix_definitions
        ) > 1
    )
    sibling_affix = next(
        item for item in catalog.sub_affix_definitions
        if item.group_key == sibling_template.sub_affix_group_key
    )
    sibling_main = _main_key(
        catalog, sibling_template, {sibling_affix.property_type}
    )
    invalid_sibling = _instance(
        sibling_template,
        sibling_main,
        (RelicSubAffixRollInput(sibling_affix.definition_key, 0, 0),),
        "integration:invalid-sibling",
    )
    sibling_build = replace(
        legal_build,
        build_id="validation:p8_s12:atomic-sibling",
        relics=(legal, invalid_sibling),
    )
    sibling_result = assemble_equipment_build(rules, sibling_build)
    character_build = CharacterBuildInput(
        build_id="validation:p8_s12:character",
        character_card_id=CARD_ID, level=1, promotion=0, eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=legal_build,
    )
    character_result = assemble_character_build(rules, character_build)
    invariant = _raises(
        lambda: replace(legal_result, battle_admission_blockers=()), ValueError
    )
    return {
        "empty": (
            empty_result.assembly_status == "assembled"
            and empty_result.battle_admission_status == "admitted"
            and not empty_result.battle_admission_blockers
        ),
        "both_paths": (
            _future_blocked(legal_result, 1)
            and _future_blocked(light_cone_result, 1)
            and not legal_result.static_contributions
            and all(
                item.source_ref.definition_kind == "light_cone"
                for item in light_cone_result.static_contributions
            )
            and invariant
        ),
        "sibling": _blocked_empty(sibling_result),
        "character": (
            character_result.assembly_status == "assembled"
            and character_result.battle_admission_status == "blocked"
            and character_result.equipment_assembly_result is not None
            and character_result.equipment_assembly_result.battle_admission_status
            == "blocked"
        ),
    }


def _formal_templates(catalog: RelicCanonicalCatalog) -> tuple[RelicTemplateDefinitionIR, ...]:
    return tuple(
        item for item in catalog.template_definitions
        if item.mode == "BASIC" and item.publication_status == "published"
        and item.coverage_status == "lowered"
    )


def _fixture(catalog: RelicCanonicalCatalog) -> Fixture:
    main_groups = {
        item.definition_key: item for item in catalog.main_affix_group_definitions
    }
    main_affixes = {
        item.definition_key: item for item in catalog.main_affix_definitions
    }
    for template in _formal_templates(catalog):
        subs = tuple(
            item for item in catalog.sub_affix_definitions
            if item.group_key == template.sub_affix_group_key
        )
        for main_key in main_groups[template.main_affix_group_key].affix_keys:
            main_property = main_affixes[main_key].property_type
            usable = tuple(item for item in subs if item.property_type != main_property)
            pair = _flat_ratio(usable)
            conflict = next(
                (item for item in subs if item.property_type == main_property), None
            )
            if len(usable) >= 5 and pair and conflict:
                return Fixture(
                    template,
                    main_key,
                    tuple(sorted(usable, key=lambda item: item.definition_key.stable_id)),
                    pair,
                    conflict,
                )
    raise RuntimeError("no structural S12 fixture exists")


def _flat_ratio(affixes):
    for left in affixes:
        left_binding = static_property_binding(left.property_type)
        if left_binding is None or left_binding.calculation_kind != "flat":
            continue
        for right in affixes:
            right_binding = static_property_binding(right.property_type)
            if (
                right_binding is not None
                and right_binding.calculation_kind == "ratio"
            ):
                return left, right
    return None


def _main_key(catalog, template, excluded: set[str]) -> EquipmentDefinitionKey:
    group = next(
        item for item in catalog.main_affix_group_definitions
        if item.definition_key == template.main_affix_group_key
    )
    affixes = {item.definition_key: item for item in catalog.main_affix_definitions}
    return next(
        key for key in group.affix_keys if affixes[key].property_type not in excluded
    )


def _instance(template, main_key, rolls: Sequence, tag: str) -> RelicInstanceInput:
    return RelicInstanceInput(
        instance_id=f"validation:p8_s12:{tag}:relic",
        template_key=template.definition_key,
        slot_key=template.slot_key,
        level=template.max_level,
        main_affix_key=main_key,
        sub_affix_rolls=rolls,
    )


def _build(template, main_key, rolls, tag: str) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=f"validation:p8_s12:{tag}",
        character_card_id=CARD_ID,
        relics=(_instance(template, main_key, rolls, tag),),
    )


def _assemble(rules: RuleBook, fixture: Fixture, rolls, tag: str):
    return assemble_equipment_build(
        rules, _build(fixture.template, fixture.main_key, rolls, tag)
    )


def _future_blocked(result: EquipmentAssemblyResult, count: int) -> bool:
    return (
        result.assembly_status == "assembled"
        and result.battle_admission_status == "blocked"
        and len(result.relic_selections) == count
        and _blockers_match(result)
    )


def _blockers_match(result: EquipmentAssemblyResult) -> bool:
    blockers = {
        item.blocker_id: item for item in result.battle_admission_blockers
        if item.channel == "relic_assembly"
    }
    return len(blockers) == len(result.relic_selections) and all(
        blocker is not None
        and blocker.target_definition_key == selection.template_key
        and blocker.gap_classification == "implementation_missing"
        and blocker.reason_code == RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON
        and blocker.source_refs == selection.assembly_source_refs
        for selection in result.relic_selections
        for blocker in (
            blockers.get(f"{result.assembly_id}:{selection.instance_id}:relic_assembly"),
        )
    )


def _blocked_empty(result: EquipmentAssemblyResult) -> bool:
    return (
        result.assembly_status == "blocked"
        and result.battle_admission_status == "blocked"
        and bool(result.diagnostics)
        and result.light_cone_selection is None
        and not result.relic_selections
        and not result.static_contributions
        and not result.dynamic_mechanisms
        and not result.activation_decisions
        and not result.battle_admission_blockers
        and not result.source_ledger
    )


def _resourced(source, fingerprint, json_path=None) -> IRSource:
    return make_equipment_source(
        source_path=source.source_path, raw_type=source.raw_type,
        raw_id=source.raw_id,
        json_path=json_path or cast(str, source.evidence["json_path"]),
        source_fingerprint=fingerprint,
        source_kind=cast(Any, source.evidence["source_kind"]),
    )


def _raises(callback, errors) -> bool:
    try:
        callback()
    except errors:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run_validation(args.tbgd_root, args.output_dir)
    print(json.dumps({"ok": summary["ok"], "checks": summary["checks"]}, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
