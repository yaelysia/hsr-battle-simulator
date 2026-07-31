from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .. import BASELINE_VERSION
from ..builds.equipment_assembler import assemble_equipment_build
from ..builds.models import CharacterBuildInput, CharacterInitialConditionInput
from ..core.model import BattleState, UnitState
from ..equipment.models import (
    EquipmentAssemblyResult, EquipmentBuildInput, EquipmentDefinitionKey,
    RelicInstanceInput, RelicSetThresholdParameterBasis,
)
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import CanonicalIR, RuleEntity
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder, _equipment_startup_spec
from ..scenarios.schema import BattleSetupSpec, ScenarioSpec, TimelineSetupSpec, UnitSpec
from ..systems.ability_provider import register_dynamic_ability_providers
from ..tbgd.character_cards import build_character_card_ir
from ..tbgd.equipment_ability_families import classify_equipment_family
from ..tbgd.lowering import (
    CHARACTER_ACTION_DEFINITION_TABLES, TBGDLowering,
    _attach_equipment_mechanism_refs, _block_status_callback_tasks_by_callback,
    _block_status_callbacks_by_event_family, _equipment_ability_source_projection,
    _link_status_effect_runtime_fields, _lower_status_event_families,
    _status_event_blocked_reasons, build_character_action_definition_ir,
)
from ..tbgd.relic_cards import build_relic_catalog, require_complete_relic_catalog
from .io import write_json


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _build_bundle(tbgd_root)
    samples = _build_samples(bundle)
    behavior = _behavior_matrix(bundle, samples)
    conflicts = _conflict_matrix(bundle, samples)
    ledger = _blocker_ledger(bundle)
    predicates = {**behavior["checks"], **conflicts["checks"]}
    predicates["s16_s17_blocker_ledger_exact"] = all(ledger["checks"].values())
    ok = all(predicates.values())
    artifacts = {
        "behavior_matrix_p8_s15.json": behavior,
        "conflict_matrix_p8_s15.json": conflicts,
        "s16_s17_family_blocker_ledger_p8_s15.json": ledger,
    }
    for filename, payload in artifacts.items():
        write_json(output_dir / filename, payload)
    graphs = bundle["graphs"]
    summary = {
        "ok": ok,
        "predicates": predicates,
        "counts": {
            "dynamic_thresholds": len(bundle["dynamic_thresholds"]),
            "executable_graphs": sum(g.coverage_status == "executable" for g in graphs),
            "blocked_graphs": sum(g.coverage_status != "executable" for g in graphs),
            "blocking_dependencies": ledger["blocking_dependency_count"],
        },
        "resources": {
            "focused_rulebooks": 1,
            "full_lowering": 0,
            "full_relic_transitions": 0,
            "artifact_files": sorted(artifacts),
        },
        "evidence_boundary": {
            "inherited": ["P8-S9 raw truth", "P8-S13 decision", "P8-S14 static ledger"],
            "raw_oracle_run": False,
            "reviewer_only": ["relic-specific event-loop absence"],
        },
    }
    write_json(output_dir / "validation_summary_p8_s15_relic_set_dynamic_startup.json", summary)
    return summary


