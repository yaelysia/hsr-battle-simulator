from __future__ import annotations

import argparse
import resource
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .. import BASELINE_VERSION
from ..build_types import (
    BASE_STAT_PROPERTY_TYPES,
    StaticStatContribution,
    aggregate_static_stat_contributions,
)
from ..builds.character_assembler import (
    assemble_character_build,
    validate_character_build_admission,
)
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.models import (
    CharacterBuildAssemblyResult,
    CharacterBuildInput,
    CharacterInitialConditionInput,
)
from ..core.model import UnitState
from ..core.reducer import MutationReducer
from ..equipment.models import (
    EquipmentBuildInput,
    LightConeInstanceInput,
    RelicSubAffixRollInput,
)
from ..rules.ir import CanonicalIR
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import (
    BattleSetupSpec,
    InitialSummonSpec,
    PanelInput,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..systems.ability_provider import register_dynamic_ability_providers
from ..systems.scheduler import CombatScheduler
from ..systems.summon import SummonSystem
from ..systems.timeline import TIMELINE_INITIALIZATION_FLAG, TimelineSystem
from ..systems.unit_stats import effective_unit_stat
from ..tbgd.light_cone_cards import build_light_cone_catalog
from ..tbgd.lowering import TBGDLowering
from .io import write_json
from .validate_p8_s15_relic_set_dynamic_startup import (
    _build_bundle,
    _equipment_build,
)
from .validate_p8_s16_relic_set_status_condition_listener_closure import (
    _equipment as _relic_equipment,
    _speed_sources,
    _templates,
)
from .validate_p8_s17_relic_set_remaining_gameplay_closure import (
    _add_owned_action_projection,
)


BASE_PROPERTIES = ("max_hp", "attack", "defense", "speed")
RELIC_PROPERTIES = (
    "HPAddedRatio",
    "HPDelta",
    "AttackAddedRatio",
    "AttackDelta",
    "DefenceAddedRatio",
    "DefenceDelta",
    "SpeedAddedRatio",
    "SpeedDelta",
    "CriticalChanceBase",
)


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = tbgd_root.resolve()
    bundle, card, projection = _world(root)
    rules = bundle["rules"]
    light_cone = _inactive_light_cone(rules, card.card_id)
    equipment, selection = _controlled_equipment(bundle, card.card_id, light_cone)
    character = _character(card.card_id, equipment, "primary")
    assembly = assemble_character_build(rules, character)
    _require_admitted(assembly, "primary")

    panel = _panel_matrix(assembly)
    permutation = _permutation_matrix(rules, character, assembly)
    delta = _delta_matrix(bundle, character, assembly, selection)
    birth = _birth_matrix(rules, card, character, assembly)
    negatives = _negative_matrix(bundle, card, character)
    summon = _summon_matrix(rules, card, character)
    walkback = _walkback(root, rules, character, assembly)
    production_path_checks = {
        "single_equipment_assembly_path": (
            birth["assembly_calls"] == {
                "character": 1,
                "equipment": 1,
            }
        ),
    }
    checks = {
        **production_path_checks,
        **panel["checks"],
        **permutation["checks"],
        **delta["checks"],
        **birth["checks"],
        **negatives["checks"],
        **summon["checks"],
        **walkback["checks"],
    }
    ok = all(checks.values())

    artifacts = {
        "panel_permutation_delta_p8_s18.json": {
            "panel": panel["evidence"],
            "permutation": permutation["evidence"],
            "delta": delta["evidence"],
        },
        "birth_and_negatives_p8_s18.json": {
            "birth": birth["evidence"],
            "negatives": negatives["evidence"],
        },
        "summon_and_walkback_p8_s18.json": {
            "summon": summon["evidence"],
            "walkback": walkback["evidence"],
            "architecture": {
                "production_path_checks": production_path_checks,
                "codegraph_chain": [
                    "assemble_equipment_build",
                    "assemble_character_build",
                    "_plan_formal_character_birth",
                    "UnitState",
                    "register_dynamic_ability_providers",
                    "_apply_startup_ability_effects",
                    "_dispatch_battle_setup_event",
                    "TimelineSystem.initialize_action_values",
                ],
            },
        },
    }
    for filename, payload in artifacts.items():
        write_json(output_dir / filename, payload)
    elapsed = time.monotonic() - started
    summary = {
        "ok": ok,
        "ready_for_review": ok,
        "predicates": checks,
        "counts": {
            "focused_rulebooks": 1,
            "ledger_terms": len(assembly.contribution_ledger),
            "provider_selections": len(
                assembly.equipment_assembly_result.dynamic_mechanisms
            ),
            "source_files": walkback["evidence"]["source_file_count"],
            "source_bytes": walkback["evidence"]["source_bytes"],
        },
        "resources": {
            "wall_seconds": round(elapsed, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "full_lowering": 0,
            "s8_s17_aggregate_runs": 0,
            "direct_runs": 0,
            "gameplay_mutation_fixtures": 0,
            "artifact_files": sorted(artifacts),
        },
        "selection": {
            "character_card_id": card.card_id,
            "light_cone_key": light_cone.definition_key.stable_id,
            "speed_threshold_key": selection["threshold"].definition_key.stable_id,
            "speed_graph_source": selection["speed_case"]["add"].source.to_json(),
            "relic_template_keys": [
                item.definition_key.stable_id for item in selection["templates"]
            ],
            "owned_projection": projection,
        },
        "static_review_boundary": [
            "runtime_does_not_read_build_or_raw",
            "content_special_cases_zero",
        ],
        "out_of_scope": ["P8-S19", "P8-S20"],
    }
    write_json(
        output_dir / "validation_summary_p8_s18_final_panel_and_birth_order.json",
        summary,
    )
    return summary


def _world(root: Path) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    owned = TBGDLowering(root).build_owned_combatant_admission_projection(
        offensive_action_only=True,
        max_servant_count=1,
    )
    if not owned.ok:
        raise ValueError(
            "owned projection blocked:"
            + ",".join(sorted({issue.code for issue in owned.issues}))
        )
    owner_refs = {
        owner_ref
        for definition in owned.servant_definitions
        for owner_ref in definition.owner_entity_refs
    }
    owner_cards = tuple(
        card for card in owned.character_data_cards if card.entity_ref in owner_refs
    )
    if len(owner_cards) != 1:
        raise ValueError(f"focused owner card count:{len(owner_cards)}")
    light_cones = build_light_cone_catalog(root)
    if not light_cones.catalog_complete:
        raise ValueError("light-cone catalog incomplete")
    projection: dict[str, Any] = {}
    blocked_probe: dict[str, Any] = {}

    def transform(ir: CanonicalIR, _lowering: TBGDLowering) -> CanonicalIR:
        merged = replace(
            _add_owned_action_projection(ir, owned, projection),
            light_cone_definitions=light_cones.canonical_definitions,
        )
        return _inject_blocked_graph_probe(merged, blocked_probe)

    bundle = _build_bundle(
        root,
        require_blocked_sample=False,
        required_card_id=owner_cards[0].card_id,
        ir_transform=transform,
    )
    bundle["blocked_graph_probe"] = blocked_probe
    card = bundle["rules"].character_data_card(owner_cards[0].card_id)
    if card is None:
        raise ValueError("owner card missing from controlled RuleBook")
    return bundle, card, projection


def _inject_blocked_graph_probe(
    ir: CanonicalIR,
    metadata: dict[str, Any],
) -> CanonicalIR:
    threshold_key_counts = Counter(
        item.definition_key for item in ir.relic_set_thresholds
    )
    templates_per_set = Counter(
        item.set_key for item in ir.relic_template_definitions
    )
    refs_by_key: dict[Any, list[Any]] = {}
    for ref in ir.equipment_mechanism_refs:
        refs_by_key.setdefault(ref.definition_key, []).append(ref)
    graphs = {
        item.standalone_ability_graph_id: item
        for item in ir.standalone_ability_graphs
    }
    graph_ref_counts = Counter(
        ref.graph_ref_id
        for threshold in ir.relic_set_thresholds
        if threshold_key_counts[threshold.definition_key] == 1
        and len(threshold.mechanism_ref_ids) == 1
        for ref in refs_by_key.get(threshold.mechanism_ref_ids[0], ())
    )
    candidates = []
    for threshold in ir.relic_set_thresholds:
        refs = (
            refs_by_key.get(threshold.mechanism_ref_ids[0], ())
            if len(threshold.mechanism_ref_ids) == 1
            else ()
        )
        graph = graphs.get(refs[0].graph_ref_id) if len(refs) == 1 else None
        if (
            threshold_key_counts[threshold.definition_key] == 1
            and threshold.require_count == 2
            and threshold.ability_source is not None
            and templates_per_set[threshold.set_key] >= threshold.require_count
            and graph is not None
            and graph.coverage_status == "executable"
            and graph_ref_counts[graph.standalone_ability_graph_id] == 1
        ):
            candidates.append((threshold, graph))
    if not candidates:
        raise ValueError("selected-graph admission probe unavailable")
    threshold, graph = min(
        candidates,
        key=lambda item: (
            item[0].definition_key.stable_id,
            item[1].standalone_ability_graph_id,
        ),
    )
    blocked_graph = replace(
        graph,
        coverage_status="blocked",
        blocked_reason="validation_selected_graph_admission_probe",
    )
    metadata.update(
        {
            "threshold_key": threshold.definition_key,
            "set_key": threshold.set_key,
            "require_count": threshold.require_count,
            "graph_id": graph.standalone_ability_graph_id,
            "source": graph.source.to_json(),
        }
    )
    return replace(
        ir,
        standalone_ability_graphs=tuple(
            blocked_graph
            if item.standalone_ability_graph_id
            == graph.standalone_ability_graph_id
            else item
            for item in ir.standalone_ability_graphs
        ),
    )


def _inactive_light_cone(rules: Any, card_id: str) -> LightConeInstanceInput:
    eligibility = next(
        item
        for item in rules.ir.character_equipment_eligibilities
        if item.character_card_id == card_id and item.coverage_status == "lowered"
    )
    definition = next(
        item
        for item in sorted(
            rules.ir.light_cone_definitions,
            key=lambda value: value.definition_key.stable_id,
        )
        if item.publication_status == "published"
        and item.coverage_status == "lowered"
        and item.path_type != eligibility.character_path_type
        and item.promotion_tiers
        and item.promotion_tiers[0].max_level >= 2
        and item.max_superimposition >= 2
    )
    return LightConeInstanceInput(
        instance_id="validation:p8_s18:light_cone",
        definition_key=definition.definition_key,
        level=1,
        promotion=0,
        superimposition=1,
    )


def _controlled_equipment(
    bundle: dict[str, Any],
    card_id: str,
    light_cone: LightConeInstanceInput,
) -> tuple[EquipmentBuildInput, dict[str, Any]]:
    catalog = bundle["catalog"]
    duplicate_set = bundle["cases"]["duplicate"].set_key
    blocked_set = bundle["blocked_graph_probe"]["set_key"]
    static_speed_ratio_sets = {
        item.set_key
        for item in catalog.set_thresholds
        if item.require_count == 2
        and item.coverage_status == "lowered"
        and any(
            prop.property_type == "SpeedAddedRatio"
            for prop in item.static_properties
        )
    }
    for speed_case in _speed_sources(bundle):
        threshold = speed_case["threshold"]
        primary = _templates(catalog, threshold.set_key, threshold.require_count)
        occupied = {item.slot_key for item in primary}
        missing = {
            slot.definition_key
            for slot in catalog.slot_definitions
            if slot.definition_key not in occupied
        }
        if len(primary) != 4 or len(missing) != 2:
            continue
        by_set: dict[Any, dict[Any, Any]] = {}
        for template in sorted(
            catalog.template_definitions,
            key=lambda item: item.definition_key.stable_id,
        ):
            if (
                template.publication_status != "published"
                or template.mode != "BASIC"
                or template.set_key not in static_speed_ratio_sets
                or template.set_key
                in {threshold.set_key, duplicate_set, blocked_set}
                or template.slot_key not in missing
            ):
                continue
            values = by_set.setdefault(template.set_key, {})
            prior = values.get(template.slot_key)
            if prior is None or _template_score(template) > _template_score(prior):
                values[template.slot_key] = template
        for fill_set in sorted(by_set, key=lambda value: value.stable_id):
            fill = by_set[fill_set]
            if set(fill) != missing:
                continue
            templates = (*primary, *(fill[key] for key in sorted(fill)))
            base = _relic_equipment(bundle, templates, "p8_s18", speed_level=0)
            equipment = replace(
                base,
                build_id="validation:p8_s18:equipment",
                character_card_id=card_id,
                light_cone=light_cone,
                relics=_with_sub_affixes(bundle, base.relics, templates),
            )
            result = assemble_character_build(
                bundle["rules"], _character(card_id, equipment, "probe")
            )
            equipment_result = result.equipment_assembly_result
            if (
                result.battle_admission_status == "admitted"
                and equipment_result is not None
                and any(
                    item.target_definition_key == threshold.definition_key
                    for item in equipment_result.dynamic_mechanisms
                )
            ):
                return equipment, {
                    "threshold": threshold,
                    "speed_case": speed_case,
                    "templates": templates,
                }
    raise ValueError("no admitted structural six-piece speed startup case")


def _template_score(template: Any) -> tuple[int, str, str]:
    return template.max_level, template.rarity, template.definition_key.stable_id


def _with_sub_affixes(
    bundle: dict[str, Any],
    relics: tuple[Any, ...],
    templates: tuple[Any, ...],
) -> tuple[Any, ...]:
    catalog = bundle["catalog"]
    selected_templates = {
        item.definition_key: item for item in templates
    }
    groups = {
        item.definition_key: item for item in catalog.sub_affix_group_definitions
    }
    definitions = {
        item.definition_key: item for item in catalog.sub_affix_definitions
    }
    main_definitions = {
        item.definition_key: item for item in catalog.main_affix_definitions
    }
    rolls: list[list[RelicSubAffixRollInput]] = [[] for _ in relics]
    available = [
        {
            definitions[key].property_type: definitions[key]
            for key in groups[
                selected_templates[relic.template_key].sub_affix_group_key
            ].affix_keys
            if definitions[key].coverage_status == "lowered"
        }
        for relic in relics
    ]
    main_properties = [
        main_definitions[relic.main_affix_key].property_type for relic in relics
    ]
    covered = set(main_properties)
    set_counts = Counter(
        selected_templates[relic.template_key].set_key for relic in relics
    )
    covered.update(
        prop.property_type
        for threshold in catalog.set_thresholds
        if threshold.coverage_status == "lowered"
        and set_counts[threshold.set_key] >= threshold.require_count
        for prop in threshold.static_properties
    )
    for property_type in RELIC_PROPERTIES:
        if property_type in covered:
            continue
        index = next(
            (
                index
                for index in range(len(relics))
                if property_type in available[index]
                and property_type != main_properties[index]
                and len(rolls[index]) < 4
            ),
            None,
        )
        if index is None:
            raise ValueError(f"relic property unavailable:{property_type}")
        rolls[index].append(
            RelicSubAffixRollInput(
                affix_key=available[index][property_type].definition_key,
                count=1,
                step=0,
            )
        )
        covered.add(property_type)
    return tuple(
        replace(relic, sub_affix_rolls=tuple(rolls[index]))
        for index, relic in enumerate(relics)
    )


def _character(
    card_id: str,
    equipment: EquipmentBuildInput,
    tag: str,
) -> CharacterBuildInput:
    return CharacterBuildInput(
        build_id=f"validation:p8_s18:character:{tag}",
        character_card_id=card_id,
        level=1,
        promotion=0,
        eidolon_level=0,
        unlocked_trace_node_ids=(),
        equipment_build=equipment,
    )


def _scenario(
    card: Any,
    character: CharacterBuildInput,
    tag: str,
    *,
    panel: PanelInput | None = None,
    timeline: TimelineSetupSpec | None = None,
    global_flags: dict[str, Any] | None = None,
    initial_servant_ref: str | None = None,
    servant_spawn_source_id: str | None = None,
) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id=f"validation:p8_s18:{tag}",
        version=BASELINE_VERSION,
        units=(
            UnitSpec(
                unit_id=f"ally:{tag}",
                side="ally",
                entity_ref=card.entity_ref,
                build_mode="assembled_character_build",
                level=character.level,
                eidolon_level=character.eidolon_level,
                position=0,
                panel=panel,
                character_build=character,
                initial_condition=CharacterInitialConditionInput("full", "0"),
            ),
        ),
        route=(),
        global_flags=global_flags or {},
        battle_setup=BattleSetupSpec(
            initial_summons=(
                (
                    InitialSummonSpec(
                        kind="servant",
                        owner_id=f"ally:{tag}",
                        summon_intent_ref=initial_servant_ref,
                        servant_spawn_source_id=servant_spawn_source_id,
                    ),
                )
                if initial_servant_ref is not None
                else ()
            ),
            timeline=timeline or TimelineSetupSpec(mode="runtime_initialize")
        ),
    )


def _require_admitted(result: CharacterBuildAssemblyResult, label: str) -> None:
    if (
        result.assembly_status != "assembled"
        or result.battle_admission_status != "admitted"
        or result.base_panel is None
        or result.equipment_assembly_result is None
    ):
        reasons = [
            *result.blocked_reasons,
            *(item.reason for item in result.unadmitted_mechanism_diagnostics),
        ]
        raise ValueError(f"{label} build blocked:{','.join(reasons)}")


def _panel_matrix(assembly: CharacterBuildAssemblyResult) -> dict[str, Any]:
    oracle = _oracle(assembly.contribution_ledger)
    canonical = {
        item.property_type: item.to_json()
        for item in aggregate_static_stat_contributions(assembly.contribution_ledger)
    }
    panel = _panel_values(assembly)
    channels = {
        property_type: {
            pool: [
                item.contribution_id
                for item in assembly.contribution_ledger
                if item.property_type == property_type
                and item.contribution_pool == pool
            ]
            for pool in ("base", "percentage", "flat")
        }
        for property_type in BASE_PROPERTIES
    }
    light_cone_base = [
        item
        for item in assembly.contribution_ledger
        if item.source_ref.definition_kind == "light_cone"
        and item.contribution_pool == "base"
    ]
    checks = {
        "character_and_light_cone_base_stats_combined_before_ratio": (
            {item.property_type for item in light_cone_base}
            == {"max_hp", "attack", "defense"}
        ),
        "flat_relic_stats_applied_after_ratio": all(
            channels[name]["percentage"] and channels[name]["flat"]
            for name in ("max_hp", "attack", "defense")
        ),
        "speed_formula_typed_and_ordered": all(
            channels["speed"][pool] for pool in ("base", "percentage", "flat")
        ),
        "ledger_reconstructs_final_panel": (
            oracle == canonical
            and panel == {
                property_type: row["final_value"]
                for property_type, row in oracle.items()
            }
        ),
        "ledger_terms_remain_source_granular": (
            len({item.contribution_id for item in assembly.contribution_ledger})
            == len(assembly.contribution_ledger)
            and any(
                item.source_ref.definition_kind == "relic_set_threshold"
                for item in assembly.contribution_ledger
            )
        ),
        "duplicate_static_producers_zero": (
            len({item.contribution_id for item in assembly.contribution_ledger})
            == len(assembly.contribution_ledger)
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "panel": panel,
            "oracle": oracle,
            "channels": channels,
            "ledger": [item.to_json() for item in assembly.contribution_ledger],
        },
    }


def _oracle(
    terms: tuple[StaticStatContribution, ...],
) -> dict[str, dict[str, Any]]:
    pool_key = {
        "base": "base_total",
        "percentage": "ratio_total",
        "flat": "flat_total",
        "resource": "resource_total",
    }
    id_key = {
        "base": "base_contribution_ids",
        "percentage": "ratio_contribution_ids",
        "flat": "flat_contribution_ids",
        "resource": "resource_contribution_ids",
    }
    totals: dict[str, dict[str, Decimal]] = {}
    ids: dict[str, dict[str, list[str]]] = {}
    for term in sorted(terms, key=lambda item: item.contribution_id):
        values = totals.setdefault(
            term.property_type,
            {key: Decimal(0) for key in pool_key.values()},
        )
        sources = ids.setdefault(
            term.property_type,
            {key: [] for key in id_key.values()},
        )
        values[pool_key[term.contribution_pool]] += Decimal(term.exact_value)
        sources[id_key[term.contribution_pool]].append(term.contribution_id)
    rows = {}
    for property_type in sorted(totals):
        values = totals[property_type]
        is_base = property_type in BASE_STAT_PROPERTY_TYPES
        final = (
            values["base_total"] * (1 + values["ratio_total"])
            + values["flat_total"]
            if is_base
            else values["resource_total"]
        )
        rows[property_type] = {
            "property_type": property_type,
            "aggregation_kind": "base_stat" if is_base else "resource",
            **{key: _decimal(value) for key, value in values.items()},
            "final_value": _decimal(final),
            **{key: sorted(value) for key, value in ids[property_type].items()},
        }
    return rows


def _decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _panel_values(assembly: CharacterBuildAssemblyResult) -> dict[str, str]:
    panel = assembly.base_panel
    if panel is None:
        raise ValueError("panel missing")
    values = {
        "max_hp": panel.max_hp,
        "attack": panel.attack,
        "defense": panel.defense,
        "speed": panel.speed,
        "critical_chance": panel.critical_chance,
        "critical_damage": panel.critical_damage,
        "base_aggro": panel.base_aggro,
        **{
            item.property_type: item.exact_value
            for item in panel.additional_resources
        },
    }
    if panel.max_energy is not None:
        values["max_energy"] = panel.max_energy
    return values


def _permutation_matrix(
    rules: Any,
    character: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
) -> dict[str, Any]:
    permuted_input = replace(
        character,
        equipment_build=replace(
            character.equipment_build,
            relics=tuple(reversed(character.equipment_build.relics)),
        ),
    )
    permuted = assemble_character_build(rules, permuted_input)
    _require_admitted(permuted, "permutation")
    providers = tuple(
        item.selection_id
        for item in assembly.equipment_assembly_result.dynamic_mechanisms
    )
    permuted_providers = tuple(
        item.selection_id
        for item in permuted.equipment_assembly_result.dynamic_mechanisms
    )
    checks = {
        "input_permutations_identical": (
            character.input_fingerprint == permuted_input.input_fingerprint
            and assembly.result_fingerprint == permuted.result_fingerprint
            and assembly.base_panel == permuted.base_panel
            and providers == permuted_providers
        ),
        "contribution_order_independent": (
            aggregate_static_stat_contributions(assembly.contribution_ledger)
            == aggregate_static_stat_contributions(
                tuple(reversed(assembly.contribution_ledger))
            )
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "input_fingerprint": character.input_fingerprint,
            "result_fingerprint": assembly.result_fingerprint,
            "provider_ids": list(providers),
        },
    }


def _delta_matrix(
    bundle: dict[str, Any],
    character: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
    selection: dict[str, Any],
) -> dict[str, Any]:
    rules = bundle["rules"]
    equipment = character.equipment_build
    light_cone = equipment.light_cone
    if light_cone is None:
        raise ValueError("delta matrix light cone missing")
    variants = {
        "remove_light_cone": _variant(
            rules, character, replace(equipment, light_cone=None)
        ),
        "light_cone_level": _variant(
            rules,
            character,
            replace(equipment, light_cone=replace(light_cone, level=2)),
        ),
        "light_cone_rank": _variant(
            rules,
            character,
            replace(
                equipment,
                light_cone=replace(light_cone, superimposition=2),
            ),
        ),
        "break_threshold": _variant(
            rules,
            character,
            _break_threshold(bundle, equipment, selection),
        ),
    }
    base = _ledger(assembly)
    deltas = {
        name: _ledger_delta(base, _ledger(result))
        for name, result in variants.items()
    }
    kinds = {
        name: _delta_kinds(base, _ledger(variants[name]), delta)
        for name, delta in deltas.items()
    }
    base_mechanisms = {
        item.target_definition_key
        for item in assembly.equipment_assembly_result.dynamic_mechanisms
    }
    broken_mechanisms = {
        item.target_definition_key
        for item in variants[
            "break_threshold"
        ].equipment_assembly_result.dynamic_mechanisms
    }
    threshold_key = selection["threshold"].definition_key
    activation = assembly.equipment_assembly_result.activation_decisions
    checks = {
        "light_cone_removal_isolated": (
            kinds["remove_light_cone"] == {"light_cone"}
            and bool(deltas["remove_light_cone"]["removed"])
        ),
        "light_cone_level_isolated": (
            kinds["light_cone_level"] == {"light_cone"}
            and bool(deltas["light_cone_level"]["changed"])
        ),
        "inactive_superimposition_static_noop": (
            len(activation) == 1
            and activation[0].activation_status == "inactive"
            and not any(deltas["light_cone_rank"].values())
        ),
        "relic_replacement_breaks_only_its_threshold": (
            threshold_key in base_mechanisms
            and threshold_key not in broken_mechanisms
            and kinds["break_threshold"].issubset({"relic_set_threshold"})
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "deltas": deltas,
            "source_kinds": {
                name: sorted(value) for name, value in kinds.items()
            },
            "speed_threshold_removed": (
                threshold_key in base_mechanisms
                and threshold_key not in broken_mechanisms
            ),
        },
    }


def _variant(
    rules: Any,
    character: CharacterBuildInput,
    equipment: EquipmentBuildInput,
) -> CharacterBuildAssemblyResult:
    result = assemble_character_build(
        rules, replace(character, equipment_build=equipment)
    )
    _require_admitted(result, "delta")
    return result


def _break_threshold(
    bundle: dict[str, Any],
    equipment: EquipmentBuildInput,
    selection: dict[str, Any],
) -> EquipmentBuildInput:
    catalog = bundle["catalog"]
    templates = {
        item.definition_key: item for item in catalog.template_definitions
    }
    speed_set = selection["threshold"].set_key
    for relic in equipment.relics:
        original = templates[relic.template_key]
        if original.set_key != speed_set:
            continue
        for candidate in sorted(
            catalog.template_definitions,
            key=lambda item: item.definition_key.stable_id,
        ):
            if (
                candidate.publication_status != "published"
                or candidate.mode != "BASIC"
                or candidate.set_key == speed_set
                or candidate.slot_key != original.slot_key
                or candidate.main_affix_group_key != original.main_affix_group_key
                or candidate.sub_affix_group_key != original.sub_affix_group_key
            ):
                continue
            replacement = replace(relic, template_key=candidate.definition_key)
            proposed = replace(
                equipment,
                relics=tuple(
                    replacement if item is relic else item
                    for item in equipment.relics
                ),
            )
            result = assemble_character_build(
                bundle["rules"],
                _character(equipment.character_card_id, proposed, "break_probe"),
            )
            if result.battle_admission_status == "admitted":
                return proposed
    raise ValueError("threshold-breaking relic replacement unavailable")


def _ledger(
    assembly: CharacterBuildAssemblyResult,
) -> dict[str, StaticStatContribution]:
    return {
        item.contribution_id: item for item in assembly.contribution_ledger
    }


def _ledger_delta(
    before: dict[str, StaticStatContribution],
    after: dict[str, StaticStatContribution],
) -> dict[str, list[str]]:
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "changed": sorted(
            key
            for key in set(before) & set(after)
            if before[key] != after[key]
        ),
    }


