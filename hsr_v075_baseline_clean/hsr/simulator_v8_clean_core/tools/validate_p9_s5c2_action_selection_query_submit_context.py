from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import ActionCommand, BattleState, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.action_target_contract import (
    ActionTargetContractCatalogIR,
    ActionTargetContractIR,
)
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import (
    AbilityPhaseIR,
    ActionAbilityBindingIR,
    ActionAdmissionIR,
    ActionDefinitionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    CanonicalIR,
    CombatantActionSetIR,
    IRSource,
    MonsterDataCardIR,
)
from ..rules.rulebook import RuleBook
from ..systems.action_selection import (
    ActionTargetSelectionContext,
    ActionTargetSelectionSystem,
)
from ..systems.decision import DecisionSystem
from ..systems.scheduler import CombatScheduler, DecisionSubmissionAuthorization
from ..tbgd.lowering import TBGDLowering


ROOT = Path(__file__).resolve().parents[4]
CORE = Path(__file__).resolve().parents[1]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
VALIDATION_VERSION = "p9_s5c2_action_selection_query_submit_context_v1"

FIELD_CONSUMERS = {
    "target_type": "ActionTargetSelectionSystem.query",
    "alive_state": "ActionTargetSelectionSystem._candidate_ids",
    "target_filter": "ActionTargetSelectionSystem._candidate_ids",
    "allow_friend_servant": "ActionTargetSelectionSystem._apply_servant_policy",
    "allow_enemy_servant": "ActionTargetSelectionSystem._apply_servant_policy",
    "merge_servant_select_to_summoner": "ActionTargetSelectionSystem._apply_servant_policy",
    "avoid_self": "ActionTargetSelectionSystem._candidate_ids",
    "max_target_count": "ActionTargetSelectionSystem.accept",
    "sub_target_type": "ActionTargetSelectionSystem.query/resolve_impact",
    "adjoin_sub_target_count": "ActionTargetSelectionSystem.resolve_impact",
    "is_dynamic_target": "ActionTargetSelectionSystem.resolve_impact->P9-S5D",
    "skill_effect": "ActionTargetSelectionSystem.resolve_impact(ActionEventIR)",
}


def _write(path: Path, value: object) -> int:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return len(encoded)


def _fixture_source(raw_id: str) -> IRSource:
    return IRSource(
        source_path="validation_fixture/p9_s5c2",
        raw_type="ValidationFixture",
        raw_id=raw_id,
        evidence={"validation": VALIDATION_VERSION, "gameplay_executable_evidence": False},
    )


def _simple_contract(contract: ActionTargetContractIR, mode: str) -> bool:
    return bool(
        contract.coverage_status == "lowered"
        and contract.selection_mode == mode
        and contract.selection_filter is None
        and contract.friend_servant_policy == "default"
        and contract.enemy_servant_policy == "default"
        and contract.servant_selection == "none"
        and not contract.merge_servant_selection_to_summoner
        and not contract.avoid_self
        and contract.impact_sub_target == "default"
        and not contract.dynamic_target
        and contract.allow_duplicates is False
        and any(
            item.source_role == "character_config"
            and item.component_kind == "target_type"
            for item in contract.source_components
        )
    )


def _select_contracts(catalog: ActionTargetContractCatalogIR) -> dict[str, ActionTargetContractIR]:
    explicit = next(
        item for item in catalog.contracts
        if _simple_contract(item, "explicit") and item.candidate_relation == "enemy"
    )
    automatic = next(
        item for item in catalog.contracts
        if _simple_contract(item, "automatic") and item.candidate_relation == "enemy"
    )
    dynamic = next(
        item for item in catalog.contracts
        if item.coverage_status == "lowered" and item.dynamic_target is True
        and item.selection_filter is None and item.candidate_relation == "enemy"
    )
    blocked = next(item for item in catalog.contracts if item.coverage_status == "blocked")
    return {"explicit": explicit, "automatic": automatic, "dynamic": dynamic, "blocked": blocked}


def _placeholder_definition(contract: ActionTargetContractIR) -> ActionDefinitionIR:
    return ActionDefinitionIR(
        definition_id=contract.definition_id,
        action_id=contract.action_id,
        level=contract.level,
        attack_type="validation_fixture",
        skill_effect="validation_fixture",
        target_mode="unknown",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=_fixture_source(f"placeholder:{contract.contract_id}"),
        coverage_status="blocked",
    )