def _build_bundle(tbgd_root: Path) -> dict[str, Any]:
    root = tbgd_root.resolve()
    catalog = require_complete_relic_catalog(build_relic_catalog(root))
    lowering = TBGDLowering(root)
    projection = sorted(_equipment_ability_source_projection(catalog.set_thresholds).items())
    lowered_files = [
        lowering._lower_ability_file(
            root / relative,
            {},
            ability_file_order=order,
            selected_equipment_sources=selected,
        )
        for order, (relative, selected) in enumerate(projection)
    ]

    def flat(field: str) -> tuple[Any, ...]:
        return tuple(item for lowered in lowered_files for item in getattr(lowered, field))

    callbacks = list(flat("status_callbacks"))
    callback_tasks = list(flat("status_callback_tasks"))
    families = list(_lower_status_event_families(callbacks, callback_tasks))
    support = _support_event_families(
        lowering,
        {"OnCreate", "OnModifierAdd", "OnListenModifierAdd"}.difference(
            family.callback_event for family in families
        ),
    )
    families = list(_unique((*families, *support), "status_event_family_id"))
    event_blocked = _status_event_blocked_reasons(families)
    callbacks = _block_status_callbacks_by_event_family(callbacks, event_blocked)
    callback_blocked = {
        callback.callback_id: event_blocked[callback.event]
        for callback in callbacks
        if callback.event in event_blocked
    }
    callback_tasks = _block_status_callback_tasks_by_callback(callback_tasks, callback_blocked)
    families = list(_unique(
        (*_lower_status_event_families(callbacks, callback_tasks), *support),
        "status_event_family_id",
    ))
    (
        graphs,
        phases,
        tasks,
        graph_effects,
        graph_conditions,
        formulas,
        graph_targets,
        parameter_reads,
    ) = lowering._lower_equipment_ability_graphs(
        catalog.set_thresholds,
        status_callbacks=callbacks,
    )
    _, clean_thresholds, clean_refs = _attach_equipment_mechanism_refs(
        (), catalog.set_thresholds, graphs, parameter_reads
    )
    cases = _choose_cases(catalog, clean_thresholds, clean_refs, graphs)
    reserved = cases["duplicate"]
    duplicate_variant = replace(
        reserved,
        coverage_status="blocked",
        blocked_reason="validation_duplicate_definition",
    )
    _, duplicate_thresholds, duplicate_refs = _attach_equipment_mechanism_refs(
        (), (reserved, duplicate_variant), graphs, parameter_reads
    )
    mechanism_key = duplicate_thresholds[0].mechanism_ref_ids[0]
    formal_thresholds = (
        *(item for item in clean_thresholds if item.definition_key != reserved.definition_key),
        *duplicate_thresholds,
    )
    formal_refs = (
        *(item for item in clean_refs if item.definition_key != mechanism_key),
        *duplicate_refs,
    )

    characters = build_character_card_ir(
        root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
    )
    profiles = {profile.avatar_profile_id: profile for profile in characters.avatar_profiles}
    card = next(
        card
        for card in sorted(characters.character_data_cards, key=lambda item: item.card_id)
        if card.coverage_status == "executable"
        and (profile := profiles.get(card.profile_id)) is not None
        and profile.coverage_status == "executable"
        and profile.resource_mode == "standard_energy"
    )
    actions = build_character_action_definition_ir(root)
    avatar_entities = (
        RuleEntity(
            entity_id=card.entity_ref,
            entity_type="avatar",
            fields={"profile_id": card.profile_id},
            source=card.source,
        )
        for card in characters.character_data_cards
    )
    entities = _unique((*flat("entities"), *avatar_entities), "entity_id")
    effects = tuple(
        _link_status_effect_runtime_fields(
            list(_unique((*flat("effects"), *graph_effects), "effect_id")),
            list(entities),
            callbacks,
            flat("ability_property_watchers"),
        )
    )
    engine = build_engine_rule_registry()
    ir = CanonicalIR(
        version=BASELINE_VERSION,
        entities=entities,
        avatar_profiles=characters.avatar_profiles,
        character_data_cards=characters.character_data_cards,
        character_equipment_eligibilities=characters.character_equipment_eligibilities,
        character_mechanism_slots=characters.character_mechanism_slots,
        character_trace_nodes=characters.character_trace_nodes,
        character_eidolon_slots=characters.character_eidolon_slots,
        action_definitions=tuple(actions),
        relic_domain_definitions=catalog.domain_definitions,
        relic_slot_definitions=catalog.slot_definitions,
        relic_main_affix_group_definitions=catalog.main_affix_group_definitions,
        relic_main_affix_definitions=catalog.main_affix_definitions,
        relic_sub_affix_group_definitions=catalog.sub_affix_group_definitions,
        relic_sub_affix_definitions=catalog.sub_affix_definitions,
        relic_template_definitions=catalog.template_definitions,
        relic_set_definitions=catalog.set_definitions,
        relic_set_thresholds=formal_thresholds,
        equipment_ability_parameter_reads=tuple(parameter_reads),
        equipment_mechanism_refs=formal_refs,
        standalone_ability_graphs=tuple(graphs),
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        effects=effects,
        conditions=_unique((*flat("conditions"), *graph_conditions), "condition_id"),
        formulas=tuple(formulas),
        target_expressions=_unique(
            (*flat("target_expressions"), *graph_targets), "target_expression_id"
        ),
        status_callbacks=tuple(callbacks),
        status_callback_tasks=tuple(callback_tasks),
        ability_property_watchers=flat("ability_property_watchers"),
        ability_property_ranges=flat("ability_property_ranges"),
        status_event_families=tuple(families),
        status_damage_emissions=flat("status_damage_emissions"),
        damage_modifiers=flat("damage_modifiers"),
        action_delay_emissions=flat("action_delay_emissions"),
        queue_intents=flat("queue_intents"),
        skill_continuations=flat("skill_continuations"),
        triggers=flat("triggers"),
        timeline_rules=engine.timeline_rules,
        resource_rules=engine.resource_rules,
    )
    rules = RuleBook(ir)
    return {
        "catalog": catalog,
        "lowering": lowering,
        "card": card,
        "rules": rules,
        "cases": cases,
        "graphs": tuple(graphs),
        "callbacks": tuple(callbacks),
        "callback_tasks": tuple(callback_tasks),
        "ability_property_watchers": flat("ability_property_watchers"),
        "ability_property_ranges": flat("ability_property_ranges"),
        "dynamic_thresholds": tuple(t for t in clean_thresholds if t.ability_source is not None),
        "clean_refs": clean_refs,
        "duplicate_thresholds": duplicate_thresholds,
        "duplicate_refs": duplicate_refs,
    }


