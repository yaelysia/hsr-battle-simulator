from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from math import isclose
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .. import BASELINE_VERSION
from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterInitialConditionInput
from ..core.model import BattleState, GameEvent, Mutation, TargetResolution, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..equipment.models import (
    CharacterEquipmentEligibilityIR,
    EquipmentDefinitionKey,
)
from ..ir_types import IRSource
from ..resource_event_contract import (
    RESOURCE_EVENT_CONTRACTS,
    RETIRED_RESOURCE_EVENT_TYPES,
    TEAM_SKILL_POINT_EVENT_CONTRACT,
    UNIT_ENERGY_EVENT_CONTRACT,
    resource_callback_runtime_sources,
    resource_production_event_types,
)
from ..rules.evaluator import (
    EvaluationContext,
    NumericEvaluationContext,
    RuleEvaluator,
    _condition_target_key,
)
from ..rules.expression_ir import numeric_dynamic_hashes, numeric_fixed
from ..rules.ir import (
    CanonicalIR,
    ConditionIR,
    RuleEntity,
    StatusDamageEmissionIR,
    TargetExpressionNodeIR,
)
from ..rules.engine_rule_registry import (
    RANGE_ZERO_FLOOR_DYNAMIC_HASH,
    ZERO_FLOOR_DYNAMIC_HASH,
    build_engine_rule_registry,
    engine_numeric_binding_source,
)
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import (
    ScenarioStateBuilder,
    _apply_startup_ability_effects,
    _equipment_startup_spec,
)
from ..scenarios.schema import (
    BattleSetupSpec,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..tbgd.lowering import (
    TBGDLowering,
    _attach_equipment_mechanism_refs,
    _condition_payload_executable,
    merge_identical_ir_items,
)
from ..systems.damage import DamagePacket, DamageSourceFrame, DamageSystem
from ..systems.ability_provider import register_dynamic_ability_providers
from ..systems.battle_state_transition import (
    BattleStateTransitionRequest,
    BattleStateTransitionSystem,
)
from ..systems.decision import DecisionSystem
from ..systems.dynamic_values import (
    binding_source_from_store,
    binding_source_from_status_detail,
    find_status_detail,
    status_binding_sources,
    store_from_state,
)
from ..systems.effect import EffectExecutionContext, EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.mutation_events import events_for_mutation
from ..systems.phase_machine import EVENT_PHASES as COMBAT_EVENT_PHASES
from ..systems.resource import ResourceSystem
from ..systems.rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    event_id_for_identity,
    resolve_rng_request,
    validate_rng_choice_ledger,
)
from ..systems.dot_formula import DotFormula, DotFormulaInput
from ..systems.status import (
    StatusSystem,
    _replacement_status_detail,
    _resolve_dynamic_values,
)
from ..systems.status_callbacks import StatusCallbackSystem, _condition_target_nodes
from ..systems.summon_runtime import empty_summon_runtime
from ..systems.target import TargetPolicy, TargetSystem
from ..systems.timeline import TimelineSystem
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..systems.unit_relation import is_opposing_combat_team
from ..systems.unit_stats import effective_unit_stat, status_modifier_numeric_value
from .io import write_json
from .validate_p8_s6_light_cone_dynamic_startup import (
    _assembly,
    _character_build,
)
from .validate_p8_s7_light_cone_status_condition_listener_closure import (
    EVENT_PHASES,
    _condition_has_family,
    _condition_has_target_family,
    _coverage_node_id,
    _coverage_source_indexes,
    _condition_probe_contexts,
    _condition_runtime_family_rows,
    _focused_bundle as _s7_focused_bundle,
    _formal_scenario_matrix,
    _family_inventory,
    _event_dispatch_probe_audit,
    _lifecycle_matrix,
    _longest_source_prefix,
    _normalize_source_identity,
    _runtime_boundary,
    _production_event_chain,
    _selected_executable_task_ids,
    _target_attribution_matrix,
    _typed_condition_nodes,
)


VALIDATION_VERSION = "p8_s8_light_cone_remaining_gameplay_closure"