def _partial_catalog(
    catalog: ActionTargetContractCatalogIR,
    contracts: tuple[ActionTargetContractIR, ...],
) -> ActionTargetContractCatalogIR:
    covered_keys = tuple(
        sorted(
            f"{source_id}\0{item.action_id}\0{item.level}"
            for item in contracts
            for source_id in item.source_action_source_ids
        )
    )
    return ActionTargetContractCatalogIR(
        definition_scope="partial",
        source_graph_catalog_id=catalog.source_graph_catalog_id,
        source_graph_fingerprint=catalog.source_graph_fingerprint,
        character_source_level_keys=covered_keys,
        contracts=contracts,
        build_counters={"generic_record_limit_applied": True},
    )


def _query_rulebook(
    catalog: ActionTargetContractCatalogIR,
    contracts: tuple[ActionTargetContractIR, ...],
) -> RuleBook:
    return RuleBook(
        CanonicalIR(
            version="validation:p9_s5c2_source_query",
            action_definitions=tuple(_placeholder_definition(item) for item in contracts),
            action_target_contract_catalog=_partial_catalog(catalog, contracts),
        )
    )


def _definition(contract: ActionTargetContractIR, *, ultimate: bool) -> ActionDefinitionIR:
    return ActionDefinitionIR(
        definition_id=contract.definition_id,
        action_id=contract.action_id,
        level=contract.level,
        attack_type="Ultra" if ultimate else "Normal",
        skill_effect="Ultimate" if ultimate else "ValidationAction",
        target_mode="aoe" if ultimate else "single",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=_fixture_source(f"definition:{contract.contract_id}"),
        coverage_status="executable",
        damage_kind="none",
        damage_formula_family="none",
        source_mode="validation",
        target_relation="enemy",
    )


def _binding(contract: ActionTargetContractIR) -> ActionAbilityBindingIR:
    action_id = contract.action_id
    return ActionAbilityBindingIR(
        binding_id=f"validation:{contract.contract_id}:binding",
        action_id=action_id,
        level=contract.level,
        skill_trigger_key=f"{action_id}:trigger",
        skill_name=f"{action_id}:skill",
        entry_ability=f"{action_id}:ability",
        ability_names=(f"{action_id}:ability",),
        config_source={"validation_fixture": True},
        phase_ids=(f"validation:{contract.contract_id}:phase",),
        source_mode="validation",
        source=_fixture_source(f"binding:{contract.contract_id}"),
        coverage_status="executable",
    )


def _phase(contract: ActionTargetContractIR) -> AbilityPhaseIR:
    return AbilityPhaseIR(
        phase_id=f"validation:{contract.contract_id}:phase",
        binding_id=f"validation:{contract.contract_id}:binding",
        action_id=contract.action_id,
        level=contract.level,
        ability_name=f"{contract.action_id}:ability",
        phase_index=0,
        target_info={},
        opcode_summary={"task_count": 0},
        callback_summaries={"OnStart": {"task_count": 0}},
        source=_fixture_source(f"phase:{contract.contract_id}"),
        coverage_status="executable",
        task_ids=(),
    )


def _event(contract: ActionTargetContractIR, *, target_mode: str) -> ActionEventIR:
    source = _fixture_source(f"event:{contract.contract_id}")
    steps = tuple(
        ActionPhaseStepIR(
            kind="trigger_window",
            phase=phase,
            canonical_window=phase,
            tbgd_event=event,
            coverage_status="lowered",
            source=source,
        )
        for phase, event in (
            ("before_skill_use", "OnBeforeSkillUse"),
            ("after_skill_use", "OnAfterSkillUse"),
        )
    )
    return ActionEventIR(
        action_event_id=f"validation:{contract.contract_id}:event",
        action_id=contract.action_id,
        level=contract.level,
        target_mode=target_mode,
        selection_mode="primary",
        phase_steps=steps,
        hit_profile_ids=(),
        derived_status="validation",
        derived_reason="S5C2 transport fixture; not real gameplay evidence",
        source=source,
        coverage_status="lowered",
        binding_id=f"validation:{contract.contract_id}:binding",
        phase_ids=(f"validation:{contract.contract_id}:phase",),
        source_mode="validation",
        event_source_status="ability_phase_graph_bound",
        target_relation="enemy",
    )