def _support_event_families(
    lowering: TBGDLowering, required_events: set[str]
) -> tuple[Any, ...]:
    pending = set(required_events)
    callbacks, tasks = [], []
    for order, path in enumerate(lowering._ability_files()):
        if not pending:
            break
        text = path.read_text(encoding="utf-8")
        if not any(f'"{event}"' in text for event in pending):
            continue
        lowered = lowering._lower_ability_file(path, {}, ability_file_order=order)
        selected = tuple(c for c in lowered.status_callbacks if c.event in pending)
        selected_ids = {c.callback_id for c in selected}
        callbacks.extend(selected)
        tasks.extend(t for t in lowered.status_callback_tasks if t.callback_id in selected_ids)
        pending.difference_update(c.event for c in selected)
    families = tuple(
        family for family in _lower_status_event_families(callbacks, tasks)
        if family.callback_event in required_events
    )
    invalid = any(
        f.coverage_status != "executable" or f.admission_status != "executable"
        for f in families
    )
    if pending or invalid:
        raise ValueError(f"focused event-family support incomplete:{sorted(pending)}")
    return families


def _unique(items: Iterable[Any], field: str) -> tuple[Any, ...]:
    result: dict[str, Any] = {}
    for item in items:
        key = getattr(item, field)
        if key in result and result[key] != item:
            raise ValueError(f"focused identity conflict:{field}:{key}")
        result[key] = item
    return tuple(result[key] for key in sorted(result))