def _delta_kinds(
    before: dict[str, StaticStatContribution],
    after: dict[str, StaticStatContribution],
    delta: dict[str, list[str]],
) -> set[str]:
    return {
        term.source_ref.definition_kind
        for key in (*delta["added"], *delta["removed"], *delta["changed"])
        if (term := after.get(key) or before.get(key)) is not None
    }


def _birth_matrix(
    rules: Any,
    card: Any,
    character: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
) -> dict[str, Any]:
    definitions = rules.servant_definitions_for_owner(card.entity_ref)
    if (
        len(definitions) != 1
        or not definitions[0].servant_ref
        or not definitions[0].spawn_sources
    ):
        raise ValueError(f"focused servant definition count:{len(definitions)}")
    spawn_source = min(
        definitions[0].spawn_sources,
        key=lambda source: (
            source.source_path,
            source.raw_type,
            source.raw_id,
        ),
    )
    assembly_calls: Counter[str] = Counter()
    assembly_codes = {
        assemble_character_build.__code__: "character",
        assemble_equipment_build.__code__: "equipment",
    }

    def profile_assembly(frame: Any, event: str, _arg: Any) -> None:
        if event == "call" and (label := assembly_codes.get(frame.f_code)):
            assembly_calls[label] += 1

    prior_profile = sys.getprofile()
    sys.setprofile(profile_assembly)
    try:
        built = ScenarioStateBuilder(rules).build(
            _scenario(
                card,
                character,
                "birth",
                initial_servant_ref=definitions[0].servant_ref,
                servant_spawn_source_id=spawn_source.raw_id,
            )
        )
    finally:
        sys.setprofile(prior_profile)
    unit_id = "ally:birth"
    unit = built.state.units[unit_id]
    pools = {item.property_type: item for item in unit.stat_pools}
    pool_rows = {
        name: {
            "base": pools[name].base_value,
            "ratio": pools[name].static_percentage,
            "flat": pools[name].static_flat,
            "recomputed": (
                pools[name].base_value
                * (1 + pools[name].static_percentage)
                + pools[name].static_flat
            ),
            "direct_panel": float(getattr(unit, name)),
        }
        for name in BASE_PROPERTIES
    }
    effective_speed = effective_unit_stat(unit, "speed")
    marker = built.state.global_flags.get(TIMELINE_INITIALIZATION_FLAG)
    marker_speed = (
        marker.get("effective_speeds", {}).get(unit_id, {}).get("value")
        if isinstance(marker, dict)
        and isinstance(marker.get("effective_speeds"), dict)
        and isinstance(marker["effective_speeds"].get(unit_id), dict)
        else None
    )
    rule, reason = rules.select_timeline_rule()
    if rule is None:
        raise ValueError(f"timeline rule missing:{reason}")
    indexes = {
        record_type: next(
            (
                index
                for index, record in enumerate(built.setup_records)
                if record.get("record_type") == record_type
            ),
            -1,
        )
        for record_type in (
            "character_build_assembly",
            "ability_provider_registration",
            "setup_battle_event",
            "setup_timeline_initialization",
        )
    }
    startup_traces = [
        trace
        for trace in built.source_traces
        if trace.get("kind") == "formal_equipment_ability"
        and trace.get("status") == "applied"
    ]
    battle_events = [
        event
        for event in built.setup_events
        if event.event_type == "battle.setup"
        and event.window == "OnEnterBattle"
    ]
    expected_battle_unit_ids = {
        candidate_id
        for candidate_id, candidate in built.state.units.items()
        if not candidate.flags.get("system_entity_kind")
    }
    replay = CombatScheduler(rules).initialize_timeline(built.state)
    provider_records = [
        record
        for record in built.setup_records
        if record.get("record_type") == "ability_provider_registration"
    ]
    raw_providers = unit.flags.get("ability_providers", ())
    provider_ids = [
        str(provider.get("provider_id") or "")
        for provider in raw_providers
        if isinstance(provider, Mapping)
    ]
    registered_provider_ids = [
        str(record.get("provider_id") or "")
        for record in provider_records
    ]
    static_mutations = [
        mutation
        for mutation in built.setup_mutations
        if mutation.source
        in {
            "character_assembler",
            "equipment_assembler",
            "relic_affix_calculator",
            "relic_set_assembler",
        }
        or "contribution_id" in mutation.metadata
    ]
    checks = {
        "formal_panel_and_stat_pools_are_one_static_result": (
            all(
                abs(row["recomputed"] - row["direct_panel"]) <= 1e-9
                for row in pool_rows.values()
            )
            and unit.max_hp == float(assembly.base_panel.max_hp)
            and unit.hp == unit.max_hp
            and unit.energy == 0.0
        ),
        "startup_after_static_panel": (
            indexes["character_build_assembly"]
            < indexes["ability_provider_registration"]
            and bool(startup_traces)
        ),
        "timeline_after_enter_battle_settlement": (
            {str(event.target_id or "") for event in battle_events}
            == expected_battle_unit_ids
            and len({event.event_id for event in battle_events})
            == len(battle_events)
            and indexes["setup_battle_event"]
            < indexes["setup_timeline_initialization"]
            and isinstance(marker, dict)
            and marker.get("phase") == "birth_after_enter_battle"
        ),
        "timeline_uses_final_effective_speed": (
            effective_speed.value > unit.speed
            and marker_speed is not None
            and abs(float(marker_speed) - effective_speed.value) <= 1e-9
            and abs(
                unit.action_value
                - float(rule.base_action_gauge) / effective_speed.value
            )
            <= 1e-9
        ),
        "startup_does_not_reapply_static_terms": not static_mutations,
        "scheduler_does_not_reinitialize_birth_timeline": (
            replay.after_state == built.state
            and not replay.transition.transaction.mutations
            and not replay.transition.coverage.get("blocked_reason")
        ),
        "duplicate_dynamic_provider_registries_zero": (
            bool(provider_ids)
            and len(provider_records) == len(provider_ids)
            and len(provider_ids) == len(set(provider_ids))
            and set(registered_provider_ids) == set(provider_ids)
        ),
    }
    return {
        "built": built,
        "assembly_calls": dict(assembly_calls),
        "checks": checks,
        "evidence": {
            "checks": checks,
            "assembly_calls": dict(assembly_calls),
            "record_indexes": indexes,
            "startup_traces": startup_traces,
            "battle_events": [event.to_json() for event in battle_events],
            "stat_pools": pool_rows,
            "static_speed": unit.speed,
            "effective_speed": effective_speed.to_json(),
            "timeline_marker": marker,
            "action_value": unit.action_value,
            "scheduler_replay_mutations": len(
                replay.transition.transaction.mutations
            ),
            "provider_registration_records": len(provider_records),
            "provider_ids": provider_ids,
            "static_term_runtime_mutations": len(static_mutations),
        },
    }