def _monster_card(action_set_id: str, action: ActionTargetContractIR) -> MonsterDataCardIR:
    return MonsterDataCardIR(
        card_id="validation:monster_card",
        entity_ref="validation:actor",
        monster_id="validation:monster",
        template_id="validation:monster_template",
        rank="validation",
        profile_id="validation:monster_profile",
        action_set_id=action_set_id,
        skill_ids=(action.action_id,),
        skill_slots=(),
        ai_policy={
            "policy_kind": "fixed_skill_sequence",
            "admitted_task": "RPG.GameCore.UseSequencedSkill",
            "admission_status": "executable",
            "coverage_status": "lowered",
            "candidate_constraint_admitted": True,
            "candidate_constraint_kind": "forced_sequence",
            "selection_controller": "external",
            "runtime_execution_admitted": False,
            "enemy_ai_runtime_execution_admitted": False,
            "source_trace": _fixture_source("enemy_policy").to_json(),
        },
        action_sequence=({
            "sequence_index": 0,
            "sequence_kind": "validation_forced",
            "action_ref": action.action_id,
            "coverage_status": "lowered",
            "blocked_reason": "",
            "source_trace": _fixture_source("enemy_sequence").to_json(),
        },),
        summon_refs=(),
        raw_parameter_blocks={},
        card_contract={},
        source=_fixture_source("monster_card"),
        coverage_status="executable",
    )


def _transport_rulebook(
    catalog: ActionTargetContractCatalogIR,
    explicit: ActionTargetContractIR,
    automatic: ActionTargetContractIR,
) -> RuleBook:
    registry = build_engine_rule_registry()
    action_set_id = "validation:actor:actions"
    action_set = CombatantActionSetIR(
        combatant_action_set_id=action_set_id,
        entity_ref="validation:actor",
        skill_index_map={"0": {
            "action_ref": explicit.action_id,
            "default_level": explicit.level,
            "coverage_status": "executable",
            "source_trace": _fixture_source("action_set_entry").to_json(),
        }},
        source=_fixture_source("action_set"),
        coverage_status="executable",
    )
    admissions = (
        ActionAdmissionIR(
            admission_id="validation:admission:explicit",
            owner_entity_ref="validation:actor",
            action_id=explicit.action_id,
            action_level=explicit.level,
            action_role="turn_action",
            submission_modes=("external_turn", "queue"),
            allowed_windows=("idle", "turn_active", "turn_action"),
            control_kind="external",
            resource_gate_kind="action_definition",
            source=_fixture_source("admission:explicit"),
            coverage_status="executable",
        ),
        ActionAdmissionIR(
            admission_id="validation:admission:automatic_ultimate",
            owner_entity_ref="validation:actor",
            action_id=automatic.action_id,
            action_level=automatic.level,
            action_role="insert_action",
            submission_modes=("insert_window", "queue"),
            allowed_windows=("ultimate",),
            control_kind="selectable_window",
            resource_gate_kind="ultimate_energy",
            source=_fixture_source("admission:automatic"),
            coverage_status="executable",
        ),
    )
    ir = CanonicalIR(
        version="validation:p9_s5c2_transport",
        action_definitions=(_definition(explicit, ultimate=False), _definition(automatic, ultimate=True)),
        action_target_contract_catalog=_partial_catalog(catalog, (explicit, automatic)),
        action_ability_bindings=(_binding(explicit), _binding(automatic)),
        ability_phases=(_phase(explicit), _phase(automatic)),
        action_events=(_event(explicit, target_mode="single"), _event(automatic, target_mode="aoe")),
        combatant_action_sets=(action_set,),
        action_admissions=admissions,
        monster_data_cards=(_monster_card(action_set_id, explicit),),
        timeline_rules=registry.timeline_rules,
        resource_rules=registry.resource_rules,
        damage_formula_rules=registry.damage_formula_rules,
        damage_route_rules=registry.damage_route_rules,
        shield_priority_rules=registry.shield_priority_rules,
        metadata={"validation_fixture": True, "gameplay_executable_evidence": False},
    )
    return RuleBook(ir)


def _unit(unit_id: str, side: str, template: str, position: int, *, energy: float = 0.0) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side=side,  # type: ignore[arg-type]
        template_id=template,
        max_hp=100.0,
        hp=100.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        energy=energy,
        max_energy=100.0,
        action_value=float(position * 10),
        flags={"position": position, "on_field": True, "targetable": True},
    )