def _choose_cases(
    catalog: Any,
    thresholds: tuple[Any, ...],
    refs: tuple[Any, ...],
    graphs: list[Any],
) -> dict[str, Any]:
    ref_by_key = {ref.definition_key: ref for ref in refs}
    graph_by_id = {graph.standalone_ability_graph_id: graph for graph in graphs}

    def graph_for(threshold: Any) -> Any | None:
        if len(threshold.mechanism_ref_ids) != 1:
            return None
        ref = ref_by_key.get(threshold.mechanism_ref_ids[0])
        return graph_by_id.get(ref.graph_ref_id) if ref is not None else None

    candidates = tuple(
        (threshold, graph_for(threshold))
        for threshold in thresholds
        if threshold.ability_source is not None
        and len(_templates(catalog, threshold.set_key)) >= threshold.require_count
    )
    executable = tuple(t for t, graph in candidates if graph and graph.coverage_status == "executable")
    blocked = tuple(t for t, graph in candidates if graph and graph.coverage_status != "executable")
    grouped: dict[EquipmentDefinitionKey, list[Any]] = {}
    for threshold in executable:
        grouped.setdefault(threshold.set_key, []).append(threshold)
    low_high = next(
        (
            (ordered[0], ordered[-1])
            for values in grouped.values()
            if len(ordered := sorted(values, key=lambda t: t.require_count)) >= 2
            and ordered[0].parameters
            and len(_templates(catalog, ordered[0].set_key)) >= ordered[-1].require_count
        ),
        None,
    )
    domains = {item.definition_key: item.domain_key.definition_identity for item in catalog.set_definitions}
    twos = tuple(t for t in executable if t.require_count == 2 and domains[t.set_key] == "outer")

    def pair_templates(left: Any, right: Any) -> tuple[Any, ...]:
        left_templates = _templates(catalog, left.set_key)[:2]
        occupied = {item.slot_key for item in left_templates}
        right_templates = tuple(
            item for item in _templates(catalog, right.set_key) if item.slot_key not in occupied
        )[:2]
        return (*left_templates, *right_templates) if len(right_templates) == 2 else ()

    two_pair = next(
        (
            (left, right, templates)
            for index, left in enumerate(twos)
            for right in twos[index + 1 :]
            if len(templates := pair_templates(left, right)) == 4
        ),
        None,
    )
    if low_high is None or two_pair is None or not blocked:
        raise ValueError("S15 compact validation samples unavailable")
    single = low_high[0]
    used_sets = {single.set_key, low_high[0].set_key, two_pair[0].set_key, two_pair[1].set_key}
    duplicate = next((t for t in executable if t.set_key not in used_sets), None)
    partial = next((t for t in blocked if t.set_key != getattr(duplicate, "set_key", None)), None)
    if duplicate is None or partial is None:
        raise ValueError("S15 duplicate or partial sample unavailable")
    return {
        "single": single,
        "active_templates": _templates(catalog, single.set_key)[: single.require_count],
        "inactive_templates": _templates(catalog, single.set_key)[: max(1, single.require_count - 1)],
        "low_high": low_high,
        "low_high_templates": _templates(catalog, low_high[0].set_key)[: low_high[-1].require_count],
        "two_plus_two": two_pair[:2],
        "two_plus_two_templates": two_pair[2],
        "partial": partial,
        "partial_templates": _templates(catalog, partial.set_key)[: partial.require_count],
        "duplicate": duplicate,
        "duplicate_templates": _templates(catalog, duplicate.set_key)[: duplicate.require_count],
    }


def _templates(catalog: Any, set_key: EquipmentDefinitionKey) -> tuple[Any, ...]:
    selected, slots = [], set()
    for template in sorted(catalog.template_definitions, key=lambda item: item.definition_key.stable_id):
        if (
            template.set_key == set_key
            and template.publication_status == "published"
            and template.mode == "BASIC"
            and template.slot_key not in slots
        ):
            selected.append(template)
            slots.add(template.slot_key)
    return tuple(selected)


def _equipment_build(bundle: dict[str, Any], card_id: str, templates: tuple[Any, ...], tag: str) -> EquipmentBuildInput:
    groups = {
        item.definition_key: item
        for item in bundle["catalog"].main_affix_group_definitions
    }
    return EquipmentBuildInput(
        build_id=f"validation:p8_s15:{tag}",
        character_card_id=card_id,
        relics=tuple(
            RelicInstanceInput(
                instance_id=f"validation:p8_s15:{tag}:relic:{index}",
                template_key=template.definition_key,
                slot_key=template.slot_key,
                level=0,
                main_affix_key=groups[template.main_affix_group_key].affix_keys[0],
            )
            for index, template in enumerate(templates)
        ),
    )


def _build_samples(bundle: dict[str, Any]) -> dict[str, Any]:
    rules, cases = bundle["rules"], bundle["cases"]
    card = bundle["card"]
    builds = {
        "active": _equipment_build(bundle, card.card_id, cases["active_templates"], "active"),
        "inactive": _equipment_build(bundle, card.card_id, cases["inactive_templates"], "inactive"),
        "low_high": _equipment_build(bundle, card.card_id, cases["low_high_templates"], "low-high"),
        "two_plus_two": _equipment_build(
            bundle, card.card_id, cases["two_plus_two_templates"], "two-plus-two"
        ),
        "partial": _equipment_build(bundle, card.card_id, cases["partial_templates"], "partial"),
        "duplicate": _equipment_build(bundle, card.card_id, cases["duplicate_templates"], "duplicate"),
    }
    results = {name: assemble_equipment_build(rules, build) for name, build in builds.items()}
    threshold_key = cases["single"].definition_key
    selection = next(
        item for item in results["active"].dynamic_mechanisms
        if item.target_definition_key == threshold_key
    )
    return {"card": card, "builds": builds, "results": results, "selection": selection}