def _negative_matrix(
    bundle: dict[str, Any],
    card: Any,
    character: CharacterBuildInput,
) -> dict[str, Any]:
    rules = bundle["rules"]
    errors = {
        "panel": _error(
            lambda: ScenarioStateBuilder(rules).build(
                _scenario(
                    card,
                    character,
                    "panel_override",
                    panel=PanelInput(max_hp=999999.0),
                )
            )
        ),
        "action_value": _error(
            lambda: ScenarioStateBuilder(rules).build(
                _scenario(
                    card,
                    character,
                    "action_value_override",
                    timeline=TimelineSetupSpec(
                        mode="explicit_action_values",
                        action_values={"ally:action_value_override": 1.0},
                    ),
                )
            )
        ),
        "timeline_marker": _error(
            lambda: ScenarioStateBuilder(rules).build(
                _scenario(
                    card,
                    character,
                    "timeline_marker",
                    global_flags={
                        TIMELINE_INITIALIZATION_FLAG: {"status": "initialized"}
                    },
                )
            )
        ),
    }
    encoded = character.equipment_build.to_json()
    encoded["activation_overrides"] = {}
    errors["activation_override"] = _error(
        lambda: EquipmentBuildInput.from_json(encoded)
    )

    blocked_probe = bundle["blocked_graph_probe"]
    blocked_templates = _templates(
        bundle["catalog"],
        blocked_probe["set_key"],
        blocked_probe["require_count"],
    )
    blocked_equipment = _equipment_build(
        bundle,
        card.card_id,
        blocked_templates,
        "p8_s18_blocked",
    )
    blocked_character = _character(
        card.card_id, blocked_equipment, "blocked_graph"
    )
    blocked_assembly = assemble_character_build(rules, blocked_character)
    calls: Counter[str] = Counter()
    labels = {
        UnitState.__init__.__code__: "unit_state",
        register_dynamic_ability_providers.__code__: "provider",
        TimelineSystem.initialize_action_values.__code__: "timeline",
    }

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event == "call" and (label := labels.get(frame.f_code)):
            calls[label] += 1

    prior = sys.getprofile()
    sys.setprofile(profile)
    try:
        errors["blocked_graph"] = _error(
            lambda: ScenarioStateBuilder(rules).build(
                _scenario(card, blocked_character, "blocked_graph")
            )
        )
    finally:
        sys.setprofile(prior)
    checks = {
        "formal_panel_override_rejected": "panel" in errors["panel"].lower(),
        "formal_action_value_override_rejected": bool(errors["action_value"]),
        "formal_activation_override_rejected": (
            "activation_overrides" in errors["activation_override"]
        ),
        "formal_timeline_marker_override_rejected": (
            "timeline initialization" in errors["timeline_marker"].lower()
        ),
        "blocked_graph_prevents_unit_birth": (
            blocked_assembly.battle_admission_status == "blocked"
            and bool(errors["blocked_graph"])
            and not calls["unit_state"]
            and not calls["provider"]
            and not calls["timeline"]
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "errors": errors,
            "blocked_graph_status": blocked_assembly.battle_admission_status,
            "blocked_graph_calls": dict(calls),
            "blocked_graph_probe": {
                "threshold_key": blocked_probe["threshold_key"].stable_id,
                "graph_id": blocked_probe["graph_id"],
                "source": blocked_probe["source"],
            },
        },
    }


