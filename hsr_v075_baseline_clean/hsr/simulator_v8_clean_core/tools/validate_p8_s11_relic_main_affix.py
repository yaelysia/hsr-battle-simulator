"""P8-S11 relic main affix legal pools and exact value validation (single entry)."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, cast

from .. import BASELINE_VERSION
from ..builds.equipment_assembler import (
    assemble_equipment_build,
    validate_equipment_assembly_admission,
)
from ..builds.relic_affix_calculator import admit_relic_main_affix
from ..equipment.models import (
    EquipmentBuildInput,
    EquipmentDefinitionKey,
    RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON,
    RelicInstanceInput,
    RelicMainAffixComputation,
    RelicTemplateDefinitionIR,
    make_equipment_source,
)
from ..immutable_json import thaw_json
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..tbgd.relic_cards import (
    RelicCanonicalCatalog,
    build_relic_catalog,
    require_complete_relic_catalog,
)
from .io import write_json


VALIDATION_VERSION = "p8_s11_relic_main_affix_v1"
MAIN_AFFIX_TABLE = "ExcelOutput/RelicMainAffixConfig.json"
BASE_TYPE_TABLE = "ExcelOutput/RelicBaseType.json"
RELIC_CONFIG_TABLE = "ExcelOutput/RelicConfig.json"
Lookup = dict[EquipmentDefinitionKey, Any]


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    catalog_result = build_relic_catalog(tbgd_root)
    catalog = require_complete_relic_catalog(catalog_result)
    rules = RuleBook(_catalog_ir(catalog))
    oracle = _RawOracle(tbgd_root)
    published = tuple(
        template
        for template in catalog.template_definitions
        if template.mode == "BASIC"
        and template.publication_status == "published"
        and template.coverage_status == "lowered"
    )
    groups: Lookup = {g.definition_key: g for g in catalog.main_affix_group_definitions}
    affixes: Lookup = {a.definition_key: a for a in catalog.main_affix_definitions}
    slots: Lookup = {s.definition_key: s for s in catalog.slot_definitions}
    representatives = _slot_representatives(published)

    slot_matrix = _slot_pool_matrix(catalog, published, groups, affixes, oracle, representatives)
    legality = _legality_matrix(rules, published, groups, slots, representatives)
    group_negatives = _group_negative_matrix(rules, catalog, published, groups, representatives)
    cross_slot = _cross_slot_matrix(rules, published, groups, representatives)
    slot_defense = _slot_pool_defense(rules, groups, affixes, slots, representatives)
    numeric = _numeric_oracle_matrix(rules, published, groups, affixes, slots, oracle)
    input_negatives = _input_negative_matrix(rules, catalog, groups, representatives)
    hardening = _production_hardening_matrix(rules, catalog, groups, affixes, slots, representatives)
    display = _display_projection_checks(rules, groups, affixes, representatives)
    walkback = _source_walkback(catalog, slots, representatives, numeric["computations"], oracle)
    invariant = _assembly_invariant(group_negatives, cross_slot, hardening)
    oracle_selftest = _oracle_canonical_selftest()

    checks = {
        "six_real_slot_pools_non_empty": slot_matrix["six_pools_non_empty"],
        "main_affix_requires_slot_and_template_group": (
            legality["all_end_to_end_assembled_and_future_blocked"]
            and legality["full_definition_coverage_complete"]
        ),
        "fixed_head_hand_are_source_derived": slot_matrix["fixed_slots_source_derived"],
        "cross_slot_main_affixes_rejected": cross_slot["all_rejected"] and slot_defense["all_rejected"],
        "template_group_restriction_enforced": group_negatives["all_rejected"],
        "level_zero_mid_max_match_independent_oracle": numeric["all_match"],
        "numeric_values_never_pass_through_float": (
            catalog_result.numeric_values_never_pass_through_float
            and numeric["oracle_rows_are_decimal"]
            and input_negatives["float_value_rejected"]
        ),
        "display_projection_not_rule_input": display["ok"],
        "user_final_value_rejected": input_negatives["all_rejected"],
        "ambiguous_affix_definition_blocked": input_negatives["ambiguity_blocked"],
        "all_results_source_backed": walkback["all_backed"],
        "blocked_main_affix_contributes_nothing": invariant["ok"],
        "source_fingerprint_mismatch_blocked": hardening["fingerprint_blocked"],
        "group_rarity_enforced_in_production": hardening["rarity_enforced"],
        "calculator_identity_closure_enforced": hardening["identity_enforced"],
        "numeric_oracle_independent_of_production_code": all(row["ok"] for row in oracle_selftest),
    }

    artifacts = {
        "slot_property_matrix.json": slot_matrix["evidence"],
        "legality_matrix.json": legality["evidence"],
        "group_negatives.json": group_negatives["evidence"],
        "cross_slot_matrix.json": cross_slot["evidence"],
        "slot_pool_defense.json": slot_defense["evidence"],
        "numeric_oracle_matrix.json": numeric["evidence"],
        "input_negative_matrix.json": input_negatives["evidence"],
        "production_hardening_matrix.json": {
            "rows": hardening["evidence"],
            "oracle_canonical_selftest": oracle_selftest,
        },
        "display_projection.json": display["evidence"],
        "source_walkback.json": walkback["evidence"],
        "assembly_invariant.json": invariant["evidence"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    for name, payload in artifacts.items():
        path = output_dir / name
        write_json(path, cast(dict[str, Any], payload))
        total_bytes += path.stat().st_size

    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(checks.values()),
        "checks": checks,
        "scope": {
            "published_basic_templates": len(published),
            "slot_count": len(catalog.slot_definitions),
            "main_affix_group_count": len(catalog.main_affix_group_definitions),
            "main_affix_definition_count": len(catalog.main_affix_definitions),
            "oracle_rows": numeric["row_count"],
            "end_to_end_positive_cases": legality["end_to_end_cases"],
            "negative_cases": (
                group_negatives["case_count"] + cross_slot["case_count"]
                + slot_defense["case_count"] + input_negatives["case_count"]
                + hardening["case_count"]
            ),
        },
        "resource": {
            "catalog_build_count": 1,
            "semantic_table_parse_count": catalog_result.semantic_table_parse_count,
            "ability_file_parse_count": catalog_result.ability_file_parse_count,
            "ability_index_build_count": catalog_result.ability_index_build_count,
            "wall_clock_seconds": round(time.monotonic() - started, 3),
            "artifact_bytes": total_bytes,
        },
        "gap_register": [],
    }
    write_json(output_dir / "validation_summary.json", summary)
    return summary


def _catalog_ir(catalog: RelicCanonicalCatalog) -> CanonicalIR:
    return CanonicalIR(
        version=BASELINE_VERSION,
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


def _swap_rules(
    catalog: RelicCanonicalCatalog,
    field: str,
    key: EquipmentDefinitionKey,
    replacement: Any,
) -> RuleBook:
    """Swap one definition inside CanonicalIR, bypassing catalog invariants."""

    ir = _catalog_ir(catalog)
    swapped = tuple(
        replacement if item.definition_key == key else item
        for item in getattr(ir, field)
    )
    return RuleBook(replace(ir, **{field: swapped}))


class _RawOracle:
    """Independent raw re-read; never calls production calculation code."""

    def __init__(self, tbgd_root: Path) -> None:
        def _read(relative: str) -> Any:
            return json.loads((tbgd_root / relative).read_bytes(), parse_float=Decimal)

        self.affix_rows: list[dict[str, Any]] = _read(MAIN_AFFIX_TABLE)
        self.base_type_rows: list[dict[str, Any]] = _read(BASE_TYPE_TABLE)
        self.relic_rows: list[dict[str, Any]] = _read(RELIC_CONFIG_TABLE)
        self.affix_by_identity = {f"{row['GroupID']}:{row['AffixID']}": row for row in self.affix_rows}
        self.base_type_by_type = {row["Type"]: row for row in self.base_type_rows if row.get("Type")}
        self.relic_by_id = {str(row["ID"]): row for row in self.relic_rows}
        self.rows_are_decimal = all(
            not isinstance(row["BaseValue"]["Value"], float)
            and not isinstance(row["LevelAdd"]["Value"], float)
            for row in self.affix_rows
        )

    def expected_value(self, affix_identity: str, level: int) -> str:
        row = self.affix_by_identity[affix_identity]
        return _oracle_canonical(row["BaseValue"]["Value"] + row["LevelAdd"]["Value"] * level)


def _oracle_canonical(value: Decimal) -> str:
    """Validator-internal canonical form; shares no code with production."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("oracle value must be a finite Decimal")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _oracle_canonical_selftest() -> list[dict[str, Any]]:
    cases = (
        (Decimal("0.000"), "0"),
        (Decimal("-0.0"), "0"),
        (Decimal("1E+2"), "100"),
        (Decimal("15.8054400"), "15.80544"),
        (Decimal("0.08571"), "0.08571"),
        (Decimal(1), "1"),
    )
    return [
        {"input": str(raw), "expected": expected, "produced": _oracle_canonical(raw), "ok": _oracle_canonical(raw) == expected}
        for raw, expected in cases
    ]