def _scenario(card: Any, equipment: EquipmentBuildInput, tag: str) -> ScenarioSpec:
    character = CharacterBuildInput(
        build_id=f"validation:p8_s15:character:{tag}", character_card_id=card.card_id,
        level=1, promotion=0, eidolon_level=0, unlocked_trace_node_ids=(),
        equipment_build=equipment,
    )
    return ScenarioSpec(
        scenario_id=f"validation:p8_s15:{tag}",
        version=BASELINE_VERSION,
        units=(
            UnitSpec(
                unit_id=f"ally:{tag}",
                side="ally",
                entity_ref=card.entity_ref,
                build_mode="assembled_character_build",
                level=character.level,
                eidolon_level=character.eidolon_level,
                panel=None,
                character_build=character,
                initial_condition=CharacterInitialConditionInput(hp_mode="full", initial_energy="0"),
            ),
        ),
        route=(),
        battle_setup=BattleSetupSpec(timeline=TimelineSetupSpec(mode="runtime_initialize")),
    )


def _provider_state(card: Any, unit_ids: tuple[str, ...]) -> BattleState:
    return BattleState(
        units={
            unit_id: UnitState(
                unit_id=unit_id,
                side="ally",
                template_id=card.entity_ref,
                flags={"character_data_card_id": card.card_id},
            )
            for unit_id in unit_ids
        }
    )


def _provider_ids(state: BattleState) -> tuple[str, ...]:
    return tuple(
        str(provider["provider_id"])
        for unit_id in sorted(state.units)
        for provider in state.units[unit_id].flags.get("ability_providers", ())
        if isinstance(provider, dict) and provider.get("provider_id")
    )