def _error(call: Callable[[], Any]) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return ""


def _summon_matrix(
    rules: Any,
    card: Any,
    character: CharacterBuildInput,
) -> dict[str, Any]:
    equipped_birth = ScenarioStateBuilder(rules).build(
        _scenario(card, character, "equipped_owner")
    )
    empty = EquipmentBuildInput(
        build_id="validation:p8_s18:empty_equipment",
        character_card_id=card.card_id,
    )
    empty_character = _character(card.card_id, empty, "empty_owner")
    empty_birth = ScenarioStateBuilder(rules).build(
        _scenario(card, empty_character, "empty_owner")
    )
    definitions = rules.servant_definitions_for_owner(card.entity_ref)
    if len(definitions) != 1 or not definitions[0].spawn_sources:
        raise ValueError(f"focused servant definition count:{len(definitions)}")
    definition = definitions[0]
    equipped_unit = _spawn(
        rules, equipped_birth.state, definition, "ally:equipped_owner"
    )
    empty_unit = _spawn(
        rules, empty_birth.state, definition, "ally:empty_owner"
    )
    owned = equipped_birth.character_build_results[0].owned_combatant_results[0]
    bindings = {
        item.property_type: item for item in owned.stat_bindings
    }
    values = {
        "max_hp": (equipped_unit.max_hp, empty_unit.max_hp),
        "attack": (equipped_unit.attack, empty_unit.attack),
        "defense": (equipped_unit.defense, empty_unit.defense),
        "speed": (equipped_unit.speed, empty_unit.speed),
        "energy": (equipped_unit.energy, empty_unit.energy),
        "max_energy": (equipped_unit.max_energy, empty_unit.max_energy),
        "base_aggro": (
            equipped_unit.resources.get("base_aggro"),
            empty_unit.resources.get("base_aggro"),
        ),
        "critical_chance": (
            equipped_unit.resources.get("critical_chance"),
            empty_unit.resources.get("critical_chance"),
        ),
        "critical_damage": (
            equipped_unit.resources.get("critical_damage"),
            empty_unit.resources.get("critical_damage"),
        ),
    }
    changed = {
        name for name, pair in values.items() if pair[0] != pair[1]
    }
    explicit = {"owner_linear", "owner_field", "owner_resource"}
    fixed = {"fixed", "inactive_schema_slot"}
    template = rules.unit_birth_template(definition.birth_template_id)
    if template is None:
        raise ValueError("servant birth template missing")
    specs = {
        key: value
        for key, value in {
            **template.unit_field_specs,
            **template.resource_specs,
        }.items()
        if key in values
    }
    checks = {
        "summon_equipment_inheritance_requires_source": (
            bool(changed)
            and all(
                bindings[name].binding_kind in explicit
                and bool(bindings[name].sources)
                for name in changed
            )
            and all(
                values[name][0] == values[name][1]
                for name, binding in bindings.items()
                if name in values and binding.binding_kind in fixed
            )
        ),
        "summon_birth_uses_explicit_owned_bindings": all(
            isinstance(spec, dict)
            and spec.get("binding_kind") == "owned_combatant_stat"
            for spec in specs.values()
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "servant_definition_id": definition.servant_definition_id,
            "birth_template_id": definition.birth_template_id,
            "changed_properties": sorted(changed),
            "bindings": {
                name: bindings[name].to_json() for name in sorted(bindings)
            },
            "values": {
                name: {"equipped_owner": pair[0], "empty_owner": pair[1]}
                for name, pair in values.items()
            },
            "birth_specs": specs,
        },
    }


