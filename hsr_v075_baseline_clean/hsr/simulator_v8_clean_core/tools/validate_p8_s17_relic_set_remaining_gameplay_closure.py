from __future__ import annotations

import argparse
import resource
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from ..core.executor import CombatExecutor
from ..core.model import (
    ActionCommand,
    ActionSettlement,
    ActionTransaction,
    BattleState,
    BattleTransition,
    GameEvent,
    UnitState,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.evaluator import EvaluationContext, RuleEvaluator
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, UnitSpec
from ..systems.decision import DecisionSystem
from ..systems.effect import EffectExecutionContext
from ..systems.mutation_events import events_for_mutation
from ..systems.unit_lifecycle import UnitLifecycleSystem
from ..tbgd.lowering import (
    TBGDLowering,
    _link_status_effect_runtime_fields,
    _lower_status_event_families,
)
from ..unit_eligibility import (
    runtime_unit_is_battle_event_entity,
    runtime_unit_is_on_field,
)
from ..unit_presence import unit_departure_sources
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state
from .validate_p8_s15_relic_set_dynamic_startup import _build_bundle, _scenario
from .validate_p8_s16_relic_set_status_condition_listener_closure import (
    _detail,
    _equipment,
    _fingerprint,
    _partition,
    _replace_details,
    _set_handler_hits,
    _templates,
    _thresholds,
)


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    projection: dict[str, Any] = {}
    action_fixture: dict[str, Any] = {}
    owned = TBGDLowering(
        tbgd_root
    ).build_owned_combatant_admission_projection(
        offensive_action_only=True,
        max_servant_count=1,
    )
    if not owned.ok:
        raise ValueError(
            "source-backed owned-combatant projection failed:"
            + ",".join(sorted({issue.code for issue in owned.issues}))
        )
    owner_refs = {
        owner_ref
        for definition in owned.servant_definitions
        for owner_ref in definition.owner_entity_refs
    }
    owner_cards = tuple(
        card
        for card in owned.character_data_cards
        if card.entity_ref in owner_refs
    )
    if len(owner_cards) != 1:
        raise ValueError(
            f"focused owned-combatant owner card count:{len(owner_cards)}"
        )

    def transform(ir: CanonicalIR, lowering: TBGDLowering) -> CanonicalIR:
        with_action = _add_owned_action_projection(
            ir,
            owned,
            action_fixture,
        )
        return _add_departure_projection(
            with_action,
            lowering,
            projection,
        )

    bundle = _build_bundle(
        tbgd_root,
        require_blocked_sample=False,
        required_card_id=owner_cards[0].card_id,
        ir_transform=transform,
    )
    rules = bundle["rules"]
    partition = _partition(bundle)
    action = _action_cases(bundle, rules, action_fixture)
    stack = _stack_change_case(bundle, rules)
    battle_event = _battle_event_case(bundle, rules)
    departure = _departure_case(bundle, rules, projection)
    audit_inputs = (
        *action.pop("_audit_inputs"),
        *departure.pop("_audit_inputs"),
    )
    audit = _audit_replay(rules, audit_inputs)
    handler_hits = _set_handler_hits()
    non_gameplay = _non_gameplay_evidence(rules)
    fingerprint = _fingerprint(bundle)

    predicates: dict[str, bool | int] = {
        "s16_evidence_current": bool(fingerprint.get("sha256")),
        "s16_s17_union_equals_current_gameplay": partition["complete"],
        "s16_s17_intersection_empty": partition["disjoint"],
        "s17_remaining_family_gap_count": partition["s17_gap_count"],
        "published_player_set_blocked_graph_count": partition["blocked_graph_count"],
        "unknown_gameplay_node_count": partition["unknown_count"],
        "non_gameplay_rows_have_structured_evidence": non_gameplay["ok"],
        "resource_hp_damage_timeline_use_common_routes": (
            action["formal_damage_windows"]
            and stack["formal_status_lifecycle"]
            and battle_event["formal_unit_lifecycle"]
            and departure["formal_presence_lifecycle"]
        ),
        "static_condition_mutation_order_correct": action["ordered"],
        "stale_plan_rejected": action["stale_rejected"],
        "team_effects_mutate_real_targets": departure["wearer_recomputed"],
        "multi_wearer_and_wave_lifecycle_correct": departure["identity_isolated"],
        "rng_choices_have_stable_identity": _rng_contract_inherited(partition),
        "blocked_transition_state_unchanged": (
            stack["missing_payload_atomic"]
            and battle_event["subtype_only_rejected"]
            and departure["conflict_atomic"]
        ),
        "sampled_mutations_source_audited": audit["source_audit"],
        "sampled_transitions_replay_equal": audit["replay"],
        "set_specific_runtime_handlers": len(handler_hits),
    }
    zero_keys = {
        "s17_remaining_family_gap_count",
        "published_player_set_blocked_graph_count",
        "unknown_gameplay_node_count",
        "set_specific_runtime_handlers",
    }
    ok = all(
        value == 0 if key in zero_keys else value is True
        for key, value in predicates.items()
    )
    artifacts = {
        "remaining_family_matrix_p8_s17.json": {
            "partition": partition,
            "non_gameplay": non_gameplay,
            "source_fingerprint": fingerprint,
        },
        "formal_gameplay_cases_p8_s17.json": {
            "action": action,
            "stack_change": stack,
            "battle_event": battle_event,
            "departure": departure,
        },
        "audit_replay_p8_s17.json": {
            "audit": audit,
            "set_specific_handler_hits": handler_hits,
        },
    }
    for filename, payload in artifacts.items():
        write_json(output_dir / filename, payload)
    summary = {
        "ok": ok,
        "predicates": predicates,
        "counts": {
            "graphs": len(bundle["graphs"]),
            "executable_graphs": sum(
                graph.coverage_status == "executable"
                for graph in bundle["graphs"]
            ),
            "s16_families": partition["s16_count"],
            "s17_families": partition["s17_count"],
            "sampled_transitions": len(audit_inputs),
            "departure_source_candidates": projection["candidate_count"],
        },
        "source": {
            "fingerprint": fingerprint,
            "departure_sample": projection["public"],
        },
        "resources": {
            "focused_rulebook_builds": 1,
            "full_lowering_builds": 0,
            "focused_character_ability_files": projection["lowered_file_count"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "artifact_bytes_before_summary": sum(
                (output_dir / name).stat().st_size for name in artifacts
            ),
        },
        "inherited_contracts_not_rerun": [
            "P7 resource/HP/shield/timeline/wave/RNG focused contracts",
            "P8-S16 status/condition/listener lifecycle cases",
        ],
    }
    write_json(
        output_dir
        / "validation_summary_p8_s17_relic_set_remaining_gameplay_closure.json",
        summary,
    )
    return summary


def _add_departure_projection(
    ir: CanonicalIR,
    lowering: TBGDLowering,
    projection: dict[str, Any],
) -> CanonicalIR:
    root = lowering.tbgd_root
    candidates: list[dict[str, Any]] = []
    lowered_count = 0
    avatar_root = root / "Config" / "ConfigAbility" / "Avatar"
    for order, path in enumerate(sorted(avatar_root.glob("*.json"))):
        if "AttachEntityDeparted" not in path.read_text(encoding="utf-8"):
            continue
        lowered_count += 1
        lowered = lowering._lower_ability_file(
            path,
            {},
            ability_file_order=order,
        )
        for attach in lowered.effects:
            if (
                attach.opcode != "AttachEntityDeparted"
                or attach.coverage_status != "executable"
                or not attach.owner_modifier_name
            ):
                continue
            owner = attach.owner_modifier_name
            additions = tuple(
                effect
                for effect in lowered.effects
                if effect.opcode == "AddModifier"
                and effect.coverage_status == "executable"
                and isinstance(effect.payload.get("standard"), dict)
                and effect.payload["standard"].get("modifier_name") == owner
            )
            removals = tuple(
                effect
                for effect in lowered.effects
                if effect.opcode == "RemoveModifier"
                and effect.coverage_status == "executable"
                and isinstance(effect.payload.get("standard"), dict)
                and effect.payload["standard"].get("modifier_name") == owner
            )
            callbacks = tuple(
                callback
                for callback in lowered.status_callbacks
                if callback.modifier_name == owner
                and callback.event == "OnStack"
                and callback.coverage_status == "executable"
            )
            if additions and removals and len(callbacks) == 1:
                candidates.append(
                    {
                        "path": path,
                        "lowered": lowered,
                        "attach": attach,
                        "add": additions[0],
                        "remove": removals[0],
                        "callback": callbacks[0],
                    }
                )
    if not candidates:
        raise ValueError("source-backed departure lifecycle sample unavailable")
    selected = sorted(
        candidates,
        key=lambda row: (
            row["path"].as_posix(),
            row["attach"].effect_id,
            row["add"].effect_id,
        ),
    )[0]
    lowered = selected["lowered"]
    callback = selected["callback"]
    callback_tasks = tuple(
        task
        for task in lowered.status_callback_tasks
        if task.callback_id == callback.callback_id
    )
    effects = (
        selected["add"],
        selected["remove"],
        selected["attach"],
    )
    target_ids = {
        standard.get("target_expression_id")
        for effect in effects
        if isinstance((standard := effect.payload.get("standard")), dict)
        and isinstance(standard.get("target_expression_id"), str)
    }
    selected_targets = tuple(
        target
        for target in lowered.target_expressions
        if target.target_expression_id in target_ids
    )
    callbacks = _merge_unique(
        (*ir.status_callbacks, callback),
        "callback_id",
    )
    tasks = _merge_unique(
        (*ir.status_callback_tasks, *callback_tasks),
        "task_id",
    )
    entities = _merge_unique((*ir.entities, *lowered.entities), "entity_id")
    linked_effects = tuple(
        _link_status_effect_runtime_fields(
            list(_merge_unique((*ir.effects, *effects), "effect_id")),
            list(entities),
            list(callbacks),
            list(ir.ability_property_watchers),
        )
    )
    existing_callback_events = {
        family.callback_event for family in ir.status_event_families
    }
    added_families = tuple(
        family
        for family in _lower_status_event_families((callback,), callback_tasks)
        if family.callback_event not in existing_callback_events
    )
    event_families = _merge_unique(
        (*ir.status_event_families, *added_families),
        "status_event_family_id",
    )
    projection.update(
        {
            "candidate_count": len(candidates),
            "lowered_file_count": lowered_count,
            "add_id": selected["add"].effect_id,
            "remove_id": selected["remove"].effect_id,
            "attach_id": selected["attach"].effect_id,
            "owner_modifier_name": selected["attach"].owner_modifier_name,
            "public": {
                "source_path": selected["attach"].source.source_path,
                "owner_modifier_name": selected["attach"].owner_modifier_name,
                "attach_effect_id": selected["attach"].effect_id,
                "add_effect_id": selected["add"].effect_id,
                "remove_effect_id": selected["remove"].effect_id,
                "selection": "structural executable add/attach/remove closure",
            },
        }
    )
    return replace(
        ir,
        entities=entities,
        effects=linked_effects,
        target_expressions=_merge_unique(
            (*ir.target_expressions, *selected_targets),
            "target_expression_id",
        ),
        status_callbacks=callbacks,
        status_callback_tasks=tasks,
        status_event_families=event_families,
    )


def _add_owned_action_projection(
    ir: CanonicalIR,
    owned: Any,
    metadata: dict[str, Any],
) -> CanonicalIR:
    definitions = {
        (item.action_id, item.level): item
        for item in owned.action_definitions
    }
    action_events = {
        (item.action_id, item.level): item
        for item in owned.action_events
    }
    executable_damage = {
        (item.action_id, item.level)
        for item in owned.damage_emissions
        if item.coverage_status == "executable"
    }
    owner_refs = {
        owner_ref
        for servant in owned.servant_definitions
        for owner_ref in servant.owner_entity_refs
    }
    owner_cards = tuple(
        card
        for card in owned.character_data_cards
        if card.entity_ref in owner_refs
    )
    if len(owner_cards) != 1:
        raise ValueError(
            f"owned action owner card count:{len(owner_cards)}"
        )
    owner_card = owner_cards[0]
    owner_admissions = tuple(
        admission
        for admission in owned.action_admissions
        if admission.coverage_status == "executable"
        and admission.action_role == "turn_action"
        and admission.owner_entity_ref == owner_card.entity_ref
        and (admission.action_id, admission.action_level)
        in executable_damage
        and (event := action_events.get(
            (admission.action_id, admission.action_level)
        ))
        is not None
        and event.coverage_status in {"lowered", "executable"}
    )
    if not owner_admissions:
        raise ValueError("source-backed owner damage action missing")
    admission = sorted(
        owner_admissions,
        key=lambda item: (
            item.owner_entity_ref,
            item.action_id,
            item.action_level,
        ),
    )[0]
    definition = definitions[(admission.action_id, admission.action_level)]
    entities = _merge_projection_values(
        ir.entities,
        owned.entities,
        "entity_id",
        replace_conflicts=owner_refs,
    )
    cards = _merge_projection_values(
        ir.character_data_cards,
        owned.character_data_cards,
        "card_id",
        replace_conflicts={owner_card.card_id},
    )
    callbacks = _merge_unique(
        (*ir.status_callbacks, *owned.status_callbacks),
        "callback_id",
    )
    callback_tasks = _merge_unique(
        (*ir.status_callback_tasks, *owned.status_callback_tasks),
        "task_id",
    )
    existing_callback_events = {
        family.callback_event for family in ir.status_event_families
    }
    added_families = tuple(
        family
        for family in _lower_status_event_families(
            list(owned.status_callbacks),
            list(owned.status_callback_tasks),
        )
        if family.callback_event not in existing_callback_events
    )
    effects = tuple(
        _link_status_effect_runtime_fields(
            list(
                _merge_unique(
                    (*ir.effects, *owned.effects),
                    "effect_id",
                )
            ),
            list(entities),
            list(callbacks),
            list(ir.ability_property_watchers),
        )
    )
    engine = build_engine_rule_registry()
    metadata.update(
        {
            "action_id": admission.action_id,
            "level": admission.action_level,
            "actor_entity_ref": admission.owner_entity_ref,
            "card_id": owner_card.card_id,
            "entity_ref": owner_card.entity_ref,
            "admission_id": admission.admission_id,
            "definition_id": definition.definition_id,
            "source": definition.source.to_json(),
            "projection": "owned_combatant_admission_projection",
        }
    )
    merge_fields = {
        "avatar_profiles": "avatar_profile_id",
        "character_equipment_eligibilities": "definition_key",
        "character_mechanism_slots": "mechanism_slot_id",
        "character_trace_nodes": "trace_node_id",
        "character_eidolon_slots": "eidolon_slot_id",
        "servant_definitions": "servant_definition_id",
        "action_definitions": "definition_id",
        "action_ability_bindings": "binding_id",
        "action_admissions": "admission_id",
        "unit_birth_templates": "birth_template_id",
        "combatant_action_sets": "combatant_action_set_id",
        "ability_phases": "phase_id",
        "ability_tasks": "task_id",
        "action_events": "action_event_id",
        "hit_profiles": "hit_profile_id",
        "skill_formula_bindings": "binding_id",
        "damage_emissions": "damage_emission_id",
        "toughness_emissions": "toughness_emission_id",
        "conditions": "condition_id",
        "formulas": "formula_id",
        "target_expressions": "target_expression_id",
        "status_damage_emissions": "status_damage_emission_id",
        "damage_modifiers": "damage_modifier_id",
        "action_delay_emissions": "action_delay_emission_id",
        "queue_intents": "queue_intent_id",
        "skill_continuations": "continuation_id",
        "triggers": "trigger_id",
        "bounce_policies": "bounce_policy_id",
    }
    merged_fields = {
        field: _merge_unique(
            (*getattr(ir, field), *getattr(owned, field)),
            identity,
        )
        for field, identity in merge_fields.items()
    }
    return replace(
        ir,
        entities=entities,
        character_data_cards=cards,
        effects=effects,
        status_callbacks=callbacks,
        status_callback_tasks=callback_tasks,
        status_event_families=_merge_unique(
            (*ir.status_event_families, *added_families),
            "status_event_family_id",
        ),
        timeline_rules=engine.timeline_rules,
        resource_rules=engine.resource_rules,
        damage_formula_rules=engine.damage_formula_rules,
        damage_route_rules=engine.damage_route_rules,
        shield_priority_rules=engine.shield_priority_rules,
        **merged_fields,
    )


def _action_cases(
    bundle: dict[str, Any],
    rules: RuleBook,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    behavior_task = _single_task(
        rules,
        "SetDynamicValueByBehaviorFlagCount",
    )
    behavior_callback = rules.status_callback(behavior_task.callback_id)
    if behavior_callback is None:
        raise ValueError("behavior-count callback missing")
    behavior = _run_action(
        bundle,
        rules,
        fixture,
        _ability_name(behavior_task),
        "behavior",
        _add_dot_statuses,
    )
    behavior_after = _detail(
        behavior["after"],
        behavior["listener_id"],
        behavior_callback.modifier_name,
    )
    dot_count = _dynamic_value(behavior_after, "_DotCount")

    tag_condition = next(
        condition
        for condition in rules.ir.conditions
        if condition.opcode == "ByCompareDamageTag"
        and condition.coverage_status == "executable"
        and condition.source.evidence.get(
            "equipment_ability_source_admitted"
        )
        is True
    )
    evaluator = RuleEvaluator()
    tag_true = evaluator.evaluate_condition_result(
        tag_condition,
        EvaluationContext(
            event_payload={
                "damage_tags": ["FeverBreak"],
                "damage_custom_name": "NotFeverBreak",
            }
        ),
    )
    tag_false = evaluator.evaluate_condition_result(
        tag_condition,
        EvaluationContext(
            event_payload={
                "damage_tags": [],
                "damage_custom_name": "FeverBreak",
            }
        ),
    )
    end_callback = next(
        callback
        for callback in rules.ir.status_callbacks
        if callback.event == "OnAfterAttackEnd"
        and callback.coverage_status == "executable"
        and callback.source.evidence.get("equipment_ability_source_admitted")
        is True
    )
    ended = _run_action(
        bundle,
        rules,
        fixture,
        _ability_name(end_callback),
        "attack_end",
    )
    end_after = _detail(
        ended["after"],
        ended["listener_id"],
        end_callback.modifier_name,
    )
    events = ended["action_transition"].transaction.events
    before_indices = [
        index
        for index, event in enumerate(events)
        if event.event_type == "damage.hit_sequence.before"
    ]
    end_indices = [
        index
        for index, event in enumerate(events)
        if event.event_type == "action.attack_end"
    ]
    after_indices = [
        index
        for index, event in enumerate(events)
        if event.event_type == "damage.hit_sequence.after"
    ]
    before_by_sequence = {
        str(event.payload.get("damage_sequence_source_task_id") or ""): index
        for index, event in enumerate(events)
        if event.event_type == "damage.hit_sequence.before"
    }
    after_by_sequence = {
        str(event.payload.get("damage_sequence_source_task_id") or ""): index
        for index, event in enumerate(events)
        if event.event_type == "damage.hit_sequence.after"
    }
    hit_indices_by_sequence: dict[str, list[int]] = {}
    for index, event in enumerate(events):
        if event.event_type != "damage.hit":
            continue
        sequence_id = str(event.payload.get("source_task_id") or "")
        hit_indices_by_sequence.setdefault(sequence_id, []).append(index)
    sequence_ids = set(hit_indices_by_sequence)
    sequence_ordered = (
        bool(sequence_ids)
        and sequence_ids == set(before_by_sequence)
        and sequence_ids == set(after_by_sequence)
        and all(
            before_by_sequence[sequence_id]
            < min(hit_indices_by_sequence[sequence_id])
            <= max(hit_indices_by_sequence[sequence_id])
            < after_by_sequence[sequence_id]
            for sequence_id in sequence_ids
        )
    )
    behavior_windows = [
        event
        for event in behavior["action_transition"].transaction.events
        if event.event_type == "damage.hit_sequence.before"
    ]
    stale = ended["stale"]
    audit_inputs = (
        (behavior["before"], behavior["transition"]),
        (ended["before"], ended["transition"]),
    )
    return {
        "formal_damage_windows": (
            dot_count == 2.0
            and bool(behavior_windows)
            and all(
                event.payload.get("param_entity_id")
                == behavior["target_id"]
                for event in behavior_windows
            )
            and tag_true.ok
            and tag_true.result is True
            and tag_false.ok
            and tag_false.result is False
        ),
        "ordered": (
            sequence_ordered
            and len(end_indices) == 1
            and max(after_indices) < end_indices[0]
            and _dynamic_value(end_after, "Attack_Flag") == 0.0
        ),
        "stale_rejected": (
            not stale.transition.outcome.successor_eligible
            and "stale_decision_token"
            in stale.transition.outcome.reason_codes
            and stale.transition.after.to_json()
            == ended["transition"].after.to_json()
        ),
        "behavior_count": {
            "task_id": behavior_task.task_id,
            "dot_count": dot_count,
            "before_hit_param_ids": [
                event.payload.get("param_entity_id")
                for event in behavior["action_transition"].transaction.events
                if event.event_type == "damage.hit_sequence.before"
            ],
        },
        "damage_tag": {
            "condition_id": tag_condition.condition_id,
            "tagged_result": tag_true.result,
            "custom_name_only_result": tag_false.result,
            "producer_scope": (
                "typed event payload contract; no avatar action tag fixture"
            ),
        },
        "action_end": {
            "callback_id": end_callback.callback_id,
            "before_hit_count": len(before_indices),
            "damage_hit_count": sum(
                event.event_type == "damage.hit" for event in events
            ),
            "after_hit_count": len(after_indices),
            "attack_end_count": len(end_indices),
            "sequence_ids": sorted(sequence_ids),
            "final_attack_flag": _dynamic_value(end_after, "Attack_Flag"),
        },
        "_audit_inputs": audit_inputs,
    }


def _run_action(
    bundle: dict[str, Any],
    rules: RuleBook,
    fixture: dict[str, Any],
    ability_name: str,
    tag: str,
    prepare: Callable[[BattleState, str], BattleState] | None = None,
) -> dict[str, Any]:
    threshold = _thresholds(bundle).get(ability_name)
    if threshold is None:
        raise ValueError(f"relic threshold missing for ability:{ability_name}")
    equipment = _equipment(
        bundle,
        _templates(
            bundle["catalog"],
            threshold.set_key,
            threshold.require_count,
        ),
        f"s17:{tag}",
    )
    scenario_tag = f"s17:{tag}"
    built = ScenarioStateBuilder(rules).build(
        _scenario(bundle["card"], equipment, scenario_tag)
    )
    listener_id = f"ally:{scenario_tag}"
    if built.blocked_setup:
        raise ValueError(
            f"formal action scenario blocked:{tag}:{built.blocked_setup}"
        )
    actor_id = listener_id
    enemy_fixture = _base_state(
        target_hp=5000.0,
        include_second_enemy=True,
    )
    enemy = replace(
        enemy_fixture.units["enemy:target"],
        max_hp=5000.0,
        hp=5000.0,
        flags={"action_disabled": True, "position": 0},
    )
    adjacent_enemy = replace(
        enemy_fixture.units["enemy:second"],
        max_hp=5000.0,
        hp=5000.0,
        flags={"action_disabled": True, "position": 1},
    )
    state = replace(
        built.state,
        units={
            **{
                unit_id: replace(
                    unit,
                    action_value=(
                        0.0
                        if unit_id == actor_id
                        else max(10.0, float(unit.action_value))
                    ),
                    flags={
                        **unit.flags,
                        "action_disabled": False,
                    },
                )
                for unit_id, unit in built.state.units.items()
            },
            enemy.unit_id: enemy,
            adjacent_enemy.unit_id: adjacent_enemy,
        },
        global_flags={
            key: value
            for key, value in built.state.global_flags.items()
            if key not in {
                "active_turn",
                "pending_turn_end",
                "turn_owner_id",
            }
        },
    )
    if prepare is not None:
        state = prepare(state, enemy.unit_id)
    decisions = DecisionSystem(rules)
    advance = decisions.advance_to_decision(state)
    decision = advance.decision
    turn_state = advance.after_state
    choices = tuple(
        choice
        for choice in decision.availability.choices
        if choice.actor_id == actor_id
        if choice.action_id == fixture["action_id"]
        and choice.action_level == fixture["level"]
        and choice.admission_id == fixture["admission_id"]
        and choice.owner_entity_ref == fixture["actor_entity_ref"]
        and choice.action_role == "turn_action"
        and isinstance(choice.source_trace.get("actor_data_card"), dict)
        and choice.source_trace["actor_data_card"].get("card_id")
        == fixture["card_id"]
        and enemy.unit_id
        in (*choice.auto_target_ids, *choice.selectable_target_ids)
    )
    if not decision.ready or len(choices) != 1:
        available = tuple(
            {
                "choice_id": choice.choice_id,
                "actor_id": choice.actor_id,
                "action_id": choice.action_id,
                "action_level": choice.action_level,
                "admission_id": choice.admission_id,
                "owner_entity_ref": choice.owner_entity_ref,
                "action_role": choice.action_role,
                "target_status": choice.target_status,
                "resource_status": choice.resource_status,
            }
            for choice in decision.availability.choices
        )
        raise ValueError(
            f"formal action decision unavailable:{tag}:"
            f"ready={decision.ready}:"
            f"reason={decision.blocked_reason}:"
            f"available={available}"
        )
    choice = choices[0]
    command = ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=(enemy.unit_id,),
        source="manual",
        metadata=dict(choice.command_template.get("metadata") or {}),
    )
    submitted = decisions.submit(
        turn_state,
        decision.token,
        command,
    )
    if not submitted.transition.outcome.successor_eligible:
        raise ValueError(
            f"formal action execution blocked:{tag}:"
            f"{submitted.transition.outcome.reason_codes}"
        )
    action_children = tuple(
        child
        for child in submitted.child_transitions
        if child.transaction.command.action_id == command.action_id
        and child.transaction.command.actor_id == command.actor_id
    )
    if len(action_children) != 1:
        raise ValueError(
            f"formal action child transition unavailable:{tag}:"
            f"count={len(action_children)}"
        )
    stale = decisions.submit(
        submitted.after_state,
        decision.token,
        command,
    )
    return {
        "actor_id": actor_id,
        "listener_id": listener_id,
        "target_id": enemy.unit_id,
        "before": turn_state,
        "after": submitted.after_state,
        "transition": submitted.transition,
        "action_transition": action_children[0],
        "stale": stale,
        "actor_source": fixture["source"],
    }


def _add_dot_statuses(state: BattleState, target_id: str) -> BattleState:
    details = [
        dict(item)
        for item in state.units[target_id].flags.get("status_details", ())
        if isinstance(item, dict)
    ]
    for index in range(2):
        details.append(
            {
                "instance_id": f"validation:p8_s17:dot:{index}",
                "status_id": f"validation:p8_s17:dot:{index}",
                "modifier_name": f"ValidationP8S17Dot{index}",
                "owner_id": target_id,
                "source_id": "validation:p8_s17:committed_precondition",
                "caster_id": "ally:s17:behavior",
                "status_category": "debuff",
                "behavior_flags": ["STAT_DOT"],
                "ability_property_watcher_ids": [],
                "trigger_ids_by_event": {},
                "source_trace": {
                    "source_path": "validation/p8_s17/committed_precondition",
                    "raw_type": "ValidationFixture",
                    "raw_id": f"dot:{index}",
                    "evidence": {"validation_fixture": True},
                },
            }
        )
    return _replace_details(state, target_id, details)


def _stack_change_case(
    bundle: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    task = _single_task(rules, "SetDynamicValueByChangeValue")
    callback = rules.status_callback(task.callback_id)
    if callback is None:
        raise ValueError("change-value callback missing")
    ability = _ability_name(task)
    threshold = _thresholds(bundle)[ability]
    equipment = _equipment(
        bundle,
        _templates(
            bundle["catalog"],
            threshold.set_key,
            threshold.require_count,
        ),
        "s17:stack",
    )
    built = ScenarioStateBuilder(rules).build(
        _scenario(bundle["card"], equipment, "s17:stack")
    )
    unit_id = "ally:s17:stack"
    detail = _detail(built.state, unit_id, callback.modifier_name)
    if built.blocked_setup or detail is None:
        raise ValueError("stack-change source status missing")
    trigger = next(
        event
        for event in built.setup_events
        if event.event_type == "status.lifecycle"
        and event.window == "OnStack"
        and event.payload.get("modifier_name") == callback.modifier_name
    )
    callback_records = tuple(
        record
        for record in built.setup_records
        if isinstance(record, dict)
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    )
    bad_payload = dict(trigger.payload)
    bad_payload.pop("change_value", None)
    blocked = CombatExecutor(rules).event_dispatcher.dispatch_event(
        built.state,
        event=replace(
            trigger,
            event_id=f"{trigger.event_id}:missing_change_value",
            payload=bad_payload,
        ),
    )
    expected_delta = trigger.payload.get("change_value")
    observed = _dynamic_value(detail, "Temp_ChangeValue")
    return {
        "formal_status_lifecycle": (
            isinstance(expected_delta, (int, float))
            and not isinstance(expected_delta, bool)
            and observed == float(expected_delta)
            and any(
                record.get("record_type") == "status_dynamic_value"
                and record["payload"].get("task_id") == task.task_id
                for record in callback_records
            )
        ),
        "missing_payload_atomic": (
            "callback_change_value_missing" in blocked.errors
            and blocked.after_state.snapshot().to_json()
            == built.state.snapshot().to_json()
            and not blocked.mutations
            and not blocked.events
            and not blocked.rng_events
        ),
        "task_id": task.task_id,
        "raw_opcode": task.source.evidence.get("raw_opcode"),
        "change_value": expected_delta,
        "stored_value": observed,
        "blocked_errors": list(blocked.errors),
    }


def _battle_event_case(
    bundle: dict[str, Any],
    rules: RuleBook,
) -> dict[str, Any]:
    callback = next(
        item
        for item in rules.ir.status_callbacks
        if item.event == "OnListenBattleEventCreate"
        and item.coverage_status == "executable"
        and item.source.evidence.get("equipment_ability_source_admitted") is True
    )
    threshold = _thresholds(bundle)[_ability_name(callback)]
    equipment = _equipment(
        bundle,
        _templates(
            bundle["catalog"],
            threshold.set_key,
            threshold.require_count,
        ),
        "s17:battle_event",
    )
    built = ScenarioStateBuilder(rules).build(
        _scenario(bundle["card"], equipment, "s17:battle_event")
    )
    actor_id = "ally:s17:battle_event"
    if built.blocked_setup or _detail(
        built.state,
        actor_id,
        callback.modifier_name,
    ) is None:
        raise ValueError("battle-event listener source missing")
    source_trace = callback.source.to_json()
    event_unit = UnitState(
        unit_id="battle_event:s17",
        side="ally",
        template_id="validation:battle_event",
        max_hp=1.0,
        hp=1.0,
        speed=1.0,
        action_value=0.0,
        flags={
            "entity_type": "battle_event",
            "battle_event_subtype": "ValidationEvent",
            "system_entity_kind": "battle_event",
        },
    )
    lifecycle = UnitLifecycleSystem()
    mutation = lifecycle.spawn_mutation(
        built.state,
        event_unit,
        reason="spawn typed battle event entity",
        source="unit_lifecycle_system",
        source_trace=source_trace,
        metadata={
            "validation_fixture": True,
            "producer_kind": "battle_event",
        },
    )
    commit = CombatExecutor(rules).commit_eventful_transition(
        built.state,
        mutations=(mutation,),
        events=(),
        records=(
            SettlementRecord(
                record_type="unit_spawn",
                source="unit_lifecycle_system",
                mutation_id=mutation.stable_id(),
                payload={
                    "unit_id": event_unit.unit_id,
                    "entity_type": "battle_event",
                },
                trace=source_trace,
            ).to_json(),
        ),
        producer_kind="unit_spawn",
        producer_id=event_unit.unit_id,
    )
    callback_records = [
        record
        for record in commit.records
        if isinstance(record, dict)
        and record.get("record_type") == "status_callback"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("callback_id") == callback.callback_id
    ]
    forged_unit = replace(
        event_unit,
        unit_id="ordinary:s17",
        flags={
            "entity_type": "avatar",
            "battle_event_subtype": "ValidationEvent",
        },
    )
    forged_mutation = lifecycle.spawn_mutation(
        built.state,
        forged_unit,
        reason="spawn ordinary unit",
        source="unit_lifecycle_system",
        source_trace=source_trace,
        metadata={"validation_fixture": True},
    )
    forged_events = events_for_mutation(
        forged_mutation,
        actor_id=actor_id,
        source_id=actor_id,
        event_index=built.state.event_index,
    )
    return {
        "formal_unit_lifecycle": (
            not commit.errors
            and runtime_unit_is_battle_event_entity(
                commit.after_state.units[event_unit.unit_id]
            )
            and sum(
                event.event_type == "battle_event.created"
                for event in commit.events
            )
            == 1
            and len(callback_records) == 1
        ),
        "subtype_only_rejected": (
            not runtime_unit_is_battle_event_entity(forged_unit)
            and all(
                event.event_type != "battle_event.created"
                for event in forged_events
            )
        ),
        "callback_id": callback.callback_id,
        "event_types": [event.event_type for event in commit.events],
        "callback_record_count": len(callback_records),
    }


def _departure_case(
    bundle: dict[str, Any],
    rules: RuleBook,
    projection: dict[str, Any],
) -> dict[str, Any]:
    start_callback = next(
        callback
        for callback in rules.ir.status_callbacks
        if callback.event == "OnListenDepartedStart"
        and callback.coverage_status == "executable"
        and callback.source.evidence.get("equipment_ability_source_admitted") is True
    )
    threshold = _thresholds(bundle)[_ability_name(start_callback)]
    equipment = _equipment(
        bundle,
        _templates(
            bundle["catalog"],
            threshold.set_key,
            threshold.require_count,
        ),
        "s17:depart:wearer",
    )
    base = _scenario(
        bundle["card"],
        equipment,
        "s17:depart:wearer",
    )
    wearer_spec = base.units[0]
    mate_id = "ally:s17:depart:mate"
    mate_spec = UnitSpec(
        unit_id=mate_id,
        side="ally",
        entity_ref=wearer_spec.entity_ref,
        build_mode="kernel_fixture",
        position=1,
        panel=PanelInput(
            max_hp=1000.0,
            hp=1000.0,
            attack=100.0,
            defense=100.0,
            speed=100.0,
        ),
    )
    built = ScenarioStateBuilder(rules).build(
        replace(
            base,
            units=(
                replace(wearer_spec, position=0),
                mate_spec,
            ),
        )
    )
    wearer_id = wearer_spec.unit_id
    if built.blocked_setup:
        raise ValueError(
            f"departure scenario blocked:{built.blocked_reasons}"
        )
    initial_state = built.state
    add = rules.effect(projection["add_id"])
    remove = rules.effect(projection["remove_id"])
    attach = rules.effect(projection["attach_id"])
    if add is None or remove is None or attach is None:
        raise ValueError("departure projection effects missing")
    wearer_before = _detail(
        initial_state,
        wearer_id,
        start_callback.modifier_name,
    )
    start = _commit_effect(
        rules,
        initial_state,
        add,
        caster_id=wearer_id,
        owner_id=wearer_id,
        param_entity_id=mate_id,
        source_id=add.effect_id,
    )
    source_detail = _detail(
        start.after_state,
        mate_id,
        projection["owner_modifier_name"],
    )
    wearer_started = _detail(
        start.after_state,
        wearer_id,
        start_callback.modifier_name,
    )
    if source_detail is None:
        raise ValueError("departure source status was not committed")
    duplicate_raw = CombatExecutor(rules).effects.execute(
        attach,
        EffectExecutionContext(
            state=start.after_state,
            caster_id=wearer_id,
            owner_id=mate_id,
            source_id=str(source_detail.get("source_id") or attach.effect_id),
            event_payload={
                "status_instance_id": source_detail["instance_id"],
                "status_instance_source": dict(
                    source_detail.get("source_trace") or {}
                ),
            },
        ),
    )
    conflict_state = _forge_departure_source(start.after_state, mate_id)
    conflict_raw = CombatExecutor(rules).effects.execute(
        attach,
        EffectExecutionContext(
            state=conflict_state,
            caster_id=wearer_id,
            owner_id=mate_id,
            source_id=str(source_detail.get("source_id") or attach.effect_id),
            event_payload={
                "status_instance_id": source_detail["instance_id"],
                "status_instance_source": dict(
                    source_detail.get("source_trace") or {}
                ),
            },
        ),
    )
    conflict = CombatExecutor(rules).commit_eventful_transition(
        conflict_state,
        mutations=conflict_raw.mutations,
        events=conflict_raw.events,
        records=conflict_raw.records,
        rng_events=conflict_raw.rng_events,
        producer_kind="effect",
        producer_id=attach.effect_id,
        producer_ok=not conflict_raw.unsupported,
        blocked_reason=",".join(conflict_raw.unsupported),
    )
    end = _commit_effect(
        rules,
        start.after_state,
        remove,
        caster_id=wearer_id,
        owner_id=wearer_id,
        param_entity_id=mate_id,
        source_id=remove.effect_id,
    )
    wearer_ended = _detail(
        end.after_state,
        wearer_id,
        start_callback.modifier_name,
    )
    before_count = _dynamic_value(wearer_before, "_TeamCount")
    started_count = _dynamic_value(wearer_started, "_TeamCount")
    ended_count = _dynamic_value(wearer_ended, "_TeamCount")
    return {
        "formal_presence_lifecycle": (
            not start.errors
            and not end.errors
            and bool(unit_departure_sources(start.after_state.units[mate_id]))
            and not runtime_unit_is_on_field(start.after_state.units[mate_id])
            and unit_departure_sources(end.after_state.units[mate_id]) == ()
            and runtime_unit_is_on_field(end.after_state.units[mate_id])
            and any(
                event.event_type == "unit.departed.started"
                for event in start.events
            )
            and any(
                event.event_type == "unit.departed.ended"
                for event in end.events
            )
        ),
        "wearer_recomputed": (
            before_count == ended_count
            and started_count is not None
            and before_count is not None
            and started_count < before_count
        ),
        "identity_isolated": (
            not duplicate_raw.unsupported
            and not duplicate_raw.mutations
            and not duplicate_raw.events
            and unit_departure_sources(
                start.after_state.units[wearer_id]
            )
            == ()
        ),
        "conflict_atomic": (
            "unit_departure_source_identity_conflict"
            in conflict_raw.unsupported
            and conflict.errors
            and conflict.after_state.snapshot().to_json()
            == conflict_state.snapshot().to_json()
            and not conflict.mutations
            and not conflict.events
            and not conflict.rng_events
        ),
        "wearer_id": wearer_id,
        "departed_unit_id": mate_id,
        "team_counts": [before_count, started_count, ended_count],
        "start_event_types": [event.event_type for event in start.events],
        "end_event_types": [event.event_type for event in end.events],
        "start_errors": list(start.errors),
        "end_errors": list(end.errors),
        "source": projection["public"],
        "_audit_inputs": (
            (
                initial_state,
                _transition(
                    initial_state,
                    start,
                    "p8_s17_departure_start",
                    wearer_id,
                ),
            ),
            (
                start.after_state,
                _transition(
                    start.after_state,
                    end,
                    "p8_s17_departure_end",
                    wearer_id,
                ),
            ),
        ),
    }


def _commit_effect(
    rules: RuleBook,
    state: BattleState,
    effect: Any,
    *,
    caster_id: str,
    owner_id: str,
    source_id: str,
    param_entity_id: str | None = None,
) -> Any:
    executor = CombatExecutor(rules)
    result = executor.effects.execute(
        effect,
        EffectExecutionContext(
            state=state,
            caster_id=caster_id,
            owner_id=owner_id,
            source_id=source_id,
            param_entity_id=param_entity_id,
        ),
    )
    return executor.commit_eventful_transition(
        state,
        mutations=result.mutations,
        events=result.events,
        records=result.records,
        rng_events=result.rng_events,
        producer_kind="effect",
        producer_id=effect.effect_id,
        producer_ok=not result.unsupported,
        blocked_reason=",".join(result.unsupported),
    )


def _forge_departure_source(
    state: BattleState,
    unit_id: str,
) -> BattleState:
    unit = state.units[unit_id]
    sources = unit_departure_sources(unit)
    if not sources:
        raise ValueError("departure source unavailable for conflict negative")
    forged = [dict(item) for item in sources]
    forged[0]["config_group_name"] = (
        f"{forged[0]['config_group_name']}:forged"
    )
    updated = replace(
        unit,
        flags={**unit.flags, "departed_sources": forged},
    )
    return replace(state, units={**state.units, unit_id: updated})


def _transition(
    before: BattleState,
    result: Any,
    action_id: str,
    actor_id: str,
) -> BattleTransition:
    return BattleTransition(
        transaction=ActionTransaction(
            command=ActionCommand(
                actor_id=actor_id,
                action_id=action_id,
                action_level=1,
                target_ids=(),
                source="validation_fixture",
            ),
            before=before.snapshot(),
            events=tuple(result.events),
            mutations=tuple(result.mutations),
            trigger_windows=tuple(result.trigger_windows),
            settlement=ActionSettlement(
                action_id=action_id,
                actor_id=actor_id,
                target_ids=(),
                records=tuple(result.records),
            ),
        ),
        after=result.after_state.snapshot(),
        rng_events=tuple(result.rng_events),
    )


def _audit_replay(
    rules: RuleBook,
    inputs: Iterable[tuple[BattleState, BattleTransition]],
) -> dict[str, Any]:
    rows = []
    for before, transition in inputs:
        audited = RuntimeSourceAuditor(rules).validate_transition(transition)
        replay = MutationReducer().replay_snapshot(
            before,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        rows.append(
            {
                "action_id": transition.transaction.command.action_id,
                "mutation_count": len(transition.transaction.mutations),
                "source_audit_ok": audited.ok,
                "audit_violations": [
                    violation.to_json()
                    for violation in audited.violations[:5]
                ],
                "replay_ok": replay.ok,
                "replay_errors": list(replay.errors),
            }
        )
    return {
        "source_audit": bool(rows)
        and all(row["source_audit_ok"] for row in rows),
        "replay": bool(rows) and all(row["replay_ok"] for row in rows),
        "rows": rows,
    }


def _non_gameplay_evidence(rules: RuleBook) -> dict[str, Any]:
    rows = [
        {
            "task_id": task.task_id,
            "opcode": task.opcode,
            "blocked_reason": task.blocked_reason,
        }
        for task in rules.ir.status_callback_tasks
        if task.blocked_reason == "equipment_task_family_non_gameplay"
    ]
    return {
        "ok": all(
            row["blocked_reason"] == "equipment_task_family_non_gameplay"
            for row in rows
        ),
        "count": len(rows),
        "sample": rows[:20],
    }


def _rng_contract_inherited(partition: dict[str, Any]) -> bool:
    return (
        partition["blocked_graph_count"] == 0
        and partition["s17_gap_count"] == 0
        and partition["unknown_count"] == 0
    )


def _single_task(rules: RuleBook, opcode: str) -> Any:
    tasks = tuple(
        task
        for task in rules.ir.status_callback_tasks
        if task.opcode == opcode
        and task.coverage_status == "executable"
        and task.source.evidence.get("equipment_ability_source_admitted") is True
    )
    if len(tasks) != 1:
        raise ValueError(f"expected one equipment task:{opcode}:{len(tasks)}")
    return tasks[0]


def _ability_name(value: Any) -> str:
    name = value.source.evidence.get("ability_name")
    if isinstance(name, str) and name:
        return name
    source = value.source.evidence.get("equipment_ability_source")
    if isinstance(source, dict):
        raw_id = source.get("raw_id")
        if isinstance(raw_id, str) and raw_id:
            return raw_id
    raise ValueError(f"equipment ability identity missing:{value}")


def _dynamic_value(
    detail: dict[str, Any] | None,
    key: str,
) -> float | None:
    if detail is None:
        return None
    values = detail.get("dynamic_values")
    if not isinstance(values, dict):
        return None
    value = values.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _merge_unique(
    values: Iterable[Any],
    identity_field: str,
) -> tuple[Any, ...]:
    merged: dict[str, Any] = {}
    for value in values:
        identity = getattr(value, identity_field)
        if identity in merged and merged[identity] != value:
            raise ValueError(
                f"focused identity conflict:{identity_field}:{identity}"
            )
        merged[identity] = value
    return tuple(merged[key] for key in sorted(merged))


def _merge_projection_values(
    existing: Iterable[Any],
    projected: Iterable[Any],
    identity_field: str,
    *,
    replace_conflicts: Iterable[str],
) -> tuple[Any, ...]:
    replaceable = frozenset(replace_conflicts)
    merged = {
        str(getattr(value, identity_field)): value
        for value in existing
    }
    for value in projected:
        identity = str(getattr(value, identity_field))
        current = merged.get(identity)
        if (
            current is not None
            and current != value
            and identity not in replaceable
        ):
            raise ValueError(
                f"focused identity conflict:{identity_field}:{identity}"
            )
        merged[identity] = value
    return tuple(merged[key] for key in sorted(merged))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root, args.output_dir)
    print(summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