def _behavior_matrix(bundle: dict[str, Any], samples: dict[str, Any]) -> dict[str, Any]:
    rules, cases, card = bundle["rules"], bundle["cases"], samples["card"]
    results, builds = samples["results"], samples["builds"]
    selection = samples["selection"]

    def register(pairs: Iterable[tuple[str, Any]]) -> Any:
        items = tuple(pairs)
        unit_ids = tuple(dict.fromkeys(unit_id for unit_id, _ in items))
        return register_dynamic_ability_providers(_provider_state(card, unit_ids), rules, items)

    call_codes = {
        register_dynamic_ability_providers.__code__: "provider",
        _equipment_startup_spec.__code__: "startup",
    }
    profiled_calls: Counter[str] = Counter()
    forbidden_modules = set()

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call":
            return
        if label := call_codes.get(frame.f_code):
            profiled_calls[label] += 1
        module = str(frame.f_globals.get("__name__") or "")
        if ".tbgd" in module or module.endswith(".builds.relic_set_assembler"):
            forbidden_modules.add(module)

    prior_profile = sys.getprofile()
    sys.setprofile(profile)
    try:
        first = register((("ally:a", selection),))
        startup_spec = _equipment_startup_spec(rules, selection)
    finally:
        sys.setprofile(prior_profile)
    replay = register_dynamic_ability_providers(first.after_state, rules, (("ally:a", selection),))
    provider_groups = {}
    for name in ("low_high", "two_plus_two"):
        keys = {item.definition_key for item in cases[name]}
        selections = tuple(
            item for item in results[name].dynamic_mechanisms
            if item.target_definition_key in keys
        )
        provider_groups[name] = (selections, register(("ally:a", item) for item in selections))
    multi = register((("ally:a", selection), ("ally:b", selection)))

    scenario = _scenario(card, builds["active"], "startup")
    built = ScenarioStateBuilder(rules).build(scenario)
    provider_indices = tuple(
        index for index, mutation in enumerate(built.setup_mutations)
        if mutation.source == "ability_provider_registry"
    )
    partial_error = _captured_value_error(
        lambda: ScenarioStateBuilder(rules).build(_scenario(card, builds["partial"], "partial"))
    )

    invalid_selections = {
        "forged_source": replace(selection, source=replace(selection.source, raw_id="forged:source")),
        "missing_parameter": replace(selection, parameter_bindings=selection.parameter_bindings[:-1]),
    }
    invalid_results = {
        name: register((("ally:negative", invalid),))
        for name, invalid in invalid_selections.items()
    }

    threshold_resolution = rules.relic_set_threshold(
        selection.target_definition_key.definition_identity
    )
    threshold = threshold_resolution.value
    context, context_reason = rules.equipment_dynamic_parameter_context(
        selection.target_definition_key, selection.parameter_basis
    )
    chain_ok = bool(
        threshold_resolution.resolution_status == "resolved" and threshold is not None
        and threshold.ability_source is not None and context is not None and not context_reason
        and context.mechanism_ref.definition_key == selection.mechanism_key
        and context.graph.standalone_ability_graph_id == selection.graph_ref_id
        and context.graph.source == threshold.ability_source.source == selection.source
        and context.mechanism_ref.parameter_binding_ids == tuple(
            item.parameter_read_id for item in selection.parameter_bindings
        )
    )
    inactive_key = cases["single"].definition_key
    mutation = first.mutations[0] if len(first.mutations) == 1 else None
    record = first.records[0] if len(first.records) == 1 else {}

    def group_ok(name: str) -> bool:
        selections, registration = provider_groups[name]
        return bool(
            results[name].battle_admission_status == "admitted"
            and registration.ok
            and len(selections) == 2
            and len(set(_provider_ids(registration.after_state))) == 2
        )

    checks = {
        "canonical_threshold_graph_parameter_source_chain": chain_ok,
        "active_inactive_threshold_selection": (
            results["active"].battle_admission_status == "admitted"
            and results["inactive"].battle_admission_status == "admitted"
            and any(m.target_definition_key == inactive_key for m in results["active"].dynamic_mechanisms)
            and not any(m.target_definition_key == inactive_key for m in results["inactive"].dynamic_mechanisms)
        ),
        "low_high_threshold_providers_distinct": group_ok("low_high"),
        "two_plus_two_providers_distinct": group_ok("two_plus_two"),
        "multi_wearer_providers_isolated": (
            multi.ok and len(set(_provider_ids(multi.after_state))) == 2
            and all(len(multi.after_state.units[u].flags.get("ability_providers", ())) == 1
                    for u in ("ally:a", "ally:b"))
        ),
        "startup_order_and_idempotence": (
            first.ok and len(first.mutations) == 1 and bool(provider_indices)
            and provider_indices == tuple(range(len(provider_indices)))
            and replay.ok and replay.state_unchanged and not replay.mutations
        ),
        "partial_graph_blocks_startup": (
            results["partial"].battle_admission_status == "blocked"
            and not results["partial"].dynamic_mechanisms
            and "equipment_build_not_admitted_for_battle" in partial_error
        ),
        "forged_source_and_missing_parameter_block_atomically": all(
            not result.ok and result.state_unchanged and not result.mutations
            for result in invalid_results.values()
        ),
        "runtime_consumes_common_selection_and_canonical_ir": (
            profiled_calls == {"provider": 1, "startup": 1} and not forbidden_modules
            and startup_spec.get("slot") is selection
            and startup_spec.get("graph_ref_id") == selection.graph_ref_id
            and mutation is not None and mutation.source == "ability_provider_registry"
            and mutation.reason == "register_canonical_ability_provider"
            and record.get("record_type") == "ability_provider_registration"
            and record.get("mutation_id") == mutation.stable_id()
        ),
    }
    return {
        "checks": checks,
        "evidence": {
            "chain_query_reason": context_reason,
            "negative_reasons": {n: r.blocked_reason for n, r in invalid_results.items()},
            "runtime_calls": dict(sorted(profiled_calls.items())),
            "forbidden_modules": sorted(forbidden_modules),
            "mutation_source": mutation.source if mutation else "",
            "record_type": record.get("record_type"),
        },
    }


def _captured_value_error(callback: Any) -> str:
    try:
        callback()
    except ValueError as exc:
        return str(exc)
    return ""