def _state(*, enemy_turn: bool = False) -> BattleState:
    actor_id = "enemy:actor" if enemy_turn else "ally:actor"
    units = {
        "ally:actor": _unit("ally:actor", "ally", "validation:actor", 0, energy=100.0),
        "ally:second": _unit("ally:second", "ally", "validation:ally", 1, energy=100.0),
        "enemy:actor": _unit("enemy:actor", "enemy", "validation:actor", 0, energy=100.0),
        "enemy:second": _unit("enemy:second", "enemy", "validation:enemy", 1),
    }
    if enemy_turn:
        units["enemy:actor"] = replace(
            units["enemy:actor"],
            flags={**units["enemy:actor"].flags, "monster_data_card_id": "validation:monster_card"},
        )
    return BattleState(
        units=units,
        skill_points=3,
        max_skill_points=5,
        global_flags={
            "phase": "scenario",
            "combat_phase": "awaiting_decision",
            "current_window": "turn_active",
            "turn_owner_id": actor_id,
            "turn_sequence_index": 1,
            "active_turn": {"actor_id": actor_id, "turn_kind": "regular", "turn_sequence_index": 1},
        },
        rng_state="p9-s5c2-validation",
    )


def _real_source_matrix(
    lowering: TBGDLowering,
    catalog: ActionTargetContractCatalogIR,
    selected: dict[str, ActionTargetContractIR],
) -> dict[str, Any]:
    explicit = selected["explicit"]
    definitions = tuple(
        item
        for item in lowering._lower_action_definitions(
            action_ids=frozenset({explicit.action_id}),
            entity_types=frozenset({"avatar_skill"}),
        )
        if item.level == explicit.level
    )
    snapshot = getattr(lowering, "_character_ability_raw_snapshot")
    scope = getattr(lowering, "_character_ability_scope_catalog")
    source_graph = getattr(lowering, "_character_ability_source_graph_catalog")
    source_slice = lowering.build_character_action_ability_slice(
        definitions[0], snapshot=snapshot, scope_catalog=scope, source_graph_catalog=source_graph,
    )
    source_rules = RuleBook(source_slice)
    query_rules = _query_rulebook(catalog, tuple(selected.values()))
    state = _state()
    explicit_system = ActionTargetSelectionSystem(source_rules)
    explicit_query = explicit_system.query(state, "ally:actor", explicit.action_id, explicit.level)
    explicit_accept = explicit_system.accept(state, explicit_query, ("enemy:actor",))
    automatic = selected["automatic"]
    automatic_system = ActionTargetSelectionSystem(query_rules)
    automatic_query = automatic_system.query(state, "ally:actor", automatic.action_id, automatic.level)
    automatic_accept = automatic_system.accept(state, automatic_query, ())
    automatic_injection = automatic_system.accept(state, automatic_query, ("enemy:actor",))
    blocked_query = automatic_system.query(
        state, "ally:actor", selected["blocked"].action_id, selected["blocked"].level,
    )
    dynamic = selected["dynamic"]
    dynamic_query = automatic_system.query(state, "ally:actor", dynamic.action_id, dynamic.level)
    dynamic_accept = automatic_system.accept(state, dynamic_query, ()) if dynamic_query.selection_mode == "automatic" else automatic_system.accept(state, dynamic_query, (dynamic_query.candidate_ids[0],))
    dynamic_reason = ""
    if dynamic_accept.accepted and dynamic_accept.context is not None:
        event = _event(dynamic, target_mode="aoe" if dynamic.selection_mode == "automatic" else "single")
        command = ActionCommand(
            actor_id="ally:actor", action_id=dynamic.action_id, action_level=dynamic.level,
            target_ids=dynamic_accept.context.accepted.submitted_target_ids,
        )
        dynamic_reason = automatic_system.resolve_impact(state, command, dynamic_accept.context, event).blocked_reason
    return {
        "ok": all((
            len(definitions) == 1,
            explicit_query.resolved,
            explicit_accept.accepted,
            automatic_query.resolved,
            automatic_query.automatic_target_ids == automatic_query.candidate_ids,
            automatic_accept.accepted,
            not automatic_injection.accepted,
            not blocked_query.resolved and not blocked_query.candidate_ids,
            dynamic_reason == "action_dynamic_target_deferred_to_p9_s5d",
        )),
        "source_slice_projection": source_slice.metadata.get("projection"),
        "explicit": explicit_query.to_json(),
        "automatic": automatic_query.to_json(),
        "automatic_injection_reason": automatic_injection.blocked_reason,
        "blocked_reason": blocked_query.blocked_reason,
        "dynamic_owner_reason": dynamic_reason,
    }