def _slot_representatives(
    published: tuple[RelicTemplateDefinitionIR, ...],
) -> dict[str, RelicTemplateDefinitionIR]:
    representatives: dict[str, RelicTemplateDefinitionIR] = {}
    for template in sorted(published, key=lambda item: item.definition_key.definition_identity):
        representatives.setdefault(template.slot_key.definition_identity, template)
    return representatives


def _make_instance(
    template: RelicTemplateDefinitionIR,
    affix_key: EquipmentDefinitionKey,
    level: int,
    instance_id: str,
) -> RelicInstanceInput:
    return RelicInstanceInput(
        instance_id=instance_id,
        template_key=template.definition_key,
        slot_key=template.slot_key,
        level=level,
        main_affix_key=affix_key,
        sub_affix_rolls=(),
    )


def _make_build(
    template: RelicTemplateDefinitionIR,
    affix_key: EquipmentDefinitionKey,
    level: int,
    tag: str,
    identity_labels: dict[str, str] | None = None,
) -> EquipmentBuildInput:
    return EquipmentBuildInput(
        build_id=f"p8_s11:{tag}",
        character_card_id="p8_s11:character",
        relics=(_make_instance(template, affix_key, level, f"p8_s11:{tag}:relic"),),
        identity_labels=identity_labels or {},
    )