def _conflict_matrix(bundle: dict[str, Any], samples: dict[str, Any]) -> dict[str, Any]:
    rules, duplicate = bundle["rules"], bundle["cases"]["duplicate"]
    resolution = rules.relic_set_threshold(duplicate.definition_key.definition_identity)
    basis = RelicSetThresholdParameterBasis(
        threshold_key=duplicate.definition_key, set_key=duplicate.set_key,
        required_count=duplicate.require_count, source=duplicate.source,
    )
    context, context_reason = rules.equipment_dynamic_parameter_context(duplicate.definition_key, basis)
    raw = next(
        t for t in bundle["catalog"].set_thresholds
        if t.definition_key == bundle["cases"]["single"].definition_key
    )
    ability = raw.ability_source
    if ability is None:
        raise ValueError("physical-source conflict sample has no ability")
    conflict_name = f"{ability.ability_name}:validation_conflict"
    conflicting = replace(
        raw,
        ability_source=replace(
            ability, ability_name=conflict_name,
            source=replace(ability.source, raw_id=conflict_name)
        ),
    )
    lowering = bundle["lowering"]
    identical = lowering._lower_equipment_ability_graphs(
        (raw, raw), status_callbacks=list(bundle["callbacks"])
    )
    orders = {"forward": (raw, conflicting), "reverse": (conflicting, raw)}
    projections = {name: _equipment_ability_source_projection(items)
                   for name, items in orders.items()}
    lowered = {
        name: lowering._lower_equipment_ability_graphs(
            items, status_callbacks=list(bundle["callbacks"])
        )
        for name, items in orders.items()
    }

    result: EquipmentAssemblyResult = samples["results"]["two_plus_two"]
    mechanisms = result.dynamic_mechanisms
    reversed_result = replace(result, dynamic_mechanisms=tuple(reversed(mechanisms)))
    reversed_payload = result.to_json()
    reversed_payload["dynamic_mechanisms"] = list(reversed(reversed_payload["dynamic_mechanisms"]))
    decoded_reversed = EquipmentAssemblyResult.from_json(reversed_payload)
    variants = {
        "selection_id": replace(mechanisms[1], selection_id=mechanisms[0].selection_id),
        "provider_semantics": replace(mechanisms[0],
                                      selection_id=f"{mechanisms[0].selection_id}:duplicate"),
    }
    constructor_errors, codec_errors = {}, {}
    for name, duplicate_selection in variants.items():
        rows = (mechanisms[0], duplicate_selection, *mechanisms[2:])
        constructor_errors[name] = _captured_value_error(
            lambda rows=rows: replace(result, dynamic_mechanisms=rows))
        payload = result.to_json()
        payload["dynamic_mechanisms"][1] = duplicate_selection.to_json()
        codec_errors[name] = _captured_value_error(
            lambda payload=payload: EquipmentAssemblyResult.from_json(payload))
    expected_errors = {
        "selection_id": "dynamic mechanism selection identities must be unique",
        "provider_semantics": "dynamic mechanism provider semantics must be unique",
    }
    duplicate_result = samples["results"]["duplicate"]
    linked = bundle["duplicate_thresholds"]
    checks = {
        "duplicate_definition_preserved_and_fail_closed": (
            len(linked) == len(bundle["duplicate_refs"]) == 2
            and tuple(item.coverage_status for item in linked) == ("lowered", "blocked")
            and resolution.resolution_status == "blocked"
            and resolution.blocked_reason == "equipment_definition_ambiguous"
            and len(resolution.candidates) == 2 and context is None
            and context_reason == "equipment_definition_ambiguous"
            and duplicate_result.assembly_status == "blocked" and not duplicate_result.dynamic_mechanisms
        ),
        "physical_source_conflict_order_invariant": (
            not projections["forward"]
            and projections["forward"] == projections["reverse"]
            and all(not channel for channel in lowered["forward"])
            and tuple(map(tuple, lowered["forward"])) == tuple(map(tuple, lowered["reverse"]))
        ),
        "identical_physical_source_lowered_once": (
            sum(len(rows) for rows in _equipment_ability_source_projection((raw, raw)).values()) == 1
            and len(identical[0]) == 1
        ),
        "dynamic_result_order_canonical": (
            reversed_result.to_json() == decoded_reversed.to_json() == result.to_json()
            and reversed_result.result_fingerprint == result.result_fingerprint
        ),
        "dynamic_result_duplicate_id_and_semantics_rejected":
            constructor_errors == codec_errors == expected_errors,
    }
    return {
        "checks": checks,
        "evidence": {
            "duplicate_key": duplicate.definition_key.stable_id,
            "physical_row": [ability.source.source_path, ability.record_index],
            "conflict_channel_counts": {n: [len(c) for c in channels]
                                        for n, channels in lowered.items()},
            "result_fingerprint": result.result_fingerprint,
            "constructor_errors": constructor_errors,
            "codec_errors": codec_errors,
        },
    }