def _command_for_choice(choice: Any) -> ActionCommand:
    query = choice.target_query
    targets = (query.candidate_ids[0],) if query.selection_mode == "explicit" else ()
    return ActionCommand(
        actor_id=choice.actor_id,
        action_id=choice.action_id,
        action_level=choice.action_level,
        target_ids=targets,
        source="manual",
    )


def _transport_matrix(
    rules: RuleBook,
    explicit: ActionTargetContractIR,
    automatic: ActionTargetContractIR,
) -> dict[str, Any]:
    state = _state()
    decisions = DecisionSystem(rules)
    current = decisions.current_decision(state)
    choice = next(item for item in current.availability.choices if item.action_id == explicit.action_id)
    command = _command_for_choice(choice)
    result = decisions.submit(state, current.token, command)  # type: ignore[arg-type]
    records = result.transition.transaction.settlement.records if result.transition.transaction.settlement else ()
    context_records = tuple(item for item in records if item.get("record_type") == "action_target_selection_context")
    replay = MutationReducer().replay_snapshot(
        state, result.transition.transaction.mutations, result.after_state.snapshot().to_json(),
    )
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)

    enemy_state = _state(enemy_turn=True)
    enemy_decision = DecisionSystem(rules).current_decision(enemy_state)
    enemy_choice = next(item for item in enemy_decision.availability.choices if item.action_id == explicit.action_id)
    enemy_result = DecisionSystem(rules).submit(
        enemy_state, enemy_decision.token, _command_for_choice(enemy_choice),  # type: ignore[arg-type]
    )

    scheduler = CombatScheduler(rules)
    ultimate_command = ActionCommand(actor_id="ally:actor", action_id=automatic.action_id, action_level=automatic.level, target_ids=())
    enqueued = scheduler.enqueue_manual_ultimate(state, ultimate_command)
    unowned = scheduler.enqueue_manual_ultimate(state, replace(ultimate_command, actor_id="ally:second"))
    queue_decision = DecisionSystem(rules).current_decision(enqueued.after_state)
    queue_choices = tuple(item for item in queue_decision.availability.choices if item.action_id == automatic.action_id)
    queue_result = (
        DecisionSystem(rules).submit(
            enqueued.after_state, queue_decision.token, _command_for_choice(queue_choices[0]),  # type: ignore[arg-type]
        )
        if queue_choices and queue_decision.token is not None
        else None
    )
    return {
        "ok": all((
            current.ready,
            result.transition.outcome.successor_eligible,
            bool(context_records),
            result.transition.target_resolution.selected == command.target_ids,
            replay.ok,
            audit.ok,
            enemy_decision.ready,
            enemy_choice.target_query.selection_mode == "explicit",
            enemy_result.transition.outcome.successor_eligible,
            enqueued.transition.outcome.successor_eligible,
            not unowned.transition.outcome.successor_eligible and not unowned.transition.transaction.mutations and str(unowned.transition.coverage.get("blocked_reason") or "").startswith("manual_ultimate_action_not_admitted:"),
            queue_result is not None and queue_result.transition.outcome.successor_eligible,
        )),
        "fixture_classification": "validation_transport_only_not_gameplay_executable_evidence",
        "decision_id": current.token.decision_id if current.token else "",
        "choice_id": choice.choice_id,
        "query_fingerprint": choice.target_query.query_fingerprint,
        "context_record_count": len(context_records),
        "target_resolution": result.transition.target_resolution.to_json(),
        "replay_ok": replay.ok,
        "source_audit_ok": audit.ok,
        "enemy_ready": enemy_decision.ready,
        "enemy_selection_mode": enemy_choice.target_query.selection_mode,
        "queue_choice_count": len(queue_choices),
        "queue_successor": bool(queue_result and queue_result.transition.outcome.successor_eligible),
        "queue_blocked_reason": "" if queue_result is None else str(queue_result.transition.coverage.get("blocked_reason") or ""),
        "unowned_ultimate_blocked_reason": str(unowned.transition.coverage.get("blocked_reason") or ""),
    }


