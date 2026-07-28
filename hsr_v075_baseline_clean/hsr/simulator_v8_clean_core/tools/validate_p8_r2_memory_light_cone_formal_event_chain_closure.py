from __future__ import annotations

import argparse
import resource
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..builds.character_assembler import assemble_character_build
from ..builds.models import CharacterInitialConditionInput
from ..core.executor import CombatExecutor, _dedupe_events
from ..core.model import (
    ActionCommand,
    BattleState,
    GameEvent,
    Mutation,
    RNGEvent,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import (
    BattleSetupSpec,
    ScenarioSpec,
    TimelineSetupSpec,
    UnitSpec,
)
from ..systems.damage import (
    DamagePacket,
    DamageSourceFrame,
    DamageSystem,
    DamageWindowLedger,
)
from ..systems.decision import DecisionSystem
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import (
    EventDispatchResult,
    EventDispatchSystem,
    _scope_matches,
)
from ..systems.mutation_events import mutation_backed_event_id
from ..systems.status import StatusSystem
from ..systems.summon_runtime import validate_summon_runtime
from ..systems.unit_relation import is_opposing_combat_team
from ..tbgd.light_cone_cards import (
    LightConeFamilyProjection,
    build_light_cone_family_projection,
    require_complete_light_cone_catalog,
)
from ..tbgd.lowering import (
    IRIdentityConflictError,
    TBGDLowering,
    _attach_light_cone_equipment_mechanism_refs,
    _block_status_callback_tasks_by_callback,
    _block_status_callbacks_by_event_family,
    _link_status_effect_runtime_fields,
    _lower_status_event_families,
    _status_event_blocked_reasons,
    merge_identical_ir_items,
)
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .validate_p8_s6_light_cone_dynamic_startup import (
    _assembly,
    _character_build,
)


VALIDATION_VERSION = "p8_r2_memory_light_cone_formal_event_chain_closure"
SUMMARY_SCHEMA_VERSION = "p8_r2_focused_summary_v1"
R2_ABILITY_MARKERS = (
    "SetDynamicValueByCopying",
    "SetModifierDynamicValue",
    "OnDeathrattle",
)
R2_SUPPORT_MARKERS = (
    "OnAddModifierSuc",
    "OnListenModifierAdd",
)
EXTERNAL_DEFERRED_EVENTS = (
    "OnCustomEvent",
    "OnListenModifierAdd",
    "OnListenModifierOnStack",
)
BASE_TYPE_LISTENER_SOURCE = {
    "source_path": "Config/ConfigAbility/Equip/Equip40.json",
    "raw_id": "MEquip_23053_Sub01_LevelEntity",
    "callback_event": "OnListenAvatarBaseTypeChange",
}


def _build_rulebook(tbgd_root: Path) -> tuple[RuleBook, dict[str, Any]]:
    light_cones = build_light_cone_family_projection(
        tbgd_root,
        required_ability_markers=R2_ABILITY_MARKERS,
        required_support_markers=R2_SUPPORT_MARKERS,
    )
    definitions = require_complete_light_cone_catalog(light_cones.catalog)
    lowering = TBGDLowering(tbgd_root)
    selected_sources: dict[str, dict[int, Any]] = {}
    for definition in definitions:
        source = definition.ability_source
        if source is None:
            continue
        selected_sources.setdefault(source.source.source_path, {})[
            source.record_index
        ] = source.source

    lowered_files = []
    for order, (relative, sources) in enumerate(sorted(selected_sources.items())):
        lowered_files.append(
            lowering._lower_ability_file(
                tbgd_root / relative,
                {},
                ability_file_order=order,
                selected_equipment_sources=sources,
            )
        )
    for relative in light_cones.support_ability_paths:
        if relative in selected_sources:
            continue
        lowered_files.append(
            lowering._lower_ability_file(
                tbgd_root / relative,
                {},
                ability_file_order=len(lowered_files),
            )
        )

    owned = lowering.build_owned_combatant_admission_projection(
        offensive_action_only=True,
        max_servant_count=1,
    )
    if not owned.ok:
        raise ValueError(
            "owned-combatant action projection failed:"
            + ",".join(sorted({issue.code for issue in owned.issues}))
        )

    callbacks = [
        callback
        for lowered in lowered_files
        for callback in lowered.status_callbacks
    ]
    callbacks.extend(owned.status_callbacks)
    callbacks = list(
        _dedupe_by(tuple(callbacks), "callback_id")
    )
    callback_tasks = [
        task
        for lowered in lowered_files
        for task in lowered.status_callback_tasks
    ]
    callback_tasks.extend(owned.status_callback_tasks)
    callback_tasks = list(
        _dedupe_by(tuple(callback_tasks), "task_id")
    )
    event_families = _lower_status_event_families(
        callbacks,
        callback_tasks,
    )
    event_blocked = _status_event_blocked_reasons(event_families)
    callbacks = _block_status_callbacks_by_event_family(
        callbacks,
        event_blocked,
    )
    callback_blocked = {
        callback.callback_id: event_blocked[callback.event]
        for callback in callbacks
        if callback.event in event_blocked
    }
    callback_tasks = _block_status_callback_tasks_by_callback(
        callback_tasks,
        callback_blocked,
    )
    event_families = _lower_status_event_families(
        callbacks,
        callback_tasks,
    )
    (
        graphs,
        phases,
        tasks,
        graph_effects,
        graph_conditions,
        graph_formulas,
        graph_targets,
        parameter_reads,
    ) = lowering._lower_equipment_ability_graphs(
        definitions,
        status_callbacks=callbacks,
    )
    definitions, mechanism_refs = (
        _attach_light_cone_equipment_mechanism_refs(
            definitions,
            graphs,
            parameter_reads,
        )
    )

    entities = _dedupe_by(
        (*_collect(lowered_files, "entities"), *owned.entities),
        "entity_id",
    )
    effects = _dedupe_by(
        (*_collect(lowered_files, "effects"), *graph_effects, *owned.effects),
        "effect_id",
    )
    effects = tuple(
        _link_status_effect_runtime_fields(
            list(effects),
            list(entities),
            callbacks,
        )
    )
    conditions = _dedupe_by(
        (
            *_collect(lowered_files, "conditions"),
            *graph_conditions,
            *owned.conditions,
        ),
        "condition_id",
    )
    targets = _dedupe_by(
        (
            *_collect(lowered_files, "target_expressions"),
            *graph_targets,
            *owned.target_expressions,
        ),
        "target_expression_id",
    )
    formulas = _dedupe_by(
        (*graph_formulas, *owned.formulas),
        "formula_id",
    )
    definitions = _dedupe_by(
        tuple(definitions),
        "definition_key",
    )
    mechanism_refs = _dedupe_by(
        tuple(mechanism_refs),
        "definition_key",
    )
    parameter_reads = _dedupe_by(
        tuple(parameter_reads),
        "parameter_read_id",
    )
    graphs = _dedupe_by(
        tuple(graphs),
        "standalone_ability_graph_id",
    )
    phases = _dedupe_by(
        (*phases, *owned.ability_phases),
        "phase_id",
    )
    tasks = _dedupe_by(
        (*tasks, *owned.ability_tasks),
        "task_id",
    )
    callbacks = _dedupe_by(
        tuple(callbacks),
        "callback_id",
    )
    callback_tasks = _dedupe_by(
        tuple(callback_tasks),
        "task_id",
    )
    event_families = _dedupe_by(
        tuple(event_families),
        "status_event_family_id",
    )
    status_damage_emissions = _dedupe_by(
        (
            *_collect(lowered_files, "status_damage_emissions"),
            *owned.status_damage_emissions,
        ),
        "status_damage_emission_id",
    )
    damage_modifiers = _dedupe_by(
        (
            *_collect(lowered_files, "damage_modifiers"),
            *owned.damage_modifiers,
        ),
        "damage_modifier_id",
    )
    action_delay_emissions = _dedupe_by(
        (
            *_collect(lowered_files, "action_delay_emissions"),
            *owned.action_delay_emissions,
        ),
        "action_delay_emission_id",
    )
    queue_intents = _dedupe_by(
        (
            *_collect(lowered_files, "queue_intents"),
            *owned.queue_intents,
        ),
        "queue_intent_id",
    )
    skill_continuations = _dedupe_by(
        (
            *_collect(lowered_files, "skill_continuations"),
            *owned.skill_continuations,
        ),
        "continuation_id",
    )
    triggers = _dedupe_by(
        (
            *_collect(lowered_files, "triggers"),
            *owned.triggers,
        ),
        "trigger_id",
    )
    engine_rules = build_engine_rule_registry()
    ir = CanonicalIR(
        version=BASELINE_VERSION,
        entities=entities,
        light_cone_definitions=definitions,
        equipment_mechanism_refs=mechanism_refs,
        equipment_ability_parameter_reads=parameter_reads,
        standalone_ability_graphs=graphs,
        ability_phases=phases,
        ability_tasks=tasks,
        effects=effects,
        conditions=conditions,
        formulas=formulas,
        target_expressions=targets,
        status_callbacks=callbacks,
        status_callback_tasks=callback_tasks,
        status_event_families=event_families,
        status_damage_emissions=status_damage_emissions,
        damage_modifiers=damage_modifiers,
        action_delay_emissions=action_delay_emissions,
        queue_intents=queue_intents,
        skill_continuations=skill_continuations,
        triggers=triggers,
        servant_definitions=owned.servant_definitions,
        action_definitions=owned.action_definitions,
        action_ability_bindings=owned.action_ability_bindings,
        action_admissions=owned.action_admissions,
        unit_birth_templates=owned.unit_birth_templates,
        combatant_action_sets=owned.combatant_action_sets,
        action_events=owned.action_events,
        hit_profiles=owned.hit_profiles,
        skill_formula_bindings=owned.skill_formula_bindings,
        damage_emissions=owned.damage_emissions,
        toughness_emissions=owned.toughness_emissions,
        avatar_profiles=owned.avatar_profiles,
        character_data_cards=owned.character_data_cards,
        character_equipment_eligibilities=(
            owned.character_equipment_eligibilities
        ),
        character_mechanism_slots=owned.character_mechanism_slots,
        character_trace_nodes=owned.character_trace_nodes,
        character_eidolon_slots=owned.character_eidolon_slots,
        bounce_policies=owned.bounce_policies,
        timeline_rules=engine_rules.timeline_rules,
        resource_rules=engine_rules.resource_rules,
        damage_formula_rules=engine_rules.damage_formula_rules,
        damage_route_rules=engine_rules.damage_route_rules,
        shield_priority_rules=engine_rules.shield_priority_rules,
        metadata={
            "validation_scope": VALIDATION_VERSION,
            "source_projection": "selected_before_ir_assembly",
        },
    )
    return RuleBook(ir), _projection_evidence(light_cones, owned)


def _dedupe_by(items: tuple[Any, ...], field: str) -> tuple[Any, ...]:
    merged = merge_identical_ir_items(
        items,
        field,
        item_kind=(
            type(items[0]).__name__
            if items
            else "ir_item"
        ),
    )
    return tuple(
        sorted(
            merged,
            key=lambda item: str(getattr(item, field)),
        )
    )


def _collect(items: list[Any], field: str) -> tuple[Any, ...]:
    return tuple(
        value
        for item in items
        for value in getattr(item, field)
    )


def _projection_evidence(
    light_cones: LightConeFamilyProjection,
    owned: Any,
) -> dict[str, Any]:
    return {
        "full_tbgd_lowering_build_count": 0,
        "source_projection_count": 1,
        "light_cone_family_projection_build_count": 1,
        "owned_combatant_projection_build_count": 1,
        "source_backed_rulebook_build_count": 1,
        "required_ability_markers": list(light_cones.required_markers),
        "marker_source_paths": {
            marker: list(paths)
            for marker, paths in light_cones.marker_source_paths
        },
        "selected_ability_paths": list(
            light_cones.selected_ability_paths
        ),
        "required_support_markers": list(
            light_cones.required_support_markers
        ),
        "support_marker_source_paths": {
            marker: list(paths)
            for marker, paths in (
                light_cones.support_marker_source_paths
            )
        },
        "support_ability_paths": list(
            light_cones.support_ability_paths
        ),
        "scanned_ability_file_count": (
            light_cones.scanned_ability_file_count
        ),
        "parsed_ability_file_count": (
            light_cones.parsed_ability_file_count
        ),
        "light_cone_definition_count": len(
            light_cones.catalog.canonical_definitions
        ),
        "servant_definition_count": len(owned.servant_definitions),
        "owned_action_definition_count": len(owned.action_definitions),
        "owned_ability_task_count": len(owned.ability_tasks),
        "character_card_count": len(owned.character_data_cards),
        "owner_character_selection": "raw_source_join_before_character_ir",
    }


def _projection_identity_conflict_contract(
    rules: RuleBook,
) -> dict[str, Any]:
    if not rules.ir.entities:
        return {
            "ok": False,
            "reason": "projection_conflict_sample_entity_missing",
        }
    sample = rules.ir.entities[0]
    exact = _dedupe_by(
        (sample, sample),
        "entity_id",
    )
    content_conflict = replace(
        sample,
        fields={
            **sample.fields,
            "validation_conflict": True,
        },
    )
    source_conflict = replace(
        sample,
        source=replace(
            sample.source,
            raw_id=f"{sample.source.raw_id}:validation-conflict",
        ),
    )
    conflicts: dict[str, dict[str, Any]] = {}
    for name, candidate in (
        ("content", content_conflict),
        ("source", source_conflict),
    ):
        try:
            _dedupe_by(
                (sample, candidate),
                "entity_id",
            )
        except IRIdentityConflictError as conflict:
            conflicts[name] = {
                "blocked": True,
                "reason_code": conflict.reason_code,
                "identity_field": conflict.identity_field,
                "identity": conflict.identity,
                "rulebook_constructed": False,
            }
        else:
            conflicts[name] = {
                "blocked": False,
                "reason_code": "",
                "identity_field": "entity_id",
                "identity": sample.entity_id,
                "rulebook_constructed": True,
            }
    ok = bool(
        len(exact) == 1
        and len(conflicts) == 2
        and all(
            row["blocked"]
            and row["reason_code"] == "ir_identity_conflict"
            and not row["rulebook_constructed"]
            for row in conflicts.values()
        )
    )
    return {
        "ok": ok,
        "exact_duplicate_merged_count": len(exact),
        "conflicts": conflicts,
    }


def _definition_for_source(
    rules: RuleBook,
    source_name: str,
) -> Any:
    candidates = tuple(
        definition
        for definition in rules.ir.light_cone_definitions
        if definition.path_type == "Memory"
        and definition.ability_source is not None
        and definition.ability_source.source.source_path.endswith(source_name)
    )
    if len(candidates) != 1:
        raise ValueError(
            f"focused Memory definition count for {source_name}:"
            f"{len(candidates)}"
        )
    return candidates[0]


def _formal_equipment_state(
    rules: RuleBook,
    definition: Any,
    *,
    scenario_suffix: str,
    initial_skill_points: int = 3,
) -> tuple[BattleState, dict[str, Any]]:
    eligible_card_ids = {
        eligibility.character_card_id
        for eligibility in rules.ir.character_equipment_eligibilities
        if eligibility.character_path_type == definition.path_type
        and eligibility.coverage_status != "blocked"
    }
    cards = tuple(
        card
        for card in rules.ir.character_data_cards
        if card.card_id in eligible_card_ids
    )
    if len(cards) != 1:
        raise ValueError(
            "focused character card count:"
            f"{len(cards)} for path {definition.path_type}"
        )
    card = cards[0]
    builds: dict[str, Any] = {}
    admissions: dict[str, str] = {}
    for role in ("ally", "enemy", "enemy-peer"):
        instance = f"validation:p8_r2:{scenario_suffix}:{role}"
        equipment, equipment_result = _assembly(
            rules, card.card_id, definition,
            instance_id=instance, rank=1,
        )
        build = _character_build(card.card_id, instance, equipment)
        builds[role] = build
        admissions[f"{role}_equipment"] = (
            equipment_result.battle_admission_status
        )
        admissions[f"{role}_character"] = (
            assemble_character_build(
                rules, build
            ).battle_admission_status
        )
    if set(admissions.values()) != {"admitted"}:
        raise ValueError(f"formal focused build not admitted:{admissions}")
    unit_rows = (
        ("ally:owner", "ally", 0),
        ("enemy:owner", "enemy", 0),
        ("enemy:peer", "enemy-peer", 1),
    )
    scenario = ScenarioSpec(
        scenario_id=f"validation:p8_r2:{scenario_suffix}",
        version=BASELINE_VERSION,
        units=tuple(
            UnitSpec(
                unit_id=unit_id,
                side="ally",
                entity_ref=card.entity_ref,
                build_mode="assembled_character_build",
                level=builds[role].level,
                eidolon_level=builds[role].eidolon_level,
                panel=None,
                position=position,
                character_build=builds[role],
                initial_condition=CharacterInitialConditionInput(
                    hp_mode="full", initial_energy="0",
                ),
            )
            for unit_id, role, position in unit_rows
        ),
        route=(),
        skill_points=initial_skill_points,
        max_skill_points=5,
        battle_setup=BattleSetupSpec(
            timeline=TimelineSetupSpec(mode="runtime_initialize"),
        ),
    )
    built = ScenarioStateBuilder(rules).build(scenario)
    ally = built.state.units["ally:owner"]
    enemy = replace(
        built.state.units["enemy:owner"],
        side="enemy",
        flags={
            **built.state.units["enemy:owner"].flags,
            "position": 0,
        },
    )
    peer = replace(
        built.state.units["enemy:peer"],
        side="enemy",
    )
    state = replace(
        built.state,
        units={
            **built.state.units,
            ally.unit_id: replace(
                ally,
                action_value=100.0,
                flags={**ally.flags, "position": 0},
            ),
            enemy.unit_id: replace(enemy, action_value=100.0),
            peer.unit_id: replace(peer, action_value=100.0),
        },
        global_flags={
            **built.state.global_flags,
            "phase": "action",
        },
    )
    return state, {
        "definition_identity": (
            definition.definition_key.definition_identity
        ),
        "ability_source": (
            definition.ability_source.source.to_json()
            if definition.ability_source is not None
            else None
        ),
        "character_card_id": card.card_id,
        "admissions": admissions,
        "scenario_unit_count": len(state.units),
        "initial_skill_points": state.skill_points,
        "maximum_skill_points": state.max_skill_points,
    }


def _formal_owned_servant_spawn(
    rules: RuleBook,
    state: BattleState,
    owner_id: str,
) -> tuple[EventDispatchResult | None, str, dict[str, Any]]:
    owner = state.units.get(owner_id)
    if owner is None:
        return None, "", {"ok": False, "reason": "formal_servant_owner_missing"}
    definitions = tuple(
        definition
        for definition in rules.servant_definitions_for_owner(owner.template_id)
        if definition.coverage_status == "executable"
        and definition.representation == "unit"
        and definition.spawn_sources
    )
    if len(definitions) != 1:
        return None, "", {
            "ok": False, "reason": "focused_servant_definition_count",
            "definition_count": len(definitions),
        }
    definition = definitions[0]
    spawn_source = definition.spawn_sources[0]
    executor = CombatExecutor(rules)
    plan = executor.summons.plan_spawn_servant(
        state, definition, owner_id=owner_id, spawn_source=spawn_source,
    )
    raw = executor.summons.apply_spawn_servant(state, plan)
    result = executor.commit_eventful_transition(
        state, mutations=raw.mutations, events=raw.events,
        records=raw.records, rng_events=raw.rng_events,
        producer_kind="summon_transition",
        producer_id=plan.intent_id or plan.operation,
        producer_ok=plan.ok, blocked_reason=plan.blocked_reason,
    )
    spawned_ids = tuple(sorted(set(result.after_state.units) - set(state.units)))
    servant_id = spawned_ids[0] if len(spawned_ids) == 1 else ""
    servant = result.after_state.units.get(servant_id)
    runtime_check = validate_summon_runtime(
        result.after_state.global_flags.get("summon_runtime"),
        units=result.after_state.units,
    )
    replay = MutationReducer().replay_snapshot(
        state, result.mutations, result.after_state.snapshot().to_json(),
    )
    creation_count = sum(
        event.event_type in {"unit.created", "summon.spawned"}
        and event.target_id == servant_id
        and event.payload.get("param_entity_id") == servant_id
        for event in result.events
    )
    relation_ok = bool(
        servant is not None
        and servant.flags.get("owner_id") == owner_id
        and servant.flags.get("summoner_id") == owner_id
    )
    evidence = {
        "ok": bool(
            not result.errors and len(spawned_ids) == 1
            and creation_count == 1 and runtime_check.ok
            and relation_ok and replay.ok
        ),
        "servant_definition_id": definition.servant_definition_id,
        "spawn_source": spawn_source.to_json(),
        "servant_id": servant_id,
        "creation_event_count": creation_count,
        "base_type_event_count": sum(
            event.event_type == "unit.base_type.changed"
            and event.target_id == servant_id
            for event in result.events
        ),
        "summon_runtime_valid": runtime_check.ok,
        "owner_relation_valid": relation_ok,
        "replay_equal": replay.ok,
        "mutation_count": len(result.mutations),
        "errors": list(result.errors),
    }
    return (
        (result, servant_id, evidence)
        if evidence["ok"]
        else (None, "", evidence)
    )


def _scheduler_result(step: Any) -> EventDispatchResult:
    transition = step.transition
    settlement = transition.transaction.settlement
    return EventDispatchResult(
        after_state=step.after_state,
        mutations=transition.transaction.mutations,
        events=transition.transaction.events,
        rng_events=transition.rng_events,
        records=settlement.records if settlement is not None else (),
        errors=(
            ()
            if transition.outcome.successor_eligible
            else transition.outcome.reason_codes
        ),
        node_results=transition.outcome.node_results,
    )


def _transition_audit(
    rules: RuleBook,
    before_state: BattleState,
    step: Any,
) -> dict[str, Any]:
    transition = step.transition
    replay = MutationReducer().replay_snapshot(
        before_state,
        transition.transaction.mutations,
        transition.after.to_json(),
    )
    source = RuntimeSourceAuditor(rules).validate_transition(transition)
    ok = bool(
        transition.outcome.successor_eligible
        and transition.transaction.settlement is not None
        and transition.transaction.before.to_json()
        == before_state.snapshot().to_json()
        and transition.after.to_json()
        == step.after_state.snapshot().to_json()
        and replay.ok
        and source.ok
    )
    return {
        "ok": ok,
        "replay_equal": replay.ok,
        "source_audit_ok": source.ok,
        "checked_mutation_count": source.checked_mutations,
        "checked_record_count": source.checked_records,
        "source_violation_count": len(source.violations),
        "outcome_category": transition.outcome.category,
        "successor_eligible": transition.outcome.successor_eligible,
        "reason_codes": list(transition.outcome.reason_codes),
    }


def _decision_advance_audit(
    rules: RuleBook,
    before_state: BattleState,
    advance: Any,
) -> dict[str, Any]:
    reducer = MutationReducer()
    auditor = RuntimeSourceAuditor(rules)
    current = before_state
    rows: list[dict[str, Any]] = []
    for transition in advance.transitions:
        before_matches = (
            transition.transaction.before.to_json()
            == current.snapshot().to_json()
        )
        replay = reducer.replay_snapshot(
            current,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        source = auditor.validate_transition(transition)
        reduction = reducer.apply_all_result(
            current,
            transition.transaction.mutations,
        )
        after_matches = bool(
            reduction.ok
            and reduction.after_state.snapshot().to_json()
            == transition.after.to_json()
        )
        row_ok = bool(
            transition.outcome.successor_eligible
            and transition.transaction.settlement is not None
            and before_matches
            and replay.ok
            and source.ok
            and after_matches
        )
        rows.append(
            {
                "ok": row_ok,
                "action_id": (
                    transition.transaction.command.action_id
                ),
                "mutation_count": len(
                    transition.transaction.mutations
                ),
                "settlement_present": (
                    transition.transaction.settlement is not None
                ),
                "before_matches_previous_after": before_matches,
                "after_matches_reduced_state": after_matches,
                "replay_equal": replay.ok,
                "source_audit_ok": source.ok,
                "successor_eligible": (
                    transition.outcome.successor_eligible
                ),
                "reason_codes": list(
                    transition.outcome.reason_codes
                ),
            }
        )
        if not reduction.ok:
            break
        current = reduction.after_state
    final_state_matches = (
        current.snapshot().to_json()
        == advance.after_state.snapshot().to_json()
    )
    return {
        "ok": bool(
            len(rows) == len(advance.transitions)
            and all(row["ok"] for row in rows)
            and final_state_matches
        ),
        "transition_count": len(advance.transitions),
        "final_state_matches": final_state_matches,
        "transitions": rows,
    }


def _choice_has_source_backed_damage(
    rules: RuleBook,
    choice: Any,
) -> bool:
    definition_ids = tuple(
        definition.definition_id
        for definition in rules.action_definition_candidates(
            choice.action_id,
            choice.action_level,
        )
        if definition.coverage_status == "executable"
    )
    return bool(
        definition_ids
        and any(
            emission.action_id == choice.action_id
            and emission.level == choice.action_level
            and emission.coverage_status == "executable"
            for emission in rules.ir.damage_emissions
        )
    )


def _submit_one_formal_servant_action(
    rules: RuleBook,
    state: BattleState,
    actor_id: str,
    *,
    required_target_id: str = "",
    expected_previous_state: BattleState | None = None,
) -> tuple[EventDispatchResult | None, BattleState, dict[str, Any]]:
    handoff_exact = bool(
        expected_previous_state is None
        or state.snapshot().to_json()
        == expected_previous_state.snapshot().to_json()
    )
    decisions = DecisionSystem(rules)
    advance = decisions.advance_to_decision(state)
    advance_audit = _decision_advance_audit(
        rules,
        state,
        advance,
    )
    turn_state = advance.after_state
    decision = advance.decision
    decision_actor_id = (
        decision.token.actor_id
        if decision.token is not None
        else ""
    )
    expected_actor_ready = bool(
        decision.availability.turn_owner_id == actor_id
        and decision_actor_id == actor_id
    )
    choices = tuple(
        choice
        for choice in decision.availability.choices
        if choice.actor_id == actor_id
        and choice.source_trace.get("owned_combatant_build_action")
        and _choice_has_source_backed_damage(rules, choice)
        and (choice.auto_target_ids or choice.selectable_target_ids)
        and (
            not required_target_id
            or required_target_id
            in (*choice.auto_target_ids, *choice.selectable_target_ids)
        )
    )
    if (
        not decision.ready
        or decision.token is None
        or not expected_actor_ready
        or not advance_audit["ok"]
        or not handoff_exact
        or not choices
    ):
        return None, turn_state, {
            "ok": False,
            "reason": (
                advance.blocked_reason
                or decision.blocked_reason
                or "formal_source_backed_damage_choice_missing"
            ),
            "choice_count": len(choices),
            "decision_ready": decision.ready,
            "decision_actor_id": decision_actor_id,
            "expected_actor_ready": expected_actor_ready,
            "internal_transition_count": len(advance.transitions),
            "internal_transition_audit": advance_audit,
            "previous_action_handoff_required": (
                expected_previous_state is not None
            ),
            "previous_action_handoff_exact": handoff_exact,
        }
    choice = sorted(
        choices,
        key=lambda item: (
            item.action_id,
            item.action_level,
            item.choice_id,
        ),
    )[0]
    target_ids = (
        choice.auto_target_ids
        if (
            not required_target_id
            or required_target_id in choice.auto_target_ids
        )
        else (required_target_id,)
    ) or (
        (required_target_id,)
        if required_target_id
        else choice.selectable_target_ids[:1]
    )
    template = choice.command_template
    template_metadata = template.get("metadata")
    queue_name = template.get("queue_name")
    command = ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=tuple(target_ids),
        source=str(template.get("source") or "manual"),
        queue_name=(
            str(queue_name) if isinstance(queue_name, str) else None
        ),
        metadata=(
            dict(template_metadata)
            if isinstance(template_metadata, dict)
            else {}
        ),
    )
    submitted = decisions.submit(
        turn_state,
        decision.token,
        command,
    )
    result = _scheduler_result(submitted)
    audit = _transition_audit(rules, turn_state, submitted)
    window_events = tuple(
        event
        for event in result.events
        if event.event_type == "action.window.after_attack"
        and event.source_id == actor_id
    )
    ok = bool(
        not result.errors
        and audit["ok"]
        and len(window_events) == 1
    )
    return (
        result if ok else None,
        turn_state,
        {
            "ok": ok,
            "reason": (
                "" if ok else "formal_servant_action_not_committed"
            ),
            "decision_entry": (
                "DecisionSystem.advance_to_decision/submit"
            ),
            "decision_id": decision.token.decision_id,
            "actor_id": actor_id,
            "decision_actor_id": decision_actor_id,
            "expected_actor_ready": expected_actor_ready,
            "action_id": choice.action_id,
            "action_level": choice.action_level,
            "target_ids": list(target_ids),
            "after_attack_event_count": len(window_events),
            "mutation_count": len(result.mutations),
            "event_count": len(result.events),
            "record_count": len(result.records),
            "internal_transition_count": len(advance.transitions),
            "internal_transition_audit": advance_audit,
            "previous_action_handoff_required": (
                expected_previous_state is not None
            ),
            "previous_action_handoff_exact": handoff_exact,
            "source_audit_replay": audit,
            "errors": list(result.errors),
        },
    )


def _nested_identity_matches(
    value: Any,
    key: str,
    expected: str,
) -> bool:
    if isinstance(value, dict):
        if value.get(key) == expected:
            return True
        return any(
            _nested_identity_matches(item, key, expected)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(
            _nested_identity_matches(item, key, expected)
            for item in value
        )
    return False


def _task_execution_evidence(
    result: EventDispatchResult,
    task: Any,
) -> dict[str, Any]:
    records = tuple(
        record
        for record in result.records
        if isinstance(record, dict)
        and (
            _nested_identity_matches(
                record,
                "task_id",
                task.task_id,
            )
            or (
                task.effect_id
                and _nested_identity_matches(
                    record,
                    "effect_id",
                    task.effect_id,
                )
            )
        )
    )
    accepted = tuple(
        record
        for record in records
        if not (
            isinstance(record.get("payload"), dict)
            and record["payload"].get("ok") is False
        )
    )
    mutations = tuple(
        mutation
        for mutation in result.mutations
        if _nested_identity_matches(
            mutation.metadata,
            "source_task_id",
            task.task_id,
        )
        or (
            task.effect_id
            and _nested_identity_matches(
                mutation.metadata,
                "effect_id",
                task.effect_id,
            )
        )
    )
    rng_events = tuple(
        event
        for event in result.rng_events
        if event.source == task.task_id
        or event.metadata.get("task_id") == task.task_id
    )
    committed_mutation_ids = {
        mutation.stable_id() for mutation in result.mutations
    }
    linked_record_mutation_ids = {
        str(record.get("mutation_id"))
        for record in records
        if isinstance(record.get("mutation_id"), str)
        and record.get("mutation_id") in committed_mutation_ids
    }
    source_paths = sorted(
        {
            str(
                record.get("trace", {})
                .get("effect_source", {})
                .get("source_path", "")
            )
            for record in records
            if isinstance(record.get("trace"), dict)
            and isinstance(
                record.get("trace", {}).get("effect_source"),
                dict,
            )
        }
        - {""}
    )
    condition_results = [
        bool(condition_result.get("result"))
        for record in records
        if isinstance(record.get("payload"), dict)
        and isinstance(
            record["payload"].get("condition_result"),
            dict,
        )
        and isinstance(
            (
                condition_result := record["payload"][
                    "condition_result"
                ]
            ).get("result"),
            bool,
        )
    ]
    return {
        "executed": bool(
            mutations
            or rng_events
            or linked_record_mutation_ids
        ),
        "record_count": len(records),
        "accepted_record_count": len(accepted),
        "mutation_count": len(mutations),
        "mutation_ids": sorted(
            mutation.stable_id() for mutation in mutations
        ),
        "linked_record_mutation_count": len(
            linked_record_mutation_ids
        ),
        "linked_record_mutation_ids": sorted(
            linked_record_mutation_ids
        ),
        "source_paths": source_paths,
        "condition_results": condition_results,
        "rng_event_count": len(rng_events),
        "record_types": sorted(
            {
                str(record.get("record_type") or "")
                for record in records
            }
        ),
    }


def _ordinary_dynamic_contract(
    rules: RuleBook,
) -> dict[str, Any]:
    definition = _definition_for_source(rules, "Equip33.json")
    state, build = _formal_equipment_state(
        rules,
        definition,
        scenario_suffix="ordinary-dynamic",
    )
    spawned, servant_id, spawn = _formal_owned_servant_spawn(
        rules,
        state,
        "ally:owner",
    )
    if spawned is None:
        return {
            "ok": False,
            "reason": "ordinary_formal_servant_spawn_failed",
            "build": build,
            "spawn": spawn,
            "formal_action_count": 0,
        }
    action_fixture = replace(
        spawned.after_state,
        units={
            unit_id: replace(
                unit,
                action_value=(
                    0.0
                    if unit_id == servant_id
                    else max(10.0, float(unit.action_value))
                ),
            )
            for unit_id, unit
            in spawned.after_state.units.items()
        },
        global_flags={
            key: value
            for key, value
            in spawned.after_state.global_flags.items()
            if key not in {
                "active_turn",
                "pending_turn_end",
                "turn_owner_id",
            }
        },
    )
    fixture_evidence = {
        "applied_before_formal_action": True,
        "servant_action_value": (
            action_fixture.units[servant_id].action_value
        ),
        "turn_markers_absent": all(
            key not in action_fixture.global_flags
            for key in {
                "active_turn",
                "pending_turn_end",
                "turn_owner_id",
            }
        ),
    }
    committed, _, action = _submit_one_formal_servant_action(
        rules,
        action_fixture,
        servant_id,
    )
    if committed is None:
        return {
            "ok": False,
            "reason": "ordinary_formal_servant_action_failed",
            "build": build,
            "spawn": spawn,
            "action_fixture": fixture_evidence,
            "action": action,
            "formal_action_count": 1,
        }
    tasks = tuple(
        task
        for task in rules.ir.status_callback_tasks
        if task.opcode
        in {
            "SetDynamicValueByCopying",
            "SetModifierDynamicValue",
        }
        and task.source.source_path.endswith("Equip33.json")
    )
    rows = [
        {
            "task_id": task.task_id,
            "opcode": task.opcode,
            "callback_id": task.callback_id,
            "source": task.source.to_json(),
            **_task_execution_evidence(committed, task),
        }
        for task in tasks
    ]
    ok = bool(
        len(tasks) == 2
        and {task.opcode for task in tasks}
        == {
            "SetDynamicValueByCopying",
            "SetModifierDynamicValue",
        }
        and all(
            row["executed"]
            and row["linked_record_mutation_count"] > 0
            for row in rows
        )
        and action["source_audit_replay"]["ok"]
    )
    return {
        "ok": ok,
        "reason": (
            "" if ok else "dynamic_tasks_not_closed_by_one_formal_action"
        ),
        "entry_chain": [
            "DecisionSystem.advance_to_decision",
            "ActionAvailability",
            "ActionCommand",
            "DecisionSystem.submit",
            "CombatExecutor.execute",
            "owned ability task/effect",
            "event listener",
            "atomic commit",
        ],
        "build": build,
        "spawn": spawn,
        "action_fixture": fixture_evidence,
        "action": action,
        "tasks": rows,
        "formal_action_count": 1,
    }


def _modifier_scope_observed(
    state: BattleState,
    result: EventDispatchResult,
    modifier_name: str,
) -> dict[str, Any]:
    active_owner_count = 0
    active_details: list[dict[str, Any]] = []
    for unit in state.units.values():
        details = unit.flags.get("status_details")
        matching_details = [
            detail
            for detail in details
            if isinstance(detail, dict)
            and detail.get("modifier_name") == modifier_name
        ] if isinstance(details, (list, tuple)) else []
        detail_match = (
            bool(matching_details)
        )
        if modifier_name in unit.statuses or detail_match:
            active_owner_count += 1
            active_details.extend(matching_details)
    transition_reference_count = sum(
        isinstance(record, dict)
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("modifier_name") == modifier_name
        for record in result.records
    )
    return {
        "active_owner_count_before_action": active_owner_count,
        "transition_reference_count": transition_reference_count,
        "_active_details": active_details,
    }


def _callback_death_scope_evidence(
    result: EventDispatchResult,
    callback: Any,
    active_details: list[dict[str, Any]],
) -> dict[str, Any]:
    death_events = tuple(
        event
        for event in result.events
        if event.event_type == "unit.defeated"
    )
    if len(death_events) != 1:
        return {
            "canonical_event_count": len(death_events),
            "matched_count": 0,
            "mismatch_reasons": [],
        }
    matches = [
        _scope_matches(
            death_events[0],
            callback.scope_kind,
            detail,
            explicit=False,
        )
        for detail in active_details
    ]
    return {
        "canonical_event_count": 1,
        "matched_count": sum(ok for ok, _ in matches),
        "mismatch_reasons": sorted(
            {
                reason
                for ok, reason in matches
                if not ok and reason
            }
        ),
    }


def _unit_has_modifier(
    state: BattleState,
    unit_id: str,
    modifier_name: str,
) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    if modifier_name in unit.statuses:
        return True
    details = unit.flags.get("status_details")
    return bool(
        isinstance(details, (list, tuple))
        and any(
            isinstance(detail, dict)
            and detail.get("modifier_name") == modifier_name
            for detail in details
        )
    )


def _death_listener_evidence(
    rules: RuleBook,
    before_action: BattleState,
    result: EventDispatchResult,
    callback_event: str,
) -> dict[str, Any]:
    callbacks = tuple(
        callback
        for callback in rules.ir.status_callbacks
        if callback.event == callback_event
    )
    rows: list[dict[str, Any]] = []
    family_executed = False
    scope_observed = False
    for callback in callbacks:
        scope = _modifier_scope_observed(
            before_action,
            result,
            callback.modifier_name,
        )
        active_details = scope.pop("_active_details")
        death_scope = _callback_death_scope_evidence(
            result,
            callback,
            active_details,
        )
        tasks = tuple(
            task
            for task in rules.ir.status_callback_tasks
            if task.callback_id == callback.callback_id
        )
        executions = [
            {
                "task_id": task.task_id,
                "opcode": task.opcode,
                **_task_execution_evidence(result, task),
            }
            for task in tasks
        ]
        callback_executed = any(
            execution["executed"] for execution in executions
        )
        predicate_results = [
            result
            for execution in executions
            for result in execution["condition_results"]
        ]
        predicate_no_match = bool(predicate_results) and not any(
            predicate_results
        )
        runtime_scope_no_match = bool(
            scope["active_owner_count_before_action"]
            and death_scope["canonical_event_count"] == 1
            and death_scope["matched_count"] == 0
            and death_scope["mismatch_reasons"]
        )
        callback_scope_candidate = bool(
            scope["active_owner_count_before_action"]
            or scope["transition_reference_count"]
        )
        family_executed = family_executed or callback_executed
        scope_observed = (
            scope_observed or callback_scope_candidate
        )
        rows.append(
            {
                "callback_id": callback.callback_id,
                "modifier_name": callback.modifier_name,
                "source": callback.source.to_json(),
                "scope": scope,
                "death_scope": death_scope,
                "executed": callback_executed,
                "predicate_no_match": predicate_no_match,
                "runtime_scope_no_match": runtime_scope_no_match,
                "true_scope_no_match": (
                    predicate_no_match
                    or runtime_scope_no_match
                ),
                "task_evidence": executions,
            }
        )
    scoped_rows = tuple(
        row
        for row in rows
        if row["scope"]["active_owner_count_before_action"]
        or row["scope"]["transition_reference_count"]
    )
    if family_executed:
        status = "executed"
        reason = ""
    elif (
        not callbacks
        or not scope_observed
        or (
            scoped_rows
            and all(
                row["true_scope_no_match"]
                for row in scoped_rows
            )
        )
    ):
        status = "true_scope_no_match"
        reason = (
            "loaded_callback_absent"
            if not callbacks
            else (
                "production_scope_or_predicate_no_match"
                if scoped_rows
                else "loaded_callback_modifier_not_active_in_selected_scenario"
            )
        )
    else:
        status = "implementation_failure"
        reason = "active_selected_equipment_listener_not_executed"
    return {
        "callback_event": callback_event,
        "status": status,
        "reason": reason,
        "canonical_death_event_ids": sorted(
            {
                event.event_id
                for event in result.events
                if event.event_type == "unit.defeated"
                and event.event_id
            }
        ),
        "callback_count": len(callbacks),
        "scope_observed": scope_observed,
        "callbacks": rows,
    }


def _death_contract(
    rules: RuleBook,
) -> dict[str, Any]:
    definition = _definition_for_source(rules, "Equip36.json")
    state, build = _formal_equipment_state(
        rules,
        definition,
        scenario_suffix="lethal-death",
        initial_skill_points=0,
    )
    victim_spawned, victim_id, victim_spawn = (
        _formal_owned_servant_spawn(
            rules,
            state,
            "ally:owner",
        )
    )
    if victim_spawned is None:
        return {
            "ok": False,
            "reason": "victim_formal_servant_spawn_failed",
            "build": build,
            "victim_spawn": victim_spawn,
            "formal_action_count": 0,
        }
    attacker_spawned, attacker_id, attacker_spawn = (
        _formal_owned_servant_spawn(
            rules,
            victim_spawned.after_state,
            "enemy:owner",
        )
    )
    if attacker_spawned is None:
        return {
            "ok": False,
            "reason": "attacker_formal_servant_spawn_failed",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "formal_action_count": 0,
        }
    victim = attacker_spawned.after_state.units.get(victim_id)
    attacker = attacker_spawned.after_state.units.get(attacker_id)
    if (
        victim is None
        or attacker is None
        or not is_opposing_combat_team(attacker, victim)
    ):
        return {
            "ok": False,
            "reason": "formal_lethal_relation_invalid",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "formal_action_count": 0,
        }
    chain_fixture = replace(
        attacker_spawned.after_state,
        units={
            unit_id: replace(
                unit,
                hp=(
                    min(1.0, unit.hp)
                    if unit_id == victim_id
                    else unit.hp
                ),
                action_value=(
                    0.0
                    if unit_id == victim_id
                    else (
                        1.0
                        if unit_id == attacker_id
                        else max(10.0, float(unit.action_value))
                    )
                ),
            )
            for unit_id, unit
            in attacker_spawned.after_state.units.items()
        },
        global_flags={
            key: value
            for key, value
            in attacker_spawned.after_state.global_flags.items()
            if key not in {
                "active_turn",
                "pending_turn_end",
                "turn_owner_id",
            }
        },
    )
    fixture_evidence = {
        "applied_before_first_formal_action": True,
        "victim_hp": chain_fixture.units[victim_id].hp,
        "victim_action_value": (
            chain_fixture.units[victim_id].action_value
        ),
        "attacker_action_value": (
            chain_fixture.units[attacker_id].action_value
        ),
        "turn_markers_absent": all(
            key not in chain_fixture.global_flags
            for key in {
                "active_turn",
                "pending_turn_end",
                "turn_owner_id",
            }
        ),
    }
    prepared, precondition_before_action, precondition_action = (
        _submit_one_formal_servant_action(
            rules,
            chain_fixture,
            victim_id,
        )
    )
    if prepared is None:
        return {
            "ok": False,
            "reason": "deathrattle_precondition_action_failed",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "chain_fixture": fixture_evidence,
            "precondition_action": precondition_action,
            "formal_action_count": 1,
        }
    precondition_callbacks = tuple(
        callback
        for callback in rules.ir.status_callbacks
        if callback.event == "OnBeforeSkillUse"
        and callback.modifier_name == "MEquip_23049_Listen"
        and callback.source.source_path.endswith("Equip36.json")
    )
    precondition_callback_ids = {
        callback.callback_id
        for callback in precondition_callbacks
    }
    precondition_tasks = tuple(
        task
        for task in rules.ir.status_callback_tasks
        if task.callback_id in precondition_callback_ids
        and task.opcode == "AddModifier"
        and task.source.source_path.endswith("Equip36.json")
    )
    precondition_task_rows = [
        {
            "task_id": task.task_id,
            "opcode": task.opcode,
            "source": task.source.to_json(),
            **_task_execution_evidence(prepared, task),
        }
        for task in precondition_tasks
    ]
    precondition_modifier_active = _unit_has_modifier(
        prepared.after_state,
        "ally:owner",
        "MEquip_23049_Sub",
    )
    precondition_modifier_absent_before = (
        precondition_before_action is not None
        and not _unit_has_modifier(
            precondition_before_action,
            "ally:owner",
            "MEquip_23049_Sub",
        )
    )
    precondition_ok = bool(
        len(precondition_callbacks) == 1
        and len(precondition_tasks) == 1
        and precondition_modifier_absent_before
        and precondition_modifier_active
        and all(
            row["executed"]
            and row["mutation_count"] > 0
            and row["linked_record_mutation_count"] > 0
            and row["source_paths"]
            == ["Config/ConfigAbility/Equip/Equip36.json"]
            for row in precondition_task_rows
        )
        and precondition_action["source_audit_replay"]["ok"]
    )
    precondition_evidence = {
        "ok": precondition_ok,
        "entry_chain": [
            "DecisionSystem.advance_to_decision",
            "ActionCommand",
            "DecisionSystem.submit",
            "OnBeforeSkillUse",
            "MEquip_23049_Listen",
            "AddModifier:MEquip_23049_Sub",
            "atomic commit",
        ],
        "modifier_name": "MEquip_23049_Sub",
        "modifier_owner_id": "ally:owner",
        "modifier_absent_before_action": (
            precondition_modifier_absent_before
        ),
        "modifier_active_after_action": precondition_modifier_active,
        "callback_count": len(precondition_callbacks),
        "task_count": len(precondition_tasks),
        "tasks": precondition_task_rows,
        "action": precondition_action,
    }
    if not precondition_ok:
        return {
            "ok": False,
            "reason": "deathrattle_precondition_not_committed",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "chain_fixture": fixture_evidence,
            "precondition": precondition_evidence,
            "formal_action_count": 1,
        }
    victim = prepared.after_state.units.get(victim_id)
    attacker = prepared.after_state.units.get(attacker_id)
    if victim is None or attacker is None:
        return {
            "ok": False,
            "reason": "formal_units_missing_after_precondition_action",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "chain_fixture": fixture_evidence,
            "precondition": precondition_evidence,
            "formal_action_count": 1,
        }
    committed, before_action, action = (
        _submit_one_formal_servant_action(
            rules,
            prepared.after_state,
            attacker_id,
            required_target_id=victim_id,
            expected_previous_state=prepared.after_state,
        )
    )
    if committed is None:
        return {
            "ok": False,
            "reason": "formal_lethal_action_failed",
            "build": build,
            "victim_spawn": victim_spawn,
            "attacker_spawn": attacker_spawn,
            "chain_fixture": fixture_evidence,
            "precondition": precondition_evidence,
            "action": action,
            "formal_action_count": 2,
        }
    death_events = tuple(
        event
        for event in committed.events
        if event.event_type == "unit.defeated"
        and event.target_id == victim_id
    )
    death_event = death_events[0] if len(death_events) == 1 else None
    target_after = committed.after_state.units.get(victim_id)
    defeat_record = (
        target_after.flags.get("defeat_record")
        if target_after is not None
        and isinstance(
            target_after.flags.get("defeat_record"),
            dict,
        )
        else {}
    )
    lifecycle_mutation_id = (
        str(
            death_event.payload.get("lifecycle_mutation_id")
            or death_event.payload.get("source_mutation_id")
            or ""
        )
        if death_event is not None
        else ""
    )
    expected_event_id = mutation_backed_event_id(
        lifecycle_mutation_id,
        "unit.defeated",
    )
    identity_ok = bool(
        death_event is not None
        and lifecycle_mutation_id
        and death_event.event_id == expected_event_id
        and death_event.payload.get("param_entity_id") == victim_id
        and defeat_record.get("lifecycle_mutation_id")
        == lifecycle_mutation_id
    )
    listeners = {
        callback_event: _death_listener_evidence(
            rules,
            before_action,
            committed,
            callback_event,
        )
        for callback_event in (
            "OnDeathrattle",
            "OnListenCharacterDie",
            "OnTriggerDeath",
        )
    }
    death_callback_ids = {
        callback.callback_id
        for callback in rules.ir.status_callbacks
        if callback.event == "OnDeathrattle"
        and callback.modifier_name == "MEquip_23049_Listen"
        and callback.source.source_path.endswith("Equip36.json")
    }
    recovery_tasks = tuple(
        task
        for task in rules.ir.status_callback_tasks
        if task.callback_id in death_callback_ids
        and task.opcode == "ModifySPNew"
        and task.source.source_path.endswith("Equip36.json")
    )
    recovery_effect_ids = {
        task.effect_id
        for task in recovery_tasks
        if task.effect_id
    }
    recovery_mutations = tuple(
        mutation
        for mutation in committed.mutations
        if mutation.path == (
            "units",
            "ally:owner",
            "energy",
        )
        and any(
                _nested_identity_matches(
                    mutation.metadata,
                    "effect_id",
                    effect_id,
                )
                for effect_id in recovery_effect_ids
            )
    )
    recovery_mutation_ids = {
        mutation.stable_id()
        for mutation in recovery_mutations
    }
    recovery_records = tuple(
        record
        for record in committed.records
        if isinstance(record, dict)
        and record.get("record_type") == "resource_delta"
        and record.get("mutation_id") in recovery_mutation_ids
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("opcode") == "ModifySPNew"
        and record["payload"].get("resource")
        == "energy"
    )
    recovery_source_paths = sorted(
        {
            str(
                record.get("trace", {})
                .get("effect_source", {})
                .get("source_path", "")
            )
            for record in recovery_records
            if isinstance(record.get("trace"), dict)
            and isinstance(
                record.get("trace", {}).get("effect_source"),
                dict,
            )
        }
        - {""}
    )
    recovery_before_unit = before_action.units.get("ally:owner")
    recovery_after_unit = committed.after_state.units.get(
        "ally:owner"
    )
    recovery_before = (
        recovery_before_unit.energy
        if recovery_before_unit is not None
        else 0.0
    )
    recovery_after = (
        recovery_after_unit.energy
        if recovery_after_unit is not None
        else 0.0
    )
    recovery_task_rows = [
        {
            "task_id": task.task_id,
            "opcode": task.opcode,
            "source": task.source.to_json(),
            **_task_execution_evidence(committed, task),
        }
        for task in recovery_tasks
    ]
    recovery_ok = bool(
        len(recovery_tasks) == 1
        and len(recovery_mutations) == 1
        and len(recovery_records) == 1
        and recovery_after > recovery_before
        and recovery_source_paths
        == ["Config/ConfigAbility/Equip/Equip36.json"]
        and all(
            row["executed"]
            and row["mutation_count"] == 1
            and row["linked_record_mutation_count"] == 1
            for row in recovery_task_rows
        )
        and action["source_audit_replay"]["ok"]
    )
    recovery_evidence = {
        "ok": recovery_ok,
        "resource": "energy",
        "resource_owner_id": "ally:owner",
        "before": recovery_before,
        "after": recovery_after,
        "delta": recovery_after - recovery_before,
        "mutation_count": len(recovery_mutations),
        "settlement_record_count": len(recovery_records),
        "mutation_ids": sorted(recovery_mutation_ids),
        "source_paths": recovery_source_paths,
        "tasks": recovery_task_rows,
        "source_audit_replay": action["source_audit_replay"],
    }
    listener_ok = bool(
        listeners["OnDeathrattle"]["status"] == "executed"
        and all(
            row["status"]
            in {"executed", "true_scope_no_match"}
            for row in listeners.values()
        )
        and death_event is not None
        and all(
            row["canonical_death_event_ids"]
            == [death_event.event_id]
            for row in listeners.values()
        )
    )
    ok = bool(
        len(death_events) == 1
        and target_after is not None
        and target_after.lifecycle_status == "defeated"
        and identity_ok
        and precondition_ok
        and recovery_ok
        and listener_ok
        and action["previous_action_handoff_exact"]
        and action["source_audit_replay"]["ok"]
    )
    return {
        "ok": ok,
        "reason": (
            "" if ok else "formal_death_event_chain_not_closed"
        ),
        "build": build,
        "victim_spawn": victim_spawn,
        "attacker_spawn": attacker_spawn,
        "chain_fixture": fixture_evidence,
        "precondition": precondition_evidence,
        "action": action,
        "resource_recovery": recovery_evidence,
        "victim_id": victim_id,
        "attacker_id": attacker_id,
        "initial_victim_hp": chain_fixture.units[victim_id].hp,
        "death_event_count": len(death_events),
        "death_event_identity": {
            "ok": identity_ok,
            "event_id": (
                death_event.event_id
                if death_event is not None
                else ""
            ),
            "expected_event_id": expected_event_id,
            "lifecycle_mutation_id": lifecycle_mutation_id,
            "defeat_record_lifecycle_mutation_id": (
                defeat_record.get("lifecycle_mutation_id")
            ),
            "param_entity_id": (
                death_event.payload.get("param_entity_id")
                if death_event is not None
                else None
            ),
        },
        "listeners": listeners,
        "formal_action_count": 2,
    }


def _base_type_source_contract(
    ordinary: dict[str, Any],
    death: dict[str, Any],
) -> dict[str, Any]:
    servant_base_type_event_count = sum(
        int(spawn.get("base_type_event_count") or 0)
        for spawn in (
            ordinary.get("spawn", {}),
            death.get("victim_spawn", {}),
            death.get("attacker_spawn", {}),
        )
        if isinstance(spawn, dict)
    )
    return {
        "ok": servant_base_type_event_count == 0,
        "status": "external_content_e2e_deferred",
        "callback_event": "OnListenAvatarBaseTypeChange",
        "runtime_event_type": "unit.base_type.changed",
        "listener_source": BASE_TYPE_LISTENER_SOURCE,
        "producer_category": (
            "formal in-combat character roster/base-type mutation"
        ),
        "required_source_condition": (
            "an admitted character unit spawn/remove or avatar_base_type "
            "flag mutation produced by a character/roster content card"
        ),
        "missing_content_owner": (
            "future character or roster role card"
        ),
        "current_source_adjudication": (
            "the selected production transition creates servants, not "
            "characters; servant birth is not a character base-type change"
        ),
        "formal_servant_spawn_base_type_event_count": (
            servant_base_type_event_count
        ),
        "synthetic_producer_used": False,
    }


def _external_deferred_contracts() -> list[dict[str, Any]]:
    ownership = {
        "OnCustomEvent": (
            "content card that declares and emits the matching custom event"
        ),
        "OnListenModifierAdd": (
            "content card that installs the listener and formally adds its "
            "matching modifier"
        ),
        "OnListenModifierOnStack": (
            "content card that installs the listener and formally changes "
            "the matching modifier stack"
        ),
    }
    return [
        {
            "ok": True,
            "callback_event": event,
            "status": "external_content_e2e_deferred",
            "required_trigger_condition": (
                "a source-backed formal parent transition with matching "
                "event payload and active listener scope"
            ),
            "missing_content_owner": ownership[event],
            "future_closure": (
                "close in the owning role/monster/content card without a "
                "validator-synthesized gameplay producer"
            ),
            "synthetic_producer_used": False,
        }
        for event in EXTERNAL_DEFERRED_EVENTS
    ]


def _direct_death_case(
    rules: RuleBook,
    *,
    target_id: str,
    sequence_id: str,
) -> tuple[BattleState, DamagePacket, Any, EventDispatchResult]:
    state = BattleState(
        units={
            "ally:direct-attacker": UnitState(
                unit_id="ally:direct-attacker",
                side="ally",
                template_id="validation:direct-attacker",
                max_hp=10.0,
                hp=10.0,
                attack=10.0,
            ),
            target_id: UnitState(
                unit_id=target_id,
                side="enemy",
                template_id="validation:direct-target",
                max_hp=1.0,
                hp=1.0,
            ),
        }
    )
    packet = DamagePacket(
        attacker_id="ally:direct-attacker",
        target_id=target_id,
        attack_type="validation_direct",
        damage_formula_family="hp_loss",
        amount=2.0,
        amount_stage="fixed_final",
        source_frame=DamageSourceFrame(
            owner_id="ally:direct-attacker",
            source_id=f"validation:{sequence_id}",
            source_kind="validation_direct_contract",
            sequence_id=sequence_id,
            target_id=target_id,
            can_continue_after_lethal=True,
            source_trace={
                "source_path": (
                    "validation/no_tbgd_direct_death_contract"
                ),
                "raw_type": "ValidationDirectContract",
                "raw_id": sequence_id,
            },
        ),
    )
    ledger = DamageWindowLedger()
    raw = DamageSystem().apply_packet(
        state,
        packet,
        window_ledger=ledger,
    )
    death_events = tuple(
        event
        for event in raw.events
        if event.event_type == "unit.defeated"
    )
    committed = CombatExecutor(rules).commit_eventful_transition(
        state,
        mutations=raw.mutations,
        events=death_events,
        records=raw.records,
        rng_events=raw.rng_events,
        producer_kind="direct_death_contract",
        producer_id=sequence_id,
        producer_ok=raw.ok,
        blocked_reason=";".join(raw.errors),
    )
    return state, packet, ledger, committed


def _direct_event_identity_conflict_contract(
    rules: RuleBook,
) -> dict[str, Any]:
    state = BattleState(
        skill_points=0,
        max_skill_points=5,
        units={
            "validation:target": UnitState(
                unit_id="validation:target",
                side="ally",
                template_id="validation:target",
                max_hp=10.0,
                hp=10.0,
            ),
        },
    )
    mutation = Mutation(
        op="set",
        path=("skill_points",),
        before=0,
        after=1,
        reason="validation event identity conflict candidate",
        source="validation",
        mutation_id="mutation:validation:event_identity_conflict",
    )
    rng_event = RNGEvent(
        rng_type="validation",
        source="validation:event_identity_conflict",
        result=1,
        event_id="rng:validation:event_identity_conflict",
    )
    base = GameEvent(
        event_type="validation.event",
        source_id="validation:source",
        target_id="validation:target",
        event_id="event:validation:identity-conflict",
        window="validation",
        process_only=False,
        payload={
            "value": 1,
            "normalized": True,
        },
    )
    auto_base = replace(base, event_id="")
    auto_event_id = str(
        auto_base.to_json().get("event_id") or ""
    )
    variants = {
        "event_type": (
            base,
            replace(base, event_type="validation.other"),
        ),
        "source_id": (
            base,
            replace(base, source_id="validation:forged-source"),
        ),
        "target_id": (
            base,
            replace(base, target_id="validation:forged-target"),
        ),
        "payload": (
            base,
            replace(
                base,
                payload={
                    "value": 2,
                    "normalized": True,
                },
            ),
        ),
        "process_only": (
            base,
            replace(base, process_only=True),
        ),
        "explicit_then_auto": (
            replace(
                auto_base,
                event_id=auto_event_id,
                source_id="validation:forged-source",
            ),
            auto_base,
        ),
        "auto_process_only": (
            auto_base,
            replace(auto_base, process_only=True),
        ),
        "payload_callback_events_injection": (
            base,
            replace(
                base,
                payload={
                    **base.payload,
                    "callback_events": ["OnForgedCallback"],
                },
            ),
        ),
        "payload_param_entity_injection": (
            base,
            replace(
                base,
                payload={
                    **base.payload,
                    "param_entity_id": "validation:forged",
                },
            ),
        ),
    }
    cases: dict[str, dict[str, Any]] = {}
    for name, pair in variants.items():
        result = CombatExecutor(
            rules
        ).commit_eventful_transition(
            state,
            mutations=(mutation,),
            events=pair,
            rng_events=(rng_event,),
            producer_kind="event_identity_conflict_contract",
            producer_id=name,
        )
        cases[name] = {
            "blocked": bool(result.errors),
            "state_unchanged": (
                result.after_state.snapshot().to_json()
                == state.snapshot().to_json()
            ),
            "mutation_count": len(result.mutations),
            "event_count": len(result.events),
            "rng_event_count": len(result.rng_events),
            "reason_codes": sorted(
                {
                    node.reason_code
                    for node in result.node_results
                    if node.reason_code
                }
            ),
            "errors": list(result.errors),
        }
    exact_duplicate = _dedupe_events(base, base)
    normalization_input = replace(
        base,
        event_id="event:validation:controlled-normalization",
        payload={"value": 1},
    )
    controlled_dispatch = EventDispatchSystem(
        rules,
        EffectRegistry(StatusSystem(rules)),
    ).dispatch_event(
        state,
        event=normalization_input,
    )
    normalized_events = _dedupe_events(
        normalization_input,
        *controlled_dispatch.events,
        event_normalizations=(
            controlled_dispatch.event_normalizations
        ),
    )
    positives = {
        "exact_duplicate": {
            "ok": len(exact_duplicate) == 1,
            "event_count": len(exact_duplicate),
        },
        "controlled_param_entity_normalization": {
            "ok": bool(
                len(controlled_dispatch.event_normalizations)
                == 1
                and len(normalized_events) == 1
                and normalized_events[0].payload
                == {
                    **normalization_input.payload,
                    "param_entity_id": "validation:target",
                }
            ),
            "event_count": len(normalized_events),
            "normalized_payload": (
                normalized_events[0].payload
                if len(normalized_events) == 1
                else {}
            ),
            "normalization_count": len(
                controlled_dispatch.event_normalizations
            ),
        },
    }
    ok = bool(
        len(cases) == len(variants)
        and all(
            row["blocked"]
            and row["state_unchanged"]
            and row["mutation_count"] == 0
            and row["event_count"] == 0
            and row["rng_event_count"] == 0
            and any(
                reason.startswith("event_identity_conflict:")
                for reason in row["reason_codes"]
            )
            for row in cases.values()
        )
        and all(row["ok"] for row in positives.values())
    )
    return {
        "ok": ok,
        "same_identity_conflict_cases": cases,
        "allowed_duplicate_cases": positives,
    }


def _direct_death_identity_contract() -> dict[str, Any]:
    rules = RuleBook(
        CanonicalIR(
            version=BASELINE_VERSION,
            metadata={
                "validation_scope": (
                    "no_tbgd_direct_death_identity_contract"
                )
            },
        )
    )
    state_a, packet_a, ledger_a, committed_a = _direct_death_case(
        rules,
        target_id="enemy:direct-a",
        sequence_id="direct-a",
    )
    state_b, _, _, committed_b = _direct_death_case(
        rules,
        target_id="enemy:direct-b",
        sequence_id="direct-b",
    )
    events_a = tuple(
        event
        for event in committed_a.events
        if event.event_type == "unit.defeated"
    )
    events_b = tuple(
        event
        for event in committed_b.events
        if event.event_type == "unit.defeated"
    )
    event_a = events_a[0] if len(events_a) == 1 else None
    event_b = events_b[0] if len(events_b) == 1 else None
    lifecycle_id_a = (
        str(
            event_a.payload.get("lifecycle_mutation_id")
            or event_a.payload.get("source_mutation_id")
            or ""
        )
        if event_a is not None
        else ""
    )
    replay_a = MutationReducer().replay_snapshot(
        state_a,
        committed_a.mutations,
        committed_a.after_state.snapshot().to_json(),
    )
    later = DamageSystem().apply_packet(
        committed_a.after_state,
        packet_a,
        window_ledger=ledger_a,
    )
    later_death_count = sum(
        event.event_type == "unit.defeated"
        for event in later.events
    )
    dispatcher = EventDispatchSystem(
        rules,
        EffectRegistry(StatusSystem(rules)),
    )
    negatives: dict[str, dict[str, Any]] = {}
    if event_a is not None:
        forged = {
            "missing_identity": (
                committed_a.after_state,
                replace(event_a, event_id=""),
            ),
            "mutation_identity_mismatch": (
                committed_a.after_state,
                replace(
                    event_a,
                    payload={
                        **event_a.payload,
                        "lifecycle_mutation_id": (
                            "mutation:forged"
                        ),
                        "source_mutation_id": "mutation:forged",
                    },
                ),
            ),
            "uncommitted_state": (
                state_a,
                event_a,
            ),
        }
        for name, (input_state, event) in forged.items():
            result = dispatcher.dispatch_event(
                input_state,
                event=event,
            )
            unchanged = (
                result.after_state.snapshot().to_json()
                == input_state.snapshot().to_json()
            )
            negatives[name] = {
                "blocked": bool(result.errors),
                "state_unchanged": unchanged,
                "mutation_count": len(result.mutations),
                "errors": list(result.errors),
            }
    stable_identity_ok = bool(
        event_a is not None
        and lifecycle_id_a
        and event_a.event_id
        == mutation_backed_event_id(
            lifecycle_id_a,
            "unit.defeated",
        )
    )
    distinct_identity_ok = bool(
        event_a is not None
        and event_b is not None
        and event_a.event_id != event_b.event_id
    )
    negatives_ok = bool(
        len(negatives) == 3
        and all(
            row["blocked"]
            and row["state_unchanged"]
            and row["mutation_count"] == 0
            for row in negatives.values()
        )
    )
    event_identity_conflicts = (
        _direct_event_identity_conflict_contract(rules)
    )
    ok = bool(
        not committed_a.errors
        and not committed_b.errors
        and len(events_a) == 1
        and len(events_b) == 1
        and stable_identity_ok
        and distinct_identity_ok
        and replay_a.ok
        and later_death_count == 0
        and negatives_ok
        and event_identity_conflicts["ok"]
        and committed_a.after_state.units[
            "enemy:direct-a"
        ].lifecycle_status
        == "defeated"
        and committed_b.after_state.units[
            "enemy:direct-b"
        ].lifecycle_status
        == "defeated"
        and state_b.units[
            "enemy:direct-b"
        ].lifecycle_status
        == "active"
    )
    return {
        "ok": ok,
        "no_tbgd_lowering": True,
        "same_mutation_normalized_death_event_count": len(events_a),
        "stable_identity_matches_lifecycle_mutation": (
            stable_identity_ok
        ),
        "different_lifecycle_mutations_have_distinct_event_ids": (
            distinct_identity_ok
        ),
        "later_hit_death_event_count": later_death_count,
        "replay_equal": replay_a.ok,
        "negative_contracts": negatives,
        "event_identity_conflicts": event_identity_conflicts,
    }


def run_validation(
    tbgd_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    rules, projection = _build_rulebook(tbgd_root)
    ordinary = _ordinary_dynamic_contract(rules)
    death = _death_contract(rules)
    event_identity_conflicts = (
        _direct_event_identity_conflict_contract(rules)
    )
    projection_identity_conflicts = (
        _projection_identity_conflict_contract(rules)
    )
    base_type = _base_type_source_contract(ordinary, death)
    deferred = _external_deferred_contracts()
    formal_action_count = int(
        ordinary.get("formal_action_count") or 0
    ) + int(death.get("formal_action_count") or 0)
    elapsed = time.monotonic() - started
    peak_rss_mib = resource.getrusage(
        resource.RUSAGE_SELF
    ).ru_maxrss / 1024.0
    predicates = {
        "two_dynamic_tasks_one_formal_action": ordinary["ok"],
        "deathrattle_precondition_and_lethal_actions_closed": (
            death["ok"]
        ),
        "same_event_identity_conflicts_fail_closed": (
            event_identity_conflicts["ok"]
        ),
        "projection_identity_conflicts_fail_closed": (
            projection_identity_conflicts["ok"]
        ),
        "base_type_source_correctly_deferred": base_type["ok"],
        "existing_external_deferrals_structured": all(
            row["ok"]
            and row["status"]
            == "external_content_e2e_deferred"
            for row in deferred
        ),
        "full_tbgd_lowering_build_count_zero": (
            projection["full_tbgd_lowering_build_count"] == 0
        ),
        "one_source_projection": (
            projection["source_projection_count"] == 1
        ),
        "one_source_backed_rulebook": (
            projection["source_backed_rulebook_build_count"] == 1
        ),
        "exactly_three_formal_actions": formal_action_count == 3,
        "peak_rss_below_1_gib": peak_rss_mib < 1024.0,
        "wall_time_below_5_minutes": elapsed < 300.0,
    }
    ok = all(predicates.values())
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "predicates": predicates,
        "source_projection": projection,
        "formal_execution": {
            "ordinary_dynamic": ordinary,
            "lethal_death": death,
            "formal_action_count": formal_action_count,
            "ordinary_action_count": int(
                ordinary.get("formal_action_count") or 0
            ),
            "lethal_action_count": int(
                death.get("formal_action_count") or 0
            ),
        },
        "base_type_source_adjudication": base_type,
        "external_content_e2e_deferred": deferred,
        "identity_conflict_contracts": {
            "event": event_identity_conflicts,
            "projection": projection_identity_conflicts,
        },
        "resource_scope": {
            "full_canonical_ir_serialized": False,
            "transition_dump_written": False,
            "cross_state_cache_used": False,
            "synthetic_gameplay_producer_used": False,
            "artifact_count": 1,
            "artifact_limit_bytes": 1024 * 1024,
            "elapsed_seconds": round(elapsed, 3),
            "peak_rss_mib": round(peak_rss_mib, 3),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / (
        "validation_summary_p8_r2_memory_light_cone_"
        "formal_event_chain_closure.json"
    )
    write_json(path, summary)
    summary["resource_scope"]["artifact_size_bytes"] = (
        path.stat().st_size
    )
    if path.stat().st_size >= 1024 * 1024:
        summary["ok"] = False
        summary["ready_for_review"] = False
        summary["predicates"]["artifact_below_1_mib"] = False
    else:
        summary["predicates"]["artifact_below_1_mib"] = True
    write_json(path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--direct-contract-only",
        action="store_true",
        help=(
            "Run only the no-TBGD direct death identity contract."
        ),
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.direct_contract_only:
        direct = _direct_death_identity_contract()
        summary = {
            "schema_version": (
                "p8_r2_direct_death_identity_contract_v1"
            ),
            "validation_version": VALIDATION_VERSION,
            "ok": direct["ok"],
            "direct_kernel_contract": direct,
        }
        write_json(
            output_dir
            / "direct_death_identity_contract_p8_r2.json",
            summary,
        )
        return 0 if summary["ok"] else 1
    root = (
        args.tbgd_root.resolve()
        if args.tbgd_root is not None
        else find_tbgd_root(Path.cwd())
    )
    summary = run_validation(root, output_dir)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