def _blocked_channels_empty(result: Any) -> bool:
    return bool(
        result.assembly_status == "blocked"
        and result.relic_selections == ()
        and result.static_contributions == ()
        and result.dynamic_mechanisms == ()
        and result.activation_decisions == ()
        and result.battle_admission_blockers == ()
        and result.source_ledger == ()
        and "exact_value" not in json.dumps(result.to_json())
        and "set_count" not in json.dumps(result.to_json())
    )


def _reject_row(case: str, result: Any, expected_reason: str) -> dict[str, Any]:
    reasons = tuple(diagnostic.reason for diagnostic in result.diagnostics)
    return {
        "case": case,
        "reasons": list(reasons),
        "rejected": reasons == (expected_reason,) and _blocked_channels_empty(result),
    }


def _slot_pool_matrix(
    catalog: RelicCanonicalCatalog,
    published: tuple[RelicTemplateDefinitionIR, ...],
    groups: Lookup,
    affixes: Lookup,
    oracle: _RawOracle,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    rows = []
    for slot in sorted(catalog.slot_definitions, key=lambda item: item.definition_key.definition_identity):
        identity = slot.definition_key.definition_identity
        raw_row = oracle.base_type_by_type.get(identity)
        raw_pool = list(raw_row["ValidPropertyList"]) if raw_row else None
        legal = sorted(
            {
                affixes[key].property_type
                for template in published
                if template.slot_key == slot.definition_key
                for key in groups[template.main_affix_group_key].affix_keys
                if affixes[key].property_type in slot.allowed_main_property_types
            }
        )
        rows.append(
            {
                "slot": identity,
                "typed_pool": list(slot.allowed_main_property_types),
                "raw_pool": raw_pool,
                "typed_pool_matches_raw": raw_pool == list(slot.allowed_main_property_types),
                "published_template_count": sum(1 for t in published if t.slot_key == slot.definition_key),
                "legal_properties": legal,
                "legal_pool_non_empty": bool(legal),
                "has_representative": identity in representatives,
            }
        )
    by_slot = {row["slot"]: row for row in rows}
    fixed_derived = bool(
        by_slot["HEAD"]["raw_pool"] == ["HPDelta"]
        and by_slot["HEAD"]["legal_properties"] == ["HPDelta"]
        and by_slot["HAND"]["raw_pool"] == ["AttackDelta"]
        and by_slot["HAND"]["legal_properties"] == ["AttackDelta"]
    )
    return {
        "six_pools_non_empty": (
            len(rows) == 6
            and all(
                row["legal_pool_non_empty"] and row["typed_pool_matches_raw"] and row["has_representative"]
                for row in rows
            )
        ),
        "fixed_slots_source_derived": fixed_derived,
        "evidence": {"slots": rows},
    }


def _legality_matrix(
    rules: RuleBook,
    published: tuple[RelicTemplateDefinitionIR, ...],
    groups: Lookup,
    slots: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    rows = []
    for slot_identity in sorted(representatives):
        template = representatives[slot_identity]
        for affix_key in groups[template.main_affix_group_key].affix_keys:
            result = assemble_equipment_build(
                rules,
                _make_build(template, affix_key, template.max_level, f"legal:{slot_identity}:{affix_key.definition_identity}"),
            )
            rows.append(
                {
                    "slot": slot_identity,
                    "template": template.definition_key.definition_identity,
                    "affix": affix_key.definition_identity,
                    "assembled": (
                        result.assembly_status == "assembled"
                        and result.battle_admission_status == "blocked"
                        and len(result.relic_selections) == 1
                        and result.relic_selections[0].main_affix.affix_key == affix_key
                        and result.relic_selections[0].affix_validation_status
                        == "main_and_sub_affixes_validated"
                        and len(result.battle_admission_blockers) == 1
                        and result.battle_admission_blockers[0].channel
                        == "relic_assembly"
                        and result.battle_admission_blockers[0].reason_code
                        == RELIC_ASSEMBLY_NOT_ASSEMBLED_REASON
                        and not result.static_contributions
                    ),
                }
            )
    full_rows = full_failures = 0
    for template in published:
        slot = slots[template.slot_key]
        for affix_key in groups[template.main_affix_group_key].affix_keys:
            full_rows += 1
            computation, issues = admit_relic_main_affix(
                rules, template, slot, _make_instance(template, affix_key, template.max_level, "p8_s11:full")
            )
            if computation is None or issues:
                full_failures += 1
    return {
        "all_end_to_end_assembled_and_future_blocked": all(
            row["assembled"] for row in rows
        ),
        "full_definition_coverage_complete": full_rows > 0 and full_failures == 0,
        "end_to_end_cases": len(rows),
        "evidence": {
            "end_to_end_rows": rows,
            "full_definition_rows_checked": full_rows,
            "full_definition_rows_rejected": full_failures,
        },
    }


def _group_negative_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    published: tuple[RelicTemplateDefinitionIR, ...],
    groups: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    body = next(
        template for template in published
        if template.slot_key.definition_identity == "BODY" and template.rarity == "CombatPowerRelicRarity5"
    )
    cross_rarity_affix = next(
        affix
        for affix in catalog.main_affix_definitions
        if affix.group_key != body.main_affix_group_key
        and affix.property_type in groups[body.main_affix_group_key].property_types
    )
    foot = next(
        template for template in published
        if template.slot_key.definition_identity == "FOOT" and template.rarity == body.rarity
    )
    cross_slot_affix = groups[foot.main_affix_group_key].affix_keys[0]
    rows = []
    for tag, affix_key, note in (
        ("cross_rarity_same_property", cross_rarity_affix.definition_key, "affix group rarity tier differs from template"),
        ("same_rarity_cross_slot_group", cross_slot_affix, "same rarity group of another slot stays outside template group"),
    ):
        result = assemble_equipment_build(rules, _make_build(body, affix_key, body.max_level, tag))
        row = _reject_row(tag, result, "relic_main_affix_not_in_template_group")
        row.update(
            {
                "note": note,
                "template": body.definition_key.definition_identity,
                "template_rarity": body.rarity,
                "affix": affix_key.definition_identity,
            }
        )
        rows.append(row)
    coherence_rows = []
    for group in sorted(catalog.main_affix_group_definitions, key=lambda item: item.definition_key.definition_identity):
        rarities = {
            t.rarity for t in catalog.template_definitions
            if t.main_affix_group_key == group.definition_key
        }
        basic_rarities = {
            t.rarity for t in published if t.main_affix_group_key == group.definition_key
        }
        coherence_rows.append(
            {
                "group": group.definition_key.definition_identity,
                "rarities": sorted(rarities),
                "projected_rarity_types": list(group.rarity_types),
                "basic_published_rarities": sorted(basic_rarities),
                "coherent": (
                    len(rarities) <= 1
                    and (not basic_rarities or basic_rarities == rarities)
                    and tuple(sorted(rarities)) == group.rarity_types
                ),
            }
        )
    return {
        "all_rejected": (
            all(row["rejected"] for row in rows) and all(row["coherent"] for row in coherence_rows)
        ),
        "case_count": len(rows),
        "evidence": {"rows": rows, "group_rarity_coherence": coherence_rows},
    }


def _cross_slot_matrix(
    rules: RuleBook,
    published: tuple[RelicTemplateDefinitionIR, ...],
    groups: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    rows = []
    for slot_identity in sorted(representatives):
        template = representatives[slot_identity]
        for other_identity in sorted(representatives):
            if other_identity == slot_identity:
                continue
            other = next(
                (
                    item for item in published
                    if item.slot_key.definition_identity == other_identity and item.rarity == template.rarity
                ),
                None,
            )
            if other is None:
                continue
            affix_key = groups[other.main_affix_group_key].affix_keys[0]
            result = assemble_equipment_build(
                rules, _make_build(template, affix_key, template.max_level, f"cross:{slot_identity}:{other_identity}")
            )
            row = _reject_row(
                f"{slot_identity}:{other_identity}", result, "relic_main_affix_not_in_template_group"
            )
            row.update({"slot": slot_identity, "foreign_slot": other_identity, "affix": affix_key.definition_identity})
            rows.append(row)
    return {
        "all_rejected": bool(rows) and all(row["rejected"] for row in rows),
        "case_count": len(rows),
        "evidence": {"rows": rows},
    }


def _slot_pool_defense(
    rules: RuleBook,
    groups: Lookup,
    affixes: Lookup,
    slots: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    # Direct calculator defense: end-to-end the same world is already blocked
    # by the S9 reference closure; these rows prove the slot layer itself.
    rows = []
    for slot_identity in sorted(representatives):
        template = representatives[slot_identity]
        slot = slots[template.slot_key]
        for affix_key in groups[template.main_affix_group_key].affix_keys:
            affix_property = affixes[affix_key].property_type
            narrowed_pool = tuple(
                item for item in slot.allowed_main_property_types if item != affix_property
            ) or next(
                (candidate,) for candidate in ("SpeedDelta", "AttackDelta", "HPDelta") if candidate != affix_property
            )
            narrowed = replace(slot, allowed_main_property_types=narrowed_pool)
            computation, issues = admit_relic_main_affix(
                rules, template, narrowed, _make_instance(template, affix_key, template.max_level, "p8_s11:slot-defense")
            )
            reasons = tuple(issue.reason for issue in issues)
            rows.append(
                {
                    "slot": slot_identity,
                    "affix": affix_key.definition_identity,
                    "reasons": list(reasons),
                    "rejected": computation is None and reasons == ("relic_main_affix_property_not_allowed_for_slot",),
                }
            )
    return {
        "all_rejected": bool(rows) and all(row["rejected"] for row in rows),
        "case_count": len(rows),
        "evidence": {"rows": rows},
    }


def _numeric_oracle_matrix(
    rules: RuleBook,
    published: tuple[RelicTemplateDefinitionIR, ...],
    groups: Lookup,
    affixes: Lookup,
    slots: Lookup,
    oracle: _RawOracle,
) -> dict[str, Any]:
    representatives_by_group: Lookup = {}
    for template in published:
        representatives_by_group.setdefault(template.main_affix_group_key, template)
    rarity_max_levels = {template.rarity: template.max_level for template in published}
    uniform_max_level = all(template.max_level == rarity_max_levels[template.rarity] for template in published)

    rows = []
    computations: list[RelicMainAffixComputation] = []
    all_match = uniform_max_level
    for group_key in sorted(representatives_by_group, key=lambda item: item.definition_identity):
        template = representatives_by_group[group_key]
        slot = slots[template.slot_key]
        levels = sorted({0, template.max_level // 2, template.max_level})
        for affix_key in groups[group_key].affix_keys:
            level_results = []
            for level in levels:
                computation, issues = admit_relic_main_affix(
                    rules, template, slot, _make_instance(template, affix_key, level, "p8_s11:oracle")
                )
                expected = oracle.expected_value(affix_key.definition_identity, level)
                produced = computation.exact_value if computation else None
                match = (
                    computation is not None and not issues
                    and produced == expected and Decimal(produced) == Decimal(expected)
                )
                all_match = all_match and match
                level_results.append({"level": level, "expected": expected, "produced": produced, "match": match})
                if computation is not None:
                    computations.append(computation)
            affix = affixes[affix_key]
            rows.append(
                {
                    "group": group_key.definition_identity,
                    "affix": affix_key.definition_identity,
                    "property": affix.property_type,
                    "base_value": affix.base_value,
                    "level_add": affix.level_add,
                    "levels": level_results,
                }
            )
    return {
        "all_match": all_match,
        "row_count": len(rows),
        "oracle_rows_are_decimal": oracle.rows_are_decimal,
        "computations": computations,
        "evidence": {"uniform_rarity_max_level": uniform_max_level, "rows": rows},
    }


def _input_negative_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    groups: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def _raises(thunk: Callable[[], Any]) -> bool:
        try:
            thunk()
        except (TypeError, ValueError):
            return True
        return False

    template = representatives["HEAD"]
    affix_key = groups[template.main_affix_group_key].affix_keys[0]
    instance_json = _make_instance(template, affix_key, 0, "p8_s11:negative:codec").to_json()
    codec_cases = (
        ("submitted_final_value_field", {"main_affix_final_value": "1"}),
        ("submitted_display_value_field", {"display_value": "45.2"}),
        ("float_level", {"level": 1.5}),
        ("float_value_field", {"main_affix_value": 45.2}),
    )
    for case, mutation in codec_cases:
        payload = {**instance_json, **mutation}
        rows.append(
            {
                "case": case,
                "mutation": sorted(mutation),
                "rejected": _raises(lambda payload=payload: RelicInstanceInput.from_json(payload)),
            }
        )

    build = _make_build(template, affix_key, template.max_level, "negative:source")
    good_result = assemble_equipment_build(rules, build)
    computation_json = good_result.relic_selections[0].main_affix.to_json()
    for case, mutation in (
        ("tampered_exact_value", {"exact_value": "1"}),
        ("tampered_computation_fingerprint", {"computation_fingerprint": "0" * 64}),
        ("float_exact_value", {"exact_value": 45.2}),
    ):
        payload = {**computation_json, **mutation}
        rows.append(
            {
                "case": case,
                "mutation": sorted(mutation),
                "rejected": _raises(lambda payload=payload: RelicMainAffixComputation.from_json(payload)),
            }
        )

    level_zero = assemble_equipment_build(rules, _make_build(template, affix_key, 0, "negative:source"))
    forged = replace(good_result, relic_selections=level_zero.relic_selections)
    admission_errors = validate_equipment_assembly_admission(rules, build, forged)
    rows.append(
        {"case": "self_consistent_forged_result", "errors": sorted(admission_errors), "rejected": bool(admission_errors)}
    )

    ambiguity = _ambiguity_case(catalog, template, affix_key)
    rows.append({"case": "ambiguous_affix_definition", "detail": ambiguity["evidence"], "rejected": ambiguity["blocked"]})
    float_cases = {"submitted_final_value_field", "float_level", "float_value_field", "float_exact_value"}
    return {
        "all_rejected": all(row["rejected"] for row in rows),
        "float_value_rejected": all(row["rejected"] for row in rows if row["case"] in float_cases),
        "ambiguity_blocked": ambiguity["blocked"],
        "case_count": len(rows),
        "evidence": {"rows": rows},
    }


def _ambiguity_case(
    catalog: RelicCanonicalCatalog,
    template: RelicTemplateDefinitionIR,
    affix_key: EquipmentDefinitionKey,
) -> dict[str, Any]:
    duplicated = tuple(catalog.main_affix_definitions) + tuple(
        affix for affix in catalog.main_affix_definitions if affix.definition_key == affix_key
    )
    ambiguous_rules = RuleBook(replace(_catalog_ir(catalog), relic_main_affix_definitions=duplicated))
    resolution = ambiguous_rules.relic_main_affix_definition(affix_key.definition_identity)
    resolution_blocked = (
        resolution.resolution_status == "blocked"
        and resolution.blocked_reason == "equipment_definition_ambiguous"
        and len(resolution.candidates) == 2
    )
    result = assemble_equipment_build(
        ambiguous_rules, _make_build(template, affix_key, template.max_level, "ambiguous")
    )
    reasons = tuple(diagnostic.reason for diagnostic in result.diagnostics)
    assembly_blocked = (
        "equipment_definition_ambiguous" in reasons
        and set(reasons) <= {"equipment_definition_ambiguous", "equipment_definition_reference_closure_invalid"}
        and _blocked_channels_empty(result)
    )
    return {
        "blocked": resolution_blocked and assembly_blocked,
        "evidence": {
            "resolution_status": resolution.resolution_status,
            "blocked_reason": resolution.blocked_reason,
            "candidate_count": len(resolution.candidates),
            "assembly_reasons": list(reasons),
        },
    }


def _production_hardening_matrix(
    rules: RuleBook,
    catalog: RelicCanonicalCatalog,
    groups: Lookup,
    affixes: Lookup,
    slots: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    """Negative probes for fingerprint, rarity and calculator identity closure."""

    template = representatives["HEAD"]
    slot = slots[template.slot_key]
    group = groups[template.main_affix_group_key]
    affix_key = group.affix_keys[0]
    affix = affixes[affix_key]
    instance = _make_instance(template, affix_key, 0, "p8_s11:hardening")
    rows: list[dict[str, Any]] = []

    fingerprint = thaw_json(affix.source.evidence["source_fingerprint"])
    fingerprint["paths"] = [*fingerprint["paths"], "validation/p8_s11/fake.json"]
    fingerprint["file_count"] = len(fingerprint["paths"])
    mismatched_affix = replace(
        affix,
        source=make_equipment_source(
            source_path=affix.source.source_path,
            raw_type=affix.source.raw_type,
            raw_id=affix.source.raw_id,
            json_path=str(affix.source.evidence["json_path"]),
            source_fingerprint=fingerprint,
            source_kind="tbgd",
        ),
    )
    mismatched_rules = _swap_rules(catalog, "relic_main_affix_definitions", affix_key, mismatched_affix)
    crashed = False
    fingerprint_result = None
    try:
        fingerprint_result = assemble_equipment_build(
            mismatched_rules, _make_build(template, affix_key, 0, "hardening:fingerprint")
        )
    except Exception:  # the probe must prove no exception escapes the assembler
        crashed = True
    fingerprint_reasons = (
        tuple(item.reason for item in fingerprint_result.diagnostics) if fingerprint_result else ()
    )
    rows.append(
        {
            "case": "source_fingerprint_mismatch",
            "crashed": crashed,
            "reasons": list(fingerprint_reasons),
            "rejected": (
                not crashed
                and fingerprint_reasons == ("relic_main_affix_source_fingerprint_mismatch",)
                and fingerprint_result is not None
                and _blocked_channels_empty(fingerprint_result)
            ),
        }
    )

    corrupted = replace(template, rarity="CombatPowerRelicRarity3")
    corrupted_rules = _swap_rules(catalog, "relic_template_definitions", template.definition_key, corrupted)
    rarity_result = assemble_equipment_build(
        corrupted_rules, _make_build(template, affix_key, 0, "hardening:rarity")
    )
    rarity_reasons = tuple(item.reason for item in rarity_result.diagnostics)
    rows.append(
        {
            "case": "rarity_corrupted_end_to_end",
            "reasons": list(rarity_reasons),
            "rejected": (
                "equipment_definition_reference_closure_invalid" in rarity_reasons
                and _blocked_channels_empty(rarity_result)
            ),
        }
    )

    ambiguous_group = replace(group, rarity_types=(*group.rarity_types, "CombatPowerRelicRarity3"))
    ambiguous_rules = _swap_rules(
        catalog, "relic_main_affix_group_definitions", group.definition_key, ambiguous_group
    )
    direct_probes = (
        ("rarity_mismatch_calculator", (rules, corrupted, slot, instance), "relic_main_affix_group_rarity_mismatch"),
        ("rarity_ambiguous_calculator", (ambiguous_rules, template, slot, instance), "relic_main_affix_group_rarity_ambiguous"),
        (
            "template_identity_mismatch",
            (rules, template, slot, replace(instance, template_key=representatives["FOOT"].definition_key)),
            "relic_main_affix_template_identity_mismatch",
        ),
        (
            "instance_slot_mismatch",
            (rules, template, slot, replace(instance, slot_key=representatives["FOOT"].slot_key)),
            "relic_main_affix_instance_slot_mismatch",
        ),
        (
            "slot_definition_mismatch",
            (rules, template, slots[representatives["FOOT"].slot_key], instance),
            "relic_main_affix_slot_definition_mismatch",
        ),
    )
    for case, probe_args, expected in direct_probes:
        computation, issues = admit_relic_main_affix(*probe_args)
        reasons = tuple(issue.reason for issue in issues)
        rows.append(
            {"case": case, "reasons": list(reasons), "rejected": computation is None and reasons == (expected,)}
        )

    by_case = {row["case"]: bool(row["rejected"]) for row in rows}
    return {
        "fingerprint_blocked": by_case["source_fingerprint_mismatch"],
        "rarity_enforced": (
            by_case["rarity_corrupted_end_to_end"]
            and by_case["rarity_mismatch_calculator"]
            and by_case["rarity_ambiguous_calculator"]
        ),
        "identity_enforced": all(
            by_case[case]
            for case in ("template_identity_mismatch", "instance_slot_mismatch", "slot_definition_mismatch")
        ),
        "case_count": len(rows),
        "evidence": rows,
    }


def _display_projection_checks(
    rules: RuleBook,
    groups: Lookup,
    affixes: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
) -> dict[str, Any]:
    template = representatives["NECK"]
    affix_key = next(
        key for key in groups[template.main_affix_group_key].affix_keys if "." in affixes[key].base_value
    )
    labels = {"main_affix_value": "999", "display_rounded": "45.2", "ui_percent": "4.3%"}
    plain_build = _make_build(template, affix_key, template.max_level, "display")
    labeled_build = _make_build(template, affix_key, template.max_level, "display", identity_labels=labels)
    plain = assemble_equipment_build(rules, plain_build)
    labeled = assemble_equipment_build(rules, labeled_build)
    exact = plain.relic_selections[0].main_affix.exact_value
    projection = str(Decimal(exact).quantize(Decimal("0.001")))
    evidence = {
        "exact_value": exact,
        "display_projection": projection,
        "projection_is_lossy": projection != exact,
        "projection_cannot_round_trip": Decimal(projection) != Decimal(exact),
        "identity_labels_excluded_from_rule_inputs": (
            plain_build.build_fingerprint == labeled_build.build_fingerprint
            and plain.to_json() == labeled.to_json()
        ),
        "full_precision_preserved": "." in exact and len(exact.split(".")[1]) >= 4,
    }
    return {
        "ok": all(value for key, value in evidence.items() if key not in {"exact_value", "display_projection"}),
        "evidence": evidence,
    }


def _source_walkback(
    catalog: RelicCanonicalCatalog,
    slots: Lookup,
    representatives: dict[str, RelicTemplateDefinitionIR],
    computations: list[RelicMainAffixComputation],
    oracle: _RawOracle,
) -> dict[str, Any]:
    rows = []
    typed_affixes = {a.definition_key: a for a in catalog.main_affix_definitions}
    for computation in computations:
        identity = computation.affix_key.definition_identity
        if any(row["affix"] == identity for row in rows):
            continue
        affix = typed_affixes[computation.affix_key]
        raw_row = oracle.affix_by_identity.get(identity)
        source = computation.affix_source
        json_path = source.evidence.get("json_path")
        row_index = int(str(json_path)[2:-1]) if isinstance(json_path, str) else -1
        indexed_row = oracle.affix_rows[row_index] if 0 <= row_index < len(oracle.affix_rows) else None
        backed = bool(
            raw_row is not None
            and indexed_row is raw_row
            and source.source_path == MAIN_AFFIX_TABLE
            and source.raw_type == "RelicMainAffixConfig"
            and source.raw_id == identity
            and raw_row["Property"] == computation.property_type
            and Decimal(raw_row["BaseValue"]["Value"]) == Decimal(affix.base_value)
            and Decimal(raw_row["LevelAdd"]["Value"]) == Decimal(affix.level_add)
        )
        rows.append({"affix": identity, "json_path": json_path, "property": computation.property_type, "backed": backed})

    relation_rows = []
    for slot_identity in sorted(representatives):
        template = representatives[slot_identity]
        raw_relic = oracle.relic_by_id.get(template.definition_key.definition_identity)
        template_source = next(
            (c.template_source for c in computations if c.template_key == template.definition_key), None
        )
        slot = slots[template.slot_key]
        raw_slot = oracle.base_type_by_type.get(slot_identity)
        backed = bool(
            raw_relic is not None
            and template_source is not None
            and template_source.raw_id == str(raw_relic["ID"])
            and str(raw_relic["MainAffixGroup"]) == template.main_affix_group_key.definition_identity
            and raw_relic["Rarity"] == template.rarity
            and raw_relic["MaxLevel"] == template.max_level
            and raw_relic["Type"] == slot_identity
            and raw_slot is not None
            and list(raw_slot["ValidPropertyList"]) == list(slot.allowed_main_property_types)
        )
        relation_rows.append({"slot": slot_identity, "template": template.definition_key.definition_identity, "backed": backed})

    fingerprints_deterministic = all(
        RelicMainAffixComputation.from_json(c.to_json()).computation_fingerprint == c.computation_fingerprint
        for c in computations[:25]
    )
    distinct_fingerprints = len({c.computation_fingerprint for c in computations}) == len(computations)
    return {
        "all_backed": (
            all(row["backed"] for row in rows)
            and all(row["backed"] for row in relation_rows)
            and fingerprints_deterministic
            and distinct_fingerprints
        ),
        "evidence": {
            "affix_rows": rows,
            "relation_rows": relation_rows,
            "affix_coverage": len(rows),
            "fingerprints_deterministic": fingerprints_deterministic,
            "distinct_computation_fingerprints": distinct_fingerprints,
        },
    }


def _assembly_invariant(
    group_negatives: dict[str, Any],
    cross_slot: dict[str, Any],
    hardening: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        {"source": "group_negatives", "case": row["case"], "empty": row["rejected"]}
        for row in group_negatives["evidence"]["rows"]
    ]
    rows += [
        {"source": "cross_slot", "case": row["case"], "empty": row["rejected"]}
        for row in cross_slot["evidence"]["rows"]
    ]
    rows += [
        {"source": "hardening", "case": row["case"], "empty": row["rejected"]}
        for row in hardening["evidence"]
        if row["case"] in {"source_fingerprint_mismatch", "rarity_corrupted_end_to_end"}
    ]
    return {"ok": bool(rows) and all(row["empty"] for row in rows), "evidence": {"rows": rows}}


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