def _blocker_ledger(bundle: dict[str, Any]) -> dict[str, Any]:
    callbacks = {item.callback_id: item for item in bundle["callbacks"]}
    tasks_by_callback: dict[str, list[Any]] = {}
    for task in bundle["callback_tasks"]:
        tasks_by_callback.setdefault(task.callback_id, []).append(task)
    refs = {item.definition_key: item for item in bundle["clean_refs"]}
    graphs = {item.standalone_ability_graph_id: item for item in bundle["graphs"]}
    blocked_graph_ids = {graph_id for graph_id, graph in graphs.items()
                         if graph.coverage_status != "executable"}
    rows = []
    for threshold in bundle["dynamic_thresholds"]:
        ref = refs.get(threshold.mechanism_ref_ids[0]) if len(threshold.mechanism_ref_ids) == 1 else None
        graph = graphs.get(ref.graph_ref_id) if ref is not None else None
        if graph is None or graph.coverage_status == "executable":
            continue
        blockers = []
        for callback_id in graph.status_callback_ids:
            callback = callbacks.get(callback_id)
            if callback is None or (
                callback.coverage_status == callback.admission_status == "executable"
            ):
                continue
            blocked_tasks = tuple(task for task in tasks_by_callback.get(callback_id, ())
                                  if task.coverage_status != "executable")
            reason = callback.blocked_reason or callback.blocking_dependency or "callback_not_admitted"
            if reason != "equipment_callback_contains_unadmitted_task" or not blocked_tasks:
                blockers.append(_family_row("event", callback.event, reason))
            blockers.extend(
                _family_row(*_task_family(task),
                            task.blocked_reason or "callback_task_not_admitted")
                for task in blocked_tasks
            )
        if not blockers:
            blockers.append(_family_row("graph", graph.blocked_reason, graph.blocked_reason))
        rows.append(
            {
                "threshold": threshold.definition_key.stable_id,
                "graph": graph.standalone_ability_graph_id,
                "graph_reason": graph.blocked_reason,
                "families": blockers,
            }
        )
    family_counts: Counter[tuple[str, str, str, str]] = Counter()
    stage_counts: Counter[str] = Counter()
    stage_thresholds: dict[str, set[str]] = {}
    for row in rows:
        for blocker in row["families"]:
            key = (blocker["stage"], blocker["kind"], blocker["family"], blocker["reason"])
            family_counts[key] += 1
            stage_counts[key[0]] += 1
            stage_thresholds.setdefault(key[0], set()).add(row["threshold"])
    totals = [
        {"stage": stage, "kind": kind, "family": family, "reason": reason,
         "dependency_count": count}
        for (stage, kind, family, reason), count in sorted(family_counts.items())
    ]
    stage_totals = {
        stage: {"dependency_count": count,
                "affected_threshold_count": len(stage_thresholds[stage])}
        for stage, count in sorted(stage_counts.items())
    }
    accounted = {row["graph"] for row in rows}
    checks = {
        "all_blocked_graphs_accounted":
            blocked_graph_ids == accounted and all(row["families"] for row in rows),
        "no_s16_s17_family_partially_executed": all(
            row["graph_reason"] in {
                "equipment_ability_callback_graph_partial",
                "equipment_ability_nested_modifier_graph_unclassified",
            }
            for row in rows
        ),
    }
    return {
        "checks": checks,
        "blocked_graph_count": len(blocked_graph_ids),
        "blocking_dependency_count": sum(family_counts.values()),
        "graph_blocked_reason_totals":
            dict(sorted(Counter(row["graph_reason"] for row in rows).items())),
        "rows": rows,
        "stage_totals": stage_totals,
        "totals": totals,
    }


def _family_row(kind: str, family: str, reason: str) -> dict[str, Any]:
    raw_stage = (
        "unknown" if "unclassified" in reason else "s8"
    ) if kind == "graph" else classify_equipment_family(kind, family)
    if "deferred_to_p8_s8" in reason:
        stage = "s8"
    elif (
        "unclassified" in reason
        or reason == "callback_not_admitted"
        or ("missing:" in reason and raw_stage == "unknown")
    ):
        stage = "unknown"
    else:
        stage = raw_stage
    return {"kind": kind, "family": family, "raw_stage": raw_stage,
            "stage": stage, "reason": reason}


def _task_family(task: Any) -> tuple[str, str]:
    reason = str(task.blocked_reason or "")
    if reason.startswith("condition_not_executable:"):
        return "condition", reason.rsplit(":", 1)[-1]
    if reason.startswith("event_source_missing:"):
        return "event", reason.split(":", 1)[1]
    if reason.startswith("target_not_executable:"):
        return "target", reason.rsplit(":", 1)[-1]
    return "task", task.opcode


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = validate(args.tbgd_root, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