def _spawn(rules: Any, state: Any, definition: Any, owner_id: str) -> UnitState:
    system = SummonSystem(rules)
    plan = system.plan_spawn_servant(
        state,
        definition,
        owner_id=owner_id,
        spawn_source=definition.spawn_sources[0],
    )
    if not plan.ok:
        raise ValueError(f"servant plan blocked:{plan.blocked_reason}")
    result = system.apply_spawn_servant(state, plan)
    if not result.plan.ok:
        raise ValueError(f"servant apply blocked:{result.plan.blocked_reason}")
    after = MutationReducer().apply_all(state, result.mutations)
    return after.units[plan.unit_ids[0]]


def _walkback(
    root: Path,
    rules: Any,
    character: CharacterBuildInput,
    assembly: CharacterBuildAssemblyResult,
) -> dict[str, Any]:
    admission_errors = validate_character_build_admission(
        rules, character, assembly
    )
    files: dict[str, int] = {}
    rows = []
    for term in assembly.contribution_ledger:
        source = term.source
        path = Path(source.source_path)
        absolute = path if path.is_absolute() else root / path
        exists = absolute.is_file()
        locators = _source_locators(source.evidence)
        if exists:
            files[source.source_path] = absolute.stat().st_size
        rows.append(
            {
                "contribution_id": term.contribution_id,
                "source_kind": term.source_ref.definition_kind,
                "source_path": source.source_path,
                "raw_type": source.raw_type,
                "raw_id": source.raw_id,
                "evidence_locators": locators,
                "exists": exists,
                "validation_source": (
                    "validation" in source.source_path.lower()
                    or "validation" in source.raw_id.lower()
                ),
            }
        )
    checks = {
        "ledger_walkback_closes_to_production_sources": (
            not admission_errors
            and all(
                row["exists"]
                and bool(row["evidence_locators"])
                and not row["validation_source"]
                for row in rows
            )
        )
    }
    return {
        "checks": checks,
        "evidence": {
            "checks": checks,
            "admission_errors": list(admission_errors),
            "source_file_count": len(files),
            "source_bytes": sum(files.values()),
            "source_files": files,
            "terms": rows,
        },
    }


def _source_locators(evidence: Any) -> list[str]:
    if not isinstance(evidence, Mapping):
        return []
    locators = [
        str(evidence[key])
        for key in ("json_path", "raw_path")
        if isinstance(evidence.get(key), str) and evidence[key]
    ]
    stat_paths = evidence.get("stat_raw_paths")
    if isinstance(stat_paths, Mapping):
        locators.extend(
            str(value)
            for _, value in sorted(stat_paths.items())
            if isinstance(value, str) and value
        )
    elif isinstance(stat_paths, Sequence) and not isinstance(
        stat_paths, (str, bytes)
    ):
        locators.extend(
            str(value)
            for value in stat_paths
            if isinstance(value, str) and value
        )
    return sorted(set(locators))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate P8-S18 final panel and formal birth order."
    )
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate(args.tbgd_root, args.output_dir)
    print(
        "P8-S18 "
        f"ok={result['ok']} "
        f"ready_for_review={result['ready_for_review']} "
        f"wall_seconds={result['resources']['wall_seconds']} "
        f"peak_rss_kib={result['resources']['peak_rss_kib']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