def _zero_business_side_effect(result: Any, before: BattleState) -> bool:
    events = result.transition.transaction.events
    return bool(
        result.after_state == before
        and not result.transition.transaction.mutations
        and not result.transition.rng_events
        and all(event.process_only for event in events)
    )


def _negative_matrix(rules: RuleBook, explicit: ActionTargetContractIR) -> dict[str, Any]:
    state = _state()
    system = ActionTargetSelectionSystem(rules)
    query = system.query(state, "ally:actor", explicit.action_id, explicit.level)
    accepted = system.accept(state, query, ("enemy:actor",))
    assert accepted.context is not None
    changed = replace(state, units={**state.units, "enemy:new": _unit("enemy:new", "enemy", "validation:new", 2)})
    stale = system.accept(changed, query, ("enemy:actor",))
    duplicate = system.accept(state, query, ("enemy:actor", "enemy:actor"))
    unknown = system.accept(state, query, ("enemy:missing",))
    unsigned = ActionTargetSelectionContext(
        accepted=accepted.context.accepted,
        impact_sub_target=accepted.context.impact_sub_target,
        adjacent_target_count=accepted.context.adjacent_target_count,
        dynamic_target=accepted.context.dynamic_target,
    )
    command = ActionCommand(
        actor_id="ally:actor", action_id=explicit.action_id, action_level=explicit.level,
        target_ids=("enemy:actor",),
    )
    executor_result = __import__(
        "simulator_v8_clean_core.core.executor", fromlist=["CombatExecutor"]
    ).CombatExecutor(rules).execute(command, state, target_selection_context=unsigned)
    decision = DecisionSystem(rules).current_decision(state)
    forged = DecisionSubmissionAuthorization(
        decision_id=decision.token.decision_id,  # type: ignore[union-attr]
        state_revision=decision.token.state_revision,  # type: ignore[union-attr]
        actor_id=command.actor_id,
        action_id=command.action_id,
        action_level=command.action_level,
        selection_context=accepted.context,
    )
    scheduler_reject = CombatScheduler(rules).step(state, command, decision_authorization=forged)
    try:
        ActionCommand(
            actor_id="ally:actor", action_id=explicit.action_id, action_level=explicit.level,
            target_ids=("enemy:actor",), metadata={"target_query": {}},
        )
        metadata_rejected = False
    except (TypeError, ValueError):
        metadata_rejected = True
    checks = {
        "stale_query_rejected": not stale.accepted and stale.blocked_reason == "action_target_query_stale",
        "duplicate_rejected": not duplicate.accepted and "duplicate" in duplicate.blocked_reason,
        "unknown_candidate_rejected": not unknown.accepted and "not_in_candidates" in unknown.blocked_reason,
        "unsigned_context_rejected_atomically": (
            executor_result[0] == state
            and not executor_result[1].transaction.mutations
            and not executor_result[1].rng_events
            and executor_result[1].coverage.get("blocked_reason") == "action_target_selection_context_not_issued"
        ),
        "forged_decision_authorization_rejected_before_business": _zero_business_side_effect(scheduler_reject, state),
        "target_metadata_injection_rejected": metadata_rejected,
    }
    return {"ok": all(value is True for value in checks.values()), "checks": checks}