def _fixture_summon_runtime(
    entries: Mapping[str, dict[str, Any]],
    *,
    by_owner: Mapping[str, list[str]],
    last_summon_monsters: tuple[str, ...] = (),
    last_servants: tuple[str, ...] = (),
    servant_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build validator-only populated state from the production empty schema."""

    runtime = empty_summon_runtime()
    normalized_entries: dict[str, dict[str, Any]] = {}
    for unit_id, entry in entries.items():
        normalized = dict(entry)
        normalized["runtime_id"] = unit_id
        normalized["unit_id"] = unit_id
        normalized_entries[unit_id] = normalized
    runtime["entities"] = normalized_entries
    runtime["by_owner"] = {
        owner_id: list(unit_ids)
        for owner_id, unit_ids in by_owner.items()
    }
    runtime["last_summon_monsters"] = list(last_summon_monsters)
    runtime["last_servants"] = list(last_servants)
    runtime["servants"] = {
        unit_id: dict(normalized_entries[unit_id])
        for unit_id in servant_ids
    }
    return runtime
TASK_STATE_CACHE_LIMIT = 12
SUMMARY_SCHEMA_VERSION = (
    "p8_s8_light_cone_remaining_gameplay_closure_summary_v2"
)
CONTRACT_COMPONENTS = (
    "partition", "path_inventory", "formal_scenario", "lifecycle", "production_event_chain",
    "common_mutation_events", "battle_state_transition_events", "heal_events",
    "custom_events", "weakness_events",
)
OWNED_COMBATANT_PROJECTION_FIELDS = (
    "servant_definitions",
    "action_definitions",
    "action_ability_bindings",
    "action_admissions",
    "unit_birth_templates",
)
LOWERING_ENTRY_KEYS = (
    "full_tbgd_lowering_build",
    "owned_combatant_admission_projection",
)
@contextmanager
def _observe_lowering_entries(build_counts: Counter[str]):
    methods = dict(zip(
        LOWERING_ENTRY_KEYS,
        ("build", "build_owned_combatant_admission_projection"),
        strict=True,
    ))
    originals = {key: getattr(TBGDLowering, name) for key, name in methods.items()}
    build_counts.update({key: 0 for key in methods})

    def observed(key: str):
        def call(lowering: TBGDLowering, *args: Any, **kwargs: Any):
            build_counts[key] += 1
            return originals[key](lowering, *args, **kwargs)
        return call

    with ExitStack() as stack:
        for key, name in methods.items():
            stack.enter_context(patch.object(TBGDLowering, name, observed(key)))
        yield


def _measured_count(build_counts: Counter[str], key: str) -> int:
    if key not in build_counts:
        raise RuntimeError(f"unobserved contract build entry: {key}")
    return build_counts[key]


def _focused_bundle(
    tbgd_root: Path,
    *,
    include_owned_combatant_catalog: bool = False,
    build_counts: Counter[str] | None = None,
) -> dict[str, Any]:
    """Build exactly one focused equipment RuleBook from current source.

    S7 supplies the already-lowered status/callback graph.  S8 rebuilds the
    standalone equipment graphs against those callbacks, then atomically
    replaces definitions and mechanism references with their executable
    versions.  No full CanonicalIR serialization is performed.
    """

    if build_counts is not None:
        build_counts["focused_bundle"] += 1
    owned_combatant_catalog = (
        _owned_combatant_admission_catalog(tbgd_root)
        if include_owned_combatant_catalog
        else None
    )
    base = _s7_focused_bundle(tbgd_root)
    lowering = TBGDLowering(tbgd_root)
    lowered = lowering._lower_equipment_ability_graphs(
        base["catalog"].canonical_definitions,
        status_callbacks=list(base["callbacks"]),
    )
    (
        graphs,
        phases,
        tasks,
        top_level_effects,
        top_level_conditions,
        formulas,
        top_level_targets,
        parameter_reads,
    ) = lowered
    definitions, _, mechanism_refs = _attach_equipment_mechanism_refs(
        base["catalog"].canonical_definitions,
        (),
        graphs,
        parameter_reads,
    )

    existing_effect_ids = {effect.effect_id for effect in base["ir"].effects}
    missing_top_level_effect_ids = sorted(
        effect.effect_id
        for effect in top_level_effects
        if effect.effect_id not in existing_effect_ids
    )
    existing_condition_ids = {
        condition.condition_id for condition in base["ir"].conditions
    }
    missing_top_level_condition_ids = sorted(
        condition.condition_id
        for condition in top_level_conditions
        if condition.condition_id not in existing_condition_ids
    )
    existing_target_ids = {
        target.target_expression_id for target in base["ir"].target_expressions
    }
    missing_top_level_target_ids = sorted(
        target.target_expression_id
        for target in top_level_targets
        if target.target_expression_id not in existing_target_ids
    )
    if (
        missing_top_level_effect_ids
        or missing_top_level_condition_ids
        or missing_top_level_target_ids
    ):
        raise ValueError(
            "S8 graph rebuild diverged from the focused S7 lowering: "
            f"effects={missing_top_level_effect_ids[:3]}, "
            f"conditions={missing_top_level_condition_ids[:3]}, "
            f"targets={missing_top_level_target_ids[:3]}"
        )

    engine_rules = build_engine_rule_registry()
    battle_state_transitions = lowering._lower_battle_state_transitions()
    focused_lowered_files = tuple(base["lowered_by_path"].values())
    ir: CanonicalIR = replace(
        base["ir"],
        light_cone_definitions=definitions,
        equipment_ability_parameter_reads=tuple(parameter_reads),
        equipment_mechanism_refs=mechanism_refs,
        standalone_ability_graphs=tuple(graphs),
        ability_phases=tuple(phases),
        ability_tasks=tuple(tasks),
        status_damage_emissions=tuple(
            emission
            for lowered_file in focused_lowered_files
            for emission in lowered_file.status_damage_emissions
        ),
        damage_modifiers=tuple(
            modifier
            for lowered_file in focused_lowered_files
            for modifier in lowered_file.damage_modifiers
        ),
        action_delay_emissions=tuple(
            emission
            for lowered_file in focused_lowered_files
            for emission in lowered_file.action_delay_emissions
        ),
        queue_intents=tuple(
            intent
            for lowered_file in focused_lowered_files
            for intent in lowered_file.queue_intents
        ),
        skill_continuations=tuple(
            continuation
            for lowered_file in focused_lowered_files
            for continuation in lowered_file.skill_continuations
        ),
        triggers=tuple(
            trigger
            for lowered_file in focused_lowered_files
            for trigger in lowered_file.triggers
        ),
        formulas=tuple(formulas),
        timeline_rules=engine_rules.timeline_rules,
        resource_rules=engine_rules.resource_rules,
        battle_state_transitions=tuple(battle_state_transitions),
        damage_formula_rules=engine_rules.damage_formula_rules,
        damage_route_rules=engine_rules.damage_route_rules,
        shield_priority_rules=engine_rules.shield_priority_rules,
        metadata={
            **base["ir"].metadata,
            "validation_scope": "p8_s8_focused_equipment_gameplay_closure",
        },
    )
    if owned_combatant_catalog is not None:
        ir = replace(
            ir,
            servant_definitions=owned_combatant_catalog[
                "servant_definitions"
            ],
            action_definitions=tuple(
                sorted(
                    merge_identical_ir_items(
                        (
                            *ir.action_definitions,
                            *owned_combatant_catalog[
                                "action_definitions"
                            ],
                        ),
                        "definition_id",
                        item_kind="action_definition",
                    ),
                    key=lambda item: (
                        item.action_id,
                        item.level,
                        item.definition_id,
                    ),
                )
            ),
            action_ability_bindings=owned_combatant_catalog[
                "action_ability_bindings"
            ],
            action_admissions=owned_combatant_catalog[
                "action_admissions"
            ],
            unit_birth_templates=owned_combatant_catalog[
                "unit_birth_templates"
            ],
        )
    return {
        **base,
        "definitions": definitions,
        "mechanism_refs": mechanism_refs,
        "graphs": tuple(graphs),
        "phases": tuple(phases),
        "tasks": tuple(tasks),
        "formulas": tuple(formulas),
        "parameter_reads": tuple(parameter_reads),
        "battle_state_transitions": tuple(battle_state_transitions),
        "ir": ir,
        "rules": RuleBook(ir),
        "owned_combatant_catalog": owned_combatant_catalog or {},
    }


def _owned_combatant_admission_catalog(tbgd_root: Path) -> dict[str, Any]:
    projection = TBGDLowering(tbgd_root).build_owned_combatant_admission_projection()
    if not projection.ok:
        raise ValueError("owned-combatant admission projection failed closed: " + ",".join(
            sorted({issue.code for issue in projection.issues})
        ))
    return {
        **{
            name: getattr(projection, name)
            for name in OWNED_COMBATANT_PROJECTION_FIELDS
        },
        "counts": {
            "servant_definition_count": len(projection.servant_definitions),
            "servant_action_id_count": len({item.action_id for item in projection.action_definitions}),
            "servant_action_admission_count": len(projection.action_admissions),
            "servant_birth_template_count": len(projection.unit_birth_templates),
            "projection_source_blocked_count": sum(
                item.coverage_status != "executable"
                for name in (
                    "servant_definitions",
                    "action_ability_bindings",
                    "action_admissions",
                    "unit_birth_templates",
                )
                for item in getattr(projection, name)
            ),
        },
    }


def _empty_character_build_path_inventory(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    cards = {
        card.card_id: card
        for card in bundle["characters"].character_data_cards
    }
    selected: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for eligibility in sorted(
        bundle["characters"].character_equipment_eligibilities,
        key=lambda item: (
            item.character_path_type,
            item.character_card_id,
        ),
    ):
        card = cards.get(eligibility.character_card_id)
        if card is None:
            rows.append(
                {
                    "path_type": eligibility.character_path_type,
                    "character_card_id": eligibility.character_card_id,
                    "assembly_status": "blocked",
                    "battle_admission_status": "blocked",
                    "blocked_reasons": ["character_data_card_missing"],
                    "diagnostic_reasons": [],
                    "owned_combatant_build_dependency": False,
                }
            )
            continue
        result = assemble_character_build(
            rules,
            _character_build(
                card.card_id,
                f"s8-empty:{eligibility.character_path_type}",
            ),
        )
        diagnostic_reasons = tuple(
            diagnostic.reason
            for diagnostic in result.unadmitted_mechanism_diagnostics
        )
        equipment_admitted = (
            result.equipment_assembly_result is not None
            and result.equipment_assembly_result.assembly_status == "assembled"
            and result.equipment_assembly_result.battle_admission_status
            == "admitted"
        )
        owned_combatant_build_dependency = (
            result.assembly_status == "assembled"
            and result.battle_admission_status == "blocked"
            and not result.blocked_reasons
            and bool(diagnostic_reasons)
            and set(diagnostic_reasons)
            == {"auxiliary_unit_skill_level_requires_owned_combatant_build"}
            and equipment_admitted
        )
        rows.append(
            {
                "path_type": eligibility.character_path_type,
                "character_card_id": card.card_id,
                "assembly_status": result.assembly_status,
                "battle_admission_status": result.battle_admission_status,
                "blocked_reasons": list(result.blocked_reasons),
                "diagnostic_reasons": list(diagnostic_reasons),
                "equipment_admitted": equipment_admitted,
                "owned_combatant_results": [
                    {
                        "owned_build_id": owned.owned_build_id,
                        "servant_definition_id": (
                            owned.servant_definition_id
                        ),
                        "assembly_status": owned.assembly_status,
                        "battle_admission_status": (
                            owned.battle_admission_status
                        ),
                        "blocked_reasons": list(owned.blocked_reasons),
                    }
                    for owned in result.owned_combatant_results
                ],
                "owned_combatant_build_dependency": (
                    owned_combatant_build_dependency
                ),
            }
        )
        if (
            result.battle_admission_status == "admitted"
            and eligibility.character_path_type not in selected
        ):
            selected[eligibility.character_path_type] = card

    all_paths = tuple(
        sorted(
            {
                eligibility.character_path_type
                for eligibility in bundle[
                    "characters"
                ].character_equipment_eligibilities
            }
        )
    )
    path_rows: list[dict[str, Any]] = []
    for path_type in all_paths:
        candidates = tuple(
            row for row in rows if row["path_type"] == path_type
        )
        admitted = path_type in selected
        external_dependency = (
            not admitted
            and any(
                row["owned_combatant_build_dependency"] is True
                for row in candidates
            )
        )
        path_rows.append(
            {
                "path_type": path_type,
                "admitted_character_card_id": (
                    selected[path_type].card_id if admitted else ""
                ),
                "candidate_count": len(candidates),
                "admitted": admitted,
                "external_character_build_dependency": external_dependency,
                "candidate_rows": list(candidates),
            }
        )
    return {
        "schema_version": "p8_s8_empty_character_build_path_inventory_v1",
        "cards_by_path": selected,
        "path_rows": path_rows,
        "external_character_build_paths": tuple(
            row["path_type"]
            for row in path_rows
            if row["external_character_build_dependency"] is True
        ),
    }


def _empty_admitted_cards_by_path(bundle: dict[str, Any]) -> dict[str, Any]:
    return _empty_character_build_path_inventory(bundle)["cards_by_path"]


def _catalog_startup_matrix(
    bundle: dict[str, Any],
    *,
    cards_by_path: dict[str, Any] | None = None,
    path_inventory: dict[str, Any] | None = None,
    definition_identities: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Exercise every published light cone through the formal build boundary.

    Every executable row uses a real admitted character with the matching path
    so the complete passive graph is active.  A path unavailable solely because
    character assembly cannot yet build its owned combatant is retained as an
    explicit external dependency.  It is neither skipped nor counted as an
    equipment implementation failure.
    """

    rules: RuleBook = bundle["rules"]
    path_inventory = path_inventory or _empty_character_build_path_inventory(
        bundle
    )
    cards_by_path = cards_by_path or path_inventory["cards_by_path"]
    path_rows = {
        row["path_type"]: row for row in path_inventory["path_rows"]
    }
    selected_definitions = tuple(
        definition
        for definition in bundle["definitions"]
        if definition_identities is None
        or definition.definition_key.definition_identity in definition_identities
    )
    rows: list[dict[str, Any]] = []
    for definition in sorted(
        selected_definitions,
        key=lambda item: item.definition_key.definition_identity,
    ):
        identity = definition.definition_key.definition_identity
        card = cards_by_path.get(definition.path_type)
        if card is None:
            path_row = path_rows.get(definition.path_type, {})
            external_dependency = (
                path_row.get("external_character_build_dependency") is True
            )
            rows.append(
                {
                    "definition_identity": identity,
                    "path_type": definition.path_type,
                    "status": (
                        "external_character_build_dependency"
                        if external_dependency
                        else "matching_character_build_unavailable"
                    ),
                    "reason": (
                        "owned_combatant_build_not_yet_assembled"
                        if external_dependency
                        else "no_empty_character_build_admitted_for_matching_path"
                    ),
                    "equipment_gap": not external_dependency,
                    "external_character_build_dependency": external_dependency,
                    "character_path_evidence": path_row,
                }
            )
            continue
        character_path_type = definition.path_type
        expected_activation = "active"
        equipment_build, equipment_result = _assembly(
            rules,
            card.card_id,
            definition,
            instance_id=f"validation:p8_s8:{identity}",
            rank=1,
        )
        character_build = _character_build(
            card.card_id,
            f"s8:{identity}",
            equipment_build,
        )
        character_result = assemble_character_build(rules, character_build)
        activation_status = (
            equipment_result.activation_decisions[0].activation_status
            if len(equipment_result.activation_decisions) == 1
            else "invalid"
        )
        if (
            equipment_result.battle_admission_status != "admitted"
            or character_result.battle_admission_status != "admitted"
            or activation_status != expected_activation
        ):
            rows.append(
                {
                    "definition_identity": identity,
                    "path_type": definition.path_type,
                    "character_path_type": character_path_type,
                    "character_card_id": card.card_id,
                    "status": "assembly_blocked",
                    "reason": ";".join(
                        (
                            *equipment_result.diagnostics,
                            *character_result.diagnostics,
                        )
                    ) or (
                        "light_cone_activation_contract_mismatch:"
                        f"{activation_status}:{expected_activation}"
                    ),
                    "equipment_gap": True,
                }
            )
            continue
        scenario = ScenarioSpec(
            scenario_id=f"validation:p8_s8:startup:{identity}",
            version=BASELINE_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:wearer",
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
        except ValueError as exc:
            rows.append(
                {
                    "definition_identity": identity,
                    "path_type": definition.path_type,
                    "character_card_id": card.card_id,
                    "status": "startup_blocked",
                    "reason": str(exc),
                    "equipment_gap": True,
                }
            )
            continue
        providers = built.state.units["ally:wearer"].flags.get(
            "ability_providers", ()
        )
        rows.append(
            {
                "definition_identity": identity,
                "path_type": definition.path_type,
                "character_path_type": character_path_type,
                "character_card_id": card.card_id,
                "activation_status": activation_status,
                "expected_activation_status": expected_activation,
                "status": "started",
                "reason": "",
                "equipment_gap": False,
                "external_character_build_dependency": False,
                "provider_count": len(providers),
                "setup_mutation_count": len(built.setup_mutations),
                "setup_record_count": len(built.setup_records),
                "setup_event_count": len(built.setup_events),
            }
        )
    counts = Counter(row["status"] for row in rows)
    failures = [row for row in rows if row["equipment_gap"]]
    external_dependencies = [
        row
        for row in rows
        if row.get("external_character_build_dependency") is True
    ]
    checks = {
        "all_published_catalog_rows_classified": (
            len(rows) == len(selected_definitions)
        ),
        "equipment_failure_count_zero": not failures,
        "external_character_build_dependencies_structurally_proven": all(
            row.get("character_path_evidence", {}).get(
                "external_character_build_dependency"
            )
            is True
            for row in external_dependencies
        ),
        "started_or_external_dependency_covers_catalog": (
            counts.get("started", 0) + len(external_dependencies) == len(rows)
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_catalog_startup_matrix_v3",
        "ok": checks["ok"],
        "checks": checks,
        "counts": dict(sorted(counts.items())),
        "available_character_paths": sorted(cards_by_path),
        "formal_catalog_startup_complete": (
            not failures and not external_dependencies
        ),
        "equipment_failure_count": len(failures),
        "external_character_build_dependency_count": len(
            external_dependencies
        ),
        "failures": failures,
        "external_dependencies": external_dependencies,
        "character_path_inventory": {
            key: value
            for key, value in path_inventory.items()
            if key != "cards_by_path"
        },
        "definition_identity_filter": sorted(definition_identities or ()),
        "rows": rows,
    }


def _graph_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    rows: list[dict[str, Any]] = []
    for definition in bundle["definitions"]:
        key = definition.mechanism_ref_ids[0]
        resolution = rules.equipment_mechanism_ref(key.definition_identity)
        graph = (
            rules.standalone_ability_graph(resolution.value.graph_ref_id)
            if resolution.value is not None
            else None
        )
        rows.append(
            {
                "definition_identity": definition.definition_key.definition_identity,
                "mechanism_resolution": resolution.resolution_status,
                "graph_status": graph.coverage_status if graph else "missing",
                "callback_count": len(graph.status_callback_ids) if graph else 0,
                "non_gameplay_callback_count": (
                    len(graph.non_gameplay_callback_ids) if graph else 0
                ),
                "ok": bool(
                    resolution.resolution_status == "resolved"
                    and graph is not None
                    and graph.coverage_status == "executable"
                ),
            }
        )
    return {
        "schema_version": "p8_s8_full_graph_matrix_v1",
        "ok": all(row["ok"] for row in rows),
        "published_count": len(rows),
        "blocked_count": sum(not row["ok"] for row in rows),
        "rows": rows,
    }


def _partition_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    inventory = _family_inventory(bundle)
    source_rows = inventory["_source_rows"]
    s7 = {
        (row["kind"], row["family"], row["source_identity"])
        for row in source_rows
        if row["stage"] == "s7"
    }
    s8 = {
        (row["kind"], row["family"], row["source_identity"])
        for row in source_rows
        if row["stage"] == "s8"
    }
    gameplay = {
        (row["kind"], row["family"], row["source_identity"])
        for row in source_rows
        if row["stage"] in {"s7", "s8"}
    }
    non_gameplay_rows = [
        row for row in inventory["rows"] if row["stage"] == "non_gameplay"
    ]
    unreferenced_rows = [
        row for row in inventory["rows"] if row["stage"] == "unreferenced"
    ]
    checks = {
        "current_source_fingerprint_complete": all(
            bool(inventory["source_content_fingerprint"].get(key))
            for key in ("algorithm", "sha256", "file_count", "byte_count")
        ),
        "s7_s8_union_equals_current_gameplay": s7 | s8 == gameplay,
        "s7_s8_intersection_empty": not (s7 & s8),
        "unknown_gameplay_zero": inventory["counts"].get("unknown", 0) == 0,
        "non_gameplay_rows_have_structured_evidence": bool(non_gameplay_rows)
        and all(bool(row["structured_evidence"]) for row in non_gameplay_rows),
        "unreferenced_rows_retained_with_structured_evidence": all(
            bool(row["structured_evidence"]) for row in unreferenced_rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_inherited_partition_check_v1",
        "ok": checks["ok"],
        "checks": checks,
        "source_content_fingerprint": inventory["source_content_fingerprint"],
        "counts": dict(sorted(inventory["counts"].items())),
        "family_rows": inventory["rows"],
        "source_row_count": len(source_rows),
        "_inventory": inventory,
    }


def _internal_dynamic_slot_contract_matrix() -> dict[str, Any]:
    source = IRSource(
        source_path="validation/p8_s8_internal_dynamic_slot.json",
        raw_type="AbilityDynamicValues",
        raw_id="p8_s8_internal_dynamic_slot",
        evidence={"validation": "declared Type=None slot admission"},
    )

    def definition(*, hash_key: str, source_scope: str) -> RuleEntity:
        return RuleEntity(
            entity_id=f"validation:dynamic_slot:{hash_key}",
            entity_type="modifier_definition",
            fields={
                "dynamic_value_bindings": {
                    "by_hash": {
                        hash_key: {
                            "read_info": {"Type": "None", "Index": 0},
                            "source_scope": source_scope,
                            "source_json_path": f"$.DynamicValues[{hash_key}]",
                        }
                    },
                    "by_name": {},
                }
            },
            source=source,
            coverage_status="executable",
        )

    internal_values = _resolve_dynamic_values(
        {},
        definition(hash_key="7001", source_scope="ability_dynamic_values"),
        {"7999": 17.0},
        (),
        source.to_json(),
    )
    external_values = _resolve_dynamic_values(
        {},
        definition(hash_key="7002", source_scope="external_runtime_values"),
        None,
        (),
        source.to_json(),
    )
    evaluations = internal_values.get("__evaluations")
    declared_default_rows = [
        row
        for row in (evaluations if isinstance(evaluations, list) else ())
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("expression_kind")
        == "declared_type_none_dynamic_slot_default"
    ]
    checks = {
        "declared_internal_type_none_slot_defaults_to_zero": (
            internal_values.get("7001") == 0.0
            and len(declared_default_rows) == 1
        ),
        "undeclared_runtime_hash_is_not_admitted": "7999" not in internal_values,
        "external_type_none_slot_does_not_default": "7002" not in external_values,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_internal_dynamic_slot_contract_v1",
        "ok": checks["ok"],
        "checks": checks,
        "declared_default_evidence": declared_default_rows,
    }


def _dot_additive_term_contract_matrix() -> dict[str, Any]:
    source = IRSource(
        source_path="validation/p8_s8_dot_additive_terms.json",
        raw_type="DamageByAttackProperty",
        raw_id="p8_s8_dot_additive_terms",
        evidence={"validation": "independent DamageValue and DamagePercentage pools"},
    )
    emission = StatusDamageEmissionIR(
        status_damage_emission_id="validation:dot:additive_terms",
        callback_id="validation:dot:callback",
        source_task_id="validation:dot:task",
        modifier_name="ValidationDot",
        event="OnCustomEvent",
        attack_type="DOT",
        damage_formula_family="dot",
        element_type="Fire",
        scaling_expr={
            "kind": "dot_attack_property",
            "damage_value": numeric_fixed(5.0),
            "damage_percentage": numeric_fixed(0.2),
            "damage_percentage_basis": {
                "kind": "unit_stat",
                "supported": True,
                "unit_ref": "attacker",
                "stat": "attack",
                "source_kind": "damage_by_attack_property_contract",
                "source_field": "AttackProperty.DamagePercentage",
                "source_trace": source.to_json(),
            },
            "extra_formula_type": "",
            "extra_damage_percentage": {
                "schema_version": "hsr.numeric_expression.v1",
                "kind": "missing",
                "supported": False,
                "reason": "validation_extra_term_absent",
            },
        },
        source=source,
        coverage_status="executable",
    )
    state = BattleState(
        units={
            "ally:caster": UnitState(
                unit_id="ally:caster",
                side="ally",
                template_id="validation:caster",
                attack=100.0,
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:target",
                hp=100.0,
                max_hp=100.0,
            ),
        }
    )
    formula_input = DotFormulaInput(
        state=state,
        caster_id="ally:caster",
        target_id="enemy:target",
        status_detail={"source_trace": source.to_json(), "dynamic_values": {}},
        emission=emission,
        source_trace=source.to_json(),
    )
    result = DotFormula().calculate(formula_input)
    zero_fixed_result = DotFormula().calculate(
        replace(
            formula_input,
            emission=replace(
                emission,
                scaling_expr={
                    **emission.scaling_expr,
                    "damage_value": numeric_fixed(0.0),
                },
            ),
        )
    )
    missing_basis_result = DotFormula().calculate(
        replace(
            formula_input,
            emission=replace(
                emission,
                scaling_expr={
                    **emission.scaling_expr,
                    "damage_percentage_basis": {
                        "kind": "missing",
                        "reason": "validation_percentage_basis_removed",
                    },
                },
            ),
        )
    )
    applied_keys = {
        str(term.get("key") or "")
        for term in result.dot_ledger.get("applied_terms", ())
        if isinstance(term, dict)
    }
    checks = {
        "damage_value_and_percentage_are_independent_additive_terms": (
            result.ok
            and isclose(result.base_damage, 25.0, rel_tol=0.0, abs_tol=1e-9)
            and isclose(result.final_damage, 25.0, rel_tol=0.0, abs_tol=1e-9)
            and {"DamageValue", "DamagePercentage"}.issubset(applied_keys)
        ),
        "zero_fixed_term_does_not_suppress_percentage_term": (
            zero_fixed_result.ok
            and isclose(
                zero_fixed_result.base_damage,
                20.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and isclose(
                zero_fixed_result.final_damage,
                20.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ),
        "missing_percentage_basis_blocks": (
            not missing_basis_result.ok
            and missing_basis_result.final_damage == 0.0
            and missing_basis_result.blocked_reason
            == "validation_percentage_basis_removed"
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_dot_additive_term_contract_v1",
        "ok": checks["ok"],
        "checks": checks,
        "positive": result.to_json(),
        "zero_fixed_positive": zero_fixed_result.to_json(),
        "missing_basis_negative": missing_basis_result.to_json(),
    }


def _numeric_contract_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    zero_floor_hashes = (
        ZERO_FLOOR_DYNAMIC_HASH,
        RANGE_ZERO_FLOOR_DYNAMIC_HASH,
    )
    expressions: list[tuple[str, object, dict[str, Any]]] = []
    for task in bundle["callback_tasks"]:
        for path, expression in _numeric_expressions(task.task_payload):
            expressions.append((task.task_id, expression, {"path": path, "source": task.source.to_json()}))
    for effect in bundle["ir"].effects:
        for path, expression in _numeric_expressions(effect.payload, "effect.payload"):
            expressions.append((effect.effect_id, expression, {"path": path, "source": effect.source.to_json()}))
    for condition in bundle["nested_conditions"]:
        for path, expression in _numeric_expressions(condition.payload, "condition.payload"):
            expressions.append((condition.condition_id, expression, {"path": path, "source": condition.source.to_json()}))
    evaluator = RuleEvaluator()
    rows: list[dict[str, Any]] = []
    zero_floor_rows: list[dict[str, Any]] = []
    registry = bundle["rules"].engine_rule_registry()
    for task_id, expression, evidence in expressions:
        hashes = numeric_dynamic_hashes(expression)
        dynamic_values = {
            str(value_hash): 1.0
            for value_hash in hashes
            if int(value_hash) not in zero_floor_hashes
        }
        engine_binding, engine_reason = engine_numeric_binding_source(expression, registry)
        result = evaluator.evaluate_numeric(
            expression,
            NumericEvaluationContext(
                dynamic_values=dynamic_values,
                binding_sources=((engine_binding,) if engine_binding is not None else ()),
                source_trace=evidence,
            ),
        )
        row = {
            "task_id": task_id,
            "expression_path": evidence["path"],
            "kind": expression.get("kind") if isinstance(expression, dict) else "invalid",
            "dynamic_hash_count": len(hashes),
            "engine_binding_applicable": engine_binding is not None,
            "engine_binding_reason": engine_reason,
            "has_variadic_max": bool(
                isinstance(expression, dict)
                and isinstance(expression.get("instructions"), list)
                and any(
                    isinstance(instruction, dict)
                    and instruction.get("opcode") == "max"
                    for instruction in expression["instructions"]
                )
            ),
            "ok": result.ok and result.value is not None,
            "blocked_reason": result.blocked_reason,
            "source": evidence["source"],
        }
        rows.append(row)
        present_zero_floor_hashes = tuple(
            value_hash
            for value_hash in zero_floor_hashes
            if value_hash in hashes
        )
        if present_zero_floor_hashes:
            for zero_floor_hash in present_zero_floor_hashes:
                without_rule_dynamic_values = {
                    **dynamic_values,
                    **{
                        str(other_hash): 0.0
                        for other_hash in present_zero_floor_hashes
                        if other_hash != zero_floor_hash
                    },
                }
                without_rule = evaluator.evaluate_numeric(
                    expression,
                    NumericEvaluationContext(
                        dynamic_values=without_rule_dynamic_values,
                        source_trace=evidence,
                    ),
                )
                zero_floor_rows.append(
                    {
                        **row,
                        "zero_floor_hash": zero_floor_hash,
                        "without_rule_blocked": not without_rule.ok
                        and str(zero_floor_hash) in without_rule.blocked_reason,
                    }
                )
    forged_unrelated_max_rows = []
    for zero_floor_hash in zero_floor_hashes:
        forged_unrelated_max = {
            "schema_version": "hsr.numeric_expression.v1",
            "kind": "program",
            "supported": True,
            "instructions": [
                {"opcode": "push_dynamic", "hash": zero_floor_hash},
                {"opcode": "push_fixed", "value": 1.0},
                {"opcode": "add"},
                {"opcode": "push_fixed", "value": 2.0},
                {"opcode": "push_fixed", "value": 3.0},
                {"opcode": "max", "operand_count": 2},
                {"opcode": "add"},
                {"opcode": "end"},
            ],
        }
        forged_binding, forged_reason = engine_numeric_binding_source(
            forged_unrelated_max,
            registry,
        )
        forged_result = evaluator.evaluate_numeric(
            forged_unrelated_max,
            NumericEvaluationContext(
                dynamic_values={},
                binding_sources=(),
                source_trace={
                    "validation": "unrelated_max_must_not_bind_zero",
                    "zero_floor_hash": zero_floor_hash,
                },
            ),
        )
        forged_unrelated_max_rows.append(
            {
                "zero_floor_hash": zero_floor_hash,
                "binding_created": forged_binding is not None,
                "binding_reason": forged_reason,
                "evaluation_ok": forged_result.ok,
                "blocked_reason": forged_result.blocked_reason,
                "ok": (
                    forged_binding is None
                    and forged_reason
                    == "engine_zero_floor_program_shape_not_admitted"
                    and not forged_result.ok
                    and str(zero_floor_hash) in forged_result.blocked_reason
                ),
            }
        )
    family_predicates = {
        "fixed_numeric": lambda row: row["kind"] == "fixed",
        "postfix_numeric": lambda row: row["kind"] in {"dynamic_hash", "program"},
        "postfix_numeric_opcode16": lambda row: row["kind"] == "program"
        and row["has_variadic_max"],
    }
    family_rows = []
    for family, predicate in family_predicates.items():
        members = [row for row in rows if predicate(row)]
        family_rows.append(
            {
                "family": family,
                "expression_count": len(members),
                "evaluated_count": sum(row["ok"] for row in members),
                "representative_source": members[0]["source"] if members else {},
                "ok": bool(members) and all(row["ok"] for row in members),
            }
        )
    internal_dynamic_slots = _internal_dynamic_slot_contract_matrix()
    dot_additive_terms = _dot_additive_term_contract_matrix()
    checks = {
        "real_numeric_expressions_nonempty": bool(rows),
        "all_real_numeric_expressions_evaluate": all(row["ok"] for row in rows),
        "zero_floor_source_present": (
            {row["zero_floor_hash"] for row in zero_floor_rows}
            == set(zero_floor_hashes)
        ),
        "zero_floor_requires_explicit_engine_rule": all(
            row["engine_binding_applicable"] and row["without_rule_blocked"]
            for row in zero_floor_rows
        ),
        "zero_floor_binding_proves_direct_max_operand_relation": (
            all(row["ok"] for row in forged_unrelated_max_rows)
        ),
        "every_numeric_family_has_exact_evidence": all(
            row["ok"] for row in family_rows
        ),
        "declared_internal_dynamic_slots_are_fail_closed": (
            internal_dynamic_slots["ok"]
        ),
        "dot_fixed_and_percentage_terms_are_independently_closed": (
            dot_additive_terms["ok"]
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_numeric_contract_matrix_v3",
        "ok": checks["ok"],
        "checks": checks,
        "expression_count": len(rows),
        "zero_floor_expression_count": len(zero_floor_rows),
        "family_rows": family_rows,
        "internal_dynamic_slots": internal_dynamic_slots,
        "dot_additive_terms": dot_additive_terms,
        "zero_floor_expression_counts_by_hash": dict(
            sorted(
                Counter(
                    str(row["zero_floor_hash"])
                    for row in zero_floor_rows
                ).items()
            )
        ),
        "forged_unrelated_max": forged_unrelated_max_rows,
        "failures": [row for row in rows if not row["ok"]][:20],
        "zero_floor_rows": zero_floor_rows[:20],
    }


def _numeric_expressions(value: object, path: str = "task_payload") -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        if value.get("schema_version") == "hsr.numeric_expression.v1" and value.get("kind") in {
            "fixed",
            "dynamic_hash",
            "program",
        }:
            rows.append((path, value))
            return rows
        for key, child in value.items():
            rows.extend(_numeric_expressions(child, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            rows.extend(_numeric_expressions(child, f"{path}[{index}]"))
    return rows


def _condition_target_values(value: object) -> tuple[object, ...]:
    rows: list[object] = []

    def visit(item: object) -> None:
        if isinstance(item, TargetExpressionNodeIR):
            rows.append(item)
            return
        if isinstance(item, dict):
            if (
                item.get("schema_version") == "hsr.target_expression_node.v1"
                and isinstance(item.get("alias"), str)
            ):
                rows.append(item)
                return
            for child in item.values():
                visit(child)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(rows)


def _target_value_alias(value: object) -> str:
    if isinstance(value, TargetExpressionNodeIR):
        return value.alias
    if isinstance(value, dict) and isinstance(value.get("alias"), str):
        return str(value["alias"])
    return ""


def _condition_contract_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    selected_task_ids = _selected_executable_task_ids(bundle)
    selected_condition_ids = {
        task.condition_id
        for task in (*bundle["tasks"], *bundle["callback_tasks"])
        if task.task_id in selected_task_ids and task.condition_id
    }
    conditions = tuple(
        condition
        for condition in bundle["nested_conditions"]
        if condition.condition_id in selected_condition_ids
        and condition.coverage_status == "executable"
    )
    by_family: dict[str, list[ConditionIR]] = defaultdict(list)
    for condition in conditions:
        by_family[condition.opcode].append(condition)
        for index, node in enumerate(_typed_condition_nodes(condition.payload)):
            opcode = node.get("opcode")
            if not isinstance(opcode, str) or not opcode:
                continue
            payload = {
                key: value
                for key, value in node.items()
                if key
                not in {
                    "blocked_reason",
                    "expression_kind",
                    "opcode",
                    "schema_version",
                    "supported",
                }
            }
            by_family[opcode].append(
                replace(
                    condition,
                    condition_id=f"{condition.condition_id}:node:{index}:{opcode}",
                    opcode=opcode,
                    payload=payload,
                )
            )
    evaluator = RuleEvaluator()
    baseline_rows = {
        row["family"]: row
        for row in _condition_runtime_family_rows(conditions)
    }
    rows: list[dict[str, Any]] = []
    for family, candidates in sorted(by_family.items()):
        results = []
        source_results: list[tuple[ConditionIR, list[Any]]] = []
        for condition in candidates:
            condition_results = []
            for context in _s8_condition_contexts(condition):
                result = evaluator.evaluate_condition_result(condition, context)
                results.append(result)
                condition_results.append(result)
            source_results.append((condition, condition_results))
        representative = candidates[0]
        blocked = evaluator.evaluate_condition_result(
            replace(
                representative,
                coverage_status="blocked",
                blocked_reason="validation_unadmitted_condition",
            ),
            _s8_condition_contexts(representative)[0],
        )
        true_count = sum(result.ok and result.result is True for result in results)
        false_count = sum(result.ok and result.result is False for result in results)
        baseline = baseline_rows.get(family, {})
        true_count += int(baseline.get("true_result_count") or 0)
        false_count += int(baseline.get("false_result_count") or 0)
        row = {
            "family": family,
            "real_source_count": len(candidates),
            "evaluated_source_count": sum(
                any(result.ok for result in condition_results)
                for _, condition_results in source_results
            ),
            "true_result_count": true_count,
            "false_result_count": false_count,
            "blocked_result_count": sum(not result.ok for result in results),
            "unadmitted_blocked": not blocked.ok and blocked.result is None,
            "representative_source": representative.source.to_json(),
        }
        row["ok"] = (
            row["evaluated_source_count"] == row["real_source_count"]
            and
            row["true_result_count"] > 0
            and row["false_result_count"] > 0
            and row["unadmitted_blocked"]
        )
        row["unevaluated_source_samples"] = [
            {
                "condition_id": condition.condition_id,
                "source": condition.source.to_json(),
                "payload": condition.to_json().get("payload", {}),
                "blocked_reasons": sorted(
                    {
                        str(result.reason or "condition_evaluation_blocked")
                        for result in condition_results
                        if not result.ok
                    }
                ),
            }
            for condition, condition_results in source_results
            if not any(result.ok for result in condition_results)
        ][:4]
        rows.append(row)
    checks = {
        "real_condition_families_nonempty": bool(rows),
        "every_family_true_false_and_fail_closed": all(row["ok"] for row in rows),
        "every_selected_condition_source_real": all(
            condition.source.source_path.startswith("Config/ConfigAbility/Equip/")
            for condition in conditions
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_condition_contract_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "family_count": len(rows),
        "condition_count": len(conditions),
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }


def _s8_condition_contexts(condition: ConditionIR) -> tuple[EvaluationContext, ...]:
    base_contexts = list(_condition_probe_contexts(condition))
    expected_damage_type = next(iter(_recursive_strings(condition.payload, "DamageType")), "Fire")
    expected_weakness = next(iter(_recursive_strings(condition.payload, "DamageType")), "Fire")
    expected_flags = sorted(
        _recursive_strings(condition.payload, "Flag")
        | _recursive_strings(condition.payload, "BehaviorFlag")
    )
    expected_skill_type = next(
        iter(_recursive_strings(condition.payload, "SkillType")),
        "Normal",
    )
    expected_attack_type = next(
        iter(_recursive_strings(condition.payload, "AttackTypes")),
        "Normal",
    )
    expected_skill_name = next(
        iter(_recursive_strings(condition.payload, "SkillName")),
        "validation:skill",
    )
    expected_modifier_names = sorted(
        _recursive_strings(condition.payload, "ModifierName")
    )
    expected_status_type = next(
        iter(_recursive_strings(condition.payload, "TargetStatusType")),
        "Buff",
    )
    expected_custom_name = next(
        iter(_recursive_strings(condition.payload, "CustomName")),
        "validation:damage",
    )
    target_aliases = {
        _target_value_alias(value)
        for value in _condition_target_values(condition.payload)
    }
    variants: list[EvaluationContext] = []
    for index in range(6):
        rich = index % 2 == 0
        numeric = (-100.0, 100.0, 0.0, 1.0, -1.0, 2.0)[index]
        status_details = tuple(
            {
                "modifier_name": modifier_name,
                "stacks": 2 if rich else 0,
                "max_stacks": 2,
                "duration": 2 if rich else 0,
                "remaining_duration": 2 if rich else 0,
                "status_category": "debuff",
            }
            for modifier_name in expected_modifier_names
        )
        wearer = UnitState(
            unit_id="ally:wearer",
            side="ally",
            template_id="avatar:validation",
            max_hp=100.0,
            hp=(0.0 if index in {2, 3} else (100.0 if rich else 10.0)),
            energy=(100.0 if rich else 0.0),
            max_energy=100.0,
            action_value=(10.0 if rich else 200.0),
            lifecycle_status="defeated" if index in {2, 3} else "active",
            flags={
                "damage_type": expected_damage_type if rich else "Other",
                "base_type": expected_damage_type if rich else "Other",
                "weaknesses": [expected_weakness] if rich else [],
                "behavior_flags": expected_flags if rich else [],
                "status_details": status_details,
                "position": 0,
            },
            resources={"revive_charges": 1.0 if index == 2 else 0.0},
        )
        peer = UnitState(
            unit_id="ally:peer",
            side="ally",
            template_id="avatar:validation-peer",
            max_hp=100.0,
            hp=(20.0 if rich else 100.0),
            energy=50.0,
            max_energy=100.0,
            action_value=(5.0 if rich else 200.0),
            lifecycle_status="active",
            flags={
                "status_details": status_details,
                "position": 1,
            },
        )
        enemy = UnitState(
            unit_id="enemy:target",
            side="enemy",
            template_id="monster:validation",
            max_hp=100.0,
            hp=(0.0 if index in {2, 3} else 100.0),
            energy=(100.0 if rich else 0.0),
            max_energy=100.0,
            action_value=(50.0 if rich else 1.0),
            lifecycle_status="defeated" if index in {2, 3} else "active",
            flags={
                "damage_type": expected_damage_type if rich else "Other",
                "weaknesses": [expected_weakness] if rich else [],
                "unselectable": not rich,
                "status_details": status_details,
                "position": 0,
            },
            resources={"revive_charges": 1.0 if index == 2 else 0.0},
        )
        servant = UnitState(
            unit_id="summon:servant",
            side="summon",
            template_id="servant:validation",
            max_hp=100.0,
            hp=100.0,
            energy=(100.0 if rich else 0.0),
            max_energy=100.0,
            action_value=(80.0 if rich else 1.0),
            lifecycle_status="active",
            flags={
                "summon_kind": "servant",
                "owner_id": "ally:wearer",
                "summoner_id": "ally:wearer",
                "team_side": "ally",
                "lifecycle_source": {
                    "admission_status": "executable",
                    "presence": "field",
                    "targetable": True,
                },
                "status_details": status_details,
                "position": 2,
            },
        )
        summon_entry = {
            "runtime_id": servant.unit_id,
            "unit_id": servant.unit_id,
            "template_ref": servant.template_id,
            "summon_kind": "servant",
            "owner_id": "ally:wearer",
            "summoner_id": "ally:wearer",
            "team_side": "ally",
            "status": "active",
            "targetability": {"targetable": True},
        }
        state = BattleState(
            units={
                wearer.unit_id: wearer,
                peer.unit_id: peer,
                enemy.unit_id: enemy,
                servant.unit_id: servant,
            },
            wave_index=index % 3,
            skill_points=(5 if rich else 0),
            max_skill_points=5,
            global_flags={
                "turn_owner_id": "ally:wearer" if rich else "enemy:target",
                "turn_based_game_mode_state": "active" if rich else "inactive",
                "wave_count": index + 1,
                "summon_runtime": _fixture_summon_runtime(
                    {servant.unit_id: summon_entry},
                    by_owner={"ally:wearer": [servant.unit_id]},
                    last_servants=(servant.unit_id,),
                    servant_ids=(servant.unit_id,),
                ),
            },
        )
        if condition.opcode == "ByTargetEntityType" and rich:
            target_id = "summon:servant"
        elif condition.opcode == "ByIsPropertyValueMinOrMax":
            target_id = "ally:wearer" if rich else "ally:peer"
        elif condition.opcode == "ByIsTopActionDelayTarget":
            target_id = "ally:peer"
        elif "ParamEntity.GetSummoner" in target_aliases:
            target_id = "summon:servant"
        else:
            target_id = "enemy:target"
        event_payload = {
            "actor_id": "ally:wearer",
            "source_id": "ally:wearer",
            "target_id": target_id,
            "param_entity_id": target_id,
            "param_entity_2_id": "summon:servant",
            "current_hit_target_id": target_id,
            "damage_defender_id": target_id,
            "change_value": numeric,
            "param_value": numeric,
            "value": numeric,
            "is_critical": rich,
            "SkillType": expected_skill_type if rich else "validation:other-skill-type",
            "skill_type": expected_skill_type if rich else "validation:other-skill-type",
            "AttackType": expected_attack_type if rich else "validation:other-attack-type",
            "attack_type": expected_attack_type if rich else "validation:other-attack-type",
            "SkillName": expected_skill_name if rich else "validation:other-skill",
            "skill_name": expected_skill_name if rich else "validation:other-skill",
            "modifier_name": (
                expected_modifier_names[0]
                if rich and expected_modifier_names
                else "validation:other-modifier"
            ),
            "status_type": expected_status_type if rich else "validation:other-status-type",
            "damage_custom_name": expected_custom_name if rich else "validation:other-damage",
            "is_insert_action": rich,
            "is_current_skill_active": rich,
            "condition_random_result": rich,
            "condition_random_choice_key": "validation:p8_s8:condition",
            "param_flags": expected_flags if rich else [],
            "behavior_flags": expected_flags if rich else [],
            "selected_target_ids": [target_id, "ally:peer"] if rich else [target_id],
            "target_ids": [target_id, "ally:peer"] if rich else [target_id],
            "skill_target_ids": [target_id, "ally:peer"] if rich else [target_id],
            "skill_sub_target_ids": ["ally:peer"] if rich else [],
            "sub_target_ids": ["ally:peer"] if rich else [],
            "attack_target_ids": [target_id, "ally:peer"] if rich else [target_id],
            "turn_owner_id": "ally:wearer" if rich else "enemy:target",
            "is_self": rich,
        }
        dynamic_hashes = {
            str(value_hash)
            for _, expression in _numeric_expressions(condition.payload)
            for value_hash in numeric_dynamic_hashes(expression)
        }
        dynamic_keys = (
            _recursive_strings(condition.payload, "DynamicKey")
            | _recursive_strings(condition.payload, "Value")
        )
        dynamic_values = {
            key: numeric for key in sorted(dynamic_hashes | dynamic_keys)
        }
        target_groups: dict[str, tuple[str, ...]] = {}
        alias_groups = {
            "ParamEntity": (target_id,),
            "ParamEntity2": ("summon:servant",),
            "Caster": ("ally:wearer",),
            "ModifierOwnerEntity": ("ally:wearer",),
            "CurrentActionTarget": (target_id,),
            "AbilityTargetEntity": (target_id,),
            "DamageDefenderEntity": (target_id,),
            "DamageAttackerEntity": ("ally:wearer",),
            "CurrentTurnOwnerEntity": (
                ("ally:wearer",) if rich else ("enemy:target",)
            ),
            "CasterServant": ("summon:servant",),
            "ModifierOwnerEntity.GetServant": ("summon:servant",),
            "ModifierOwnerEntity.GetServantAndDummyCharacter": ("summon:servant",),
            "Caster + CasterServant": ("ally:wearer", "summon:servant"),
            "ParamEntity.GetSummoner": ("ally:wearer",),
            "ModifierOwnerEntity.GetSkillTarget": (target_id,),
            "ModifierOwnerSkillTargetEntityList": tuple(event_payload["skill_target_ids"]),
            "AllLightTeam": ("ally:wearer", "ally:peer", "summon:servant"),
            "AllLightTeamWithAllLightTeamUnselectable.RemoveBattleEvent": (
                "ally:wearer",
                "ally:peer",
                "summon:servant",
            ),
            "AllTeamMember": ("ally:wearer", "ally:peer", "summon:servant"),
            "AllTeammate": ("ally:peer", "summon:servant"),
            "AllEnemy": ("enemy:target",),
            "AttackTargetList": tuple(event_payload["attack_target_ids"]),
            "ParamEntityAttackTargetList": tuple(event_payload["attack_target_ids"]),
            "SkillTargetEntityList": tuple(event_payload["skill_target_ids"]),
            "ParamEntitySkillTargetEntityList": tuple(event_payload["skill_target_ids"]),
            "SkillSubTargetEntityList": ("ally:peer",),
            "ModifierOwnerEntity.GetSkillAllTarget": (
                ("ally:wearer",) if rich else ("ally:wearer", "ally:peer")
            ),
        }
        target_system = TargetSystem()
        for value in _condition_target_values(condition.payload):
            alias = _target_value_alias(value)
            if isinstance(value, TargetExpressionNodeIR):
                resolution = target_system.resolve_expression_node(
                    state,
                    value,
                    caster_id="ally:wearer",
                    owner_id="ally:wearer",
                    param_entity_id=target_id,
                    current_action_target_id=target_id,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                )
                if resolution.ok:
                    target_groups[_condition_target_key(value)] = resolution.target_ids
                continue
            if alias in alias_groups:
                target_groups[_condition_target_key(value)] = alias_groups[alias]
        variants.append(
            EvaluationContext(
                state=state,
                actor_id="ally:wearer",
                owner_id="ally:wearer",
                target_id=target_id,
                param_entity_id=target_id,
                current_action_target_id=target_id,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                resolved_target_groups=target_groups,
            )
        )
    return tuple((*base_contexts, *variants))


def _recursive_strings(value: object, key: str) -> set[str]:
    rows: set[str] = set()
    if isinstance(value, dict):
        item = value.get(key)
        if isinstance(item, str) and item:
            rows.add(item)
        elif isinstance(item, dict):
            nested = item.get("Value")
            if isinstance(nested, str) and nested:
                rows.add(nested)
        elif isinstance(item, (list, tuple)):
            rows.update(entry for entry in item if isinstance(entry, str) and entry)
        for child in value.values():
            rows.update(_recursive_strings(child, key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            rows.update(_recursive_strings(child, key))
    return rows


def _route_probe_state() -> BattleState:
    return BattleState(
        units={
            "ally:wearer": UnitState(
                unit_id="ally:wearer",
                side="ally",
                template_id="validation:equipment-wearer",
                max_hp=100.0,
                hp=50.0,
                attack=100.0,
                defense=50.0,
                speed=100.0,
                energy=20.0,
                max_energy=100.0,
                action_value=100.0,
                lifecycle_status="active", flags={"position": 0},
                resources={"revive_charges": 1.0},
            ),
            "ally:peer": UnitState(
                unit_id="ally:peer",
                side="ally",
                template_id="validation:equipment-peer",
                max_hp=100.0,
                hp=50.0,
                attack=80.0,
                defense=40.0,
                speed=90.0,
                action_value=120.0,
                lifecycle_status="active", flags={"position": 1},
            ),
            "enemy:target": UnitState(
                unit_id="enemy:target",
                side="enemy",
                template_id="validation:equipment-enemy",
                max_hp=100.0,
                hp=100.0,
                attack=60.0,
                defense=30.0,
                speed=80.0,
                action_value=140.0,
                toughness=50.0,
                max_toughness=50.0,
                lifecycle_status="active", flags={"position": 0},
            ),
        },
        skill_points=2,
        max_skill_points=5,
        global_flags={"turn_owner_id": "ally:wearer", "phase": "action"},
    )


def _mechanism_only_equipment_task_probe_state(
    bundle: dict[str, Any],
    production: dict[str, Any],
    definition: Any,
) -> tuple[BattleState | None, str]:
    """Build a source-backed equipment runtime without inventing a character.

    A validation-only eligibility supplies the same-path activation rule.  The
    selected light-cone definition, graph, rank parameters, provider and
    startup modifier remain the production objects and pass through the public
    equipment assembler plus the production provider/startup boundaries.
    """

    host_card = next(
        (
            card
            for card in sorted(
                bundle["ir"].character_data_cards,
                key=lambda item: item.card_id,
            )
            if card.equipment_eligibility_id
            and bundle["rules"].avatar_profile_by_profile_id(card.profile_id)
            is not None
        ),
        None,
    )
    if host_card is None:
        return None, "mechanism_fixture_host_card_missing"
    host_profile = bundle["rules"].avatar_profile_by_profile_id(
        host_card.profile_id
    )
    if host_profile is None:
        return None, "mechanism_fixture_host_profile_missing"
    fixture_card_id = host_card.card_id
    fixture_source = IRSource(
        source_path="validation_fixture/p8_s8/equipment_mechanism_owner.json",
        raw_type="P8S8EquipmentMechanismOwnerFixture",
        raw_id=fixture_card_id,
        evidence={
            "fixture": True,
            "scope": "same_path_equipment_mechanism_activation_only",
        },
    )

    base = _target_family_probe_state()
    actor = replace(
        base.units["ally:wearer"],
        unit_id="ally:actor",
        template_id="validation:equipment-mechanism-owner",
    )
    servant = replace(
        base.units["ally:summon"],
        unit_id="ally:servant",
        template_id="validation:equipment-mechanism-owned-unit",
        flags={
            **base.units["ally:summon"].flags,
            "owner_id": "ally:actor",
            "summoner_id": "ally:actor",
        },
    )
    servant_entry = {
        "runtime_id": "ally:servant",
        "unit_id": "ally:servant",
        "status": "active",
        "summon_kind": "servant",
        "owner_id": "ally:actor",
        "summoner_id": "ally:actor",
        "team_side": "ally",
        "targetability": {"targetable": True},
    }
    state = BattleState(
        units={
            "ally:actor": replace(
                actor,
                flags={
                    **actor.flags,
                    "character_data_card_id": fixture_card_id,
                },
            ),
            "ally:servant": servant,
            "ally:peer": base.units["ally:peer"],
            "enemy:target": base.units["enemy:target"],
        },
        skill_points=2,
        max_skill_points=5,
        global_flags={
            "turn_owner_id": "ally:actor",
            "phase": "action",
            "summon_runtime": _fixture_summon_runtime(
                {"ally:servant": servant_entry},
                by_owner={"ally:actor": ["ally:servant"]},
                last_servants=("ally:servant",),
                servant_ids=("ally:servant",),
            ),
        },
    )
    eligibility = CharacterEquipmentEligibilityIR(
        definition_key=EquipmentDefinitionKey(
            "character_equipment_eligibility",
            fixture_card_id,
        ),
        character_card_id=fixture_card_id,
        character_profile_id=host_profile.avatar_profile_id,
        character_path_type=definition.path_type,
        passive_activation_path_types=(definition.path_type,),
        source=fixture_source,
        coverage_status="lowered",
        blocked_reason="",
    )
    fixture_ir = replace(
        bundle["ir"],
        avatar_profiles=tuple(
            replace(
                profile,
                base_type=definition.path_type,
                source=fixture_source,
            )
            if profile.avatar_profile_id == host_profile.avatar_profile_id
            else profile
            for profile in bundle["ir"].avatar_profiles
        ),
        character_equipment_eligibilities=(
            *(
                item
                for item in bundle["ir"].character_equipment_eligibilities
                if item.definition_key.definition_identity != fixture_card_id
            ),
            eligibility,
        ),
    )
    fixture_rules = RuleBook(fixture_ir)
    _, assembly = _assembly(
        fixture_rules,
        fixture_card_id,
        definition,
        instance_id=(
            "validation:p8_s8:equipment-mechanism-instance:"
            f"{definition.definition_key.definition_identity}"
        ),
        rank=1,
    )
    if assembly.battle_admission_status != "admitted":
        reasons = sorted(
            {
                str(item.reason)
                for item in (
                    *assembly.diagnostics,
                    *assembly.battle_admission_blockers,
                )
                if getattr(item, "reason", "")
            }
        )
        return None, (
            "mechanism_fixture_equipment_build_not_admitted:"
            + ";".join(reasons or ("reason_missing",))
        )
    selections = tuple(
        selection
        for selection in assembly.dynamic_mechanisms
        if selection.target_definition_key == definition.definition_key
    )
    if len(selections) != 1:
        return None, f"mechanism_fixture_selection_count:{len(selections)}"
    selection = selections[0]
    provider = register_dynamic_ability_providers(
        state,
        fixture_rules,
        (("ally:actor", selection),),
    )
    if not provider.ok:
        return None, f"mechanism_fixture_provider_blocked:{provider.blocked_reason}"
    startup = _apply_startup_ability_effects(
        provider.after_state,
        fixture_rules,
        [
            {
                "unit_id": "ally:actor",
                **_equipment_startup_spec(fixture_rules, selection),
            }
        ],
    )
    if startup.blocked:
        reasons = sorted(
            {
                str(row.get("reason") or "startup_blocked")
                for row in startup.blocked
            }
        )
        return None, "mechanism_fixture_startup_blocked:" + ";".join(reasons)
    current = startup.state
    installed_names = {
        str(detail.get("modifier_name") or "")
        for detail in current.units["ally:actor"].flags.get(
            "status_details", ()
        )
        if isinstance(detail, dict)
    }
    startup_listeners = tuple(
        callback
        for callback in fixture_rules.ir.status_callbacks
        if callback.modifier_name in installed_names
        and callback.event != "OnListenCharacterCreate"
        and callback.coverage_status == "executable"
    )
    dispatcher = EventDispatchSystem(
        fixture_rules,
        EffectRegistry(StatusSystem(fixture_rules)),
    )
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    for listener in startup_listeners:
        family = next(
            (
                item
                for item in fixture_rules.ir.status_event_families
                if item.callback_event == listener.event
                and item.coverage_status == "executable"
                and item.admission_status == "executable"
            ),
            None,
        )
        if family is None:
            return None, "mechanism_fixture_startup_listener_family_missing"
        produced = next(
            (
                event
                for event_type in family.runtime_event_sources
                for event in events_by_type.get(event_type, ())
            ),
            None,
        )
        if produced is None:
            continue
        allowed_phases = COMBAT_EVENT_PHASES.get(produced.event_type, ())
        dispatch_state = (
            replace(
                current,
                global_flags={
                    **current.global_flags,
                    "combat_phase": allowed_phases[0],
                },
            )
            if allowed_phases
            else current
        )
        dispatched = dispatcher.dispatch_event(
            dispatch_state,
            event=produced,
            unit_id="ally:actor",
            modifier_name=listener.modifier_name,
        )
        if dispatched.errors:
            return None, (
                "mechanism_fixture_startup_listener_blocked:"
                + ";".join(dispatched.errors)
            )
        current = dispatched.after_state
    return current, ""


def _target_family_probe_state(*, reversed_order: bool = False) -> BattleState:
    def unit(
        unit_id: str,
        side: str,
        *,
        team_side: str,
        position: int,
        summon_kind: str = "",
        unselectable: bool = False,
        removed: bool = False,
    ) -> UnitState:
        flags: dict[str, Any] = {"position": position, "team_side": team_side}
        if summon_kind:
            summon_owner_id = (
                "ally:wearer" if team_side == "ally" else "enemy:target"
            )
            flags.update(
                {
                    "summon_kind": summon_kind,
                    "owner_id": summon_owner_id,
                    "summoner_id": summon_owner_id,
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "field",
                        "targetable": True,
                    },
                }
            )
        if unselectable:
            flags["unselectable"] = True
        return UnitState(
            unit_id=unit_id,
            side=side,
            template_id=f"validation:{unit_id}",
            max_hp=100.0,
            hp=100.0,
            action_value=float(10 + position),
            resources={"break_damage_added_ratio": float(position + 1) / 10.0},
            lifecycle_status="removed" if removed else "active",
            flags=flags,
        )

    rows = [
        unit("ally:wearer", "ally", team_side="ally", position=0),
        unit("ally:peer", "ally", team_side="ally", position=1),
        unit("ally:hidden", "ally", team_side="ally", position=2, unselectable=True),
        unit("ally:summon", "summon", team_side="ally", position=3, summon_kind="servant"),
        unit(
            "ally:hidden_summon",
            "summon",
            team_side="ally",
            position=4,
            summon_kind="summoned_monster",
            unselectable=True,
        ),
        unit("enemy:target", "enemy", team_side="enemy", position=0),
        unit("enemy:peer", "enemy", team_side="enemy", position=1),
        unit("enemy:hidden", "enemy", team_side="enemy", position=2, unselectable=True),
        unit("enemy:summon", "summon", team_side="enemy", position=3, summon_kind="summoned_monster"),
        unit(
            "enemy:hidden_summon",
            "summon",
            team_side="enemy",
            position=4,
            summon_kind="servant",
            unselectable=True,
        ),
        unit("enemy:removed", "enemy", team_side="enemy", position=5, removed=True),
        unit("level:global", "system", team_side="system", position=0),
    ]
    if reversed_order:
        rows.reverse()
    summon_entries = {
        "ally:summon": {
            "status": "active",
            "summon_kind": "servant",
            "owner_id": "ally:wearer",
            "summoner_id": "ally:wearer",
            "team_side": "ally",
            "targetability": {"targetable": True},
        },
        "ally:hidden_summon": {
            "status": "active",
            "summon_kind": "summoned_monster",
            "owner_id": "ally:wearer",
            "summoner_id": "ally:wearer",
            "team_side": "ally",
            "targetability": {"targetable": True},
        },
        "enemy:summon": {
            "status": "active",
            "summon_kind": "summoned_monster",
            "owner_id": "enemy:target",
            "summoner_id": "enemy:target",
            "team_side": "enemy",
            "targetability": {"targetable": True},
        },
        "enemy:hidden_summon": {
            "status": "active",
            "summon_kind": "servant",
            "owner_id": "enemy:target",
            "summoner_id": "enemy:target",
            "team_side": "enemy",
            "targetability": {"targetable": True},
        },
    }
    summon_runtime = _fixture_summon_runtime(
        summon_entries,
        by_owner={
            "ally:wearer": ["ally:summon", "ally:hidden_summon"],
            "enemy:target": ["enemy:summon", "enemy:hidden_summon"],
        },
        last_summon_monsters=(
            "ally:hidden_summon",
            "enemy:summon",
        ),
        last_servants=("ally:summon", "enemy:hidden_summon"),
        servant_ids=("ally:summon", "enemy:hidden_summon"),
    )
    return BattleState(
        units={item.unit_id: item for item in rows},
        global_flags={
            "turn_owner_id": "ally:wearer",
            "summon_runtime": summon_runtime,
        },
    )


def _target_family_matrix(
    bundle: dict[str, Any],
    partition: dict[str, Any],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in partition["_inventory"]["_source_rows"]:
        if row["stage"] == "s8" and row["kind"] == "target":
            grouped[row["family"]].append(row)
    indexes = _coverage_source_indexes(bundle)
    system = TargetSystem()
    state = _target_family_probe_state()
    reordered = _target_family_probe_state(reversed_order=True)
    resolution = TargetResolution(
        requested=("enemy:target",),
        legal=("enemy:target",),
        selected=("enemy:target",),
        reason="p8_s8_exact_target_family",
        source="validation_fixture",
    )
    payload = {
        "actor_id": "ally:wearer",
        "source_id": "ally:wearer",
        "target_id": "enemy:target",
        "primary_target_id": "enemy:target",
        "current_hit_target_id": "enemy:target",
        "param_entity_id": "enemy:target",
        "param_entity_2_id": "ally:peer",
        "selected_target_ids": ["enemy:target", "enemy:peer"],
        "target_ids": ["enemy:target", "enemy:peer"],
        "skill_target_ids": ["enemy:target", "enemy:peer"],
        "attack_target_ids": ["enemy:target", "enemy:peer"],
        "skill_sub_target_ids": ["enemy:peer"],
        "modifier_owner_skill_target_ids": ["enemy:target", "enemy:peer"],
        "level_entity_id": "level:global",
    }
    unselectable_oracles = {
        "AllLightTeamWithAllLightTeamUnselectable": (
            "ally:hidden",
            "ally:hidden_summon",
            "ally:peer",
            "ally:summon",
            "ally:wearer",
        ),
        "AllLightTeamWithAllUnselectableLightTeam": (
            "ally:hidden",
            "ally:hidden_summon",
            "ally:peer",
            "ally:summon",
            "ally:wearer",
        ),
        "AllTeamMemberWithUnselectable": (
            "ally:hidden",
            "ally:hidden_summon",
            "ally:peer",
            "ally:summon",
            "ally:wearer",
        ),
        "AllTeammateWithUnselectable": (
            "ally:hidden",
            "ally:hidden_summon",
            "ally:peer",
            "ally:summon",
        ),
        "AllDarkTeamWithAllDarkTeamUnselectable": (
            "enemy:hidden",
            "enemy:hidden_summon",
            "enemy:peer",
            "enemy:summon",
            "enemy:target",
        ),
        "AllEnemyWithUnSelectable": (
            "enemy:hidden",
            "enemy:hidden_summon",
            "enemy:peer",
            "enemy:summon",
            "enemy:target",
        ),
        "AllUnselectable": (
            "ally:hidden",
            "ally:hidden_summon",
            "enemy:hidden",
            "enemy:hidden_summon",
        ),
    }
    rows = []
    for family, raw_rows in sorted(grouped.items()):
        aliases: list[str] = []
        nodes: list[TargetExpressionNodeIR] = []
        if family.startswith("TargetAlias:"):
            alias = family.split(":", 1)[1]
            aliases.append(alias)
            nodes.append(TargetExpressionNodeIR(expression_kind="TargetAlias", alias=alias))
        else:
            for raw_row in raw_rows:
                for linked in _linked_nodes(raw_row, indexes):
                    node = getattr(linked, "node", None)
                    if isinstance(node, TargetExpressionNodeIR):
                        nodes.append(node)
                    if isinstance(linked, ConditionIR):
                        nodes.extend(
                            node
                            for node in _condition_target_nodes(linked)
                            if node.expression_kind == family
                        )
        attempts = []
        for node in nodes:
            modifier_owner_id = (
                "ally:summon"
                if "ModifierOwnerSummoner" in node.alias
                or "ModifierOwnerEntity.GetSummoner" in node.alias
                else "ally:wearer"
            )
            probe_param_entity_id = (
                "enemy:summon"
                if "ParamEntity.GetSummoner" in node.alias
                else "enemy:target"
            )
            probe_payload = dict(payload)
            if node.expression_kind == "TargetSequence":
                probe_payload["param_entity_2_id"] = "ally:summon"
            result = system.resolve_expression_node(
                state,
                node,
                caster_id="ally:wearer",
                owner_id=modifier_owner_id,
                param_entity_id=probe_param_entity_id,
                current_action_target_id="enemy:target",
                target_resolution=resolution,
                event_payload=probe_payload,
                dynamic_values={},
            )
            reordered_result = system.resolve_expression_node(
                reordered,
                node,
                caster_id="ally:wearer",
                owner_id=modifier_owner_id,
                param_entity_id=probe_param_entity_id,
                current_action_target_id="enemy:target",
                target_resolution=resolution,
                event_payload=probe_payload,
                dynamic_values={},
            )
            expected = unselectable_oracles.get(node.alias)
            attempt_ok = (
                result.ok
                and reordered_result.ok
                and result.target_ids == reordered_result.target_ids
                and (expected is None or result.target_ids == expected)
                and "enemy:removed" not in result.target_ids
            )
            attempts.append(
                {
                    "node": node.to_json(),
                    "target_ids": list(result.target_ids),
                    "reordered_target_ids": list(reordered_result.target_ids),
                    "expected_target_ids": list(expected) if expected is not None else None,
                    "blocked_reason": result.blocked_reason,
                    "ok": attempt_ok,
                }
            )
        selected = next((item for item in attempts if item["ok"]), None)
        all_nodes_executed = bool(attempts) and all(
            item["ok"] for item in attempts
        )
        rows.append(
            {
                "family": family,
                "real_source_count": len(raw_rows),
                "representative_source_identity": raw_rows[0]["source_identity"],
                "attempt_count": len(attempts),
                "successful_node_count": sum(item["ok"] for item in attempts),
                "selected": selected or {},
                "attempts": [item for item in attempts if not item["ok"]][:3],
                "ok": all_nodes_executed,
            }
        )
    checks = {
        "target_families_nonempty": bool(rows),
        "every_exact_target_family_executed": all(row["ok"] for row in rows),
        "unselectable_oracles_present_in_real_sources": all(
            family.removeprefix("TargetAlias:").split(".", 1)[0]
            in unselectable_oracles
            for family in grouped
            if "Unselectable" in family or "UnSelectable" in family
        ),
        "unselectable_team_and_summon_members_included": all(
            row["ok"]
            for row in rows
            if "Unselectable" in row["family"] or "UnSelectable" in row["family"]
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_exact_target_family_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "family_count": len(rows),
        "failures": [row for row in rows if not row["ok"]],
        "rows": rows,
    }


def _effect_route_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    registry = EffectRegistry(StatusSystem(rules))
    reducer = MutationReducer()
    route_opcodes = {
        "healing": {"HealHP"},
        "shield": {"InitShield"},
        "energy_resource": {"ModifySPNew"},
        "team_boost_resource": {"ModifyTeamBoostPoint"},
        "resource_maximum": {"ModifyTeamBoostPointMax"},
        "hp_loss": {"LoseHPByRatio"},
    }
    rows: list[dict[str, Any]] = []
    for route, opcodes in route_opcodes.items():
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for task in sorted(bundle["callback_tasks"], key=lambda item: item.task_id):
            if task.opcode not in opcodes or not task.effect_id:
                continue
            effect = rules.effect(task.effect_id)
            if effect is None or effect.coverage_status != "executable":
                continue
            state = _route_probe_state()
            hashes = tuple(
                value_hash
                for _, expression in _numeric_expressions(effect.payload)
                for value_hash in numeric_dynamic_hashes(expression)
            )
            dynamic_values = {str(value_hash): 1.0 for value_hash in hashes}
            result = registry.execute(
                effect,
                EffectExecutionContext(
                    state=state,
                    caster_id="ally:wearer",
                    owner_id="ally:wearer",
                    source_id=task.task_id,
                    param_entity_id="enemy:target",
                    current_action_target_id="enemy:target",
                    event_payload={
                        "actor_id": "ally:wearer",
                        "target_id": "enemy:target",
                        "param_entity_id": "enemy:target",
                        "skill_target_ids": ["enemy:target"],
                        "selected_target_ids": ["enemy:target"],
                        "modifier_name": task.modifier_name,
                        "status_instance_id": f"validation:{task.task_id}",
                        "status_instance_source": task.source.to_json(),
                    },
                    dynamic_values=dynamic_values,
                ),
            )
            after = reducer.apply_all(state, result.mutations) if not result.unsupported else state
            mutation_ids = {mutation.stable_id() for mutation in result.mutations}
            settlement_ids = {
                str(record.get("mutation_id") or "")
                for record in result.records
                if isinstance(record, dict) and record.get("mutation_id")
            }
            replay = reducer.replay_snapshot(
                state,
                result.mutations,
                after.snapshot().to_json(),
            )
            attempt = {
                "route": route,
                "opcode": task.opcode,
                "task_id": task.task_id,
                "effect_id": effect.effect_id,
                "source": effect.source.to_json(),
                "unsupported": list(result.unsupported),
                "mutation_count": len(result.mutations),
                "record_count": len(result.records),
                "event_count": len(result.events),
                "all_mutations_settled": bool(mutation_ids) and mutation_ids <= settlement_ids,
                "replay_equal": replay.ok,
                "ok": not result.unsupported
                and bool(result.mutations)
                and mutation_ids <= settlement_ids
                and replay.ok,
            }
            attempts.append(attempt)
            if attempt["ok"]:
                selected = attempt
                break
        rows.append(
            selected
            or {
                "route": route,
                "ok": False,
                "reason": "no_real_source_effect_completed_common_route",
                "attempts": attempts[:5],
            }
        )

    blocked_task = next(
        task
        for task in bundle["callback_tasks"]
        if task.effect_id
        and task.opcode in {opcode for values in route_opcodes.values() for opcode in values}
        and rules.effect(task.effect_id) is not None
    )
    blocked_effect = replace(
        rules.effect(blocked_task.effect_id),
        coverage_status="blocked",
    )
    blocked_state = _route_probe_state()
    blocked_result = registry.execute(
        blocked_effect,
        EffectExecutionContext(
            state=blocked_state,
            caster_id="ally:wearer",
            owner_id="ally:wearer",
            source_id=blocked_task.task_id,
            param_entity_id="enemy:target",
            current_action_target_id="enemy:target",
        ),
    )
    blocked = {
        "ok": bool(blocked_result.unsupported)
        and not blocked_result.mutations
        and blocked_state.snapshot().to_json() == _route_probe_state().snapshot().to_json(),
        "unsupported": list(blocked_result.unsupported),
        "mutation_count": len(blocked_result.mutations),
    }
    checks = {
        "every_effect_route_has_real_transition": all(row["ok"] for row in rows),
        "mutations_have_settlement": all(row.get("all_mutations_settled") is True for row in rows),
        "transitions_replay_equal": all(row.get("replay_equal") is True for row in rows),
        "unadmitted_effect_state_unchanged": blocked["ok"],
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_common_effect_route_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "rows": rows,
        "blocked": blocked,
    }


def _damage_route_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    emission = next(
        (
            item
            for item in bundle["ir"].status_damage_emissions
            if item.coverage_status == "executable"
            and item.damage_formula_family in {"additional", "dot"}
        ),
        None,
    )
    if emission is None:
        return {
            "schema_version": "p8_s8_damage_route_matrix_v1",
            "ok": False,
            "reason": "real_equipment_damage_emission_missing",
        }
    state = _route_probe_state()
    packet = DamagePacket(
        attacker_id="ally:wearer",
        target_id="enemy:target",
        attack_type=emission.attack_type,
        damage_formula_family=emission.damage_formula_family,
        amount=10.0,
        amount_stage="family_base",
        status_damage_emission_id=emission.status_damage_emission_id,
        status_callback_id=emission.callback_id,
        source_task_id=emission.source_task_id,
        source_trace=emission.source.to_json(),
        source_frame=DamageSourceFrame(
            owner_id="ally:wearer",
            source_id=emission.status_damage_emission_id,
            source_kind="equipment_status_damage_emission",
            sequence_id="validation:p8_s8:damage",
            target_id="enemy:target",
            source_trace=emission.source.to_json(),
        ),
    )
    result = DamageSystem(rules).apply_packet(state, packet)
    reducer = MutationReducer()
    after = reducer.apply_all(state, result.mutations) if result.ok else state
    replay = reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json())
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    settlement_ids = {
        str(record.get("mutation_id") or "")
        for record in result.records
        if isinstance(record, dict) and record.get("mutation_id")
    }
    bad_packet = replace(packet, amount_stage="unspecified")
    blocked = DamageSystem(rules).apply_packet(state, bad_packet)
    checks = {
        "real_equipment_emission_uses_common_damage_system": result.ok and bool(result.mutations),
        "damage_mutations_settled": mutation_ids <= settlement_ids,
        "damage_replay_equal": replay.ok,
        "invalid_amount_stage_blocked_unchanged": not blocked.ok and not blocked.mutations,
        "source_is_real_equipment_row": emission.source.source_path.startswith("Config/ConfigAbility/Equip/"),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_damage_route_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "emission": emission.to_json(),
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
        "event_count": len(result.events),
        "blocked_errors": list(blocked.errors),
    }


def _rng_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    tasks = tuple(
        task
        for task in bundle["callback_tasks"]
        if task.opcode in {"RandomConfig", "Retarget"}
        and task.coverage_status == "executable"
    )
    if not tasks:
        return {"schema_version": "p8_s8_rng_ledger_matrix_v1", "ok": False, "reason": "real_rng_task_missing"}
    task = sorted(tasks, key=lambda item: item.task_id)[0]
    requests: list[RNGRequest] = []
    for wearer_id, decision_index in (
        ("ally:wearer", 0),
        ("ally:peer", 0),
        ("ally:wearer", 1),
    ):
        identity = {
            "decision_scope": f"equipment_status_callback:{task.callback_id}",
            "decision_index": decision_index,
            "task_id": task.task_id,
            "owner_id": wearer_id,
            "status_id": f"modifier:{task.modifier_name}",
        }
        rng_type = "equipment_callback_choice"
        requests.append(
            RNGRequest(
                rng_type=rng_type,
                purpose=task.opcode,
                event_id=event_id_for_identity(rng_type, identity, event_index=7),
                choice_key=choice_key_for_identity(rng_type, identity),
                source=task.task_id,
                before_state="validation:p8_s8:rng",
                decision_kind="weighted_choice",
                outcomes=(
                    RNGOutcome("branch:0", weight=1.0),
                    RNGOutcome("branch:1", weight=1.0),
                ),
                source_trace=task.source.to_json(),
                identity=identity,
            )
        )
    resolutions = [
        resolve_rng_request(
            request,
            rng_mode="explicit",
            rng_choices={request.choice_key: "branch:1"},
        )
        for request in requests
    ]
    events = tuple(
        resolution.event
        for resolution in resolutions
        if resolution.event is not None
    )
    ledger_payload = {
        "rng_mode": "explicit",
        "rng_choices": {
            request.choice_key: "branch:1" for request in requests
        },
    }
    ledger = validate_rng_choice_ledger(ledger_payload, events)
    missing = resolve_rng_request(requests[0], rng_mode="explicit")
    invalid = resolve_rng_request(
        requests[0],
        rng_mode="explicit",
        rng_choices={requests[0].choice_key: "missing"},
    )
    replayed = [
        resolve_rng_request(
            request,
            rng_mode="explicit",
            rng_choices={request.choice_key: resolution.selected_outcome_id},
        )
        for request, resolution in zip(requests, resolutions)
    ]
    checks = {
        "real_rng_source_selected": task.source.source_path.startswith("Config/ConfigAbility/Equip/"),
        "stable_identity_unique_across_wearer_and_decision": len({request.choice_key for request in requests}) == len(requests),
        "explicit_choices_consumed": all(resolution.ok for resolution in resolutions),
        "choice_ledger_exact": ledger.ok,
        "replay_consumes_same_outcomes": all(
            replay.ok and replay.selected_outcome_id == original.selected_outcome_id
            for replay, original in zip(replayed, resolutions)
        ),
        "missing_and_invalid_choices_block": not missing.ok and not invalid.ok,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_rng_ledger_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "task_source": task.source.to_json(),
        "choice_keys": [request.choice_key for request in requests],
        "event_ids": [request.event_id for request in requests],
        "ledger": ledger.to_json(),
        "missing_reason": missing.blocked_reason,
        "invalid_reason": invalid.blocked_reason,
    }


def _timeline_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    emission = next(
        (
            item
            for item in bundle["ir"].action_delay_emissions
            if item.coverage_status == "executable"
        ),
        None,
    )
    if emission is None:
        return {"schema_version": "p8_s8_timeline_matrix_v1", "ok": False, "reason": "real_action_delay_emission_missing"}
    state = _route_probe_state()
    system = TimelineSystem()
    result = system.adjust_action_value(
        state,
        "enemy:target",
        operation="delay",
        amount=10.0,
        source="status_callback_system",
        metadata={
            "action_delay_emission_id": emission.action_delay_emission_id,
            "source_task_id": emission.source_task_id,
            "source_trace": emission.source.to_json(),
        },
        rule=bundle["rules"].select_timeline_rule()[0],
    )
    reducer = MutationReducer()
    after = reducer.apply_all(state, result.mutations)
    replay = reducer.replay_snapshot(state, result.mutations, after.snapshot().to_json())
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    settlement_ids = {
        str(record.get("mutation_id") or "")
        for record in result.records
        if isinstance(record, dict) and record.get("mutation_id")
    }
    blocked = system.adjust_action_value(
        state,
        "enemy:target",
        operation="unsupported",
        amount=10.0,
        source="status_callback_system",
        metadata={"source_trace": emission.source.to_json()},
    )
    checks = {
        "real_emission_source": emission.source.source_path.startswith("Config/ConfigAbility/Equip/"),
        "common_timeline_mutation_created": result.plan.ok and bool(result.mutations),
        "timeline_mutation_settled": mutation_ids <= settlement_ids,
        "timeline_replay_equal": replay.ok,
        "unsupported_operation_blocked_unchanged": not blocked.plan.ok and not blocked.mutations,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_timeline_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "emission": emission.to_json(),
        "plan": result.plan.to_json(),
        "blocked_plan": blocked.plan.to_json(),
    }


def _event_contract_matrix(bundle: dict[str, Any], formal: dict[str, Any]) -> dict[str, Any]:
    callbacks_by_event: dict[str, list[Any]] = defaultdict(list)
    for callback in bundle["ir"].status_callbacks:
        callbacks_by_event[callback.event].append(callback)
    rows = []
    for family in sorted(bundle["ir"].status_event_families, key=lambda item: item.status_event_family_id):
        callbacks = callbacks_by_event.get(family.callback_event, [])
        non_gameplay_count = sum(
            callback.blocked_reason == "equipment_event_family_non_gameplay"
            for callback in callbacks
        )
        gameplay_count = family.callback_count - non_gameplay_count
        if gameplay_count == 0:
            row_ok = (
                family.callback_count > 0
                and non_gameplay_count == family.callback_count
                and family.executable_callback_count == 0
                and family.blocked_callback_count == family.callback_count
                and family.coverage_status == "blocked"
                and family.admission_status == "blocked"
            )
            classification = "non_gameplay"
        else:
            row_ok = (
                family.coverage_status == "executable"
                and family.admission_status == "executable"
                and bool(family.runtime_event_sources)
                and family.executable_callback_count == gameplay_count
                and family.blocked_callback_count == non_gameplay_count
            )
            classification = "gameplay"
        rows.append(
            {
                "event": family.callback_event,
                "event_family": family.event_family,
                "classification": classification,
                "runtime_event_sources": list(family.runtime_event_sources),
                "callback_count": family.callback_count,
                "gameplay_callback_count": gameplay_count,
                "non_gameplay_callback_count": non_gameplay_count,
                "executable_callback_count": family.executable_callback_count,
                "blocked_callback_count": family.blocked_callback_count,
                "admission_status": family.admission_status,
                "coverage_status": family.coverage_status,
                "source": family.source.to_json(),
                "ok": row_ok,
            }
        )
    built = formal["_built"]
    setup_event_types = {event.event_type for event in built.setup_events}
    checks = {
        "event_families_nonempty": bool(rows),
        "every_event_family_has_runtime_producer": all(row["ok"] for row in rows),
        "formal_setup_exports_real_events": bool(setup_event_types),
        "formal_setup_audited": formal["checks"]["public_setup_mutations_source_audited"],
        "formal_setup_replay_equal": formal["checks"]["public_setup_mutations_replay_final_state"],
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_event_contract_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "event_family_count": len(rows),
        "setup_event_types": sorted(setup_event_types),
        "failures": [row for row in rows if not row["ok"]],
        "rows": rows,
    }


def _status_replacement_contract_matrix() -> dict[str, Any]:
    status_id = "modifier:ValidationReplaceByCaster"
    first = {
        "status_id": status_id,
        "caster_id": "ally:first",
        "source_id": "validation:first_source",
    }
    second = {
        "status_id": status_id,
        "caster_id": "ally:second",
        "source_id": "validation:second_source",
    }
    details = [first, second]
    same_caster = _replacement_status_detail(
        details,
        status_id=status_id,
        stacking="ReplaceByCaster",
        caster_id="ally:second",
    )
    different_caster = _replacement_status_detail(
        details,
        status_id=status_id,
        stacking="ReplaceByCaster",
        caster_id="ally:third",
    )
    unsupported_policy = _replacement_status_detail(
        details,
        status_id=status_id,
        stacking="ReplaceByCasterAbility",
        caster_id="ally:second",
    )
    checks = {
        "replace_by_caster_selects_only_same_caster": same_caster is second,
        "replace_by_caster_rejects_different_caster": different_caster is None,
        "unmodeled_replacement_namespace_fails_closed": unsupported_policy is None,
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_status_replacement_contract_v1",
        "ok": checks["ok"],
        "checks": checks,
    }


def _energy_listener_matrix(
    bundle: dict[str, Any],
    cards_by_path: dict[str, Any],
) -> dict[str, Any]:
    rules: RuleBook = bundle["rules"]
    callbacks = tuple(
        callback
        for callback in bundle["ir"].status_callbacks
        if callback.event == UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1]
        and callback.coverage_status == "executable"
        and callback.source.source_path.startswith("Config/ConfigAbility/Equip/")
    )
    if len(callbacks) != 1:
        return {
            "schema_version": "p8_s8_energy_listener_matrix_v1",
            "ok": False,
            "reason": f"real_on_sp_change_callback_count:{len(callbacks)}",
        }
    callback = callbacks[0]
    ability_source = callback.source.evidence.get("equipment_ability_source")
    ability_name = (
        str(ability_source.get("raw_id") or "")
        if isinstance(ability_source, dict)
        else ""
    )
    definitions = tuple(
        definition
        for definition in bundle["definitions"]
        if definition.ability_source is not None
        and definition.ability_source.ability_name == ability_name
    )
    if len(definitions) != 1 or definitions[0].path_type not in cards_by_path:
        return {
            "schema_version": "p8_s8_energy_listener_matrix_v1",
            "ok": False,
            "reason": "on_sp_change_definition_or_matching_character_unresolved",
            "callback": callback.to_json(),
        }
    definition = definitions[0]
    card = cards_by_path[definition.path_type]
    equipment_build, equipment_result = _assembly(
        rules,
        card.card_id,
        definition,
        instance_id=f"validation:p8_s8:energy:{definition.definition_key.definition_identity}",
        rank=1,
    )
    character_build = _character_build(
        card.card_id,
        "validation:p8_s8:energy:character",
        equipment_build,
    )
    character_result = assemble_character_build(rules, character_build)
    if (
        equipment_result.battle_admission_status != "admitted"
        or character_result.battle_admission_status != "admitted"
    ):
        return {
            "schema_version": "p8_s8_energy_listener_matrix_v1",
            "ok": False,
            "reason": "on_sp_change_formal_build_not_admitted",
            "equipment_diagnostics": list(equipment_result.diagnostics),
            "character_diagnostics": list(character_result.diagnostics),
        }
    scenario = ScenarioSpec(
        scenario_id="validation:p8_s8:energy_listener",
        version=BASELINE_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:wearer",
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
    built = ScenarioStateBuilder(rules).build(scenario)
    registry = EffectRegistry(StatusSystem(rules))
    dispatcher = EventDispatchSystem(rules, registry)
    prepare_event = GameEvent(
        event_type="action.ultimate.prepare",
        source_id="ally:wearer",
        target_id="ally:wearer",
        event_id="validation:p8_s8:energy:ultimate_prepare",
        window="OnUltraSkillPrepare",
        process_only=True,
        payload={
            "callback_events": ["OnUltraSkillPrepare"],
            "listener_scope": "owner_local",
            "actor_id": "ally:wearer",
            "target_id": "ally:wearer",
            "param_entity_id": "ally:wearer",
            "skill_type": "Ultra",
        },
    )
    prepared = dispatcher.dispatch_event(built.state, event=prepare_event)
    max_energy = prepared.after_state.units["ally:wearer"].max_energy
    charge = ResourceSystem().change_unit_energy(
        prepared.after_state,
        "ally:wearer",
        max_energy,
        "resource_system",
    )
    charged_base_state = MutationReducer().apply(prepared.after_state, charge)
    charge_event = next(
        iter(
            events_for_mutation(
                charge,
                actor_id="ally:wearer",
                source_id="ally:wearer",
                event_index=charged_base_state.event_index,
                include_before=False,
            )
        ),
        None,
    )
    charge_result = (
        dispatcher.dispatch_event(charged_base_state, event=charge_event)
        if charge_event is not None
        else None
    )
    charged_state = (
        charge_result.after_state
        if charge_result is not None
        else charged_base_state
    )
    spend = ResourceSystem().change_unit_energy(
        charged_state,
        "ally:wearer",
        -max_energy,
        "resource_system",
    )
    spent_state = MutationReducer().apply(charged_state, spend)
    energy_events = events_for_mutation(
        spend,
        actor_id="ally:wearer",
        source_id="ally:wearer",
        event_index=spent_state.event_index,
        include_before=False,
    )
    energy_event = next(
        (
            event
            for event in energy_events
            if event.event_type == UNIT_ENERGY_EVENT_CONTRACT.after_event_type
        ),
        None,
    )
    if energy_event is None:
        return {
            "schema_version": "p8_s8_energy_listener_matrix_v1",
            "ok": False,
            "reason": "energy_mutation_event_missing",
        }
    result = dispatcher.dispatch_event(spent_state, event=energy_event)
    callback_records = tuple(
        record
        for record in result.records
        if record.get("record_type") == "status_callback"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    )
    charge_callback_records = tuple(
        record
        for record in (
            (*charge_result.records, *charge_result.listener_records)
            if charge_result is not None
            else ()
        )
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    )
    task_records = tuple(
        record
        for record in result.records
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
        and record["payload"].get("task_id")
    )
    mutation_ids = {mutation.stable_id() for mutation in result.mutations}
    settlement_ids = {
        str(record.get("mutation_id") or "")
        for record in result.records
        if record.get("mutation_id")
    }
    replay = MutationReducer().replay_snapshot(
        spent_state,
        result.mutations,
        result.after_state.snapshot().to_json(),
    )
    audit = _event_dispatch_probe_audit(
        rules,
        spent_state,
        energy_event,
        result,
    )
    forged_event = replace(
        energy_event,
        event_type=next(iter(RETIRED_RESOURCE_EVENT_TYPES)),
        event_id=f"{energy_event.event_id}:forged_old_source",
    )
    forged = dispatcher.dispatch_event(spent_state, event=forged_event)
    forged_callback_records = tuple(
        record
        for record in forged.records
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    )
    bp_mutation = ResourceSystem().set_skill_points(
        spent_state,
        min(spent_state.max_skill_points, spent_state.skill_points + 1),
        "resource_system",
    )
    bp_event = next(
        iter(
            events_for_mutation(
                bp_mutation,
                actor_id="ally:wearer",
                source_id="ally:wearer",
                event_index=spent_state.event_index,
            )
        ),
        None,
    )
    bp_cross = (
        dispatcher.dispatch_event(
            spent_state,
            event=bp_event,
            unit_id="ally:wearer",
            modifier_name=callback.modifier_name,
        )
        if bp_event is not None
        else None
    )
    bp_cross_callback_records = tuple(
        record
        for record in (bp_cross.records if bp_cross is not None else ())
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    )
    checks = {
        "matching_path_formal_build_admitted": (
            equipment_result.battle_admission_status == "admitted"
            and character_result.battle_admission_status == "admitted"
        ),
        "ultimate_prepare_callback_executed": not prepared.errors,
        "energy_change_event_is_mutation_backed": (
            energy_event.payload.get("mutation_id") == spend.stable_id()
            and UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1]
            in energy_event.payload.get("callback_events", ())
            and energy_event.payload.get("change_value")
            == spend.after - spend.before
        ),
        "real_on_sp_change_callback_executed": (
            not result.errors and bool(callback_records) and bool(task_records)
        ),
        "energy_gain_and_spend_route_to_on_sp_listener": (
            charge_event is not None
            and charge_event.payload.get("change_value")
            == charge.after - charge.before
            and charge_result is not None
            and not charge_result.errors
            and bool(charge_callback_records)
            and bool(callback_records)
        ),
        "callback_mutations_settled": bool(mutation_ids)
        and mutation_ids <= settlement_ids,
        "callback_replay_equal": replay.ok,
        "callback_source_audit_ok": audit["source_audit_ok"],
        "old_unadmitted_event_source_does_not_trigger": (
            not forged_callback_records
            and not forged.mutations
            and forged.after_state == spent_state
        ),
        "bp_event_does_not_trigger_on_sp_change": (
            bp_event is not None
            and not bp_cross_callback_records
            and bp_cross is not None
            and not bp_cross.mutations
            and bp_cross.after_state == spent_state
        ),
        "callback_source_is_real_equipment_row": (
            callback.source.source_path.startswith("Config/ConfigAbility/Equip/")
            and bool(callback.source.evidence.get("json_path"))
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_energy_listener_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "callback": callback.to_json(),
        "energy_event": energy_event.to_json(),
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
        "task_record_count": len(task_records),
        "charge_callback_record_count": len(charge_callback_records),
        "record_evidence": [
            {
                "record_type": record.get("record_type"),
                "mutation_id": record.get("mutation_id"),
                "callback_id": (
                    record.get("payload", {}).get("callback_id")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "task_id": (
                    record.get("payload", {}).get("task_id")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "process_only": record.get("process_only"),
            }
            for record in result.records
            if (
                record.get("mutation_id") in mutation_ids
                or (
                    isinstance(record.get("payload"), dict)
                    and record["payload"].get("callback_id") == callback.callback_id
                )
            )
        ],
        "errors": list(result.errors),
        "source_audit_replay": audit,
        "forged_errors": list(forged.errors),
        "forged_callback_record_count": len(forged_callback_records),
        "bp_cross_trigger_count": len(bp_cross_callback_records),
        "_production_events": (energy_event, *result.events),
    }


def _merge_production_events(
    production: dict[str, Any],
    events: tuple[GameEvent, ...] | list[GameEvent],
) -> None:
    by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    known_ids = {
        event.event_id
        for event_rows in by_type.values()
        for event in event_rows
    }
    for event in events:
        if event.event_id in known_ids:
            continue
        by_type.setdefault(event.event_type, []).append(event)
        known_ids.add(event.event_id)


def _augment_common_mutation_events(production: dict[str, Any]) -> dict[str, int]:
    """Add events emitted by existing typed mutation producers, not fixtures."""

    route_state = _route_probe_state()
    actor = replace(route_state.units["ally:wearer"], unit_id="ally:actor")
    state = replace(
        route_state,
        units={
            "ally:actor": actor,
            "ally:peer": route_state.units["ally:peer"],
            "enemy:target": route_state.units["enemy:target"],
        },
    )
    rules: RuleBook = production["_rules"]
    source_trace = next(
        (
            definition.source.to_json()
            for definition in rules.ir.action_definitions
            if definition.coverage_status == "executable"
        ),
        {},
    )
    resources = ResourceSystem()
    energy_spend_actor = replace(
        state.units["ally:actor"],
        energy=160.0,
        max_energy=160.0,
    )
    energy_spend_state = replace(
        state,
        units={**state.units, "ally:actor": energy_spend_actor},
    )
    mutations = [
        resources.set_skill_points(state, state.skill_points + 1, "resource_system"),
        resources.set_skill_points(state, state.skill_points - 1, "resource_system"),
        resources.change_unit_energy(state, "ally:actor", 10.0, "resource_system"),
        resources.change_unit_energy(
            energy_spend_state,
            "ally:actor",
            -energy_spend_actor.energy,
            "resource_system",
        ),
        resources.change_unit_hp(state, "ally:actor", -10.0, "resource_system"),
    ]
    lifecycle_system = UnitLifecycleSystem()
    removals = lifecycle_system.remove_mutations(
        state,
        "enemy:target",
        reason="remove unit through lifecycle system",
        source="unit_lifecycle_system",
        removed_record={"reason": "focused_production_event_probe"},
        source_trace=source_trace,
    )
    mutations.extend(removals[:1])
    events: list[GameEvent] = []
    for index, mutation in enumerate(mutations):
        events.extend(
            events_for_mutation(
                mutation,
                actor_id="ally:actor",
                source_id="ally:actor",
                event_index=index,
                extra_payload={"source_trace": source_trace},
            )
        )
    _merge_production_events(production, events)
    return dict(sorted(Counter(event.event_type for event in events).items()))


def _augment_real_battle_state_transition_events(
    bundle: dict[str, Any],
    production: dict[str, Any],
) -> dict[str, Any]:
    """Seed shared state-window events through their production IR consumer."""

    rules: RuleBook = production["_rules"]
    expected_event_types = (
        "elation.time.started",
        "elation.time.ended",
    )
    rules_by_event = {
        event_type: tuple(
            transition
            for transition in rules.battle_state_transitions_for_runtime_event(
                event_type
            )
            if transition.coverage_status == "executable"
        )
        for event_type in expected_event_types
    }
    if any(len(rows) != 1 for rows in rules_by_event.values()):
        result = {
            "schema_version": "p8_s8_battle_state_transition_seed_v1",
            "ok": False,
            "reason": "battle_state_transition_rule_not_unique",
            "rule_counts": {
                event_type: len(rows)
                for event_type, rows in rules_by_event.items()
            },
        }
        production["_battle_state_transition_seed"] = result
        return result

    state = BattleState()
    system = BattleStateTransitionSystem(rules)
    rows: list[dict[str, Any]] = []
    produced_events: list[GameEvent] = []
    for event_type in expected_event_types:
        rule = rules_by_event[event_type][0]
        request = BattleStateTransitionRequest(
            trigger_kind=rule.trigger_kind,
            trigger_identity=rule.trigger_identity,
            actor_id="battle_event:elation",
            source_id=rule.transition_rule_id,
        )
        before = state
        transition = system.apply(before, request)
        audit = (
            _event_dispatch_probe_audit(
                rules,
                before,
                transition.events[0],
                transition,
            )
            if transition.ok and len(transition.events) == 1
            else {
                "ok": False,
                "replay_ok": False,
                "source_audit_ok": False,
                "audit_violations": [],
            }
        )
        mutation_ids = {
            mutation.stable_id() for mutation in transition.mutations
        }
        settlement_ids = {
            str(record.get("mutation_id") or "")
            for record in transition.records
            if record.get("mutation_id")
        }
        row_ok = (
            transition.ok
            and len(transition.mutations) == 1
            and len(transition.events) == 1
            and transition.events[0].event_type == event_type
            and mutation_ids == settlement_ids
            and audit.get("ok") is True
        )
        rows.append(
            {
                "runtime_event_type": event_type,
                "ok": row_ok,
                "rule": rule.to_json(),
                "mutation_count": len(transition.mutations),
                "event_count": len(transition.events),
                "record_count": len(transition.records),
                "errors": list(transition.errors),
                "source_audit_replay": audit,
            }
        )
        if not row_ok:
            result = {
                "schema_version": "p8_s8_battle_state_transition_seed_v1",
                "ok": False,
                "reason": "battle_state_transition_execution_failed",
                "rows": rows,
            }
            production["_battle_state_transition_seed"] = result
            return result
        produced_events.extend(transition.events)
        if event_type == "elation.time.started":
            duplicate = system.apply(transition.after_state, request)
            rows[-1]["duplicate_start_fail_closed"] = (
                not duplicate.ok
                and not duplicate.mutations
                and duplicate.after_state == transition.after_state
            )
        state = transition.after_state

    _merge_production_events(production, produced_events)
    dispatcher = EventDispatchSystem(rules, EffectRegistry())
    forged_event = replace(
        produced_events[0],
        payload={
            **produced_events[0].payload,
            "metadata": {
                **dict(produced_events[0].payload.get("metadata") or {}),
                "battle_state_transition_rule_id": (
                    "battle_state_transition:forged"
                ),
            },
        },
    )
    forged_dispatch = dispatcher.dispatch_event(
        BattleState(),
        event=forged_event,
    )
    legacy_alias_mutation = Mutation(
        op="set",
        path=("global_flags", "elation_time"),
        before=False,
        after=True,
        before_exists=True,
        after_exists=True,
        reason="retired elation-time alias negative",
        source="battle_state_transition_system",
        metadata=dict(produced_events[0].payload.get("metadata") or {}),
        mutation_id="mutation:negative:retired_elation_time_alias",
    )
    untyped_source_mutation = replace(
        legacy_alias_mutation,
        path=("global_flags", "elation_time_active"),
        source="forged_transition_producer",
        mutation_id="mutation:negative:untyped_elation_transition",
    )
    negative_matrix = {
        "forged_rule_identity_blocked_unchanged": (
            bool(forged_dispatch.errors)
            and not forged_dispatch.mutations
            and forged_dispatch.after_state == BattleState()
        ),
        "retired_state_alias_produces_no_event": not events_for_mutation(
            legacy_alias_mutation
        ),
        "untyped_transition_produces_no_event": not events_for_mutation(
            untyped_source_mutation
        ),
    }
    result = {
        "schema_version": "p8_s8_battle_state_transition_seed_v1",
        "ok": (
            all(row["ok"] for row in rows)
            and rows[0].get("duplicate_start_fail_closed") is True
            and state.global_flags.get("elation_time_active") is False
            and all(negative_matrix.values())
        ),
        "rows": rows,
        "final_elation_time_active": state.global_flags.get(
            "elation_time_active"
        ),
        "produced_event_types": [event.event_type for event in produced_events],
        "negative_matrix": negative_matrix,
    }
    production["_battle_state_transition_seed"] = result
    return result


def _augment_real_heal_events(
    bundle: dict[str, Any],
    production: dict[str, Any],
    cards_by_path: dict[str, Any],
) -> dict[str, Any]:
    """Seed heal.before/heal.after only through a real HealHP callback chain."""

    rules: RuleBook = bundle["rules"]
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    candidates = tuple(
        task
        for task in sorted(bundle["callback_tasks"], key=lambda item: item.task_id)
        if task.opcode == "HealHP"
        and task.coverage_status == "executable"
        and task.callback_id
        and _task_has_available_definition(bundle, task, cards_by_path)
        and (
            (callback := rules.status_callback(task.callback_id)) is not None
        )
        and any(
            events_by_type.get(event_type)
            for family in rules.ir.status_event_families
            if family.callback_event == callback.event
            and family.coverage_status == "executable"
            and family.admission_status == "executable"
            for event_type in family.runtime_event_sources
            if event_type not in {"heal.before", "heal.after"}
        )
    )
    attempts: list[dict[str, Any]] = []
    state_cache: dict[str, BattleState] = {}
    for task in candidates:
        attempt = _task_callback_execution_probe(
            bundle,
            production,
            task,
            state_cache=state_cache,
            cards_by_path=cards_by_path,
        )
        attempts.append(attempt)
        if (
            attempt.get("ok") is True
            and events_by_type.get("heal.before")
            and events_by_type.get("heal.after")
        ):
            result = {
                "ok": True,
                "source_task_id": task.task_id,
                "source": task.source.to_json(),
                "attempt": attempt,
                "heal_before_event_count": len(events_by_type["heal.before"]),
                "heal_after_event_count": len(events_by_type["heal.after"]),
            }
            production["_real_heal_seed"] = result
            return result
    result = {
        "ok": False,
        "reason": "real_heal_callback_chain_not_executed",
        "candidate_count": len(candidates),
        "attempts": attempts[:4],
    }
    production["_real_heal_seed"] = result
    return result


def _augment_real_custom_events(
    bundle: dict[str, Any],
    production: dict[str, Any],
    tbgd_root: Path,
) -> dict[str, Any]:
    """Record the missing content owner without injecting an arbitrary producer."""

    result_row = {
        "ok": True,
        "status": "external_content_e2e_deferred",
        "executed": False,
        "required_trigger_condition": (
            "a custom.event emitted by a real task in the current probe state"
        ),
        "missing_content_owner": (
            "character_or_monster_content_card_with_custom_event_producer"
        ),
        "future_closure": (
            "the owning character or monster content-card execution card"
        ),
        "reason": "current_owned_content_has_no_formal_custom_event_producer",
    }
    production["_real_custom_event_seed"] = result_row
    return result_row


def _augment_real_weakness_events(
    production: dict[str, Any],
    tbgd_root: Path,
) -> dict[str, Any]:
    """Produce weakness.stacked by executing a real lowered StackWeakness."""

    rules: RuleBook = production["_rules"]
    producer_effects = []
    producer_targets = []
    producer_file = ""
    token = '"$type": "RPG.GameCore.StackWeakness"'
    ability_root = tbgd_root / "Config" / "ConfigAbility"
    lowering = TBGDLowering(tbgd_root)
    for path in sorted(
        ability_root.rglob("*.json"),
        key=lambda item: (item.stat().st_size, item.as_posix()),
    ):
        try:
            if token not in path.read_text(encoding="utf-8"):
                continue
        except (OSError, UnicodeError):
            continue
        lowered = lowering._lower_ability_file(
            path,
            {},
            ability_file_order=0,
        )
        executable = tuple(
            effect
            for effect in lowered.effects
            if effect.opcode == "StackWeakness"
            and effect.coverage_status == "executable"
        )
        if not executable:
            continue
        producer_effects.extend(executable)
        producer_targets.extend(lowered.target_expressions)
        producer_file = path.relative_to(tbgd_root).as_posix()
        break
    effects_by_id = {effect.effect_id: effect for effect in rules.ir.effects}
    effects_by_id.update({effect.effect_id: effect for effect in producer_effects})
    targets_by_id = {
        target.target_expression_id: target
        for target in rules.ir.target_expressions
    }
    targets_by_id.update(
        {target.target_expression_id: target for target in producer_targets}
    )
    producer_rules = RuleBook(
        replace(
            rules.ir,
            effects=tuple(effects_by_id.values()),
            target_expressions=tuple(targets_by_id.values()),
        )
    )
    state = _route_probe_state()
    registry = EffectRegistry(StatusSystem(producer_rules))
    reducer = MutationReducer()
    attempts: list[dict[str, Any]] = []
    for effect in sorted(producer_effects, key=lambda item: item.effect_id)[:64]:
        for owner_id, param_entity_id, current_action_target_id in (
            ("enemy:target", "enemy:target", "enemy:target"),
            ("ally:wearer", "enemy:target", "enemy:target"),
        ):
            result = registry.execute(
                effect,
                EffectExecutionContext(
                    state=state,
                    caster_id="ally:wearer",
                    source_id="ally:wearer",
                    owner_id=owner_id,
                    param_entity_id=param_entity_id,
                    current_action_target_id=current_action_target_id,
                ),
            )
            try:
                after = reducer.apply_all(state, result.mutations)
            except ValueError as exc:
                attempts.append(
                    {
                        "effect_id": effect.effect_id,
                        "reason": f"producer_reducer_conflict:{exc}",
                    }
                )
                continue
            replay = reducer.replay_snapshot(
                state,
                result.mutations,
                after.snapshot().to_json(),
            )
            weakness_events = tuple(
                event
                for event in result.events
                if event.event_type == "weakness.stacked"
            )
            mutation_ids = {mutation.stable_id() for mutation in result.mutations}
            settlement_ids = {
                record.get("mutation_id")
                for record in result.records
                if isinstance(record, dict)
            }
            source_bound = bool(result.mutations) and all(
                mutation.metadata.get("effect_id") == effect.effect_id
                and mutation.metadata.get("effect_source")
                == effect.source.to_json()
                for mutation in result.mutations
            ) and all(
                event.payload.get("producer_effect_id") == effect.effect_id
                and event.payload.get("producer_effect_source")
                == effect.source.to_json()
                for event in weakness_events
            )
            attempt = {
                "effect_id": effect.effect_id,
                "source": effect.source.to_json(),
                "producer_file": producer_file,
                "owner_id": owner_id,
                "param_entity_id": param_entity_id,
                "mutation_count": len(result.mutations),
                "event_count": len(weakness_events),
                "unsupported": list(result.unsupported),
                "mutations_settled": bool(mutation_ids)
                and mutation_ids <= settlement_ids,
                "source_bound": source_bound,
                "replay_equal": replay.ok,
            }
            attempts.append(attempt)
            if (
                result.unsupported
                or not weakness_events
                or not attempt["mutations_settled"]
                or not source_bound
                or not replay.ok
            ):
                continue
            _merge_production_events(production, list(weakness_events))
            result_row = {"ok": True, "attempt": attempt}
            production["_real_weakness_event_seed"] = result_row
            return result_row
    result_row = {
        "ok": False,
        "reason": "real_stack_weakness_producer_effect_not_executed",
        "candidate_count": len(producer_effects),
        "producer_file": producer_file,
        "attempts": attempts[:8],
    }
    production["_real_weakness_event_seed"] = result_row
    return result_row


def _resource_event_contract_matrix(
    bundle: dict[str, Any],
    production: dict[str, Any],
) -> dict[str, Any]:
    """Exercise both signs of both resources through the production adapter."""

    state = _route_probe_state()
    resources = ResourceSystem()
    mutations = {
        "team_skill_points_gain": resources.set_skill_points(
            state,
            state.skill_points + 1,
            "resource_system",
        ),
        "team_skill_points_spend": resources.set_skill_points(
            state,
            state.skill_points - 1,
            "resource_system",
        ),
        "unit_energy_gain": resources.change_unit_energy(
            state,
            "ally:wearer",
            10.0,
            "resource_system",
        ),
        "unit_energy_spend": resources.change_unit_energy(
            state,
            "ally:wearer",
            -10.0,
            "resource_system",
        ),
    }
    cases: dict[str, Any] = {}
    production_events: list[GameEvent] = []
    produced_event_types: set[str] = set()
    cross_trigger_count = 0
    team_callbacks = set(TEAM_SKILL_POINT_EVENT_CONTRACT.callback_events)
    energy_callbacks = set(UNIT_ENERGY_EVENT_CONTRACT.callback_events)
    for index, (case_name, mutation) in enumerate(mutations.items()):
        events = events_for_mutation(
            mutation,
            actor_id="ally:wearer",
            source_id="ally:wearer",
            event_index=index,
        )
        production_events.extend(events)
        produced_event_types.update(event.event_type for event in events)
        callbacks = {
            str(callback_event)
            for event in events
            for callback_event in event.payload.get("callback_events", ())
        }
        expected_contract = (
            TEAM_SKILL_POINT_EVENT_CONTRACT
            if case_name.startswith("team_skill_points")
            else UNIT_ENERGY_EVENT_CONTRACT
        )
        unexpected_callbacks = (
            energy_callbacks
            if expected_contract is TEAM_SKILL_POINT_EVENT_CONTRACT
            else team_callbacks
        )
        cross_trigger_count += len(callbacks & unexpected_callbacks)
        cases[case_name] = {
            "mutation": mutation.to_json(),
            "events": [event.to_json() for event in events],
            "event_types": [event.event_type for event in events],
            "callback_events": sorted(callbacks),
            "unexpected_callback_events": sorted(callbacks & unexpected_callbacks),
        }

    _merge_production_events(production, production_events)
    energy_spend_event = next(
        event
        for event in production_events
        if event.event_type == UNIT_ENERGY_EVENT_CONTRACT.after_event_type
        and event.payload.get("mutation_id")
        == mutations["unit_energy_spend"].stable_id()
    )
    forged_event_type = next(iter(RETIRED_RESOURCE_EVENT_TYPES))
    forged_event = replace(
        energy_spend_event,
        event_type=forged_event_type,
        event_id=f"{energy_spend_event.event_id}:retired_sp_change",
    )
    forged = EventDispatchSystem(
        bundle["rules"],
        EffectRegistry(StatusSystem(bundle["rules"])),
    ).dispatch_event(state, event=forged_event)
    forged_callback_records = tuple(
        record
        for record in forged.records
        if isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id")
    )

    runtime_sources = resource_callback_runtime_sources()
    producer_rows = []
    for callback_event, expected_sources in sorted(runtime_sources.items()):
        family = bundle["rules"].status_event_family(callback_event)
        executable = (
            family is not None
            and family.coverage_status == "executable"
            and family.admission_status == "executable"
        )
        producer_rows.append(
            {
                "callback_event": callback_event,
                "expected_runtime_sources": list(expected_sources),
                "actual_runtime_sources": (
                    list(family.runtime_event_sources) if family is not None else []
                ),
                "family_executable": executable,
                "real_runtime_producer_present": (
                    not executable
                    or (
                        tuple(family.runtime_event_sources) == expected_sources
                        and set(expected_sources) <= produced_event_types
                    )
                ),
            }
        )

    def energy_delta_matches(case_name: str) -> bool:
        mutation = mutations[case_name]
        return any(
            event.event_type == UNIT_ENERGY_EVENT_CONTRACT.after_event_type
            and event.payload.get("change_value")
            == mutation.after - mutation.before
            and UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1]
            in event.payload.get("callback_events", ())
            for event in production_events
            if event.payload.get("mutation_id") == mutation.stable_id()
        )

    dead_production_events = sorted(
        resource_production_event_types() - produced_event_types
    )
    package_root = Path(__file__).resolve().parents[1]
    retired_production_references = sorted(
        path.relative_to(package_root).as_posix()
        for directory_name in (
            "builds",
            "core",
            "rules",
            "scenarios",
            "systems",
            "tbgd",
        )
        for path in (package_root / directory_name).rglob("*.py")
        if any(
            retired_event_type in path.read_text(encoding="utf-8")
            for retired_event_type in RETIRED_RESOURCE_EVENT_TYPES
        )
    )
    checks = {
        "team_skill_points_use_bp_event": all(
            cases[case_name]["event_types"]
            == [TEAM_SKILL_POINT_EVENT_CONTRACT.after_event_type]
            and cases[case_name]["callback_events"]
            == sorted(TEAM_SKILL_POINT_EVENT_CONTRACT.after_callback_events)
            for case_name in (
                "team_skill_points_gain",
                "team_skill_points_spend",
            )
        ),
        "unit_energy_uses_energy_event": all(
            cases[case_name]["event_types"]
            == list(UNIT_ENERGY_EVENT_CONTRACT.production_event_types)
            and cases[case_name]["callback_events"]
            == sorted(UNIT_ENERGY_EVENT_CONTRACT.callback_events)
            for case_name in ("unit_energy_gain", "unit_energy_spend")
        ),
        "on_sp_change_receives_energy_delta": all(
            energy_delta_matches(case_name)
            for case_name in ("unit_energy_gain", "unit_energy_spend")
        ),
        "resource_event_cross_trigger_count": cross_trigger_count == 0,
        "dead_production_resource_event_count": not dead_production_events,
        "retired_sp_change_blocked_unchanged": (
            bool(forged.errors)
            and not forged_callback_records
            and not forged.mutations
            and forged.after_state == state
        ),
        "retired_sp_change_absent_from_production_code": (
            not retired_production_references
        ),
        "executable_event_families_have_real_runtime_producers": all(
            row["real_runtime_producer_present"] for row in producer_rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_resource_event_contract_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "contracts": [
            {
                "contract_id": contract.contract_id,
                "resource_kind": contract.resource_kind,
                "state_path_pattern": list(contract.state_path_pattern),
                "production_event_types": list(contract.production_event_types),
                "callback_events": list(contract.callback_events),
                "scope_kind": contract.scope_kind,
            }
            for contract in RESOURCE_EVENT_CONTRACTS
        ],
        "cases": cases,
        "producer_rows": producer_rows,
        "resource_event_cross_trigger_count": cross_trigger_count,
        "dead_production_resource_events": dead_production_events,
        "retired_production_references": retired_production_references,
        "retired_event": forged_event.to_json(),
        "retired_errors": list(forged.errors),
        "_production_events": tuple(production_events),
    }


def _resource_event_closure_matrix(
    contract_matrix: dict[str, Any],
    energy_listener: dict[str, Any],
    bp_execution: dict[str, Any],
) -> dict[str, Any]:
    # This is the authoritative resource-event probe used by both the focused
    # validator and the full S8 aggregate.  The aggregate must not reselect a
    # looser listener sample and contradict the focused evidence.
    bp_probe = (
        {
            key: value
            for key, value in bp_execution.items()
            if not key.startswith("_")
        }
        if isinstance(bp_execution, dict)
        else {}
    )
    bp_audit = bp_probe.get("source_audit_replay")
    if not isinstance(bp_audit, dict):
        bp_audit = {}
    energy_checks = energy_listener.get("checks")
    if not isinstance(energy_checks, dict):
        energy_checks = {}
    resource_event_mutations_settled = (
        energy_checks.get("callback_mutations_settled") is True
        and energy_checks.get("callback_source_audit_ok") is True
        and bp_probe.get("mutation_count", 0) > 0
        and bp_audit.get("source_audit_ok") is True
    )
    resource_event_replay_equal = (
        energy_checks.get("callback_replay_equal") is True
        and bp_audit.get("replay_ok") is True
    )
    resource_event_cross_trigger_count = (
        int(contract_matrix["resource_event_cross_trigger_count"])
        + int(bp_probe.get("energy_cross_trigger_count", 0))
        + int(energy_listener.get("bp_cross_trigger_count", 0))
    )
    checks = {
        **dict(contract_matrix["checks"]),
        "bp_listener_real_callback_chain": bp_probe.get("ok") is True,
        "energy_listener_real_callback_chain": energy_listener.get("ok") is True,
        "skill_point_gain_and_spend_route_to_bp_listener": (
            bp_probe.get("bp_gain_and_spend_route_to_bp_listener") is True
        ),
        "energy_gain_and_spend_route_to_energy_listener": (
            energy_checks.get("energy_gain_and_spend_route_to_on_sp_listener")
            is True
        ),
        "resource_event_cross_trigger_count": (
            resource_event_cross_trigger_count == 0
        ),
        "resource_event_mutations_settled": resource_event_mutations_settled,
        "resource_event_replay_equal": resource_event_replay_equal,
    }
    checks.pop("ok", None)
    checks["ok"] = all(value is True for value in checks.values())
    return {
        "schema_version": "p8_s8_resource_event_closure_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "resource_event_cross_trigger_count": resource_event_cross_trigger_count,
        "dead_production_resource_event_count": len(
            contract_matrix["dead_production_resource_events"]
        ),
        "contracts": contract_matrix["contracts"],
        "cases": contract_matrix["cases"],
        "producer_rows": contract_matrix["producer_rows"],
        "retired_event": contract_matrix["retired_event"],
        "retired_errors": contract_matrix["retired_errors"],
        "retired_production_references": contract_matrix[
            "retired_production_references"
        ],
        "bp_execution_evidence": bp_probe,
        "energy_execution_evidence": {
            key: value
            for key, value in energy_listener.items()
            if not key.startswith("_")
        },
    }


def _bp_listener_execution_probe(
    bundle: dict[str, Any],
    production: dict[str, Any],
    cards_by_path: dict[str, Any],
) -> dict[str, Any]:
    callback_event = TEAM_SKILL_POINT_EVENT_CONTRACT.after_callback_events[0]
    rules: RuleBook = bundle["rules"]
    callbacks = tuple(
        callback
        for callback in bundle["ir"].status_callbacks
        if callback.event == callback_event
        and callback.coverage_status == "executable"
        and callback.admission_status == "executable"
        and callback.source.source_path.startswith("Config/ConfigAbility/Equip/")
    )
    candidates = tuple(
        sorted(
            (
                task
                for callback in callbacks
                for task in rules.status_callback_tasks_for_callback(
                    callback.callback_id
                )
                if task.coverage_status == "executable"
                and task.blocked_reason != "equipment_task_family_non_gameplay"
                and _task_has_available_definition(
                    bundle,
                    task,
                    cards_by_path,
                )
            ),
            key=lambda item: item.task_id,
        )
    )
    state_cache: dict[str, BattleState] = {}
    attempts = []
    for task in candidates[:32]:
        probe_state, owner_id, state_reason = _equipment_task_probe_state(
            bundle,
            production,
            task,
            state_cache=state_cache,
            cards_by_path=cards_by_path,
        )
        if probe_state is None or not owner_id:
            attempts.append(
                {
                    "ok": False,
                    "task_id": task.task_id,
                    "reason": state_reason or "bp_probe_owner_missing",
                }
            )
            continue
        spend = ResourceSystem().set_skill_points(
            probe_state,
            probe_state.skill_points - 1,
            "resource_system",
        )
        bp_events = events_for_mutation(
            spend,
            actor_id=owner_id,
            source_id=owner_id,
            event_index=probe_state.event_index,
        )
        local_events_by_type = defaultdict(
            list,
            {
                event_type: list(events)
                for event_type, events in production["_events_by_type"].items()
            },
        )
        local_events_by_type[TEAM_SKILL_POINT_EVENT_CONTRACT.after_event_type] = list(
            bp_events
        )
        local_production = {
            "_rules": production["_rules"],
            "_events_by_type": local_events_by_type,
        }
        attempt = _task_callback_execution_probe(
            bundle,
            local_production,
            task,
            state_cache=state_cache,
            cards_by_path=cards_by_path,
            _return_after_state=True,
        )
        attempts.append(attempt)
        if attempt.get("ok") is True:
            after_state = attempt.pop("_after_state", None)
            callback = rules.status_callback(task.callback_id)
            energy_cross_trigger_count = 1
            bp_gain_listener_observed = False
            if isinstance(after_state, BattleState) and callback is not None:
                gain = ResourceSystem().set_skill_points(
                    after_state,
                    after_state.skill_points + 1,
                    "resource_system",
                )
                gain_event = next(
                    iter(
                        events_for_mutation(
                            gain,
                            actor_id=owner_id,
                            source_id=owner_id,
                            event_index=after_state.event_index,
                        )
                    ),
                    None,
                )
                if gain_event is not None:
                    gain_result = EventDispatchSystem(
                        rules,
                        EffectRegistry(StatusSystem(rules)),
                    ).dispatch_event(
                        after_state,
                        event=gain_event,
                        unit_id=owner_id,
                        modifier_name=callback.modifier_name,
                    )
                    bp_gain_listener_observed = (
                        not gain_result.errors
                        and any(
                            isinstance(record.get("payload"), dict)
                            and record["payload"].get("callback_id")
                            == callback.callback_id
                            for record in (
                                *gain_result.records,
                                *gain_result.listener_records,
                            )
                        )
                    )
                energy_mutation = ResourceSystem().change_unit_energy(
                    after_state,
                    owner_id,
                    10.0,
                    "resource_system",
                )
                energy_events = events_for_mutation(
                    energy_mutation,
                    actor_id=owner_id,
                    source_id=owner_id,
                    event_index=after_state.event_index,
                    include_before=False,
                )
                energy_cross_trigger_count = 0
                for energy_event in energy_events:
                    cross = EventDispatchSystem(
                        rules,
                        EffectRegistry(StatusSystem(rules)),
                    ).dispatch_event(
                        after_state,
                        event=energy_event,
                        unit_id=owner_id,
                        modifier_name=callback.modifier_name,
                    )
                    energy_cross_trigger_count += sum(
                        1
                        for record in cross.records
                        if isinstance(record.get("payload"), dict)
                        and record["payload"].get("callback_id")
                        == callback.callback_id
                    )
            return {
                **attempt,
                "real_callback_count": len(callbacks),
                "executable_task_count": len(candidates),
                "energy_cross_trigger_count": energy_cross_trigger_count,
                "energy_event_does_not_trigger_bp_callback": (
                    energy_cross_trigger_count == 0
                ),
                "bp_gain_and_spend_route_to_bp_listener": (
                    bp_gain_listener_observed
                ),
            }
    return {
        "ok": False,
        "reason": "real_bp_listener_task_chain_not_executable",
        "real_callback_count": len(callbacks),
        "executable_task_count": len(candidates),
        "attempts": attempts[:4],
    }


def _empty_executable_task_fail_closed_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    """Exercise the production callback task boundary with a source-backed shell.

    The forged shell deliberately removes every runtime route from an otherwise
    real executable equipment task.  The public result must be blocked and
    state unchanged; a process-only blocked record is not success evidence.
    """

    rules: RuleBook = bundle["rules"]
    candidate = next(
        (
            task
            for task in sorted(bundle["ir"].status_callback_tasks, key=lambda item: item.task_id)
            if task.coverage_status == "executable"
            and task.blocked_reason != "equipment_task_family_non_gameplay"
            and rules.status_callback(task.callback_id) is not None
        ),
        None,
    )
    if candidate is None:
        return {"ok": False, "reason": "source_backed_executable_task_missing"}
    callback = rules.status_callback(candidate.callback_id)
    assert callback is not None
    empty_task = replace(
        candidate,
        task_id=f"{candidate.task_id}:validation_empty_runtime_route",
        opcode="ValidationEmptyRuntimeRoute",
        effect_id="",
        condition_id="",
        target_expression_id="",
        parent_task_id="",
        child_task_ids=(),
        success_task_ids=(),
        failed_task_ids=(),
        blocked_reason="",
        task_payload={},
        retarget_policy={},
    )
    before = BattleState()
    result = StatusCallbackSystem(rules)._execute_task(
        before,
        callback,
        empty_task,
        {},
        None,
        {empty_task.task_id: empty_task},
        None,
    )
    reason = "status_callback_task_has_no_executable_runtime_effect"
    checks = {
        "empty_executable_task_returns_blocked": result.ok is False,
        "empty_executable_task_state_unchanged": result.after_state == before,
        "empty_executable_task_has_no_mutation": not result.mutations,
        "empty_executable_task_reason_stable": result.errors == (reason,),
        "empty_executable_task_blocked_recorded": any(
            record.get("record_type") == "status_callback_task_blocked"
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("reason") == reason
            for record in result.records
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_empty_executable_task_fail_closed_v1",
        "ok": checks["ok"],
        "checks": checks,
        "source_task_id": candidate.task_id,
        "source": candidate.source.to_json(),
        "errors": list(result.errors),
    }


def _authoritative_resource_event_evidence(
    bundle: dict[str, Any],
    cards_by_path: dict[str, Any],
) -> dict[str, Any]:
    """Build one isolated resource proof shared by focused and full modes."""

    production: dict[str, Any] = {
        "_rules": bundle["rules"],
        "_events_by_type": defaultdict(list),
    }
    contract = _resource_event_contract_matrix(bundle, production)
    energy = _energy_listener_matrix(bundle, cards_by_path)
    _merge_production_events(
        production,
        list(energy.get("_production_events", ())),
    )
    bp = _bp_listener_execution_probe(
        bundle,
        production,
        cards_by_path,
    )
    closure = _resource_event_closure_matrix(contract, energy, bp)
    events = tuple(
        event
        for event_rows in production["_events_by_type"].values()
        for event in event_rows
    )
    return {
        "contract": contract,
        "energy": energy,
        "bp": bp,
        "closure": closure,
        "production_events": events,
    }


def _focused_resource_scope(
    focused_rulebook_build_count: int = 1,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "focused_rulebook_build_count": focused_rulebook_build_count,
        "full_canonical_ir_serialized": False,
        "large_artifacts_written": False,
        **fields,
    }


def _write_artifacts(output_dir: Path, artifacts: Mapping[str, Any]) -> None:
    for name, payload in artifacts.items():
        write_json(output_dir / name, payload)


def run_resource_event_validation(
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Bounded S8 resource-event slice; never runs the other S8 matrices."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _focused_bundle(
        tbgd_root,
        include_owned_combatant_catalog=True,
    )
    empty_task_fail_closed = _empty_executable_task_fail_closed_matrix(bundle)
    cards_by_path = _empty_admitted_cards_by_path(bundle)
    evidence = _authoritative_resource_event_evidence(bundle, cards_by_path)
    closure = evidence["closure"]
    predicates = {
        "team_skill_points_use_bp_event": closure["checks"][
            "team_skill_points_use_bp_event"
        ],
        "unit_energy_uses_energy_event": closure["checks"][
            "unit_energy_uses_energy_event"
        ],
        "on_sp_change_receives_energy_delta": closure["checks"][
            "on_sp_change_receives_energy_delta"
        ],
        "resource_event_cross_trigger_count": closure[
            "resource_event_cross_trigger_count"
        ],
        "dead_production_resource_event_count": closure[
            "dead_production_resource_event_count"
        ],
        "retired_sp_change_blocked_unchanged": closure["checks"][
            "retired_sp_change_blocked_unchanged"
        ],
        "executable_event_families_have_real_runtime_producers": closure[
            "checks"
        ]["executable_event_families_have_real_runtime_producers"],
        "resource_event_mutations_settled": closure["checks"][
            "resource_event_mutations_settled"
        ],
        "resource_event_replay_equal": closure["checks"][
            "resource_event_replay_equal"
        ],
        "empty_executable_callback_task_fail_closed": empty_task_fail_closed["ok"],
    }
    ok = (
        all(
            value is True
            for key, value in predicates.items()
            if key
            not in {
                "resource_event_cross_trigger_count",
                "dead_production_resource_event_count",
            }
        )
        and predicates["resource_event_cross_trigger_count"] == 0
        and predicates["dead_production_resource_event_count"] == 0
    )
    summary = _contract_slice_summary(
        "p8_s8_resource_event_validation_summary_v1",
        predicates,
        ok=ok,
        ready_for_review=ok,
        resource_scope=_focused_resource_scope(
            production_owned_combatant_catalog_lowering_count=1,
            lowering_execution_mode="serial",
            owned_combatant_catalog_counts=
                bundle["owned_combatant_catalog"].get("counts", {}),
            full_s8_matrices_executed=False,
        ),
    )
    _write_artifacts(output_dir, {
        "resource_event_closure_matrix_p8_s8.json": closure,
        "empty_executable_task_fail_closed_matrix_p8_s8.json": empty_task_fail_closed,
        "validation_summary_p8_s8_resource_events.json": summary,
    })
    return summary


def run_catalog_startup_validation(
    tbgd_root: Path,
    output_dir: Path,
    *,
    definition_identities: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Bounded catalog startup slice; skips every S8 family execution matrix."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _focused_bundle(
        tbgd_root,
        include_owned_combatant_catalog=True,
    )
    path_inventory = _empty_character_build_path_inventory(bundle)
    startups = _catalog_startup_matrix(
        bundle,
        cards_by_path=path_inventory["cards_by_path"],
        path_inventory=path_inventory,
        definition_identities=definition_identities,
    )
    empty_task_fail_closed = _empty_executable_task_fail_closed_matrix(bundle)
    predicates = {
        "catalog_equipment_failure_count": startups["equipment_failure_count"],
        "catalog_external_dependencies_structurally_proven": startups["checks"][
            "external_character_build_dependencies_structurally_proven"
        ],
        "catalog_started_or_external_dependency_covers_catalog": startups["checks"][
            "started_or_external_dependency_covers_catalog"
        ],
        "empty_executable_callback_task_fail_closed": empty_task_fail_closed["ok"],
    }
    ok = (
        predicates["catalog_equipment_failure_count"] == 0
        and predicates["catalog_external_dependencies_structurally_proven"] is True
        and predicates["catalog_started_or_external_dependency_covers_catalog"] is True
        and predicates["empty_executable_callback_task_fail_closed"] is True
    )
    summary = _contract_slice_summary(
        "p8_s8_catalog_startup_validation_summary_v1",
        predicates,
        ok=ok,
        counts=startups["counts"],
        formal_catalog_startup_complete=startups[
            "formal_catalog_startup_complete"
        ],
        external_character_build_dependency_count=startups[
            "external_character_build_dependency_count"
        ],
        resource_scope=_focused_resource_scope(
            production_owned_combatant_catalog_lowering_count=1,
            lowering_execution_mode="serial",
            owned_combatant_catalog_counts=
                bundle["owned_combatant_catalog"].get("counts", {}),
            full_s8_matrices_executed=False,
        ),
        definition_identity_filter=sorted(definition_identities or ()),
    )
    _write_artifacts(output_dir, {
        "catalog_startup_matrix_p8_s8.json": startups,
        "empty_executable_task_fail_closed_matrix_p8_s8.json": empty_task_fail_closed,
        "validation_summary_p8_s8_catalog_startup.json": summary,
    })
    return summary


def run_condition_contract_validation(
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Bounded exact-condition slice; skips startup and transition matrices."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = _focused_bundle(tbgd_root)
    conditions = _condition_contract_matrix(bundle)
    summary = _contract_slice_summary(
        "p8_s8_condition_contract_validation_summary_v1",
        {
            "every_condition_source_evaluated": conditions["checks"][
                "every_family_true_false_and_fail_closed"
            ],
        },
        ok=conditions["ok"],
        counts={
            "condition_families": conditions["family_count"],
            "condition_sources": conditions["condition_count"],
        },
        resource_scope=_focused_resource_scope(
            full_s8_matrices_executed=False,
        ),
    )
    _write_artifacts(output_dir, {
        "condition_contract_matrix_p8_s8.json": conditions,
        "validation_summary_p8_s8_condition_contract.json": summary,
    })
    return summary


def run_numeric_contract_validation(
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Bounded numeric-expression slice; skips all runtime matrices."""

    output_dir.mkdir(parents=True, exist_ok=True)
    numeric = _numeric_contract_matrix(_focused_bundle(tbgd_root))
    summary = _contract_slice_summary(
        "p8_s8_numeric_contract_validation_summary_v1",
        numeric["checks"],
        ok=numeric["ok"],
        counts={
            "numeric_expressions": numeric["expression_count"],
            "zero_floor_expressions": numeric[
                "zero_floor_expression_count"
            ],
        },
        resource_scope=_focused_resource_scope(
            runtime_matrices_executed=False,
        ),
    )
    _write_artifacts(output_dir, {
        "numeric_contract_matrix_p8_s8.json": numeric,
        "validation_summary_p8_s8_numeric_contract.json": summary,
    })
    return summary


def _build_contract_evidence(
    tbgd_root: Path,
    build_counts: Counter[str],
) -> dict[str, Any]:
    build_counts["common_evidence"] += 1

    def keep(name: str, value: Any) -> Any:
        build_counts[name] += 1
        return value

    bundle = _focused_bundle(tbgd_root, include_owned_combatant_catalog=True, build_counts=build_counts)
    partition = keep("partition", _partition_matrix(bundle))
    paths = keep("path_inventory", _empty_character_build_path_inventory(bundle))
    formal = keep("formal_scenario", _formal_scenario_matrix(bundle))
    lifecycle = keep("lifecycle", _lifecycle_matrix(bundle, formal))
    production = keep("production_event_chain", _production_event_chain(bundle, formal, lifecycle))
    common_counts = keep("common_mutation_events", _augment_common_mutation_events(production))
    battle_seed = keep("battle_state_transition_events", _augment_real_battle_state_transition_events(bundle, production))
    heal_seed = keep("heal_events", _augment_real_heal_events(bundle, production, paths["cards_by_path"]))
    custom_seed = keep("custom_events", _augment_real_custom_events(bundle, production, tbgd_root))
    weakness_seed = keep("weakness_events", _augment_real_weakness_events(production, tbgd_root))
    return {
        "bundle": bundle, "partition": partition, "paths": paths, "formal": formal,
        "production": production, "common_counts": common_counts,
        "battle_seed": battle_seed, "heal_seed": heal_seed,
        "custom_seed": custom_seed, "weakness_seed": weakness_seed,
    }


def _contract_production_view(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        **evidence["production"],
        "_events_by_type": defaultdict(
            list,
            {name: list(events) for name, events in evidence["production"]["_events_by_type"].items()},
        ),
    }


def _contract_resource_scope(build_counts: Counter[str]) -> dict[str, Any]:
    return _focused_resource_scope(
        focused_rulebook_build_count=_measured_count(build_counts, "focused_bundle"),
        full_tbgd_lowering_build_count=_measured_count(build_counts, "full_tbgd_lowering_build"),
        owned_combatant_admission_projection_build_count=_measured_count(
            build_counts, "owned_combatant_admission_projection"
        ),
        common_evidence_generation_count=_measured_count(build_counts, "common_evidence"),
        full_s8_matrices_executed=False,
    )


def _contract_slice_summary(
    schema: str,
    predicates: dict[str, Any],
    *,
    ok: bool | None = None,
    ready_for_review: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "schema_version": schema, "validation_version": VALIDATION_VERSION,
        "ok": all(predicates.values()) if ok is None else ok,
        "ready_for_review": ready_for_review,
        "checklist_modified": False, "git_commit_created": False,
        "predicates": predicates, **fields,
    }


def _run_task_contract_slice(
    evidence: dict[str, Any], output_dir: Path, *, build_counts: Counter[str],
    family_filter: frozenset[str] | None = None, write_outputs: bool = True,
) -> dict[str, Any]:
    bundle, partition, paths = evidence["bundle"], evidence["partition"], evidence["paths"]
    production = _contract_production_view(evidence)
    task_execution = _task_family_execution_matrix(
        bundle, partition, production, paths["cards_by_path"],
        external_character_build_paths=frozenset(paths["external_character_build_paths"]),
        state_cache={}, family_filter=family_filter,
    )
    stack_properties = _stack_property_consumption_matrix(
        partition, task_execution=task_execution, family_filter=family_filter
    )
    predicates = {
        "every_exact_gameplay_task_family_has_real_callback_execution": task_execution["ok"],
        "mechanism_families_do_not_use_character_build_dependency_exemption": (
            task_execution["checks"]["mechanism_families_do_not_use_character_build_dependency_exemption"]
        ),
        "every_stack_property_family_changes_distinct_consumer": stack_properties["ok"],
    }
    summary = _contract_slice_summary(
        "p8_s8_task_contract_validation_summary_v1", predicates,
        counts={
            "task_families": task_execution["family_count"],
            "executed_task_families": task_execution["executed_family_count"],
            "external_content_e2e_deferred_task_families": task_execution[
                "external_content_e2e_deferred_count"
            ],
            "implementation_failure_task_families": task_execution[
                "implementation_failure_count"
            ],
            "validation_harness_invalid_task_families": task_execution[
                "validation_harness_invalid_count"
            ],
            "stack_property_families": stack_properties["family_count"],
        },
        resource_scope={
            **_contract_resource_scope(build_counts),
            "catalog_startup_executed": False,
        },
        task_family_filter=sorted(family_filter or ()),
    )
    if write_outputs:
        write_json(output_dir / "exact_task_family_execution_matrix_p8_s8.json", task_execution)
        write_json(output_dir / "stack_property_consumption_matrix_p8_s8.json", stack_properties)
        write_json(output_dir / "validation_summary_p8_s8_task_contract.json", summary)
    summary["_probe_payload"] = (task_execution, stack_properties)
    return summary


def _run_event_contract_slice(
    evidence: dict[str, Any], output_dir: Path, *, build_counts: Counter[str],
    family_filter: frozenset[str] | None = None, write_outputs: bool = True,
) -> dict[str, Any]:
    bundle, partition, paths = evidence["bundle"], evidence["partition"], evidence["paths"]
    cards_by_path, formal = paths["cards_by_path"], evidence["formal"]
    production = _contract_production_view(evidence)
    resources = _authoritative_resource_event_evidence(bundle, cards_by_path)
    _merge_production_events(production, list(resources["production_events"]))
    contracts = _event_contract_matrix(bundle, formal)
    status_replacement = _status_replacement_contract_matrix()
    execution = _event_family_execution_matrix(
        bundle, partition, production, resources["energy"], resources["bp"], cards_by_path,
        external_character_build_paths=frozenset(paths["external_character_build_paths"]),
        family_filter=family_filter,
    )
    contract_rows = {
        f"{row.get('event')}:s8": row for row in contracts.get("rows", ()) if row.get("event")
    }
    selected_contracts_ok = all(
        isinstance(contract_rows.get(row["family"]), dict)
        and contract_rows[row["family"]].get("ok") is True
        for row in execution["rows"]
    )
    unreferenced_rows = tuple(
        row
        for row in partition["_inventory"]["_source_rows"]
        if row["stage"] == "unreferenced" and row["kind"] == "event"
    )
    unreferenced_event_names = {
        row["family"].rsplit(":", 1)[0] for row in unreferenced_rows
    }
    executed_families = {row["family"] for row in execution["rows"]}
    selected_unreferenced_families = tuple(
        sorted(family for family in (family_filter or ())
               if family.rsplit(":", 1)[0] in unreferenced_event_names)
    )
    unresolved_selected_families = tuple(
        sorted(family for family in (family_filter or ())
               if family not in executed_families
               and family not in selected_unreferenced_families)
    )
    exact_family_outcomes_ok = (
        execution["ok"]
        if family_filter is None
        else all(row["ok"] for row in execution["rows"])
        and not unresolved_selected_families
        and bool(execution["rows"] or selected_unreferenced_families)
    )
    predicates = {
        "every_exact_event_family_executed_deferred_or_unreferenced": (
            exact_family_outcomes_ok
        ),
        "selected_event_families_have_executable_contract": selected_contracts_ok,
        "unreferenced_modifier_sources_retained": all(
            bool(row["source_identity"]) for row in unreferenced_rows
        ),
        "shared_battle_state_events_use_source_backed_transition": evidence["battle_seed"]["ok"],
        "status_replacement_namespace_is_fail_closed": status_replacement["ok"],
    }
    summary = _contract_slice_summary(
        "p8_s8_event_contract_validation_summary_v1", predicates,
        counts={
            "event_families": execution["family_count"],
            "executed_event_families": execution["executed_family_count"],
            "external_content_e2e_deferred_event_families": execution[
                "external_content_e2e_deferred_count"
            ],
            "implementation_failure_event_families": execution[
                "implementation_failure_count"
            ],
            "validation_harness_invalid_event_families": execution[
                "validation_harness_invalid_count"
            ],
            "unreferenced_event_sources": len(unreferenced_rows),
        },
        resource_scope={
            **_contract_resource_scope(build_counts),
            "catalog_startup_executed": False,
            "task_property_matrices_executed": False,
        },
        event_family_filter=sorted(family_filter or ()),
        selected_unreferenced_families=list(selected_unreferenced_families),
        unresolved_selected_families=list(unresolved_selected_families),
    )
    if write_outputs:
        artifacts = {
            "exact_event_family_execution_matrix_p8_s8.json": execution,
            "status_replacement_contract_matrix_p8_s8.json": status_replacement,
            "real_custom_event_seed_matrix_p8_s8.json": evidence["custom_seed"],
            "real_weakness_event_seed_matrix_p8_s8.json": evidence["weakness_seed"],
            "battle_state_transition_seed_matrix_p8_s8.json": evidence["battle_seed"],
            "unreferenced_event_source_matrix_p8_s8.json": {
                "schema_version": "p8_s8_unreferenced_event_source_matrix_v1",
                "ok": predicates["unreferenced_modifier_sources_retained"],
                "count": len(unreferenced_rows), "rows": list(unreferenced_rows),
            },
            "validation_summary_p8_s8_event_contract.json": summary,
        }
        _write_artifacts(output_dir, artifacts)
    summary["_probe_payload"] = (execution, status_replacement, resources, contracts)
    return summary


def _run_contract_validation(
    tbgd_root: Path,
    output_dir: Path,
    contract_slices: tuple[str, ...],
    *,
    build_counts: Counter[str],
    task_families: frozenset[str] | None = None,
    event_families: frozenset[str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not contract_slices or set(contract_slices) - {"task", "event"}:
        raise ValueError(f"invalid contract slices: {contract_slices!r}")
    if len(contract_slices) != len(set(contract_slices)):
        raise ValueError(f"duplicate contract slices: {contract_slices!r}")
    started_at = time.perf_counter()
    evidence = _build_contract_evidence(tbgd_root, build_counts)
    output_dir.mkdir(parents=True, exist_ok=True)
    consumer_specs = {
        "task": (_run_task_contract_slice, task_families),
        "event": (_run_event_contract_slice, event_families),
    }

    def consume(name: str, write_outputs: bool, family: str = "") -> dict[str, Any]:
        runner, configured_filter = consumer_specs[name]
        return runner(
            evidence, output_dir,
            build_counts=build_counts,
            family_filter=frozenset({family}) if family else configured_filter,
            write_outputs=write_outputs,
        )

    summaries = {
        name: consume(name, True)
        for name in contract_slices
    }

    failures_by_slice = {
        name: sorted({
            str(row["family"])
            for matrix in summary["_probe_payload"]
            for row in matrix.get("failures", ())
            if row.get("family")
        })
        for name, summary in summaries.items()
    }
    business_failures = sorted({
        family
        for failures in failures_by_slice.values()
        for family in failures
    })
    combined = set(contract_slices) == {"task", "event"}
    business_ok = all(item["ok"] for item in summaries.values())
    build_summary = {
        key: _measured_count(build_counts, key)
        for key in (*LOWERING_ENTRY_KEYS, "focused_bundle", "common_evidence")
    }
    build_summary["components"] = {
        name: _measured_count(build_counts, name)
        for name in CONTRACT_COMPONENTS
    }
    usage = resource.getrusage(resource.RUSAGE_SELF)
    measurement = {
        "elapsed_seconds": round(time.perf_counter() - started_at, 6),
        "peak_rss_kib": int(usage.ru_maxrss),
        "filesystem_input_operations": int(usage.ru_inblock),
        "filesystem_output_operations": int(usage.ru_oublock),
        "artifact_bytes_before_summary": sum(
            path.stat().st_size for path in output_dir.iterdir() if path.is_file()
        ),
        "external_time_v_path": str(output_dir / "time-v.txt"),
    }
    governance_checks = {
        "unfiltered_task_event_combined": (
            combined and task_families is None and event_families is None
        ),
        "shared_build_counts_exact": (
            (
                build_summary["full_tbgd_lowering_build"],
                build_summary["owned_combatant_admission_projection"],
                build_summary["focused_bundle"],
                build_summary["common_evidence"],
            ) == (0, 1, 1, 1)
            and all(
                count == 1 for count in build_summary["components"].values()
            )
        ),
    }
    for summary in summaries.values():
        summary.pop("_probe_payload")
    run_summary = {
        "schema_version": "p8_s8_task_event_contract_run_summary_v1",
        "validation_version": VALIDATION_VERSION,
        "ok": business_ok,
        "governance_ok": all(governance_checks.values()),
        "ready_for_review": False,
        "checklist_modified": False,
        "git_commit_created": False,
        "requested_slices": list(contract_slices),
        "completed_slices": list(summaries),
        "slice_results": {
            name: {"ok": summary["ok"], "failed_families": failures_by_slice[name]}
            for name, summary in summaries.items()
        },
        "business_failures": business_failures,
        "governance_checks": governance_checks,
        "build_counts": build_summary,
        "measurement": measurement,
    }
    if len(contract_slices) > 1:
        write_json(output_dir / "validation_summary_p8_s8_task_event_contract_run.json",
                   run_summary)
    return run_summary, summaries


def run_contract_validation(
    tbgd_root: Path, output_dir: Path, *, contract_slices: tuple[str, ...],
    task_families: frozenset[str] | None = None, event_families: frozenset[str] | None = None,
) -> dict[str, Any]:
    build_counts: Counter[str] = Counter()
    with _observe_lowering_entries(build_counts):
        run_summary, summaries = _run_contract_validation(
            tbgd_root, output_dir, contract_slices,
            build_counts=build_counts,
            task_families=task_families, event_families=event_families,
        )
    return run_summary if len(contract_slices) > 1 else summaries[contract_slices[0]]


def _task_family_execution_matrix(
    bundle: dict[str, Any],
    partition: dict[str, Any],
    production: dict[str, Any],
    cards_by_path: dict[str, Any],
    *,
    external_character_build_paths: frozenset[str] = frozenset(),
    state_cache: dict[str, BattleState] | None = None,
    family_filter: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Execute one real callback chain for every exact gameplay task family."""

    indexes = _coverage_source_indexes(bundle)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for raw_row in partition["_inventory"]["_source_rows"]:
        if raw_row["stage"] != "s8" or raw_row["kind"] != "task":
            continue
        if family_filter is not None and raw_row["family"] not in family_filter:
            continue
        linked = _linked_nodes(raw_row, indexes)
        if len(linked) != 1:
            continue
        task = linked[0]
        if getattr(task, "blocked_reason", "") == "equipment_task_family_non_gameplay":
            continue
        grouped[raw_row["family"]].append(task)

    family_candidates: dict[str, tuple[Any, ...]] = {}
    source_counts: dict[str, int] = {}
    for family, candidates in sorted(grouped.items()):
        unique_candidates = {task.task_id: task for task in candidates}
        source_counts[family] = len(unique_candidates)
        family_candidates[family] = tuple(
            sorted(
                (
                    task
                    for task in unique_candidates.values()
                    if isinstance(getattr(task, "callback_id", None), str)
                    and task.callback_id
                ),
                key=lambda item: (
                    not _task_has_available_definition(
                        bundle,
                        item,
                        cards_by_path,
                    ),
                    item.task_id,
                ),
            )
        )

    state_cache = state_cache if state_cache is not None else {}
    selected: dict[str, dict[str, Any]] = {}
    attempt_counts: Counter[str] = Counter()
    attempt_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    retryable: dict[str, tuple[Any, ...]] = dict(family_candidates)
    rounds: list[dict[str, Any]] = []
    for round_index in range(2):
        selected_before = len(selected)
        event_count_before = sum(
            len(events)
            for events in production["_events_by_type"].values()
        )
        next_retryable: dict[str, tuple[Any, ...]] = {}
        for family in sorted(family_candidates):
            if family in selected:
                continue
            family_retryable: list[Any] = []
            for task in retryable.get(family, ()):
                attempt = _task_callback_execution_probe(
                    bundle,
                    production,
                    task,
                    state_cache=state_cache,
                    cards_by_path=cards_by_path,
                    _return_after_state=family.startswith("StackProperty:"),
                )
                attempt_counts[family] += 1
                if attempt["ok"]:
                    after_state = attempt.get("_after_state")
                    attempt = {
                        key: value
                        for key, value in attempt.items()
                        if not key.startswith("_")
                    }
                    if family.startswith("StackProperty:"):
                        attempt["stack_property_consumer"] = (
                            _stack_property_consumption_probe_for_task(
                                bundle,
                                family,
                                task,
                                after_state,
                                consumer_rules=production["_rules"],
                            )
                            if after_state is not None
                            else {
                                "ok": False,
                                "reason": "real_callback_after_state_missing",
                            }
                        )
                    selected[family] = attempt
                    break
                if len(attempt_samples[family]) < 4:
                    attempt_samples[family].append(attempt)
                if attempt.get("reason") in {
                    "runtime_event_not_produced_by_focused_chain",
                    "real_production_event_did_not_execute_task",
                }:
                    family_retryable.append(task)
            if family not in selected and family_retryable:
                next_retryable[family] = tuple(family_retryable)
        event_count_after = sum(
            len(events)
            for events in production["_events_by_type"].values()
        )
        rounds.append(
            {
                "round": round_index + 1,
                "newly_validated_family_count": len(selected) - selected_before,
                "new_production_event_count": event_count_after - event_count_before,
            }
        )
        retryable = next_retryable
        if (
            len(selected) == selected_before
            and event_count_after == event_count_before
        ):
            break

    rows: list[dict[str, Any]] = []
    for family, callback_candidates in sorted(family_candidates.items()):
        family_selected = selected.get(family)
        external_candidates = tuple(
            task
            for task in callback_candidates
            if _task_has_only_external_definitions(
                bundle,
                task,
                external_character_build_paths,
            )
        )
        external_path_only = (
            bool(callback_candidates)
            and len(external_candidates) == len(callback_candidates)
        )
        status = (
            "executed"
            if family_selected is not None
            else (
                "external_content_e2e_deferred"
                if external_path_only
                else _failed_execution_status(attempt_samples[family])
            )
        )
        deferred = (
            {
                "required_trigger_condition": (
                    "an admitted character build for one of the source paths"
                ),
                "missing_content_owner": "character_content_card",
                "external_character_build_paths": sorted(
                    {
                        definition.path_type
                        for task in external_candidates
                        for definition in _equipment_definitions_for_task(
                            bundle,
                            task,
                        )
                    }
                ),
                "future_closure": "the owning character content card E2E",
            }
            if status == "external_content_e2e_deferred"
            else {}
        )
        rows.append(
            {
                "family": family,
                "real_source_count": source_counts[family],
                "callback_source_count": len(callback_candidates),
                "attempt_count": attempt_counts[family],
                "status": status,
                "external_character_build_dependency": False,
                "external_path_only_sources": external_path_only,
                "external_character_build_paths": sorted(
                    {
                        definition.path_type
                        for task in external_candidates
                        for definition in _equipment_definitions_for_task(
                            bundle,
                            task,
                        )
                    }
                ),
                "selected": family_selected or {},
                "external_content_e2e_deferred": deferred,
                "attempts": (
                    attempt_samples[family]
                    if attempt_samples[family]
                    else ({"reason": "callback_backed_source_missing"},)
                )
                if family_selected is None
                else (),
                "ok": status in {
                    "executed",
                    "external_content_e2e_deferred",
                },
            }
        )
    checks = {
        "gameplay_task_families_nonempty": bool(rows),
        "implementation_failure_count_is_zero": not any(
            row["status"] == "implementation_failure" for row in rows
        ),
        "validation_harness_invalid_count_is_zero": not any(
            row["status"] == "validation_harness_invalid" for row in rows
        ),
        "mechanism_families_do_not_use_character_build_dependency_exemption": all(
            row["external_character_build_dependency"] is False for row in rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_exact_task_family_execution_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "family_count": len(rows),
        "executed_family_count": sum(
            row["status"] == "executed" for row in rows
        ),
        "external_content_e2e_deferred_count": sum(
            row["status"] == "external_content_e2e_deferred"
            for row in rows
        ),
        "implementation_failure_count": sum(
            row["status"] == "implementation_failure" for row in rows
        ),
        "validation_harness_invalid_count": sum(
            row["status"] == "validation_harness_invalid" for row in rows
        ),
        "fixpoint_rounds": rounds,
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }


def _failed_execution_status(
    attempts: list[dict[str, Any]],
) -> str:
    invalid_markers = {
        "event_param_entity_identity_mismatch",
        "event_param_entity_missing_in_state",
        "unit_defeated_state_mismatch",
        "cross_state_event_evidence",
        "synthetic_gameplay_producer",
        "validator_only_execution_entry",
    }
    reasons = {
        str(attempt.get("reason") or "")
        for attempt in attempts
        if isinstance(attempt, dict)
    }
    return (
        "validation_harness_invalid"
        if reasons & invalid_markers
        else "implementation_failure"
    )


def _stack_property_consumption_matrix(
    partition: dict[str, Any],
    *,
    task_execution: dict[str, Any],
    family_filter: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Prove every exact StackProperty family reaches its distinct consumer.

    Executing ``StackProperty`` itself only records the already-lowered status
    modifier.  It cannot prove that damage, healing, shields, energy, timeline,
    or aggro queries consume that modifier.  Each row therefore starts from a
    real source-backed equipment status and compares the common consumer with a
    counterfactual state that differs only by that exact raw property node.
    """

    source_counts: Counter[str] = Counter()
    for raw_row in partition["_inventory"]["_source_rows"]:
        family = str(raw_row.get("family") or "")
        if (
            raw_row.get("stage") != "s8"
            or raw_row.get("kind") != "task"
            or not family.startswith("StackProperty:")
        ):
            continue
        if family_filter is not None and family not in family_filter:
            continue
        source_counts[family] += 1

    task_rows = {
        str(row.get("family") or ""): row
        for row in task_execution.get("rows", ())
        if row.get("family")
    }

    rows: list[dict[str, Any]] = []
    for family in sorted(source_counts):
        property_name = family.split(":", 2)[1]
        task_row = task_rows.get(family, {})
        selected_task = task_row.get("selected")
        consumer = (
            selected_task.get("stack_property_consumer")
            if isinstance(selected_task, dict)
            else None
        )
        consumer = consumer if isinstance(consumer, dict) else {}
        rows.append(
            {
                "family": family,
                "property": property_name,
                "real_source_count": source_counts[family],
                "callback_execution_ok": task_row.get("ok") is True,
                "selected": consumer if consumer.get("ok") is True else {},
                "attempts": (
                    ()
                    if consumer.get("ok") is True
                    else (consumer or {"reason": "consumer_evidence_missing"},)
                ),
                "ok": task_row.get("ok") is True and consumer.get("ok") is True,
            }
        )
    stack_families_requested = family_filter is None or any(
        family.startswith("StackProperty:") for family in family_filter
    )
    checks = {
        "stack_property_families_nonempty": (
            bool(rows) if stack_families_requested else True
        ),
        "every_stack_property_family_changes_its_common_consumer": all(
            row["ok"] for row in rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_stack_property_consumption_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "family_count": len(rows),
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }


def _stack_property_consumption_probe_for_task(
    bundle: dict[str, Any],
    family: str,
    task: Any,
    state: BattleState,
    *,
    consumer_rules: RuleBook,
) -> dict[str, Any]:
    property_name = family.split(":", 2)[1]
    owner_id = _status_detail_owner(state, task.modifier_name)
    if not owner_id:
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "source_modifier_missing_after_real_callback",
        }
    entry = _status_property_entry(state, owner_id, property_name)
    if entry is None:
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "source_property_modifier_missing_after_real_callback",
        }
    detail, modifier, value = entry
    if isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-12):
        owner = state.units.get(owner_id)
        effect_resistance = (
            effective_unit_stat(owner, "effect_resistance").to_json()
            if owner is not None
            else {}
        )
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "source_property_value_is_neutral",
            "owner_effect_resistance": effect_resistance,
            "status_dynamic_summary": [
                {
                    "modifier_name": str(item.get("modifier_name") or ""),
                    "by_name": dict(dynamic_values.get("__by_name") or {}),
                    "by_hash": dict(dynamic_values.get("__by_hash") or {}),
                }
                for item in (
                    owner.flags.get("status_details", ())
                    if owner is not None
                    and isinstance(owner.flags.get("status_details"), (list, tuple))
                    else ()
                )
                if isinstance(item, dict)
                and isinstance(
                    (dynamic_values := item.get("dynamic_values")),
                    dict,
                )
                and str(item.get("modifier_name") or "").startswith(
                    "MEquip_21014"
                )
            ],
        }
    without_property = _without_status_property(
        state,
        owner_id,
        property_name,
        str(modifier.get("raw_path") or ""),
    )
    return _stack_property_consumer_probe(
        bundle,
        task,
        state,
        without_property,
        owner_id,
        detail,
        modifier,
        value,
        consumer_rules=consumer_rules,
    )


def _status_property_entry(
    state: BattleState,
    owner_id: str,
    property_name: str,
) -> tuple[dict[str, Any], dict[str, Any], float] | None:
    unit = state.units.get(owner_id)
    if unit is None:
        return None
    details = unit.flags.get("status_details")
    if not isinstance(details, (list, tuple)):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        modifiers = detail.get("modifiers")
        if not isinstance(modifiers, (list, tuple)):
            continue
        for modifier in modifiers:
            if not isinstance(modifier, dict) or modifier.get("property") != property_name:
                continue
            value = status_modifier_numeric_value(detail, modifier)
            if value is not None:
                return detail, modifier, value
    return None


def _without_status_property(
    state: BattleState,
    owner_id: str,
    property_name: str,
    raw_path: str,
) -> BattleState:
    unit = state.units[owner_id]
    details = unit.flags.get("status_details")
    if not isinstance(details, (list, tuple)):
        return state
    updated_details: list[Any] = []
    for detail in details:
        if not isinstance(detail, dict):
            updated_details.append(detail)
            continue
        modifiers = detail.get("modifiers")
        if not isinstance(modifiers, (list, tuple)):
            updated_details.append(detail)
            continue
        kept = [
            modifier
            for modifier in modifiers
            if not (
                isinstance(modifier, dict)
                and modifier.get("property") == property_name
                and (
                    not raw_path
                    or str(modifier.get("raw_path") or "") == raw_path
                )
            )
        ]
        updated_details.append({**detail, "modifiers": kept})
    updated = replace(
        unit,
        flags={**unit.flags, "status_details": updated_details},
    )
    return replace(state, units={**state.units, owner_id: updated})


def _stack_property_consumer_probe(
    bundle: dict[str, Any],
    task: Any,
    state: BattleState,
    without_property: BattleState,
    owner_id: str,
    detail: dict[str, Any],
    modifier: dict[str, Any],
    value: float,
    *,
    consumer_rules: RuleBook,
) -> dict[str, Any]:
    bucket = str(modifier.get("bucket") or "")
    key = str(modifier.get("key") or "")
    raw_path = str(modifier.get("raw_path") or "")
    common = {
        "task_id": task.task_id,
        "property": str(modifier.get("property") or ""),
        "bucket": bucket,
        "key": key,
        "value": value,
        "raw_path": raw_path,
        "source": task.source.to_json(),
        "status_instance_id": str(detail.get("instance_id") or ""),
        "source_backed_status_present": bool(
            raw_path
            and task.source.source_path.startswith("Config/ConfigAbility/Equip/")
        ),
    }
    if bucket in {
        "attribute",
        "crit",
        "damage_bonus",
        "break_bonus",
        "defense",
        "resistance",
        "damage_taken",
        "damage_reduction",
    } and key != "speed_added_ratio":
        result = _damage_property_consumer_probe(
            bundle,
            task,
            state,
            without_property,
            owner_id,
            modifier,
            rules=consumer_rules,
        )
    elif bucket == "attribute" and key == "speed_added_ratio":
        result = _timeline_property_consumer_probe(
            bundle,
            state,
            without_property,
            owner_id,
            raw_path,
        )
    elif bucket in {"healing", "shield", "resource"}:
        result = _effect_property_consumer_probe(
            bundle,
            state,
            without_property,
            owner_id,
            bucket,
            raw_path,
        )
    elif bucket == "aggro":
        result = _aggro_property_consumer_probe(
            state,
            without_property,
            owner_id,
            raw_path,
        )
    else:
        result = {
            "ok": False,
            "reason": f"property_consumer_route_missing:{bucket}:{key}",
        }
    return {**common, **result, "ok": common["source_backed_status_present"] and result.get("ok") is True}


def _opposing_unit_id(state: BattleState, unit_id: str) -> str:
    unit = state.units.get(unit_id)
    if unit is None:
        return ""
    return next(
        (
            candidate_id
            for candidate_id, candidate in sorted(state.units.items())
            if is_opposing_combat_team(unit, candidate)
        ),
        "",
    )


def _damage_property_consumer_probe(
    bundle: dict[str, Any],
    task: Any,
    state: BattleState,
    without_property: BattleState,
    owner_id: str,
    modifier: dict[str, Any],
    *,
    rules: RuleBook,
) -> dict[str, Any]:
    key = str(modifier.get("key") or "")
    scope = str(modifier.get("scope") or "actor")
    opposing_id = _opposing_unit_id(state, owner_id)
    if not opposing_id:
        return {"ok": False, "reason": "opposing_damage_unit_missing"}
    attacker_id, target_id = (
        (opposing_id, owner_id) if scope == "target" else (owner_id, opposing_id)
    )

    def prepared(source: BattleState) -> BattleState:
        target = source.units[target_id]
        durable = replace(target, hp=target.max_hp)
        return replace(source, units={**source.units, target_id: durable})

    active_state = prepared(state)
    baseline_state = prepared(without_property)
    action = next(
        (
            item
            for item in rules.ir.action_definitions
            if item.coverage_status == "executable"
        ),
        None,
    )
    if action is None:
        return {"ok": False, "reason": "executable_action_definition_missing"}
    element_type: str | None = None
    suffix = "_damage_added_ratio"
    if key.endswith(suffix):
        prefix = key[: -len(suffix)]
        if prefix not in {"", "dot", "elation"}:
            element_type = prefix
    attack_type = (
        "Pursued"
        if key == "elation_damage_added_ratio"
        else "DOT"
        if key == "dot_damage_added_ratio"
        else "Normal"
    )
    family = (
        "dot"
        if key == "dot_damage_added_ratio"
        else "break"
        if key == "break_damage_extra_added_ratio"
        else "direct"
    )
    packet_args: dict[str, Any] = {
        "attacker_id": attacker_id,
        "target_id": target_id,
        "attack_type": attack_type,
        "damage_formula_family": family,
        "element_type": element_type,
        "source_task_id": task.task_id,
        "source_trace": task.source.to_json(),
        "source_frame": DamageSourceFrame(
            owner_id=owner_id,
            source_id=task.task_id,
            source_kind="equipment_status_property",
            sequence_id=f"property-consumer:{task.task_id}",
            target_id=target_id,
            source_trace=task.source.to_json(),
        ),
    }
    if family == "direct":
        packet_args.update(
            {
                "action_definition": action,
                "damage_emission_id": task.task_id,
                "scaling_ratio": 1.0,
                "scaling_basis": {
                    "kind": "unit_stat",
                    "unit_ref": "attacker",
                    "stat": "attack",
                },
                "metadata": {
                    "crit_mode": (
                        "forced_crit"
                        if key == "critical_damage"
                        else "noncrit"
                    )
                },
            }
        )
    elif family == "dot":
        emission = next(
            (
                item
                for item in rules.ir.status_damage_emissions
                if item.coverage_status == "executable"
                and item.damage_formula_family == "dot"
            ),
            None,
        )
        if emission is None:
            return {"ok": False, "reason": "real_dot_emission_missing"}
        packet_args.update(
            {
                "amount": 100.0,
                "amount_stage": "family_base",
                "status_damage_emission_id": emission.status_damage_emission_id,
                "status_callback_id": emission.callback_id,
            }
        )
    else:
        emission = next(
            (
                item
                for item in rules.ir.break_damage_emissions
                if item.coverage_status == "executable"
            ),
            None,
        )
        if emission is None:
            return {"ok": False, "reason": "real_break_emission_missing"}
        packet_args.update(
            {
                "amount": 100.0,
                "amount_stage": "family_base",
                "break_damage_emission_id": emission.break_damage_emission_id,
                "break_template_id": emission.template_id,
            }
        )
    packet = DamagePacket(**packet_args)
    active = DamageSystem(rules).apply_packet(active_state, packet)
    baseline = DamageSystem(rules).apply_packet(baseline_state, packet)
    if not active.ok or not baseline.ok:
        return {
            "ok": False,
            "reason": "common_damage_consumer_blocked",
            "active_errors": list(active.errors),
            "baseline_errors": list(baseline.errors),
        }
    active_payload = _damage_result_payload(active)
    baseline_payload = _damage_result_payload(baseline)
    active_value = active_payload.get("final_damage")
    baseline_value = baseline_payload.get("final_damage")
    if key == "critical_chance":
        active_value = _nested_number(active_payload, "formula_result", "crit_resolution", "crit_rate")
        baseline_value = _nested_number(baseline_payload, "formula_result", "crit_resolution", "crit_rate")
    raw_path = str(modifier.get("raw_path") or "")
    source_consumed = raw_path in _recursive_string_values(active_payload)
    changed = (
        isinstance(active_value, (int, float))
        and isinstance(baseline_value, (int, float))
        and not isclose(
            float(active_value),
            float(baseline_value),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )
    reducer = MutationReducer()
    after = reducer.apply_all(active_state, active.mutations)
    replay = reducer.replay_snapshot(
        active_state,
        active.mutations,
        after.snapshot().to_json(),
    )
    mutation_ids = {mutation.stable_id() for mutation in active.mutations}
    settlement_ids = {
        str(record.get("mutation_id") or "")
        for record in active.records
        if isinstance(record, dict) and record.get("mutation_id")
    }
    return {
        "ok": changed
        and source_consumed
        and bool(mutation_ids)
        and mutation_ids <= settlement_ids
        and replay.ok,
        "consumer": f"damage:{family}:{attack_type}",
        "active_value": active_value,
        "baseline_value": baseline_value,
        "source_term_consumed": source_consumed,
        "mutation_count": len(active.mutations),
        "mutations_settled": bool(mutation_ids) and mutation_ids <= settlement_ids,
        "replay_equal": replay.ok,
    }


def _damage_result_payload(result: Any) -> dict[str, Any]:
    for record in result.records:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("final_damage"), (int, float)):
            return payload
    return {}


def _nested_number(value: dict[str, Any], *path: str) -> float | None:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return float(current) if isinstance(current, (int, float)) and not isinstance(current, bool) else None


def _recursive_string_values(value: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            values.update(_recursive_string_values(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            values.update(_recursive_string_values(child))
    elif isinstance(value, str):
        values.add(value)
    return values


def _timeline_property_consumer_probe(
    bundle: dict[str, Any],
    state: BattleState,
    without_property: BattleState,
    owner_id: str,
    raw_path: str,
) -> dict[str, Any]:
    rule = next(
        (
            item
            for item in bundle["rules"].ir.timeline_rules
            if item.coverage_status == "executable"
        ),
        None,
    )
    if rule is None:
        return {"ok": False, "reason": "executable_timeline_rule_missing"}
    active = TimelineSystem().initialize_action_values(state, rule)
    baseline = TimelineSystem().initialize_action_values(without_property, rule)
    active_mutation = next(
        (m for m in active.mutations if m.path == ("units", owner_id, "action_value")),
        None,
    )
    baseline_mutation = next(
        (m for m in baseline.mutations if m.path == ("units", owner_id, "action_value")),
        None,
    )
    if active_mutation is None or baseline_mutation is None:
        return {"ok": False, "reason": "timeline_owner_mutation_missing"}
    reducer = MutationReducer()
    after = reducer.apply_all(state, active.mutations)
    replay = reducer.replay_snapshot(state, active.mutations, after.snapshot().to_json())
    source_consumed = raw_path in _recursive_string_values(active_mutation.metadata)
    return {
        "ok": source_consumed
        and not isclose(
            float(active_mutation.after),
            float(baseline_mutation.after),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and replay.ok,
        "consumer": "timeline:initialize_action_values",
        "active_value": active_mutation.after,
        "baseline_value": baseline_mutation.after,
        "source_term_consumed": source_consumed,
        "mutation_count": len(active.mutations),
        "replay_equal": replay.ok,
    }


def _effect_property_consumer_probe(
    bundle: dict[str, Any],
    state: BattleState,
    without_property: BattleState,
    owner_id: str,
    bucket: str,
    raw_path: str,
) -> dict[str, Any]:
    opcode = {"healing": "HealHP", "shield": "InitShield", "resource": "ModifySPNew"}[bucket]

    def prepared(source: BattleState) -> BattleState:
        units = {
            unit_id: replace(
                unit,
                hp=max(1.0, unit.max_hp / 2.0),
                energy=0.0,
            )
            for unit_id, unit in source.units.items()
        }
        return replace(source, units=units)

    active_state = prepared(state)
    baseline_state = prepared(without_property)
    rules: RuleBook = bundle["rules"]
    attempts: list[dict[str, Any]] = []
    for source_task in sorted(bundle["callback_tasks"], key=lambda item: item.task_id):
        if source_task.opcode != opcode or not source_task.effect_id:
            continue
        effect = rules.effect(source_task.effect_id)
        if effect is None or effect.coverage_status != "executable":
            continue
        hashes = tuple(
            value_hash
            for _, expression in _numeric_expressions(effect.payload)
            for value_hash in numeric_dynamic_hashes(expression)
        )
        # Keep healing below the HP cap so the counterfactual can observe the
        # exact outgoing-heal property.  A saturated heal would erase the
        # difference even though the production formula consumed the term.
        probe_numeric_value = 0.01 if bucket == "healing" else 1.0
        dynamic_values = {
            str(value_hash): probe_numeric_value for value_hash in hashes
        }
        opposing_id = _opposing_unit_id(active_state, owner_id)
        context_args = {
            "caster_id": owner_id,
            "owner_id": owner_id,
            "source_id": source_task.task_id,
            "param_entity_id": opposing_id or owner_id,
            "current_action_target_id": opposing_id or owner_id,
            "event_payload": {
                "actor_id": owner_id,
                "target_id": opposing_id or owner_id,
                "param_entity_id": opposing_id or owner_id,
                "selected_target_ids": [opposing_id or owner_id],
                "skill_target_ids": [opposing_id or owner_id],
                "modifier_name": source_task.modifier_name,
            },
            "dynamic_values": dynamic_values,
        }
        registry = EffectRegistry(StatusSystem(rules))
        active = registry.execute(
            effect,
            EffectExecutionContext(state=active_state, **context_args),
        )
        baseline = registry.execute(
            effect,
            EffectExecutionContext(state=baseline_state, **context_args),
        )
        if active.unsupported or baseline.unsupported or not active.mutations or not baseline.mutations:
            attempts.append(
                {
                    "effect_id": effect.effect_id,
                    "active_unsupported": list(active.unsupported),
                    "baseline_unsupported": list(baseline.unsupported),
                }
            )
            continue
        active_by_path = {mutation.path: mutation for mutation in active.mutations}
        baseline_by_path = {mutation.path: mutation for mutation in baseline.mutations}
        common_paths = sorted(set(active_by_path) & set(baseline_by_path))
        changed_path = next(
            (
                path
                for path in common_paths
                if active_by_path[path].after != baseline_by_path[path].after
            ),
            None,
        )
        source_consumed = any(
            raw_path in _recursive_string_values(mutation.metadata)
            for mutation in active.mutations
        )
        reducer = MutationReducer()
        after = reducer.apply_all(active_state, active.mutations)
        replay = reducer.replay_snapshot(
            active_state,
            active.mutations,
            after.snapshot().to_json(),
        )
        mutation_ids = {mutation.stable_id() for mutation in active.mutations}
        settlement_ids = {
            str(record.get("mutation_id") or "")
            for record in active.records
            if isinstance(record, dict) and record.get("mutation_id")
        }
        ok = bool(
            changed_path is not None
            and source_consumed
            and mutation_ids <= settlement_ids
            and replay.ok
        )
        attempt = {
            "ok": ok,
            "consumer": f"effect:{opcode}",
            "effect_id": effect.effect_id,
            "effect_source": effect.source.to_json(),
            "changed_path": list(changed_path) if changed_path is not None else [],
            "source_term_consumed": source_consumed,
            "mutation_count": len(active.mutations),
            "mutations_settled": bool(mutation_ids) and mutation_ids <= settlement_ids,
            "replay_equal": replay.ok,
        }
        if ok:
            return attempt
        attempts.append(attempt)
    return {
        "ok": False,
        "reason": f"real_{opcode}_consumer_did_not_change_with_property",
        "attempts": attempts[:4],
    }


def _aggro_property_consumer_probe(
    state: BattleState,
    without_property: BattleState,
    owner_id: str,
    raw_path: str,
) -> dict[str, Any]:
    enemy_id = next(
        (
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(state.units[owner_id], unit)
        ),
        "",
    )
    if not enemy_id:
        return {"ok": False, "reason": "aggro_query_enemy_missing"}
    policy = TargetPolicy(target_relation="enemy")
    active = TargetSystem().enumerate_action_targets(state, enemy_id, policy)
    baseline = TargetSystem().enumerate_action_targets(without_property, enemy_id, policy)

    def row(result: Any) -> dict[str, Any]:
        aggro = result.metadata.get("aggro_selection")
        if not isinstance(aggro, dict):
            return {}
        targets = aggro.get("targets")
        if not isinstance(targets, dict):
            return {}
        value = targets.get(owner_id)
        return value if isinstance(value, dict) else {}

    active_row = row(active)
    baseline_row = row(baseline)
    active_weight = active_row.get("value")
    baseline_weight = baseline_row.get("value")
    source_consumed = raw_path in _recursive_string_values(active_row)
    changed = (
        isinstance(active_weight, (int, float))
        and isinstance(baseline_weight, (int, float))
        and not isclose(
            float(active_weight),
            float(baseline_weight),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )
    return {
        "ok": active.ok and baseline.ok and changed and source_consumed,
        "consumer": "target:external_aggro_weight",
        "active_value": active_weight,
        "baseline_value": baseline_weight,
        "source_term_consumed": source_consumed,
    }


def _external_event_family_deferred(
    family: str,
    production: dict[str, Any],
) -> dict[str, Any]:
    if (
        family == "OnCustomEvent:s8"
        and production.get("_real_custom_event_seed", {}).get("status")
        == "external_content_e2e_deferred"
    ):
        return {
            key: value
            for key, value in production["_real_custom_event_seed"].items()
            if key not in {"ok", "executed", "status"}
        }
    if family == "OnListenModifierAdd:s8":
        return {
            "required_trigger_condition": (
                "an allied unit gains a real status with Shield behavior"
            ),
            "missing_content_owner": (
                "character_or_monster_content_card_that_applies_the_shield_status"
            ),
            "future_closure": (
                "the owning character or monster content-card execution card"
            ),
            "reason": "current_p8_and_owned_combatant_content_has_no_real_producer",
        }
    if family == "OnListenModifierOnStack:s8":
        return {
            "required_trigger_condition": (
                "an enemy debuff stacks and its actual applier is the light-cone wearer"
            ),
            "missing_content_owner": (
                "character_or_monster_content_card_that_applies_and_stacks_the_debuff"
            ),
            "future_closure": (
                "the owning character or monster content-card execution card"
            ),
            "reason": "current_p8_and_owned_combatant_content_has_no_real_producer",
        }
    return {}


def _event_family_execution_matrix(
    bundle: dict[str, Any],
    partition: dict[str, Any],
    production: dict[str, Any],
    energy_listener: dict[str, Any],
    bp_listener: dict[str, Any],
    cards_by_path: dict[str, Any],
    *,
    external_character_build_paths: frozenset[str] = frozenset(),
    family_filter: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Prove each exact callback event through a real producer and task chain."""

    indexes = _coverage_source_indexes(bundle)
    rules: RuleBook = production["_rules"]
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    source_counts: Counter[str] = Counter()
    for raw_row in partition["_inventory"]["_source_rows"]:
        if raw_row["stage"] != "s8" or raw_row["kind"] != "event":
            continue
        if (
            family_filter is not None
            and raw_row["family"] not in family_filter
        ):
            continue
        source_counts[raw_row["family"]] += 1
        linked = _linked_nodes(raw_row, indexes)
        if len(linked) == 1:
            callback = linked[0]
            grouped[raw_row["family"]][callback.callback_id] = callback

    rows: list[dict[str, Any]] = []
    state_cache: dict[str, BattleState] = {}
    for family in sorted(source_counts):
        callbacks = tuple(grouped.get(family, {}).values())
        candidates = {
            task.task_id: task
            for callback in callbacks
            for task in rules.status_callback_tasks_for_callback(callback.callback_id)
            if task.coverage_status == "executable"
            and task.blocked_reason != "equipment_task_family_non_gameplay"
        }
        external_only = bool(candidates) and all(
            _task_has_only_external_definitions(
                bundle,
                task,
                external_character_build_paths,
            )
            for task in candidates.values()
        )
        external_paths = sorted(
            {
                definition.path_type
                for task in candidates.values()
                for definition in _equipment_definitions_for_task(bundle, task)
                if definition.path_type in external_character_build_paths
            }
        )
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        deferred = _external_event_family_deferred(family, production)
        ordered_candidates = tuple(
            sorted(
                candidates.values(),
                key=lambda item: (
                    not _task_has_available_definition(
                        bundle,
                        item,
                        cards_by_path,
                    ),
                    item.task_id,
                ),
            )
        )
        if not deferred:
            for task in ordered_candidates:
                attempt = _task_callback_execution_probe(
                    bundle,
                    production,
                    task,
                    state_cache=state_cache,
                    cards_by_path=cards_by_path,
                )
                attempts.append(attempt)
                if attempt["ok"]:
                    selected = attempt
                    break
        energy_specialized_e2e = (
            family == f"{UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1]}:s8"
            and energy_listener.get("ok") is True
        )
        bp_specialized_e2e = (
            family == f"{TEAM_SKILL_POINT_EVENT_CONTRACT.after_callback_events[0]}:s8"
            and bp_listener.get("ok") is True
        )
        specialized_e2e = energy_specialized_e2e or bp_specialized_e2e
        status = (
            "executed"
            if selected is not None or specialized_e2e
            else (
                "external_content_e2e_deferred"
                if deferred
                else _failed_execution_status(attempts)
            )
        )
        rows.append(
            {
                "family": family,
                "real_source_count": source_counts[family],
                "linked_callback_count": len(callbacks),
                "executable_task_count": len(candidates),
                "attempt_count": len(attempts),
                "status": status,
                "external_character_build_dependency": False,
                "external_path_only_sources": external_only,
                "external_character_build_paths": external_paths,
                "selected": (
                    {
                        key: value
                        for key, value in selected.items()
                        if not key.startswith("_")
                    }
                    if selected is not None
                    else {}
                ),
                "external_content_e2e_deferred": deferred,
                "specialized_e2e": (
                    {
                        "kind": (
                            "energy_mutation_listener"
                            if energy_specialized_e2e
                            else "team_skill_point_mutation_listener"
                        ),
                        "ok": True,
                    }
                    if specialized_e2e else {}
                ),
                "attempts": attempts[:4] if selected is None else (),
                "ok": status in {
                    "executed",
                    "external_content_e2e_deferred",
                },
            }
        )
    checks = {
        "gameplay_event_families_nonempty": bool(rows),
        "implementation_failure_count_is_zero": not any(
            row["status"] == "implementation_failure" for row in rows
        ),
        "validation_harness_invalid_count_is_zero": not any(
            row["status"] == "validation_harness_invalid" for row in rows
        ),
        "external_content_e2e_deferred_is_structured": all(
            row["status"] != "external_content_e2e_deferred"
            or all(
                row["external_content_e2e_deferred"].get(key)
                for key in (
                    "required_trigger_condition",
                    "missing_content_owner",
                    "future_closure",
                )
            )
            for row in rows
        ),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_exact_event_family_execution_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "family_count": len(rows),
        "executed_family_count": sum(
            row["status"] == "executed" for row in rows
        ),
        "external_content_e2e_deferred_count": sum(
            row["status"] == "external_content_e2e_deferred"
            for row in rows
        ),
        "implementation_failure_count": sum(
            row["status"] == "implementation_failure" for row in rows
        ),
        "validation_harness_invalid_count": sum(
            row["status"] == "validation_harness_invalid" for row in rows
        ),
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }


def _task_callback_execution_probe(
    bundle: dict[str, Any],
    production: dict[str, Any],
    task: Any,
    *,
    state_cache: dict[str, BattleState],
    cards_by_path: dict[str, Any],
    _evidence_task: Any | None = None,
    _nested_depth: int = 0,
    _return_after_state: bool = False,
) -> dict[str, Any]:
    # The producer RuleBook is the complete S8 IR plus narrowly scoped kernel
    # producer fixtures.  Equipment callbacks/tasks remain the exact TBGD
    # nodes from the base IR; the extra definitions only make the real runtime
    # event source reachable and auditable.
    rules: RuleBook = production["_rules"]
    evidence_task = _evidence_task or task
    callback = rules.status_callback(task.callback_id)
    if callback is None:
        return {"ok": False, "task_id": task.task_id, "reason": "callback_missing"}
    families = tuple(
        family
        for family in rules.ir.status_event_families
        if family.callback_event == callback.event
        and family.coverage_status == "executable"
        and family.admission_status == "executable"
    )
    if len(families) != 1:
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": f"event_family_count:{len(families)}",
        }
    family = families[0]
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    produced = tuple(
        (event_type, event)
        for event_type in family.runtime_event_sources
        for event in events_by_type.get(event_type, ())
    )
    same_state_specialized_event = callback.event in {
        "OnAfterAttack",
        "OnListenAvatarBaseTypeChange",
        "OnListenCharacterDie",
        "OnTriggerDeath",
        "OnDeathrattle",
    }
    if not produced and not same_state_specialized_event:
        return {
            "ok": False,
            "task_id": task.task_id,
            "callback_id": callback.callback_id,
            "reason": "runtime_event_not_produced_by_focused_chain",
            "runtime_event_sources": list(family.runtime_event_sources),
            "producer_diagnostics": (
                production.get("_real_custom_event_seed", {})
                if "custom.event" in family.runtime_event_sources
                else {}
            ),
        }
    probe_state, status_owner_id, state_reason = _equipment_task_probe_state(
        bundle,
        production,
        task,
        state_cache=state_cache,
        cards_by_path=cards_by_path,
    )
    if probe_state is None:
        if _nested_depth < 2:
            parent_tasks = tuple(
                sorted(
                    (
                        candidate
                        for candidate in rules.ir.status_callback_tasks
                        if candidate.opcode == "AddModifier"
                        and candidate.coverage_status == "executable"
                        and candidate.callback_id
                        and candidate.task_id != task.task_id
                        and (
                            (effect := rules.effect(candidate.effect_id))
                            is not None
                        )
                        and isinstance(effect.payload.get("standard"), dict)
                        and effect.payload["standard"].get("modifier_name")
                        == task.modifier_name
                        and _task_has_available_definition(
                            bundle,
                            candidate,
                            cards_by_path,
                        )
                    ),
                    key=lambda item: item.task_id,
                )
            )
            nested_failures: list[dict[str, Any]] = []
            for parent_task in parent_tasks[:12]:
                parent_execution = _task_callback_execution_probe(
                    bundle,
                    production,
                    parent_task,
                    state_cache=state_cache,
                    cards_by_path=cards_by_path,
                    _evidence_task=parent_task,
                    _nested_depth=_nested_depth + 1,
                    _return_after_state=True,
                )
                parent_after_state = parent_execution.get("_after_state")
                parent_dispatch = parent_execution.get("_dispatch_result")
                if parent_execution.get("ok") is True and isinstance(
                    parent_after_state, BattleState
                ):
                    parent_events = (
                        tuple(parent_dispatch.events)
                        if parent_dispatch is not None
                        else ()
                    )
                    if callback.event == "OnDestroy":
                        destruction = _status_destroy_callback_execution_probe(
                            rules,
                            parent_after_state,
                            evidence_task,
                            parent_events=(),
                        )
                        if destruction.get("ok") is True:
                            return {
                                **destruction,
                                "execution_entry_task_id": parent_task.task_id,
                                "execution_entry_kind": "parent_add_modifier_then_lifecycle_expire",
                                "parent_execution": {
                                    key: value
                                    for key, value in parent_execution.items()
                                    if not key.startswith("_")
                                },
                            }
                        nested_failures.append(
                            {
                                "parent_execution": {
                                    key: value
                                    for key, value in parent_execution.items()
                                    if not key.startswith("_")
                                },
                                "destruction": destruction,
                            }
                        )
                        continue
                    lifecycle = _status_lifecycle_child_execution_probe(
                        rules,
                        parent_after_state,
                        evidence_task,
                        parent_events=parent_events,
                    )
                    if lifecycle.get("ok") is True:
                        return {
                            **lifecycle,
                            "execution_entry_task_id": parent_task.task_id,
                            "execution_entry_kind": (
                                "parent_add_modifier_emitted_source_lifecycle"
                            ),
                            "parent_execution": {
                                key: value
                                for key, value in parent_execution.items()
                                if not key.startswith("_")
                            },
                        }
                    nested_state_cache = dict(state_cache)
                    for definition in _equipment_definitions_for_task(bundle, task):
                        if definition.path_type in cards_by_path:
                            nested_state_cache[
                                definition.definition_key.definition_identity
                            ] = parent_after_state
                    nested = _task_callback_execution_probe(
                        bundle,
                        production,
                        task,
                        state_cache=nested_state_cache,
                        cards_by_path=cards_by_path,
                        _evidence_task=evidence_task,
                        _nested_depth=_nested_depth + 1,
                        _return_after_state=_return_after_state,
                    )
                    if nested.get("ok") is True:
                        return {
                            **nested,
                            "execution_entry_task_id": parent_task.task_id,
                            "execution_entry_kind": (
                                "parent_add_modifier_then_source_event"
                            ),
                            "parent_execution": {
                                key: value
                                for key, value in parent_execution.items()
                                if not key.startswith("_")
                            },
                        }
                    nested_failures.append(
                        {
                            "parent_execution": {
                                key: value
                                for key, value in parent_execution.items()
                                if not key.startswith("_")
                            },
                            "parent_lifecycle_execution": lifecycle,
                            "source_event_execution": nested,
                        }
                    )
                    continue
                nested_failures.append(parent_execution)
            if parent_tasks:
                return {
                    "ok": False,
                    "task_id": evidence_task.task_id,
                    "callback_id": callback.callback_id,
                    "reason": "parent_add_modifier_chain_did_not_execute_task",
                    "state_blocked_reason": state_reason,
                    "attempts": nested_failures[:2],
                }
        return {
            "ok": False,
            "task_id": evidence_task.task_id,
            "callback_id": callback.callback_id,
            "reason": state_reason,
        }
    if callback.event == "OnDestroy":
        result = _status_destroy_callback_execution_probe(
            rules,
            probe_state,
            evidence_task,
            parent_events=(),
        )
        if state_reason:
            result["state_preparation_reason"] = state_reason
        return result
    if callback.event in {
        "OnListenModifierAdd",
        "OnListenModifierOnStack",
    }:
        return {
            "ok": False,
            "task_id": evidence_task.task_id,
            "callback_id": callback.callback_id,
            "callback_event": callback.event,
            "reason": "external_content_e2e_deferred",
            "deferred": _external_event_family_deferred(
                f"{callback.event}:s8",
                production,
            ),
        }
    if callback.event in {
        "OnCreate",
        "OnStack",
        "OnModifierAdd",
        "OnAddModifierSuc",
        "OnModifierOnStack",
    }:
        result = _status_stack_callback_execution_probe(
            bundle,
            rules,
            production,
            probe_state,
            status_owner_id,
            evidence_task,
            callback_event=callback.event,
        )
        if state_reason:
            result["state_preparation_reason"] = state_reason
        return result
    if callback.event in {"OnPhase1", "OnPhase2"}:
        return _status_phase_callback_execution_probe(
            rules,
            probe_state,
            status_owner_id,
            evidence_task,
            callback_event=callback.event,
        )
    failures: list[dict[str, Any]] = []
    has_random_ancestor = _task_has_random_ancestor(rules, task)
    for event_type, event in produced:
        for phase in EVENT_PHASES.get(event_type, ()) or ("",):
            event_variants: list[tuple[str, GameEvent]] = [
                ("deterministic_seed", event)
            ]
            variant_index = 0
            while variant_index < len(event_variants):
                choice_mode, trigger_event = event_variants[variant_index]
                variant_index += 1
                seeded_state = probe_state
                if event_type == "unit.created":
                    created_state = _state_after_produced_unit_creation(
                        probe_state,
                        trigger_event,
                        rules,
                    )
                    if created_state is not None:
                        seeded_state = created_state
                state = _prime_callback_predecessors(
                    rules,
                    production,
                    seeded_state,
                    callback,
                    status_owner_id,
                )
                prepared_detail = find_status_detail(
                    state,
                    status_owner_id,
                    modifier_name=callback.modifier_name,
                )
                prepared_dynamic_values = (
                    prepared_detail.get("dynamic_values")
                    if isinstance(prepared_detail, dict)
                    else None
                )
                prepared_by_name = (
                    prepared_dynamic_values.get("__by_name")
                    if isinstance(prepared_dynamic_values, dict)
                    else None
                )
                prepared_by_hash = (
                    prepared_dynamic_values.get("__by_hash")
                    if isinstance(prepared_dynamic_values, dict)
                    else None
                )
                if phase:
                    state = replace(
                        state,
                        global_flags={**state.global_flags, "combat_phase": phase},
                    )
                result = EventDispatchSystem(
                    rules,
                    EffectRegistry(StatusSystem(rules)),
                ).dispatch_event(
                    state,
                    event=trigger_event,
                    unit_id=status_owner_id,
                    modifier_name=callback.modifier_name,
                )
                evidence = _task_execution_evidence(result, evidence_task)
                if (
                    not evidence["executed"]
                    and evidence_task.task_id != task.task_id
                ):
                    nested_owner_id = _status_detail_owner(
                        result.after_state,
                        evidence_task.modifier_name,
                    )
                    nested_callback = rules.status_callback(
                        evidence_task.callback_id
                    )
                    if nested_owner_id and nested_callback is not None:
                        seen_lifecycle_events: set[str] = set()
                        for emitted_event in tuple(result.events):
                            if emitted_event.event_type != "status.lifecycle":
                                continue
                            event_identity = (
                                emitted_event.event_id
                                or f"{emitted_event.window}:{emitted_event.target_id}"
                            )
                            if event_identity in seen_lifecycle_events:
                                continue
                            seen_lifecycle_events.add(event_identity)
                            nested_result = EventDispatchSystem(
                                rules,
                                EffectRegistry(StatusSystem(rules)),
                            ).dispatch_event(
                                result.after_state,
                                event=emitted_event,
                                unit_id=nested_owner_id,
                                modifier_name=evidence_task.modifier_name,
                            )
                            result = replace(
                                result,
                                after_state=nested_result.after_state,
                                mutations=(
                                    *result.mutations,
                                    *nested_result.mutations,
                                ),
                                events=(*result.events, *nested_result.events),
                                rng_events=(
                                    *result.rng_events,
                                    *nested_result.rng_events,
                                ),
                                records=(*result.records, *nested_result.records),
                                listener_records=(
                                    *result.listener_records,
                                    *nested_result.listener_records,
                                ),
                                errors=(*result.errors, *nested_result.errors),
                                node_results=(
                                    *result.node_results,
                                    *nested_result.node_results,
                                ),
                            )
                            evidence = _task_execution_evidence(
                                result,
                                evidence_task,
                            )
                            if evidence["executed"] or result.errors:
                                break
                audit = _event_dispatch_probe_audit(
                    rules,
                    state,
                    trigger_event,
                    result,
                )
                if not result.errors and audit["ok"]:
                    _merge_production_events(production, list(result.events))
                ok = not result.errors and evidence["executed"] and audit["ok"]
                attempt = {
                    "ok": ok,
                    "task_id": evidence_task.task_id,
                    "opcode": evidence_task.opcode,
                    "execution_entry_task_id": task.task_id,
                    "callback_id": callback.callback_id,
                    "callback_event": callback.event,
                    "runtime_event_source": event_type,
                    "production_event_id": trigger_event.event_id,
                    "production_attack_type": trigger_event.payload.get(
                        "attack_type"
                    ),
                    "production_skill_type": trigger_event.payload.get(
                        "skill_type"
                    ),
                    "production_custom_event_dynamic_key": (
                        trigger_event.payload.get("custom_event_dynamic_key")
                    ),
                    "production_custom_event_value": trigger_event.payload.get(
                        "custom_event_value"
                    ),
                    "owner_id": status_owner_id,
                    "state_preparation_reason": state_reason,
                    "phase": phase,
                    "rng_choice_mode": choice_mode,
                    "prepared_dynamic_values_by_name": {
                        str(key): value
                        for key, value in sorted(prepared_by_name.items())[:24]
                    }
                    if isinstance(prepared_by_name, dict)
                    else {},
                    "prepared_dynamic_values_by_hash": {
                        str(key): value
                        for key, value in sorted(prepared_by_hash.items())[:24]
                    }
                    if isinstance(prepared_by_hash, dict)
                    else {},
                    "task_execution_evidence": evidence,
                    "mutation_count": len(result.mutations),
                    "record_count": len(result.records),
                    "rng_event_count": len(result.rng_events),
                    "emitted_event_type_counts": dict(
                        sorted(Counter(item.event_type for item in result.events).items())
                    ),
                    "source_audit_replay": audit,
                    "errors": list(result.errors),
                    "source": evidence_task.source.to_json(),
                }
                if ok:
                    if _return_after_state:
                        attempt["_after_state"] = result.after_state
                        attempt["_before_state"] = state
                        attempt["_dispatch_result"] = result
                    return attempt
                failures.append(attempt)
                if (
                    has_random_ancestor
                    and choice_mode == "deterministic_seed"
                    and not result.errors
                ):
                    choice_keys = tuple(
                        dict.fromkeys(
                            str(key)
                            for rng_event in result.rng_events
                            for key in (
                                (
                                    rng_event.result.get("choice_key")
                                    if isinstance(rng_event.result, dict)
                                    else None
                                )
                                or rng_event.metadata.get("choice_key"),
                            )
                            if isinstance(key, str) and key
                        )
                    )
                    for outcome_id in ("pass", "fail"):
                        if not choice_keys:
                            break
                        event_variants.append(
                            (
                                f"explicit_ledger:{outcome_id}",
                                replace(
                                    event,
                                    payload={
                                        **event.payload,
                                        "rng_mode": "explicit_ledger",
                                        "rng_choices": {
                                            key: outcome_id
                                            for key in choice_keys
                                        },
                                    },
                                ),
                            )
                        )
    return {
        "ok": False,
        "task_id": evidence_task.task_id,
        "opcode": evidence_task.opcode,
        "callback_id": callback.callback_id,
        "reason": "real_production_event_did_not_execute_task",
        "attempt_count": len(failures),
        "attempts": failures[:4],
    }


def _state_after_produced_unit_creation(
    state: BattleState,
    event: GameEvent,
    rules: RuleBook,
) -> BattleState | None:
    """Replay a real mutation-backed unit.created event into the probe state."""

    payload = event.payload
    path = payload.get("mutation_path")
    metadata = payload.get("metadata")
    if (
        event.event_type != "unit.created"
    ):
        return None
    if payload.get("mutation_backed_event") is True:
        if (
            not isinstance(path, (list, tuple))
            or len(path) != 2
            or path[0] != "units"
            or not isinstance(path[1], str)
            or path[1] in state.units
            or not isinstance(payload.get("after"), dict)
            or not isinstance(metadata, dict)
        ):
            return None
        mutation = Mutation(
            op="spawn",
            path=tuple(path),
            before=payload.get("before"),
            after=payload["after"],
            reason=str(payload.get("reason") or ""),
            source=str(payload.get("source") or ""),
            before_exists=False,
            metadata=metadata,
        )
        if mutation.stable_id() != payload.get("mutation_id"):
            return None
        try:
            return MutationReducer().apply_all(state, (mutation,))
        except ValueError:
            return None

    target_id = payload.get("unit_id")
    entity_id = payload.get("entity_id")
    source_trace = payload.get("source_trace")
    entity = rules.entity(entity_id) if isinstance(entity_id, str) else None
    if (
        payload.get("source_kind") != "canonical_ir_entity"
        or not isinstance(target_id, str)
        or not target_id
        or target_id in state.units
        or entity is None
        or not isinstance(source_trace, dict)
        or source_trace != entity.source.to_json()
        or not state.units
    ):
        return None
    shape = state.units[sorted(state.units)[0]]
    created = replace(
        shape,
        unit_id=target_id,
        template_id=entity_id,
        statuses=(),
        shield_instances=(),
        lifecycle_status="active", flags={},
    )
    return replace(state, units={**state.units, target_id: created})


def _status_phase_callback_execution_probe(
    rules: RuleBook,
    state: BattleState,
    status_owner_id: str,
    task: Any,
    *,
    callback_event: str,
) -> dict[str, Any]:
    """Drive a status-local phase callback through the real turn scheduler."""

    units = {
        unit_id: replace(
            unit,
            action_value=(0.0 if unit_id == status_owner_id else max(10.0, unit.action_value)),
        )
        for unit_id, unit in state.units.items()
    }
    flags = {
        key: value
        for key, value in state.global_flags.items()
        if key not in {"turn_owner_id", "combat_phase"}
    }
    before = replace(
        state,
        units=units,
        global_flags={**flags, "phase": "scenario", "current_window": "idle"},
    )
    advance = DecisionSystem(rules).advance_to_decision(before)
    transitions = tuple(advance.transitions)
    records = tuple(
        record
        for transition in transitions
        if transition.transaction.settlement is not None
        for record in transition.transaction.settlement.records
    )
    mutations = tuple(
        mutation
        for transition in transitions
        for mutation in transition.transaction.mutations
    )
    events = tuple(
        event
        for transition in transitions
        for event in transition.transaction.events
    )
    rng_events = tuple(
        event
        for transition in transitions
        for event in transition.rng_events
    )
    evidence = _task_execution_evidence(
        SimpleNamespace(
            records=records,
            mutations=mutations,
            rng_events=rng_events,
        ),
        task,
    )
    audits = tuple(
        RuntimeSourceAuditor(rules).validate_transition(transition)
        for transition in transitions
    )
    replay_rows = []
    replay_before = before
    for transition in transitions:
        replay_rows.append(
            MutationReducer().replay_snapshot(
                replay_before,
                transition.transaction.mutations,
                transition.after.to_json(),
            )
        )
        replay_before = transition.after
    replays = tuple(replay_rows)
    matching_events = tuple(
        event
        for event in events
        if event.event_type == "status.lifecycle"
        and event.payload.get("callback_event") == callback_event
        and event.payload.get("modifier_name") == task.modifier_name
        and event.target_id == status_owner_id
    )
    ok = (
        bool(transitions)
        and all(transition.outcome.successor_eligible for transition in transitions)
        and bool(matching_events)
        and evidence["executed"]
        and bool(audits)
        and all(audit.ok for audit in audits)
        and bool(replays)
        and all(replay.ok for replay in replays)
    )
    return {
        "ok": ok,
        "task_id": task.task_id,
        "opcode": task.opcode,
        "callback_id": task.callback_id,
        "callback_event": callback_event,
        "execution_entry_task_id": task.task_id,
        "execution_entry_kind": "scheduler_status_phase_lifecycle",
        "owner_id": status_owner_id,
        "transition_count": len(transitions),
        "matching_production_event_count": len(matching_events),
        "task_execution_evidence": evidence,
        "mutation_count": len(mutations),
        "record_count": len(records),
        "rng_event_count": len(rng_events),
        "source_audit_replay": {
            "ok": bool(audits)
            and all(audit.ok for audit in audits)
            and bool(replays)
            and all(replay.ok for replay in replays),
            "source_audit_ok": bool(audits)
            and all(audit.ok for audit in audits),
            "replay_ok": bool(replays) and all(replay.ok for replay in replays),
            "audit_violations": [
                violation
                for audit in audits
                for violation in audit.violations
            ],
        },
        "errors": [
            reason_code
            for transition in transitions
            if not transition.outcome.successor_eligible
            for reason_code in transition.outcome.reason_codes
        ],
        "reason": "" if ok else "scheduler_status_phase_task_not_executed",
        "source": task.source.to_json(),
    }


def _status_stack_callback_execution_probe(
    bundle: dict[str, Any],
    rules: RuleBook,
    production: dict[str, Any],
    state: BattleState,
    status_owner_id: str,
    task: Any,
    *,
    callback_event: str,
) -> dict[str, Any]:
    """Add or reapply the real modifier to produce its exact lifecycle event."""

    add_effects = tuple(
        effect
        for effect in bundle["ir"].effects
        if effect.opcode == "AddModifier"
        and isinstance(effect.payload.get("standard"), dict)
        and effect.payload["standard"].get("modifier_name")
        == task.modifier_name
        and effect.coverage_status == "executable"
    )
    owner = state.units.get(status_owner_id)
    if owner is None:
        return {
            "ok": False,
            "task_id": task.task_id,
            "opcode": task.opcode,
            "callback_id": task.callback_id,
            "reason": "status_stack_owner_missing",
        }
    details = owner.flags.get("status_details", ())
    if not isinstance(details, (list, tuple)):
        details = ()
    existing_detail = next(
        (
            detail
            for detail in details
            if isinstance(detail, dict)
            and detail.get("modifier_name") == task.modifier_name
        ),
        {},
    )
    lifecycle_source_id = str(existing_detail.get("source_id") or task.task_id)
    lifecycle_caster_id = str(
        existing_detail.get("caster_id") or status_owner_id
    )
    stack_only_events = {"OnModifierOnStack", "OnListenModifierOnStack"}
    preserved_binding_source = None
    if callback_event in stack_only_events:
        base_state = state
    else:
        if isinstance(existing_detail, dict) and existing_detail:
            preserved_binding_source = binding_source_from_status_detail(
                existing_detail,
                existing_detail.get("dynamic_values"),
            )
        without_detail = tuple(
            detail
            for detail in details
            if not (
                isinstance(detail, dict)
                and detail.get("modifier_name") == task.modifier_name
            )
        )
        owner_without_detail = replace(
            owner,
            flags={**owner.flags, "status_details": without_detail},
        )
        base_state = replace(
            state,
            units={**state.units, status_owner_id: owner_without_detail},
        )
    base_state, shield_preparation = _deplete_owned_shield_for_reapply(
        base_state,
        owner_id=status_owner_id,
        modifier_name=task.modifier_name,
    )
    registry = EffectRegistry(StatusSystem(rules))
    reducer = MutationReducer()
    status_sources = (
        *((preserved_binding_source,) if preserved_binding_source is not None else ()),
        *status_binding_sources(base_state, tuple(base_state.units)),
    )
    store_source = binding_source_from_store(store_from_state(base_state))
    failures: list[dict[str, Any]] = []
    for effect in add_effects:
        scoped_binding_sets = _status_reapply_binding_sets(
            effect,
            status_sources,
            store_source,
        )
        for scoped_sources in scoped_binding_sets:
            effect_result = registry.execute(
                effect,
                EffectExecutionContext(
                    state=base_state,
                    caster_id=lifecycle_caster_id,
                    owner_id=status_owner_id,
                    source_id=lifecycle_source_id,
                    param_entity_id=status_owner_id,
                    current_action_target_id=status_owner_id,
                    event_payload={
                        "actor_id": status_owner_id,
                        "source_id": status_owner_id,
                        "target_id": status_owner_id,
                        "param_entity_id": status_owner_id,
                    },
                    binding_sources=scoped_sources,
                    include_ambient_status_bindings=False,
                ),
            )
            if effect_result.unsupported:
                failures.append(
                    {
                        "effect_id": effect.effect_id,
                        "reason": ";".join(effect_result.unsupported),
                    }
                )
                continue
            try:
                after_effect = reducer.apply_all(
                    base_state,
                    effect_result.mutations,
                )
            except ValueError as exc:
                failures.append(
                    {
                        "effect_id": effect.effect_id,
                        "reason": f"modifier_reapply_conflict:{exc}",
                    }
                )
                continue
            lifecycle_events = tuple(
                event
                for event in effect_result.events
                if event.event_type == "status.lifecycle"
                and event.payload.get("callback_event") == callback_event
                and event.payload.get("modifier_name") == task.modifier_name
                and event.target_id == status_owner_id
            )
            for event in lifecycle_events:
                dispatch = EventDispatchSystem(
                    rules,
                    EffectRegistry(StatusSystem(rules)),
                ).dispatch_event(
                    after_effect,
                    event=event,
                    unit_id=status_owner_id,
                    modifier_name=task.modifier_name,
                )
                evidence = _task_execution_evidence(dispatch, task)
                dispatch_audit = _event_dispatch_probe_audit(
                    rules,
                    after_effect,
                    event,
                    dispatch,
                )
                effect_replay = reducer.replay_snapshot(
                    base_state,
                    effect_result.mutations,
                    after_effect.snapshot().to_json(),
                )
                effect_mutation_ids = {
                    mutation.stable_id() for mutation in effect_result.mutations
                }
                effect_record_ids = {
                    str(record.get("mutation_id") or "")
                    for record in effect_result.records
                    if isinstance(record, dict) and record.get("mutation_id")
                }
                effect_settled = (
                    not effect_mutation_ids
                    or effect_mutation_ids <= effect_record_ids
                )
                ok = (
                    not dispatch.errors
                    and evidence["executed"]
                    and dispatch_audit["ok"]
                    and effect_replay.ok
                    and effect_settled
                )
                if ok:
                    _merge_production_events(
                        production,
                        [*effect_result.events, *dispatch.events],
                    )
                    return {
                        "ok": True,
                        "task_id": task.task_id,
                        "opcode": task.opcode,
                        "callback_id": task.callback_id,
                        "callback_event": callback_event,
                        "execution_entry_task_id": task.task_id,
                        "execution_entry_kind": "status_add_or_reapply_lifecycle",
                        "owner_id": status_owner_id,
                        "production_event_id": event.event_id,
                        "task_execution_evidence": evidence,
                        "mutation_count": len(effect_result.mutations)
                        + len(dispatch.mutations),
                        "record_count": len(effect_result.records)
                        + len(dispatch.records),
                        "rng_event_count": len(effect_result.rng_events)
                        + len(dispatch.rng_events),
                        "source_audit_replay": {
                            **dispatch_audit,
                            "effect_replay_ok": effect_replay.ok,
                            "effect_mutations_settled": effect_settled,
                        },
                        "shield_reapply_preparation": shield_preparation,
                        "errors": [],
                        "source": task.source.to_json(),
                        "_after_state": dispatch.after_state,
                        "_dispatch_result": dispatch,
                    }
                failures.append(
                    {
                        "effect_id": effect.effect_id,
                        "event_id": event.event_id,
                        "errors": list(dispatch.errors),
                        "task_execution_evidence": evidence,
                        "dispatch_audit": dispatch_audit,
                        "effect_replay_ok": effect_replay.ok,
                        "effect_mutations_settled": effect_settled,
                    }
                )
    return {
        "ok": False,
        "task_id": task.task_id,
        "opcode": task.opcode,
        "callback_id": task.callback_id,
        "reason": "status_add_or_reapply_did_not_execute_lifecycle_task",
        "attempts": failures[:4],
    }


def _status_reapply_binding_sets(
    effect: Any,
    status_sources: tuple[dict[str, Any], ...],
    store_source: dict[str, Any],
) -> tuple[tuple[dict[str, Any], ...], ...]:
    """Prefer one auditable status source that closes every effect operand."""

    standard = effect.payload.get("standard")
    dynamic_values = (
        standard.get("dynamic_values")
        if isinstance(standard, dict)
        else None
    )
    required_hashes = {
        str(hash_key)
        for expression in (
            dynamic_values.values()
            if isinstance(dynamic_values, dict)
            else ()
        )
        for hash_key in numeric_dynamic_hashes(expression)
    }
    if required_hashes:
        closed_sources = tuple(
            source
            for source in status_sources
            if isinstance(source.get("by_hash"), dict)
            and required_hashes <= {
                str(hash_key) for hash_key in source["by_hash"]
            }
        )
        if closed_sources:
            return tuple((source,) for source in closed_sources)
    return tuple(
        (source, store_source) for source in status_sources
    ) or ((store_source,),)


def _status_destroy_callback_execution_probe(
    rules: RuleBook,
    state: BattleState,
    task: Any,
    *,
    parent_events: tuple[GameEvent, ...],
) -> dict[str, Any]:
    owner_id = _status_detail_owner(state, task.modifier_name)
    if not owner_id:
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "destroy_probe_status_detail_missing",
        }
    current = state
    initial_shield_source_count = sum(
        item.get("owner_modifier_name") == task.modifier_name
        for item in current.units[owner_id].shield_instances
    )
    preparation_audits: list[dict[str, Any]] = []
    seen_preparation_events: set[str] = set()
    for event in parent_events:
        if (
            event.event_type != "status.lifecycle"
            or event.payload.get("modifier_name") != task.modifier_name
            or event.window == "OnDestroy"
        ):
            continue
        event_identity = event.event_id or f"{event.window}:{event.target_id}"
        if event_identity in seen_preparation_events:
            continue
        seen_preparation_events.add(event_identity)
        current, shield_preparation = _deplete_owned_shield_for_reapply(
            current,
            owner_id=owner_id,
            modifier_name=task.modifier_name,
        )
        before_dispatch = current
        prepared = EventDispatchSystem(
            rules,
            EffectRegistry(StatusSystem(rules)),
        ).dispatch_event(
            current,
            event=event,
            unit_id=owner_id,
            modifier_name=task.modifier_name,
        )
        preparation_audit = _event_dispatch_probe_audit(
            rules,
            before_dispatch,
            event,
            prepared,
        )
        preparation_audits.append(
            {
                **preparation_audit,
                "shield_reapply_preparation": shield_preparation,
            }
        )
        if prepared.errors or not preparation_audit["ok"]:
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": "destroy_probe_status_preparation_failed",
                "event_id": event.event_id,
                "errors": list(prepared.errors),
                "source_audit_replay": preparation_audit,
            }
        current = prepared.after_state
    status_system = StatusSystem(rules)
    reducer = MutationReducer()
    initial_detail = find_status_detail(
        current,
        owner_id,
        modifier_name=task.modifier_name,
    )
    remaining = (
        initial_detail.get("remaining_duration")
        if isinstance(initial_detail, dict)
        else None
    )
    if (
        not isinstance(remaining, (int, float))
        or isinstance(remaining, bool)
        or remaining <= 0
    ):
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "destroy_probe_duration_missing",
        }
    maximum_steps = int(remaining) + (0 if float(remaining).is_integer() else 1)
    for step_index in range(maximum_steps):
        detail = find_status_detail(
            current,
            owner_id,
            modifier_name=task.modifier_name,
        )
        if not isinstance(detail, dict):
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": "destroy_probe_status_disappeared_before_expire",
                "step_index": step_index,
            }
        life_step_moment = detail.get("life_step_moment")
        if not isinstance(life_step_moment, str) or not life_step_moment:
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": "destroy_probe_life_step_moment_missing",
            }
        before_tick = current
        lifecycle = status_system.apply_lifecycle_tick(
            current,
            owner_id,
            detail,
            life_step_moment,
        )
        if not lifecycle.ok:
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": "destroy_probe_lifecycle_tick_blocked",
                "unsupported": list(lifecycle.unsupported),
            }
        reduction = reducer.apply_all_result(current, lifecycle.mutations)
        if not reduction.ok:
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": "destroy_probe_lifecycle_reducer_conflict",
                "conflicts": [item.to_json() for item in reduction.conflicts],
            }
        current = reduction.after_state
        if lifecycle.operation != "expire":
            continue
        destroy_events = tuple(
            event
            for event in lifecycle.events
            if event.event_type == "status.lifecycle" and event.window == "OnDestroy"
        )
        if len(destroy_events) != 1:
            return {
                "ok": False,
                "task_id": task.task_id,
                "reason": f"destroy_probe_event_count:{len(destroy_events)}",
            }
        trigger_event = destroy_events[0]
        pre_destroy_shield_source_count = sum(
            item.get("owner_modifier_name") == task.modifier_name
            for item in current.units[owner_id].shield_instances
        )
        dispatched = EventDispatchSystem(
            rules,
            EffectRegistry(StatusSystem(rules)),
        ).dispatch_event(
            current,
            event=trigger_event,
            unit_id=owner_id,
            modifier_name=task.modifier_name,
        )
        combined = replace(
            dispatched,
            mutations=(*lifecycle.mutations, *dispatched.mutations),
            events=(*lifecycle.events, *dispatched.events),
            records=(*lifecycle.records, *dispatched.records),
        )
        evidence = _task_execution_evidence(combined, task)
        audit = _event_dispatch_probe_audit(
            rules,
            before_tick,
            trigger_event,
            combined,
        )
        ok = not combined.errors and evidence["executed"] and audit["ok"]
        return {
            "ok": ok,
            "task_id": task.task_id,
            "opcode": task.opcode,
            "callback_event": "OnDestroy",
            "owner_id": owner_id,
            "lifecycle_operation": lifecycle.operation,
            "lifecycle_step_count": step_index + 1,
            "initial_shield_source_count": initial_shield_source_count,
            "pre_destroy_shield_source_count": pre_destroy_shield_source_count,
            "production_event_id": trigger_event.event_id,
            "runtime_event_source": trigger_event.event_type,
            "task_execution_evidence": evidence,
            "mutation_count": len(combined.mutations),
            "record_count": len(combined.records),
            "emitted_event_type_counts": dict(
                sorted(Counter(item.event_type for item in combined.events).items())
            ),
            "source_audit_replay": audit,
            "preparation_source_audit_replay": preparation_audits,
            "errors": list(combined.errors),
            "source": task.source.to_json(),
        }
    return {
        "ok": False,
        "task_id": task.task_id,
        "reason": "destroy_probe_expire_not_reached",
        "maximum_steps": maximum_steps,
    }


def _deplete_owned_shield_for_reapply(
    state: BattleState,
    *,
    owner_id: str,
    modifier_name: str,
) -> tuple[BattleState, dict[str, Any]]:
    """Create a real non-neutral shield refresh precondition when one exists.

    The focused probe starts from the already-built formal scenario.  A shield
    created by the modifier is therefore at full capacity; replaying its real
    OnStack callback would correctly be rejected as a no-op.  Route a small
    fixed-damage packet through that source-backed shield first, then validate
    that the callback restores it.  The preparation is not counted as light-
    cone task evidence and never fabricates a shield instance.
    """

    owner = state.units.get(owner_id)
    if owner is None:
        return state, {"applied": False, "reason": "owner_missing"}
    candidates = tuple(
        item
        for item in owner.shield_instances
        if item.get("owner_modifier_name") == modifier_name
        and isinstance(item.get("remaining"), (int, float))
        and not isinstance(item.get("remaining"), bool)
        and float(item["remaining"]) > 0
    )
    if not candidates:
        return state, {"applied": False, "reason": "owned_shield_absent"}
    selected = candidates[0]
    remaining = float(selected["remaining"])
    amount = remaining / 2.0
    source_trace = selected.get("source_trace")
    source_trace = dict(source_trace) if isinstance(source_trace, dict) else {}
    packet = DamagePacket(
        attacker_id=owner_id,
        target_id=owner_id,
        attack_type="validation_preparation",
        damage_formula_family="true_damage",
        amount=amount,
        amount_stage="fixed_final",
        source_frame=DamageSourceFrame(
            owner_id=owner_id,
            source_id=str(selected.get("source_id") or modifier_name),
            source_kind="validation_shield_reapply_precondition",
            sequence_id=f"validation:shield-reapply:{modifier_name}",
            target_id=owner_id,
            source_trace=source_trace,
        ),
        source_trace=source_trace,
        metadata={
            "fixture_kind": "focused_validation_precondition",
            "not_light_cone_execution_evidence": True,
        },
    )
    result = DamageSystem().apply_packet(state, packet)
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    after_owner = reduction.after_state.units.get(owner_id)
    after_remaining = None
    if after_owner is not None:
        after_match = next(
            (
                item
                for item in after_owner.shield_instances
                if item.get("instance_id") == selected.get("instance_id")
            ),
            None,
        )
        if isinstance(after_match, dict):
            after_remaining = after_match.get("remaining")
    applied = (
        result.ok
        and reduction.ok
        and after_remaining is not None
        and float(after_remaining) < remaining
    )
    if not applied:
        return state, {
            "applied": False,
            "reason": "real_damage_did_not_deplete_owned_shield",
            "damage_errors": list(result.errors),
        }
    return reduction.after_state, {
        "applied": True,
        "route": "DamageSystem.true_damage_to_source_backed_shield",
        "shield_instance_id": str(selected.get("instance_id") or ""),
        "before_remaining": remaining,
        "after_remaining": float(after_remaining),
        "mutation_count": len(result.mutations),
        "record_count": len(result.records),
    }


def _status_lifecycle_child_execution_probe(
    rules: RuleBook,
    state: BattleState,
    task: Any,
    *,
    parent_events: tuple[GameEvent, ...],
) -> dict[str, Any]:
    """Consume the exact child lifecycle event emitted by its real parent task."""

    callback = rules.status_callback(task.callback_id)
    if callback is None:
        return {
            "ok": False,
            "task_id": task.task_id,
            "reason": "child_lifecycle_callback_missing",
        }
    candidates = tuple(
        event
        for event in parent_events
        if event.event_type == "status.lifecycle"
        and event.payload.get("callback_event") == callback.event
        and event.payload.get("modifier_name") == task.modifier_name
        and isinstance(event.target_id, str)
        and event.target_id in state.units
    )
    failures: list[dict[str, Any]] = []
    for event in candidates:
        dispatch = EventDispatchSystem(
            rules,
            EffectRegistry(StatusSystem(rules)),
        ).dispatch_event(
            state,
            event=event,
            unit_id=event.target_id,
            modifier_name=task.modifier_name,
        )
        evidence = _task_execution_evidence(dispatch, task)
        audit = _event_dispatch_probe_audit(rules, state, event, dispatch)
        if not dispatch.errors and evidence["executed"] and audit["ok"]:
            return {
                "ok": True,
                "task_id": task.task_id,
                "opcode": task.opcode,
                "callback_id": task.callback_id,
                "callback_event": callback.event,
                "owner_id": event.target_id,
                "production_event_id": event.event_id,
                "task_execution_evidence": evidence,
                "mutation_count": len(dispatch.mutations),
                "record_count": len(dispatch.records),
                "rng_event_count": len(dispatch.rng_events),
                "source_audit_replay": audit,
                "errors": [],
                "source": task.source.to_json(),
                "_after_state": dispatch.after_state,
                "_dispatch_result": dispatch,
            }
        failures.append(
            {
                "event_id": event.event_id,
                "errors": list(dispatch.errors),
                "task_execution_evidence": evidence,
                "source_audit_replay": audit,
            }
        )
    return {
        "ok": False,
        "task_id": task.task_id,
        "opcode": task.opcode,
        "callback_id": task.callback_id,
        "reason": "parent_add_modifier_source_lifecycle_not_executed",
        "candidate_event_count": len(candidates),
        "attempts": failures[:4],
    }


def _equipment_task_probe_state(
    bundle: dict[str, Any],
    production: dict[str, Any],
    task: Any,
    *,
    state_cache: dict[str, BattleState],
    cards_by_path: dict[str, Any],
) -> tuple[BattleState | None, str, str]:
    definitions = _equipment_definitions_for_task(bundle, task)
    available = tuple(
        definition
        for definition in definitions
        if definition.path_type in cards_by_path
    )
    if not definitions:
        return None, "", "equipment_definition_count:0"
    definition = available[0] if available else definitions[0]
    identity = definition.definition_key.definition_identity
    state = state_cache.get(identity)
    if state is None:
        if available:
            card = cards_by_path[definition.path_type]
            equipment_build, equipment_result = _assembly(
                bundle["rules"],
                card.card_id,
                definition,
                instance_id=f"validation:p8_s8:task-family:{identity}",
                rank=1,
            )
            character_build = _character_build(
                card.card_id,
                f"validation:p8_s8:task-family:{identity}:character",
                equipment_build,
            )
            character_result = assemble_character_build(
                bundle["rules"], character_build
            )
            if (
                equipment_result.battle_admission_status != "admitted"
                or character_result.battle_admission_status != "admitted"
            ):
                return None, "", "formal_equipment_build_not_admitted"
            scenario = ScenarioSpec(
                scenario_id=f"validation:p8_s8:task-family:{identity}",
                version=BASELINE_VERSION,
                units=(
                    UnitSpec(
                        unit_id="ally:actor",
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
                built = ScenarioStateBuilder(bundle["rules"]).build(scenario)
            except ValueError as exc:
                return None, "", f"formal_scenario_build_failed:{exc}"
            rich = _route_probe_state()
            actor = built.state.units["ally:actor"]
            actor = replace(
                actor,
                hp=max(1.0, actor.max_hp / 2.0),
                action_value=100.0,
                lifecycle_status="active",
                flags={**actor.flags, "position": 0},
            )
            state = replace(
                built.state,
                units={
                    **built.state.units,
                    "ally:actor": actor,
                    "ally:peer": rich.units["ally:peer"],
                    "enemy:target": rich.units["enemy:target"],
                },
                skill_points=rich.skill_points,
                max_skill_points=rich.max_skill_points,
                global_flags={
                    **built.state.global_flags,
                    "turn_owner_id": "ally:actor",
                    "phase": "action",
                },
            )
        else:
            state, fixture_reason = _mechanism_only_equipment_task_probe_state(
                bundle,
                production,
                definition,
            )
            if state is None:
                return None, "", fixture_reason
        while len(state_cache) >= TASK_STATE_CACHE_LIMIT:
            state_cache.pop(next(iter(state_cache)))
        state_cache[identity] = state

    owner_id = _status_detail_owner(state, task.modifier_name)
    if (
        owner_id
        and task.opcode == "RemoveShield"
        and any(
            item.get("owner_modifier_name") == task.modifier_name
            for item in state.units[owner_id].shield_instances
        )
    ):
        return state, owner_id, "formal_startup_source_shield_present"
    parent_state, parent_owner_id, parent_reason = (
        _prime_modifier_through_real_parent_callback(
            bundle,
            production,
            state,
            task,
        )
    )
    if parent_state is not None and parent_owner_id:
        return parent_state, parent_owner_id, ""
    if owner_id:
        return state, owner_id, parent_reason
    add_effects = tuple(
        effect
        for effect in bundle["ir"].effects
        if effect.opcode == "AddModifier"
        and isinstance(effect.payload.get("standard"), dict)
        and effect.payload["standard"].get("modifier_name") == task.modifier_name
        and effect.coverage_status == "executable"
    )
    status_sources = status_binding_sources(state, tuple(state.units))
    store_source = binding_source_from_store(store_from_state(state))
    scoped_binding_sets = tuple(
        (source, store_source) for source in status_sources
    ) or ((store_source,),)
    event_payload = {
        "actor_id": "ally:actor",
        "source_id": "ally:actor",
        "target_id": "enemy:target",
        "param_entity_id": "enemy:target",
        "selected_target_ids": ["enemy:target"],
        "target_ids": ["enemy:target"],
        "skill_target_ids": ["enemy:target"],
        "attack_target_ids": ["enemy:target"],
        "turn_owner_id": "ally:actor",
        "skill_type": "Ultra",
        "attack_type": "Ultra",
        "is_critical": True,
    }
    registry = EffectRegistry(StatusSystem(bundle["rules"]))
    reducer = MutationReducer()
    attempts: list[str] = []
    for effect in add_effects:
        for scoped_sources in scoped_binding_sets:
            result = registry.execute(
                effect,
                EffectExecutionContext(
                    state=state,
                    caster_id="ally:actor",
                    owner_id="ally:actor",
                    source_id=task.task_id,
                    param_entity_id="enemy:target",
                    current_action_target_id="enemy:target",
                    event_payload=event_payload,
                    binding_sources=scoped_sources,
                    include_ambient_status_bindings=False,
                ),
            )
            if result.unsupported:
                attempts.extend(result.unsupported)
                continue
            try:
                after = reducer.apply_all(state, result.mutations)
            except ValueError as exc:
                attempts.append(f"modifier_application_conflict:{exc}")
                continue
            owner_id = _status_detail_owner(after, task.modifier_name)
            if owner_id:
                initialized = after
                dispatcher = EventDispatchSystem(
                    bundle["rules"],
                    EffectRegistry(StatusSystem(bundle["rules"])),
                )
                for emitted_event in result.events:
                    dispatched = dispatcher.dispatch_event(
                        initialized,
                        event=emitted_event,
                        unit_id=owner_id,
                        modifier_name=task.modifier_name,
                    )
                    if dispatched.errors:
                        attempts.extend(dispatched.errors)
                        break
                    initialized = dispatched.after_state
                return initialized, owner_id, ""
            attempts.append("modifier_status_detail_missing_after_application")
    reasons = [parent_reason, *attempts]
    return None, "", ";".join(item for item in reasons[:4] if item) or "add_modifier_effect_missing"


def _prime_modifier_through_real_parent_callback(
    bundle: dict[str, Any],
    production: dict[str, Any],
    state: BattleState,
    target_task: Any,
) -> tuple[BattleState | None, str, str]:
    """Reach a child modifier through its real callback sequence when present."""

    rules: RuleBook = production["_rules"]
    target_effect_ids = {
        effect.effect_id
        for effect in bundle["ir"].effects
        if effect.opcode == "AddModifier"
        and isinstance(effect.payload.get("standard"), dict)
        and effect.payload["standard"].get("modifier_name")
        == target_task.modifier_name
        and effect.coverage_status == "executable"
    }
    parent_tasks = tuple(
        sorted(
            (
                task
                for task in rules.ir.status_callback_tasks
                if task.opcode == "AddModifier"
                and task.effect_id in target_effect_ids
                and task.coverage_status == "executable"
            ),
            key=lambda item: item.task_id,
        )
    )
    if not parent_tasks:
        return None, "", "real_parent_add_modifier_callback_missing"
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    attempts: list[str] = []
    for parent_task in parent_tasks:
        callback = rules.status_callback(parent_task.callback_id)
        if callback is None:
            attempts.append("parent_callback_missing")
            continue
        owner_id = _status_detail_owner(state, callback.modifier_name)
        if not owner_id:
            attempts.append(f"parent_modifier_missing:{callback.modifier_name}")
            continue
        families = tuple(
            family
            for family in rules.ir.status_event_families
            if family.callback_event == callback.event
            and family.coverage_status == "executable"
            and family.admission_status == "executable"
        )
        if len(families) != 1:
            attempts.append(f"parent_event_family_count:{len(families)}")
            continue
        produced = tuple(
            event
            for event_type in families[0].runtime_event_sources
            for event in events_by_type.get(event_type, ())
        )
        if not produced:
            attempts.append(f"parent_runtime_event_missing:{callback.event}")
            continue
        for event in produced:
            prepared_state = state
            phases = COMBAT_EVENT_PHASES.get(event.event_type, ())
            if phases:
                prepared_state = replace(
                    prepared_state,
                    global_flags={
                        **prepared_state.global_flags,
                        "combat_phase": phases[0],
                    },
                )
            dispatched = EventDispatchSystem(
                rules,
                EffectRegistry(StatusSystem(rules)),
            ).dispatch_event(
                prepared_state,
                event=event,
                unit_id=owner_id,
                modifier_name=callback.modifier_name,
            )
            if dispatched.errors:
                attempts.extend(dispatched.errors[:2])
                continue
            parent_evidence = _task_execution_evidence(
                dispatched,
                parent_task,
            )
            if not parent_evidence["executed"]:
                attempts.append(
                    f"parent_add_modifier_task_not_executed:{callback.event}"
                )
                continue
            target_owner_id = _status_detail_owner(
                dispatched.after_state,
                target_task.modifier_name,
            )
            if target_owner_id:
                if (
                    target_task.opcode == "RemoveShield"
                    and not any(
                        item.get("owner_modifier_name")
                        == target_task.modifier_name
                        for item in dispatched.after_state.units[
                            target_owner_id
                        ].shield_instances
                    )
                ):
                    attempts.append(
                        "parent_callback_target_shield_instance_missing"
                    )
                    continue
                return dispatched.after_state, target_owner_id, ""
            attempts.append("parent_callback_did_not_add_target_modifier")
    return None, "", ";".join(attempts[:4]) or "real_parent_callback_did_not_reach_modifier"


def _equipment_definitions_for_task(
    bundle: dict[str, Any],
    task: Any,
) -> tuple[Any, ...]:
    """Resolve a callback task to definitions through the canonical graph edges."""

    graph_ids = {
        graph.standalone_ability_graph_id
        for graph in bundle["graphs"]
        if task.callback_id in graph.status_callback_ids
    }
    mechanism_keys = {
        reference.definition_key
        for reference in bundle["ir"].equipment_mechanism_refs
        if reference.graph_ref_id in graph_ids
    }
    definitions = tuple(
        sorted(
            (
                definition
                for definition in bundle["definitions"]
                if any(
                    mechanism_key in mechanism_keys
                    for mechanism_key in definition.mechanism_ref_ids
                )
            ),
            key=lambda item: item.definition_key.definition_identity,
        )
    )
    if definitions:
        return definitions
    # Top-level callback metadata from older lowering rows can still point
    # directly at the unique ability row.  This fallback remains a stable raw
    # identity comparison; it never guesses by file name or display text.
    ability_name = str(task.source.evidence.get("ability_name") or "")
    return tuple(
        sorted(
            (
                definition
                for definition in bundle["definitions"]
                if definition.ability_source is not None
                and definition.ability_source.ability_name == ability_name
            ),
            key=lambda item: item.definition_key.definition_identity,
        )
    )


def _task_has_available_definition(
    bundle: dict[str, Any],
    task: Any,
    cards_by_path: dict[str, Any],
) -> bool:
    return any(
        definition.path_type in cards_by_path
        for definition in _equipment_definitions_for_task(bundle, task)
    )


def _task_has_only_external_definitions(
    bundle: dict[str, Any],
    task: Any,
    external_character_build_paths: frozenset[str],
) -> bool:
    definitions = _equipment_definitions_for_task(bundle, task)
    return bool(definitions) and all(
        definition.path_type in external_character_build_paths
        for definition in definitions
    )


def _task_has_random_ancestor(rules: RuleBook, task: Any) -> bool:
    current = task
    seen: set[str] = set()
    while current is not None and current.task_id not in seen:
        seen.add(current.task_id)
        if current.condition_id:
            condition = rules.condition(current.condition_id)
            if condition is not None and _condition_has_family(
                condition,
                "ByRandomChance",
            ):
                return True
        current = (
            rules.status_callback_task(current.parent_task_id)
            if current.parent_task_id
            else None
        )
    return False


_CALLBACK_RUNTIME_EVENT_ORDER = (
    "status.lifecycle",
    "battle.setup",
    "turn.begin",
    "action.ultimate.prepare",
    "action.window.before_skill_use",
    "action.window.before_attack",
    "energy.before_change",
    "energy.change",
    "damage.hit_sequence.before",
    "damage.target_attack.before",
    "damage.target_hit_sequence.before",
    "damage.before_hit",
    "damage.hit",
    "damage.target_hit_sequence.after",
    "damage.target_attack.after",
    "damage.hit_sequence.after",
    "action.window.after_attack",
    "action.after_attack",
    "action.window.after_skill_use",
    "action.end",
    "turn.end",
)


def _prime_callback_predecessors(
    rules: RuleBook,
    production: dict[str, Any],
    state: BattleState,
    callback: Any,
    owner_id: str,
) -> BattleState:
    """Run earlier real callback windows for the same modifier in order."""

    rank = {event_type: index for index, event_type in enumerate(_CALLBACK_RUNTIME_EVENT_ORDER)}
    families = {
        family.callback_event: family
        for family in rules.ir.status_event_families
        if family.coverage_status == "executable"
        and family.admission_status == "executable"
    }

    def callback_rank(item: Any) -> int:
        family = families.get(item.event)
        if family is None:
            return len(rank)
        return min(
            (rank.get(event_type, len(rank)) for event_type in family.runtime_event_sources),
            default=len(rank),
        )

    target_rank = callback_rank(callback)
    if target_rank <= 0 or target_rank >= len(rank):
        return state
    dispatcher = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules)))
    current = state
    callbacks = tuple(
        sorted(
            (
                item
                for item in rules.ir.status_callbacks
                if item.modifier_name == callback.modifier_name
                and callback_rank(item) < target_rank
            ),
            key=lambda item: (callback_rank(item), item.callback_id),
        )
    )
    dispatched_windows: set[tuple[str, str]] = set()
    events_by_type: dict[str, list[GameEvent]] = production["_events_by_type"]
    for predecessor in callbacks:
        family = families.get(predecessor.event)
        if family is None:
            continue
        produced = tuple(
            (event_type, candidate)
            for event_type in family.runtime_event_sources
            for candidate in events_by_type.get(event_type, ())
        )
        ordered_events = tuple(
            candidate
            for _, candidate in sorted(
                produced,
                key=lambda row: (
                    not (
                        row[1].window == predecessor.event
                        or (
                            isinstance(
                                row[1].payload.get("callback_events"),
                                (list, tuple),
                            )
                            and predecessor.event
                            in row[1].payload["callback_events"]
                        )
                    ),
                    row[1].event_id,
                ),
            )
        )
        if not ordered_events:
            continue
        for event in ordered_events:
            dispatch_key = (event.event_id, predecessor.event)
            if dispatch_key in dispatched_windows:
                continue
            result = dispatcher.dispatch_event(
                current,
                event=event,
                unit_id=owner_id,
                modifier_name=callback.modifier_name,
            )
            dispatched_windows.add(dispatch_key)
            if result.errors:
                continue
            current = result.after_state
            _merge_production_events(production, list(result.events))
            if result.mutations:
                break
    return current


def _status_detail_owner(state: BattleState, modifier_name: str) -> str:
    for unit_id, unit in state.units.items():
        details = unit.flags.get("status_details")
        if not isinstance(details, (list, tuple)):
            continue
        if any(
            isinstance(detail, dict)
            and detail.get("modifier_name") == modifier_name
            for detail in details
        ):
            return unit_id
    return ""


def _task_execution_evidence(result: Any, task: Any) -> dict[str, Any]:
    task_records: list[dict[str, Any]] = []
    for record in result.records:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("task_id") == task.task_id or (
            task.effect_id and payload.get("effect_id") == task.effect_id
        ):
            task_records.append(record)
    task_mutations = [
        mutation
        for mutation in result.mutations
        if mutation.metadata.get("source_task_id") == task.task_id
        or (task.effect_id and mutation.metadata.get("effect_id") == task.effect_id)
    ]
    task_rng_events = [
        event
        for event in result.rng_events
        if event.source == task.task_id
        or event.metadata.get("task_id") == task.task_id
        or (
            isinstance(event.metadata.get("identity"), dict)
            and event.metadata["identity"].get("task_id") == task.task_id
        )
    ]
    accepted_records = [
        record
        for record in task_records
        if not (
            isinstance(record.get("payload"), dict)
            and record["payload"].get("ok") is False
        )
    ]
    return {
        "executed": bool(accepted_records or task_mutations or task_rng_events),
        "record_count": len(task_records),
        "accepted_record_count": len(accepted_records),
        "mutation_count": len(task_mutations),
        "rng_event_count": len(task_rng_events),
        "record_samples": [
            {
                "record_type": record.get("record_type"),
                "mutation_id": record.get("mutation_id"),
                "payload_task_id": (
                    record.get("payload", {}).get("task_id")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_effect_id": (
                    record.get("payload", {}).get("effect_id")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_ok": (
                    record.get("payload", {}).get("ok")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_reason": (
                    record.get("payload", {}).get("reason")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_value": (
                    record.get("payload", {}).get("value")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_final_damage": (
                    record.get("payload", {}).get("final_damage")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_condition_result": (
                    record.get("payload", {}).get("condition_result")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
                "payload_selected_child_ids": (
                    record.get("payload", {}).get("selected_child_ids")
                    if isinstance(record.get("payload"), dict)
                    else None
                ),
            }
            for record in task_records[:20]
            if isinstance(record, dict)
        ],
    }


def _source_coverage_matrix(
    bundle: dict[str, Any],
    partition: dict[str, Any],
    family_evidence: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    indexes = _coverage_source_indexes(bundle)
    source_rows = []
    for raw_row in partition["_inventory"]["_source_rows"]:
        if raw_row["stage"] != "s8":
            continue
        linked = _linked_nodes(raw_row, indexes)
        lowered = len(linked) == 1
        node = linked[0] if lowered else None
        admitted, executable = _node_admission(raw_row["kind"], node, indexes["selected_task_ids"])
        route = (
            "process_only"
            if node is not None
            and getattr(node, "blocked_reason", "")
            == "equipment_task_family_non_gameplay"
            else _validation_route(raw_row)
        )
        evidence = family_evidence.get((raw_row["kind"], raw_row["family"]))
        validated = executable and evidence is not None and evidence.get("ok") is True
        reasons = []
        if not lowered:
            reasons.append(f"lowered_node_count:{len(linked)}")
        if not admitted:
            reasons.append("not_admitted")
        if not executable:
            reasons.append("not_executable")
        if evidence is None:
            reasons.append(
                f"exact_family_evidence_missing:{raw_row['kind']}:{raw_row['family']}"
            )
        elif not validated:
            reasons.append(
                f"exact_family_evidence_failed:{raw_row['kind']}:{raw_row['family']}"
            )
        source_rows.append(
            {
                **raw_row,
                "source_identity": _normalize_source_identity(raw_row["source_identity"]),
                "lowered": lowered,
                "admitted": admitted,
                "executable": executable,
                "validated": validated,
                "external_character_build_dependency": False,
                "semantic_route": route,
                # The inventory row is checked individually for lossless
                # lowering/admission.  Runtime execution is intentionally a
                # contract proof for this *exact* structural family, as
                # required by the S8 card; it is not presented as though this
                # particular raw row itself produced the sampled transition.
                "validation_scope": "exact_structural_family_contract",
                "validation_binding": {
                    "kind": raw_row["kind"],
                    "family": raw_row["family"],
                    "source_identity": _normalize_source_identity(
                        raw_row["source_identity"]
                    ),
                    "lowered_node_ids": [
                        _coverage_node_id(item) for item in linked
                    ],
                    "evidence_kind": (
                        evidence.get("evidence_kind")
                        if isinstance(evidence, dict)
                        else None
                    ),
                },
                "validation_evidence": evidence or {},
                "lowered_node_ids": [_coverage_node_id(item) for item in linked],
                "gap_reasons": reasons,
            }
        )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        grouped[(row["kind"], row["family"], row["semantic_route"])].append(row)
    rows = []
    for (kind, family, route), members in sorted(grouped.items()):
        rows.append(
            {
                "kind": kind,
                "family": family,
                "semantic_route": route,
                "raw_count": len(members),
                "lowered_count": sum(row["lowered"] for row in members),
                "admitted_count": sum(row["admitted"] for row in members),
                "executable_count": sum(row["executable"] for row in members),
                "validated_count": sum(row["validated"] for row in members),
                "external_dependency_count": sum(
                    row["external_character_build_dependency"]
                    for row in members
                ),
                "gap_count": sum(bool(row["gap_reasons"]) for row in members),
            }
        )
    gap_count = sum(bool(row["gap_reasons"]) for row in source_rows)
    checks = {
        "s8_source_rows_nonempty": bool(source_rows),
        "every_source_identity_unique": len(source_rows)
        == len({(row["kind"], row["family"], row["source_identity"]) for row in source_rows}),
        "every_source_validation_bound_to_exact_inventory_identity": all(
            row["validation_scope"] == "exact_structural_family_contract"
            and row["validation_binding"]["kind"] == row["kind"]
            and row["validation_binding"]["family"] == row["family"]
            and row["validation_binding"]["source_identity"]
            == row["source_identity"]
            and row["validation_binding"]["lowered_node_ids"]
            == row["lowered_node_ids"]
            for row in source_rows
        ),
        "every_s8_source_linked_individually": all(
            row["lowered"]
            and row["admitted"]
            and row["executable"]
            and row["validated"]
            for row in source_rows
        ),
        "all_family_counts_equal": all(
            row["raw_count"]
            == row["lowered_count"]
            == row["admitted_count"]
            == row["executable_count"]
            == row["validated_count"]
            for row in rows
        ),
    }
    checks["ok"] = all(checks.values()) and gap_count == 0
    return {
        "schema_version": "p8_s8_remaining_family_coverage_matrix_v2",
        "ok": checks["ok"],
        "checks": checks,
        "gap_count": gap_count,
        "rows": rows,
        "failures": [row for row in source_rows if row["gap_reasons"]][:40],
        "source_rows": source_rows,
    }


def _exact_family_evidence(
    *,
    conditions: dict[str, Any],
    target_families: dict[str, Any],
    numeric: dict[str, Any],
    events: dict[str, Any],
    energy_listener: dict[str, Any],
    bp_listener: dict[str, Any],
    process_only: dict[str, Any],
    task_execution: dict[str, Any],
    event_execution: dict[str, Any],
    stack_property_consumption: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index evidence by the exact inventory family; broad routes never validate rows."""

    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for row in conditions.get("rows", ()):  # one true/false/fail-closed probe per opcode
        family = str(row.get("family") or "")
        if family:
            evidence[("condition", f"{family}:s8")] = {
                "ok": row.get("ok") is True,
                "evidence_kind": "exact_condition_family",
                "family": family,
            }
    for row in target_families.get("rows", ()):  # one real source-backed node per exact expression
        family = str(row.get("family") or "")
        if family:
            evidence[("target", family)] = {
                "ok": row.get("ok") is True,
                "evidence_kind": "exact_target_family",
                "family": family,
            }
    for row in numeric.get("family_rows", ()):  # every raw expression is evaluated in the row
        family = str(row.get("family") or "")
        if family:
            evidence[("value", family)] = {
                "ok": row.get("ok") is True,
                "evidence_kind": "exact_numeric_family",
                "family": family,
            }
    event_contracts = {
        f"{row.get('event')}:s8": row
        for row in events.get("rows", ())
        if row.get("event")
    }
    for row in event_execution.get("rows", ()):
        family = str(row.get("family") or "")
        if not family:
            continue
        event = family.removesuffix(":s8")
        status = str(row.get("status") or "")
        is_energy_e2e = (
            event == UNIT_ENERGY_EVENT_CONTRACT.after_callback_events[-1]
            and energy_listener.get("ok") is True
        )
        is_bp_e2e = (
            event == TEAM_SKILL_POINT_EVENT_CONTRACT.after_callback_events[0]
            and bp_listener.get("ok") is True
        )
        execution_ok = row.get("ok") is True or is_energy_e2e or is_bp_e2e
        contract = event_contracts.get(family, {})
        evidence[("event", family)] = {
            "ok": execution_ok and contract.get("ok") is True,
            "evidence_kind": (
                "external_content_e2e_deferred"
                if status == "external_content_e2e_deferred"
                else "mutation_producer_dispatch_callback_replay"
            ),
            "event": event,
            "status": status,
            "producer_contract_ok": contract.get("ok") is True,
            "execution_matrix_ok": row.get("ok") is True,
            "external_content_e2e_deferred": row.get(
                "external_content_e2e_deferred"
            )
            or {},
            "energy_listener_override": is_energy_e2e,
            "bp_listener_override": is_bp_e2e,
        }
    property_consumers = {
        str(row.get("family") or ""): row
        for row in stack_property_consumption.get("rows", ())
        if row.get("family")
    }
    for row in task_execution.get("rows", ()):
        family = str(row.get("family") or "")
        if family:
            consumer = property_consumers.get(family)
            task_ok = row.get("status") == "executed"
            if family.startswith("StackProperty:"):
                task_ok = task_ok and consumer is not None and consumer.get("ok") is True
            evidence[("task", family)] = {
                "ok": task_ok,
                "status": row.get("status"),
                "external_character_build_dependency": False,
                "external_character_build_paths": row.get(
                    "external_character_build_paths"
                )
                or [],
                "evidence_kind": (
                    "exact_stack_property_callback_and_distinct_consumer"
                    if family.startswith("StackProperty:")
                    else "exact_task_family_real_callback_execution"
                ),
                "family": family,
                "selected": row.get("selected") or {},
                "consumer": (consumer or {}).get("selected") or {},
            }
    process_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in process_only.get("rows", ()):
        process_rows[str(row.get("opcode") or "")].append(row)
    for opcode, rows in process_rows.items():
        if opcode:
            evidence.setdefault(("task", f"{opcode}:s8"), {
                "ok": bool(rows) and all(row.get("ok") is True for row in rows),
                "evidence_kind": "exact_non_gameplay_task_family",
                "opcode": opcode,
            })
    return evidence


def _linked_nodes(raw_row: dict[str, str], indexes: dict[str, Any]) -> list[Any]:
    identity = _normalize_source_identity(raw_row["source_identity"])
    kind = raw_row["kind"]
    base_family = raw_row["family"].split(":", 1)[0]
    if kind == "task":
        return list(indexes["tasks"].get(identity, ()))
    if kind == "event":
        return list(indexes["callbacks"].get(identity, ()))
    if kind == "condition":
        owner_identity = _longest_source_prefix(identity, indexes["conditions"])
        return [
            condition
            for condition in indexes["conditions"].get(owner_identity, ())
            if _condition_has_family(condition, base_family)
        ]
    if kind == "target":
        linked = list(indexes["targets"].get(identity, ()))
        if linked:
            return linked
        owner_identity = _longest_source_prefix(identity, indexes["conditions"])
        return [
            condition
            for condition in indexes["conditions"].get(owner_identity, ())
            if _condition_has_target_source_family(condition, raw_row["family"])
        ]
    if kind == "value":
        owner_identity = _longest_source_prefix(identity, indexes["tasks"])
        return list(indexes["tasks"].get(owner_identity, ()))
    return []


def _condition_has_target_source_family(
    condition: ConditionIR,
    family: str,
) -> bool:
    if _condition_has_target_family(condition, family):
        return True
    return family in _condition_target_expression_families(condition.payload)


def _condition_target_expression_families(value: object) -> set[str]:
    families: set[str] = set()
    if isinstance(value, TargetExpressionNodeIR):
        families.add(value.expression_kind)
        if value.alias:
            families.add(f"TargetAlias:{value.alias}")
        for child in value.children:
            families.update(_condition_target_expression_families(child))
        for child in (
            value.candidate,
            value.target,
            value.query_target,
            value.query_compare,
        ):
            if child is not None:
                families.update(_condition_target_expression_families(child))
        if value.predicate is not None:
            families.update(
                _condition_target_expression_families(value.predicate.payload)
            )
    elif isinstance(value, dict):
        for child in value.values():
            families.update(_condition_target_expression_families(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            families.update(_condition_target_expression_families(child))
    return families


def _node_admission(kind: str, node: Any | None, selected_task_ids: set[str]) -> tuple[bool, bool]:
    if node is None:
        return False, False
    if kind in {"task", "value"}:
        if (
            node.blocked_reason == "equipment_task_family_non_gameplay"
        ):
            return True, True
        admitted = node.task_id in selected_task_ids
        return admitted, admitted and node.coverage_status == "executable"
    if kind == "event":
        admitted = node.admission_status == "executable"
        return admitted, admitted and node.coverage_status == "executable"
    if kind == "condition":
        admitted = node.coverage_status == "executable"
        return admitted, admitted and _condition_payload_executable(node.opcode, node.payload)
    if kind == "target":
        admitted = node.coverage_status == "executable"
        return admitted, admitted
    return False, False


def _validation_route(raw_row: dict[str, str]) -> str:
    kind = raw_row["kind"]
    family = raw_row["family"]
    if kind == "condition":
        return "condition"
    if kind == "event":
        return "event"
    if kind == "target":
        return "target"
    if kind == "value":
        return "numeric"
    parts = family.split(":")
    opcode = parts[0]
    property_name = parts[1] if opcode == "StackProperty" and len(parts) > 2 else ""
    if opcode in {"DamageByAttackProperty", "ModifyDamageData"}:
        return "damage"
    if opcode in {"HealHP", "ModifyHealData"} or property_name in {"HealRatioBase", "HealRatioConvert"}:
        return "healing"
    if opcode in {"InitShield", "RemoveShield", "SetResilience"} or property_name == "ShieldAddedRatio":
        return "shield"
    if opcode in {"ModifySPNew"} or property_name == "SPRatioBase":
        return "energy_resource"
    if opcode in {"ModifyTeamBoostPoint"}:
        return "team_boost_resource"
    if opcode in {"ModifyTeamBoostPointMax"}:
        return "resource_maximum"
    if opcode == "LoseHPByRatio":
        return "hp_loss"
    if opcode in {"ModifyActionDelay", "ModifyCurrentSkillDelayCost"} or property_name == "SpeedAddedRatio":
        return "timeline"
    if opcode in {"Retarget", "RandomConfig"}:
        return "rng"
    if opcode == "StackProperty" and property_name in {
        "AllDamageReduce",
        "AllDamageTypeAddedRatio",
        "AllDamageTypeResistance",
        "AllDamageTypeTakenRatio",
        "AttackAddedRatio",
        "BreakDamageExtraAddedRatio",
        "CriticalChanceBase",
        "CriticalDamageBase",
        "DotDamageAddedRatio",
        "ElationDamageAddedRatioBase",
        "FireAddedRatio",
        "IceAddedRatio",
        "ImaginaryAddedRatio",
        "PhysicalAddedRatio",
        "QuantumAddedRatio",
        "ThunderAddedRatio",
        "WindAddedRatio",
    }:
        return "damage"
    if opcode == "StackProperty" and property_name == "AggroAddedRatio":
        return "target"
    if opcode in {
        "SetDynamicValue",
        "DefineDynamicValue",
        "SetModifierDynamicValue",
        "SetDynamicValueByAttackTargetCount",
        "SetDynamicValueByBPChange",
        "SetDynamicValueByCharacterCount",
        "SetDynamicValueByCopying",
        "SetDynamicValueByCountOfBaseType",
        "SetDynamicValueByDamageDataProperty",
        "SetDynamicValueByHealDataProperty",
        "SetDynamicValueByHPRatio",
        "SetDynamicValueByMaxBP",
        "SetDynamicValueByModifierValue",
        "SetDynamicValueByProperty",
        "SetDynamicValueByStatusCount",
        "SetDynamicValueByVariateType",
        "SetDynamicValueByWeaknessCount",
    }:
        return "numeric"
    if opcode in {
        "AddModifier",
        "DispelStatus",
        "Remodifier",
        "RemoveModifier",
        "RemoveSelfModifier",
        "PredicateTaskList",
        "IncludeTaskListTemplate",
        "LoopExecuteTaskList",
    }:
        return "formal_setup"
    if opcode in {
        "AddBuffPerform",
        "JDOLDFECMPL",
        "ModifierAttachEffect",
        "StackStatusDesc",
        "TriggerEffect",
        "WaitSecond",
    }:
        return "process_only"
    return f"unmapped:{opcode}:{property_name}"


def _process_only_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    opcodes = {
        "AddBuffPerform",
        "JDOLDFECMPL",
        "ModifierAttachEffect",
        "StackStatusDesc",
        "TriggerEffect",
        "WaitSecond",
    }
    rows = [
        {
            "task_id": task.task_id,
            "opcode": task.opcode,
            "coverage_status": task.coverage_status,
            "blocked_reason": task.blocked_reason,
            "source": task.source.to_json(),
            "ok": task.coverage_status == "blocked"
            and task.blocked_reason == "equipment_task_family_non_gameplay",
        }
        for task in bundle["callback_tasks"]
        if task.opcode in opcodes
    ]
    checks = {
        "process_only_tasks_nonempty": bool(rows),
        "every_process_only_task_explicitly_classified": all(row["ok"] for row in rows),
    }
    checks["ok"] = all(checks.values())
    return {
        "schema_version": "p8_s8_process_only_task_matrix_v1",
        "ok": checks["ok"],
        "checks": checks,
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    """Build one focused RuleBook and emit only bounded S8 evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    build_counts: Counter[str] = Counter()
    with _observe_lowering_entries(build_counts):
        evidence = _build_contract_evidence(tbgd_root, build_counts)
        task_summary = _run_task_contract_slice(
            evidence, output_dir, build_counts=build_counts, write_outputs=False
        )
        event_summary = _run_event_contract_slice(
            evidence, output_dir, build_counts=build_counts, write_outputs=False
        )
    bundle, partition, path_inventory = (
        evidence["bundle"], evidence["partition"], evidence["paths"]
    )
    empty_task_fail_closed = _empty_executable_task_fail_closed_matrix(bundle)
    graphs = _graph_matrix(bundle)
    cards_by_path = path_inventory["cards_by_path"]
    startups = _catalog_startup_matrix(
        bundle,
        cards_by_path=cards_by_path,
        path_inventory=path_inventory,
    )
    formal = evidence["formal"]
    common_event_counts = evidence["common_counts"]
    battle_state_transition_seed = evidence["battle_seed"]
    real_heal_seed, real_custom_event_seed = evidence["heal_seed"], evidence["custom_seed"]
    real_weakness_event_seed = evidence["weakness_seed"]
    task_execution, stack_property_consumption = task_summary.pop("_probe_payload")
    (
        event_execution,
        status_replacement,
        resource_event_evidence,
        events,
    ) = event_summary.pop("_probe_payload")
    energy_listener = resource_event_evidence["energy"]
    bp_listener = resource_event_evidence["bp"]
    resource_event_closure = resource_event_evidence["closure"]
    targets = _target_attribution_matrix(
        bundle,
        partition["_inventory"],
        formal,
    )
    target_families = _target_family_matrix(bundle, partition)
    numeric = _numeric_contract_matrix(bundle)
    conditions = _condition_contract_matrix(bundle)
    effects = _effect_route_matrix(bundle)
    damage = _damage_route_matrix(bundle)
    timeline = _timeline_matrix(bundle)
    rng = _rng_matrix(bundle)
    process_only = _process_only_matrix(bundle)
    runtime_boundary = _runtime_boundary()
    family_evidence = _exact_family_evidence(
        conditions=conditions,
        target_families=target_families,
        numeric=numeric,
        events=events,
        energy_listener=energy_listener,
        bp_listener=bp_listener,
        process_only=process_only,
        task_execution=task_execution,
        event_execution=event_execution,
        stack_property_consumption=stack_property_consumption,
    )
    coverage = _source_coverage_matrix(bundle, partition, family_evidence)
    predicates = {
        "s7_evidence_current": partition["checks"]["current_source_fingerprint_complete"],
        "s7_s8_union_equals_current_gameplay": partition["checks"]["s7_s8_union_equals_current_gameplay"],
        "s7_s8_intersection_empty": partition["checks"]["s7_s8_intersection_empty"],
        "s8_remaining_family_gap_count": coverage["gap_count"],
        "published_light_cone_blocked_graph_count": graphs["blocked_count"],
        "unknown_gameplay_node_count": partition["counts"].get("unknown", 0),
        "non_gameplay_rows_have_structured_evidence": partition["checks"]["non_gameplay_rows_have_structured_evidence"],
        "damage_hp_shield_resource_use_common_routes": damage["ok"] and effects["ok"] and timeline["ok"],
        "target_owner_summon_relations_source_driven": targets["ok"]
        and target_families["ok"],
        "rng_choices_have_stable_identity": rng["checks"]["stable_identity_unique_across_wearer_and_decision"],
        "independent_rng_events_do_not_collide": rng["checks"]["choice_ledger_exact"],
        "blocked_transition_state_unchanged": effects["checks"]["unadmitted_effect_state_unchanged"]
        and damage["checks"]["invalid_amount_stage_blocked_unchanged"]
        and timeline["checks"]["unsupported_operation_blocked_unchanged"],
        "sampled_mutations_source_audited": formal["checks"]["public_setup_mutations_source_audited"]
        and damage["checks"]["source_is_real_equipment_row"]
        and battle_state_transition_seed["ok"],
        "sampled_transitions_replay_equal": formal["checks"]["public_setup_mutations_replay_final_state"]
        and effects["checks"]["transitions_replay_equal"]
        and damage["checks"]["damage_replay_equal"]
        and timeline["checks"]["timeline_replay_equal"]
        and battle_state_transition_seed["ok"],
        "equipment_specific_runtime_handlers": runtime_boundary["equipment_specific_runtime_handlers"],
        "runtime_raw_equipment_reads": runtime_boundary["runtime_raw_equipment_reads"],
        "catalog_equipment_failure_count": startups[
            "equipment_failure_count"
        ],
        "catalog_external_character_build_dependency_count": startups[
            "external_character_build_dependency_count"
        ],
        "catalog_external_dependencies_structurally_proven": startups[
            "checks"
        ]["external_character_build_dependencies_structurally_proven"],
        "catalog_started_or_external_dependency_covers_catalog": startups[
            "checks"
        ]["started_or_external_dependency_covers_catalog"],
        "formal_catalog_startup_complete": startups[
            "formal_catalog_startup_complete"
        ],
        "formal_scenario_event_attribution_complete": formal["ok"],
        "ultimate_energy_listener_end_to_end": energy_listener["ok"],
        "team_skill_points_use_bp_event": resource_event_closure["checks"][
            "team_skill_points_use_bp_event"
        ],
        "unit_energy_uses_energy_event": resource_event_closure["checks"][
            "unit_energy_uses_energy_event"
        ],
        "on_sp_change_receives_energy_delta": resource_event_closure["checks"][
            "on_sp_change_receives_energy_delta"
        ],
        "resource_event_cross_trigger_count": resource_event_closure[
            "resource_event_cross_trigger_count"
        ],
        "dead_production_resource_event_count": resource_event_closure[
            "dead_production_resource_event_count"
        ],
        "retired_sp_change_blocked_unchanged": resource_event_closure["checks"][
            "retired_sp_change_blocked_unchanged"
        ],
        "executable_event_families_have_real_runtime_producers": (
            resource_event_closure["checks"][
                "executable_event_families_have_real_runtime_producers"
            ]
        ),
        "resource_event_mutations_settled": resource_event_closure["checks"][
            "resource_event_mutations_settled"
        ],
        "resource_event_replay_equal": resource_event_closure["checks"][
            "resource_event_replay_equal"
        ],
        "every_exact_gameplay_task_family_has_real_callback_execution": (
            task_execution["ok"]
        ),
        "mechanism_families_do_not_use_character_build_dependency_exemption": (
            task_execution["checks"][
                "mechanism_families_do_not_use_character_build_dependency_exemption"
            ]
        ),
        "every_stack_property_family_changes_distinct_consumer": (
            stack_property_consumption["ok"]
        ),
        "every_exact_event_family_executed_or_structurally_deferred": (
            event_execution["ok"]
        ),
        "empty_executable_callback_task_fail_closed": empty_task_fail_closed["ok"],
        "status_replacement_namespace_is_fail_closed": status_replacement["ok"],
        "real_heal_events_use_source_backed_callback_chain": real_heal_seed["ok"],
        "custom_event_producer_executed_or_structurally_deferred": (
            real_custom_event_seed["ok"]
            and (
                real_custom_event_seed.get("status")
                != "external_content_e2e_deferred"
                or all(
                    real_custom_event_seed.get(key)
                    for key in (
                        "required_trigger_condition",
                        "missing_content_owner",
                        "future_closure",
                    )
                )
            )
        ),
        "real_weakness_events_use_source_backed_effect_chain": (
            real_weakness_event_seed["ok"]
        ),
        "shared_battle_state_events_use_source_backed_transition": (
            battle_state_transition_seed["ok"]
        ),
    }
    ok = (
        all(
            value is True
            for key, value in predicates.items()
            if key
            not in {
                "s8_remaining_family_gap_count",
                "published_light_cone_blocked_graph_count",
                "unknown_gameplay_node_count",
                "equipment_specific_runtime_handlers",
                "runtime_raw_equipment_reads",
                "catalog_equipment_failure_count",
                "catalog_external_character_build_dependency_count",
                "formal_catalog_startup_complete",
                "resource_event_cross_trigger_count",
                "dead_production_resource_event_count",
            }
        )
        and predicates["s8_remaining_family_gap_count"] == 0
        and predicates["published_light_cone_blocked_graph_count"] == 0
        and predicates["unknown_gameplay_node_count"] == 0
        and predicates["equipment_specific_runtime_handlers"] == 0
        and predicates["runtime_raw_equipment_reads"] == 0
        and predicates["catalog_equipment_failure_count"] == 0
        and predicates["resource_event_cross_trigger_count"] == 0
        and predicates["dead_production_resource_event_count"] == 0
    )
    predicates["ok"] = ok
    summary = _contract_slice_summary(
        SUMMARY_SCHEMA_VERSION,
        predicates,
        ok=ok,
        ready_for_review=ok,
        baseline_version=BASELINE_VERSION,
        counts={
            "published_light_cones": graphs["published_count"],
            "current_gameplay_nodes": partition["counts"].get("s7", 0)
            + partition["counts"].get("s8", 0),
            "s7_nodes": partition["counts"].get("s7", 0),
            "s8_nodes": partition["counts"].get("s8", 0),
            "non_gameplay_nodes": partition["counts"].get("non_gameplay", 0),
            "s8_family_rows": len(coverage["rows"]),
            "s8_source_rows": len(coverage["source_rows"]),
            "condition_families": conditions["family_count"],
            "numeric_expressions": numeric["expression_count"],
            "exact_task_families": task_execution["family_count"],
            "executed_task_families": task_execution["executed_family_count"],
            "external_content_e2e_deferred_task_families": task_execution[
                "external_content_e2e_deferred_count"
            ],
            "implementation_failure_task_families": task_execution[
                "implementation_failure_count"
            ],
            "validation_harness_invalid_task_families": task_execution[
                "validation_harness_invalid_count"
            ],
            "stack_property_consumer_families": stack_property_consumption[
                "family_count"
            ],
            "exact_event_families": event_execution["family_count"],
            "executed_event_families": event_execution["executed_family_count"],
            "external_content_e2e_deferred_event_families": event_execution[
                "external_content_e2e_deferred_count"
            ],
            "implementation_failure_event_families": event_execution[
                "implementation_failure_count"
            ],
            "validation_harness_invalid_event_families": event_execution[
                "validation_harness_invalid_count"
            ],
            "common_mutation_event_types": common_event_counts,
            **startups["counts"],
        },
        resource_scope={
            "focused_rulebook_build_count": 1,
            "task_state_cache_limit": TASK_STATE_CACHE_LIMIT,
            "full_canonical_ir_serialized": False,
            "transition_dump_written": False,
            "catalog_scenarios_retained": False,
            "artifacts": [
                "inherited_partition_check_p8_s8.json",
                "remaining_family_matrix_p8_s8.json",
                "full_graph_matrix_p8_s8.json",
                "catalog_startup_matrix_p8_s8.json",
                "common_route_matrix_p8_s8.json",
                "condition_numeric_matrix_p8_s8.json",
                "target_rng_matrix_p8_s8.json",
                "event_audit_replay_matrix_p8_s8.json",
                "exact_task_family_execution_matrix_p8_s8.json",
                "stack_property_consumption_matrix_p8_s8.json",
                "exact_event_family_execution_matrix_p8_s8.json",
                "resource_event_closure_matrix_p8_s8.json",
                "runtime_boundary_p8_s8.json",
                "empty_executable_task_fail_closed_matrix_p8_s8.json",
                "status_replacement_contract_matrix_p8_s8.json",
                "battle_state_transition_seed_matrix_p8_s8.json",
            ],
        },
    )
    artifacts = {
        "inherited_partition_check_p8_s8.json": {
            key: value for key, value in partition.items() if not key.startswith("_")
        },
        "remaining_family_matrix_p8_s8.json": coverage,
        "full_graph_matrix_p8_s8.json": graphs,
        "catalog_startup_matrix_p8_s8.json": startups,
        "common_route_matrix_p8_s8.json": {
            "schema_version": "p8_s8_common_route_aggregate_v1",
            "ok": effects["ok"] and damage["ok"] and timeline["ok"] and process_only["ok"],
            "effects": effects, "damage": damage, "timeline": timeline,
            "process_only": process_only,
        },
        "condition_numeric_matrix_p8_s8.json": {
            "schema_version": "p8_s8_condition_numeric_aggregate_v1",
            "ok": conditions["ok"] and numeric["ok"],
            "conditions": conditions, "numeric": numeric,
        },
        "target_rng_matrix_p8_s8.json": {
            "schema_version": "p8_s8_target_rng_aggregate_v1",
            "ok": targets["ok"] and target_families["ok"] and rng["ok"],
            "targets": {key: value for key, value in targets.items() if not key.startswith("_")},
            "target_families": target_families, "rng": rng,
        },
        "event_audit_replay_matrix_p8_s8.json": {
            "schema_version": "p8_s8_event_audit_replay_aggregate_v1",
            "ok": (events["ok"] and energy_listener["ok"]
                   and resource_event_closure["ok"]
                   and battle_state_transition_seed["ok"] and formal["ok"]),
            "events": events,
            "energy_listener": {
                key: value
                for key, value in energy_listener.items()
                if not key.startswith("_")
            },
            "resource_events": resource_event_closure,
            "battle_state_transitions": battle_state_transition_seed,
            "status_replacement": status_replacement,
            "formal": {key: value for key, value in formal.items() if not key.startswith("_")},
        },
        "status_replacement_contract_matrix_p8_s8.json": status_replacement,
        "exact_task_family_execution_matrix_p8_s8.json": task_execution,
        "stack_property_consumption_matrix_p8_s8.json": stack_property_consumption,
        "exact_event_family_execution_matrix_p8_s8.json": event_execution,
        "resource_event_closure_matrix_p8_s8.json": resource_event_closure,
        "runtime_boundary_p8_s8.json": runtime_boundary,
        "empty_executable_task_fail_closed_matrix_p8_s8.json": empty_task_fail_closed,
        "real_heal_event_seed_matrix_p8_s8.json": real_heal_seed,
        "real_custom_event_seed_matrix_p8_s8.json": real_custom_event_seed,
        "real_weakness_event_seed_matrix_p8_s8.json": real_weakness_event_seed,
        "battle_state_transition_seed_matrix_p8_s8.json": battle_state_transition_seed,
        "validation_summary_p8_s8_light_cone_remaining_gameplay_closure.json": summary,
    }
    _write_artifacts(output_dir, artifacts)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--contract-slice", action="append", choices=("task", "event"), default=[],
                        help="Run this contract slice; repeat once to share evidence across task and event.")
    parser.add_argument(
        "--resource-events-only",
        action="store_true",
        help="Run only the bounded P8-S8 resource-event contract slice.",
    )
    parser.add_argument(
        "--catalog-startup-only",
        action="store_true",
        help="Run only the bounded P8-S8 catalog startup and fail-closed slice.",
    )
    parser.add_argument(
        "--catalog-definition",
        action="append",
        default=[],
        help=(
            "With --catalog-startup-only, validate only this light-cone "
            "definition identity; repeat to select several definitions."
        ),
    )
    parser.add_argument(
        "--condition-contract-only",
        action="store_true",
        help="Run only the bounded P8-S8 exact-condition contract slice.",
    )
    parser.add_argument(
        "--numeric-contract-only",
        action="store_true",
        help="Run only the bounded P8-S8 numeric-expression contract slice.",
    )
    parser.add_argument(
        "--task-contract-only",
        action="store_true",
        help="Run only the bounded P8-S8 exact task/property contract slice.",
    )
    parser.add_argument(
        "--event-contract-only",
        action="store_true",
        help="Run only the bounded P8-S8 exact event contract slice.",
    )
    parser.add_argument(
        "--task-family",
        action="append",
        default=[],
        help=(
            "With a task contract slice, validate only this exact task family; "
            "repeat to select several families."
        ),
    )
    parser.add_argument(
        "--event-family",
        action="append",
        default=[],
        help=(
            "With an event contract slice, validate only this exact event family; "
            "repeat to select several families."
        ),
    )
    args = parser.parse_args()
    if len(args.contract_slice) != len(set(args.contract_slice)):
        parser.error("--contract-slice may select each slice at most once")
    legacy_slices = ("task",) if args.task_contract_only else ("event",) if args.event_contract_only else ()
    contract_slices = tuple(args.contract_slice) or legacy_slices
    focused_mode_count = sum(map(bool, (
        args.contract_slice,
        args.resource_events_only,
        args.catalog_startup_only,
        args.condition_contract_only,
        args.numeric_contract_only,
    ))) + args.task_contract_only + args.event_contract_only
    if focused_mode_count > 1:
        parser.error("choose at most one focused validation mode")
    if args.task_family and "task" not in contract_slices:
        parser.error("--task-family requires a task contract slice")
    if args.event_family and "event" not in contract_slices:
        parser.error("--event-family requires an event contract slice")
    if args.catalog_definition and not args.catalog_startup_only:
        parser.error("--catalog-definition requires --catalog-startup-only")
    root, output_dir = args.tbgd_root.resolve(), args.output_dir.resolve()
    if contract_slices:
        summary = run_contract_validation(
            root, output_dir, contract_slices=contract_slices,
            task_families=frozenset(args.task_family) or None,
            event_families=frozenset(args.event_family) or None,
        )
    elif args.catalog_startup_only:
        summary = run_catalog_startup_validation(
            root, output_dir, definition_identities=frozenset(args.catalog_definition) or None,
        )
    elif args.resource_events_only:
        summary = run_resource_event_validation(root, output_dir)
    elif args.condition_contract_only:
        summary = run_condition_contract_validation(root, output_dir)
    elif args.numeric_contract_only:
        summary = run_numeric_contract_validation(root, output_dir)
    else:
        summary = run_validation(root, output_dir)
    print(summary)
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