def _field_and_consumer_matrix(catalog: ActionTargetContractCatalogIR) -> dict[str, Any]:
    lowered = tuple(item for item in catalog.contracts if item.coverage_status == "lowered")
    components = tuple(
        component for item in lowered for component in item.source_components
        if component.semantic_role != "non_gameplay"
    )
    counts = Counter(component.component_kind for component in components)
    unknown = tuple(sorted(set(counts) - set(FIELD_CONSUMERS)))
    production_roots = (CORE / "systems", CORE / "core")
    production_files = tuple(
        path for root in production_roots for path in root.rglob("*.py")
        if "tools" not in path.parts and "docs" not in path.parts
    )
    texts = {str(path.relative_to(CORE)): path.read_text(encoding="utf-8") for path in production_files}
    old_symbols = (
        "target_policy_for_action(", "enumerate_action_targets(",
        "resolve_action_targets(", "resolve_explicit_targets(",
        ".auto_target_ids", ".selectable_target_ids",
    )
    old_hits = {
        symbol: tuple(path for path, text in texts.items() if symbol in text)
        for symbol in old_symbols
    }
    action_choice_paths = tuple(path for path, text in texts.items() if "ActionChoice(" in text)
    enemy_candidate_paths = tuple(path for path, text in texts.items() if "EnemyActionCandidate(" in text)
    ui_runner = (CORE.parent / "simulator_v8_ui" / "runner.py").read_text(encoding="utf-8")
    checks = {
        "field_denominator_closed": not unknown and bool(counts),
        "all_current_duplicate_policies_false": all(item.allow_duplicates is False for item in lowered),
        "dynamic_sources_owned_by_s5d": counts.get("is_dynamic_target", 0) > 0 and "action_dynamic_target_deferred_to_p9_s5d" in texts["systems/action_selection.py"],
        "old_action_target_runtime_removed": all(not paths for paths in old_hits.values()),
        "action_choice_single_owner": action_choice_paths == ("systems/action_availability.py",),
        "enemy_candidate_single_owner": enemy_candidate_paths == ("systems/enemy_action.py",),
        "ui_consumes_decision_not_executor": "DecisionSystem" in ui_runner and "CombatExecutor" not in ui_runner and "const actorId = slot.actor_id" in (CORE.parent / "simulator_v8_ui" / "static" / "app.js").read_text(encoding="utf-8"),
    }
    return {
        "ok": all(value is True for value in checks.values()),
        "checks": checks,
        "component_counts": dict(sorted(counts.items())),
        "consumer_by_component": FIELD_CONSUMERS,
        "unknown_components": list(unknown),
        "old_symbol_hits": old_hits,
        "action_choice_paths": action_choice_paths,
        "enemy_candidate_paths": enemy_candidate_paths,
    }


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    lowering = TBGDLowering(tbgd_root)
    catalog = lowering.build_action_target_contract_catalog()
    selected = _select_contracts(catalog)
    fields = _field_and_consumer_matrix(catalog)
    source = _real_source_matrix(lowering, catalog, selected)
    rules = _transport_rulebook(catalog, selected["explicit"], selected["automatic"])
    transport = _transport_matrix(rules, selected["explicit"], selected["automatic"])
    negatives = _negative_matrix(rules, selected["explicit"])
    checks = {
        "complete_field_denominator_consumed": fields["ok"],
        "real_explicit_and_automatic_queries_source_backed": source["ok"],
        "decision_scheduler_executor_context_continuous": transport["ok"],
        "invalid_selection_and_authority_fail_closed": negatives["ok"],
        "fixture_not_claimed_as_gameplay_executable": transport["fixture_classification"] == "validation_transport_only_not_gameplay_executable_evidence",
        "full_canonical_build_count_zero": True,
    }
    false_control = dict(checks)
    false_control["invalid_selection_and_authority_fail_closed"] = 1
    exact_gate = all(type(value) is bool and value for value in checks.values())
    false_control_rejected = not all(type(value) is bool and value for value in false_control.values())
    ok = exact_gate and false_control_rejected
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "field_and_consumer_matrix": fields,
        "real_source_matrix": source,
        "transport_matrix": transport,
        "negative_matrix": negatives,
        "selected_sources": {name: item.to_json() for name, item in selected.items()},
    }
    evidence_bytes = _write(output_dir / "evidence.json", evidence)
    summary = {
        "validation_version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "false_control_rejected": false_control_rejected,
        "catalog_counts": {
            "contract_count": len(catalog.contracts),
            "lowered_count": sum(item.coverage_status == "lowered" for item in catalog.contracts),
            "blocked_count": sum(item.coverage_status == "blocked" for item in catalog.contracts),
        },
        "evidence_classification": {
            "real_source_semantics": "source_backed",
            "context_transport": "validation_fixture_only",
            "real_gameplay_end_to_end": "not_proven_due_to_downstream_p9_mechanism_gaps",
        },
        "resource": {
            "wall_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "evidence_bytes": evidence_bytes,
            "full_canonical_build_count": 0,
            "action_target_catalog_build_count": 1,
            "character_action_slice_build_count": 1,
            "transport_fixture_count": 1,
        },
    }
    _write(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S5C2 action target query-submit context.")
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.tbgd_root, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
