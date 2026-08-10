from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, UnitState
from ..rules.engine_rule_registry import build_engine_rule_registry
from ..rules.ir import CanonicalIR, IRSource
from ..rules.rulebook import RuleBook
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.target import TargetSystem, resolve_action_bounce_policy
from ..systems.target_random import replay_target_random
from ..tbgd.action_target_contracts import build_action_target_contract_catalog
from ..tbgd.character_cards import CHARACTER_ACTION_DEFINITION_TABLES, build_character_card_ir
from ..tbgd.lowering import TBGDLowering, _hit_profiles_from_definition
from ..tbgd.paths import find_tbgd_root
from ..tbgd.target_source import build_target_source_projection
from .io import write_json


STAGE = "P9-S5D2"
_RESOLVED_S5 = {
    "p9_s5b_entity_relation_deterministic_target",
    "p9_s5c_action_target_selection",
    "p9_s5d_rng",
}
_EXTERNAL = {
    "p9_s6_s7_condition_evaluator",
    "p9_s9_s17_typed_event_or_entity_producer",
    "p9_s17_body_part_producer",
    "p9_s17_source_language_decode",
}
_ACTION_EXTERNAL_PREFIXES = (
    "effect_coverage_status:unsupported:",
    "condition_not_executable:unsupported:",
)


def _source_key(source: IRSource | Mapping[str, Any]) -> tuple[str, str, str]:
    if isinstance(source, Mapping):
        evidence = source.get("evidence")
        path = str(evidence.get("json_path") or "") if isinstance(evidence, Mapping) else ""
        return str(source.get("source_path") or ""), path.removesuffix(".$type"), str(source.get("raw_id") or "")
    path = str(source.evidence.get("json_path") or "")
    return source.source_path, path.removesuffix(".$type"), source.raw_id


def _digest(rows: list[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(rows), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_action_map(graph: Any) -> dict[tuple[str, int], tuple[str, ...]]:
    action_by_source = {item.action_source_id: item.action_id for item in graph.action_sources}
    by_definition: dict[str, set[str]] = defaultdict(set)
    for binding in graph.bindings:
        action_id = action_by_source.get(binding.action_source_id)
        if action_id:
            by_definition[binding.ability_definition_id].add(action_id)
    result: dict[tuple[str, int], set[str]] = defaultdict(set)
    for definition in graph.definitions:
        index = definition.source.evidence.get("ability_index")
        if type(index) is int:
            result[(definition.source.source_path, index)].update(by_definition.get(definition.definition_id, ()))
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _actions_for_source(source: IRSource, mapping: dict[tuple[str, int], tuple[str, ...]]) -> tuple[str, ...]:
    match = re.match(r"^\$\.AbilityList\[(\d+)\]", str(source.evidence.get("json_path") or ""))
    return mapping.get((source.source_path, int(match.group(1))), ()) if match else ()


def _inventory(tbgd_root: Path) -> dict[str, Any]:
    full_build_calls = 0
    original_build = TBGDLowering.build

    def forbidden(_self: TBGDLowering) -> object:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError("S5D2 invoked full Canonical IR lowering")

    TBGDLowering.build = forbidden
    try:
        lowering = TBGDLowering(tbgd_root)
        graph = lowering.build_character_ability_source_graph_catalog()
        snapshot = lowering._character_ability_raw_snapshot
        scope = lowering._character_ability_scope_catalog
        definitions = tuple(lowering._lower_action_definitions())
    finally:
        TBGDLowering.build = original_build
    return {
        "lowering": lowering,
        "graph": graph,
        "snapshot": snapshot,
        "scope": scope,
        "definitions": definitions,
        "full_build_calls": full_build_calls,
    }


def _policy_matrix(inventory: dict[str, Any]) -> dict[str, Any]:
    definitions = {(item.action_id, item.level): item for item in inventory["definitions"]}
    formulas: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for binding in inventory["cards"].skill_formula_bindings:
        formulas[(binding.action_id, binding.level)].append(binding)
    policies = tuple(
        policy for policy in inventory["cards"].bounce_policies
        if policy.coverage_status == "executable"
    )
    rules = RuleBook(CanonicalIR(version="validation:p9_s5d2_policy", bounce_policies=policies))
    rows: list[dict[str, Any]] = []
    profiles_by_policy: dict[str, tuple[Any, ...]] = {}
    for policy in policies:
        definition = definitions.get((policy.action_id, policy.level))
        profiles = tuple(_hit_profiles_from_definition(
            definition,
            tuple(formulas.get((policy.action_id, policy.level), ())),
            policy,
        )) if definition is not None else ()
        profiles_by_policy[policy.bounce_policy_id] = profiles
        resolution = resolve_action_bounce_policy(rules, policy.action_id, policy.level, hit_profiles=profiles)
        rows.append({
            "policy_id": policy.bounce_policy_id,
            "action_id": policy.action_id,
            "level": policy.level,
            "resolved": resolution.resolved,
            "blocked_reason": resolution.blocked_reason,
            "target_mode": definition.target_mode if definition else "",
            "bounce_count": policy.bounce_count,
            "profile_groups": [profile.target_group for profile in profiles],
            "selector_sources": [source.to_json() for source in policy.random_selector_sources],
        })
    linked = tuple(policy for policy in policies if policy.random_selector_sources)
    selected = next((
        policy for policy in sorted(linked, key=lambda item: (item.action_id, item.level))
        if policy.bounce_count > 2
        and next(row for row in rows if row["policy_id"] == policy.bounce_policy_id)["resolved"]
    ), None)
    return {
        "rules": rules,
        "rows": rows,
        "profiles": profiles_by_policy,
        "selected": selected,
        "checks": {
            "executable_bounce_policies_exist": bool(policies),
            "all_executable_policies_close_hit_profiles": bool(rows) and all(row["resolved"] for row in rows),
            "real_random_selector_links_exist": bool(linked),
            "linked_selector_count_matches_bounce_count": all(
                len(policy.random_selector_sources) == policy.bounce_count for policy in linked
            ),
            "source_structured_repeat_case_exists": selected is not None,
        },
    }


def _unit(unit_id: str, side: str, template: str, position: int) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side=side,  # type: ignore[arg-type]
        template_id=template,
        max_hp=100000.0,
        hp=100000.0,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        energy=100.0,
        max_energy=100.0,
        toughness=1000.0,
        max_toughness=1000.0,
        flags={"position": position, "on_field": True, "targetable": True},
    )


def _state(actor_template: str) -> BattleState:
    return BattleState(
        units={
            "ally:actor": _unit("ally:actor", "ally", actor_template, 0),
            "enemy:a": _unit("enemy:a", "enemy", "validation:enemy:a", 0),
            "enemy:b": _unit("enemy:b", "enemy", "validation:enemy:b", 1),
        },
        skill_points=5,
        max_skill_points=5,
        rng_state="p9-s5d2-bounce",
        global_flags={
            "phase": "scenario",
            "combat_phase": "awaiting_decision",
            "current_window": "turn_active",
            "turn_owner_id": "ally:actor",
            "turn_sequence_index": 1,
            "active_turn": {"actor_id": "ally:actor", "turn_kind": "regular", "turn_sequence_index": 1},
        },
    )


def _resolve_hit(
    system: TargetSystem,
    state: BattleState,
    policy: Any,
    index: int,
    previous: tuple[str, ...],
    payload: dict[str, Any] | None = None,
    *,
    primary_target_id: str = "enemy:a",
) -> Any:
    return system.resolve_bounce_hit_target(
        state,
        actor_id="ally:actor",
        primary_target_id=primary_target_id,
        bounce_policy=policy,
        hit_index=index,
        previous_hit_targets=previous,
        action_id=policy.action_id,
        action_level=policy.level,
        source_task_id=f"source-task:{index}",
        hit_profile_id=f"hit-profile:{index}",
        event_payload=payload,
    )


def _direct_matrix(policy: Any, card: Any) -> dict[str, Any]:
    state, system = _state(card.entity_ref), TargetSystem()
    previous: list[str] = []
    results = []
    for index in range(1, policy.bounce_count + 1):
        result = _resolve_hit(system, state, policy, index, tuple(previous))
        results.append(result)
        if result.ok and not result.sequence_exhausted:
            previous.append(result.target_id)
    replay_ok = all(
        result.random_plan is not None
        and replay_target_random(result.random_plan, (result.rng_event,) if result.rng_event else ()).ok
        for result in results
    )
    first = results[0]
    tamper_rejected = stale_rejected = False
    if first.random_plan is not None and first.rng_event is not None:
        tampered = replace(first.rng_event, metadata={**first.rng_event.metadata, "hit_index": 999})
        tamper_rejected = not replay_target_random(first.random_plan, (tampered,)).ok
        selected = str(first.rng_event.result.get("selected_outcome_id") or "")
        stale_state = replace(state, units={
            key: replace(unit, flags={**unit.flags, "unselectable": True}) if key == selected else unit
            for key, unit in state.units.items()
        })
        stale = _resolve_hit(system, stale_state, policy, 1, ())
        stale_rejected = (
            stale.ok
            and stale.random_plan is not None
            and not replay_target_random(stale.random_plan, (first.rng_event,)).ok
        )
    no_repeat_policy = replace(
        policy,
        selection_strategy="prefer_unhit_then_random",
        allow_repeat_after_all_hit=False,
        random_selector_sources=(),
    )
    no_repeat = _resolve_hit(system, state, no_repeat_policy, 1, ("enemy:a", "enemy:b"))
    defeated = replace(state, units={
        key: replace(unit, lifecycle_status="defeated", hp=0.0) if key.startswith("enemy:") else unit
        for key, unit in state.units.items()
    })
    exhausted = _resolve_hit(system, defeated, policy, 1, ())
    malformed_rejected = reordered_rejected = False
    try:
        replace(policy, random_selector_sources=policy.random_selector_sources[:-1])
    except (TypeError, ValueError):
        malformed_rejected = True
    try:
        replace(policy, random_selector_sources=tuple(reversed(policy.random_selector_sources)))
    except (TypeError, ValueError):
        reordered_rejected = True
    owner_rules = RuleBook(CanonicalIR(
        version="validation:p9_s5d2_owner",
        bounce_policies=(policy,),
        character_data_cards=(card,),
    ))
    wrong_owner = resolve_action_bounce_policy(
        owner_rules,
        policy.action_id,
        policy.level,
        actor_entity_ref="avatar:wrong-owner",
    )
    missing_primary = _resolve_hit(
        system, state, policy, 1, (), primary_target_id="enemy:missing"
    )
    friendly_primary = _resolve_hit(
        system, state, policy, 1, (), primary_target_id="ally:actor"
    )
    checks = {
        "all_hits_use_shared_sampler": len(results) == policy.bounce_count and all(result.ok and result.random_plan for result in results),
        "real_selector_sources_consumed_in_order": tuple(
            _source_key(result.random_plan.source_trace) for result in results if result.random_plan
        ) == tuple(_source_key(source) for source in policy.random_selector_sources),
        "independent_hits_can_repeat": len(previous) > len(set(previous)),
        "each_draw_replays_exactly": replay_ok,
        "hit_event_tampering_rejected": tamper_rejected,
        "stale_candidate_choice_rejected": stale_rejected,
        "policy_repeat_switch_enforced": not no_repeat.ok and no_repeat.error == "bounce_repeat_after_all_hit_not_admitted",
        "all_defeated_completes_without_retargeting_defeated": exhausted.ok and exhausted.sequence_exhausted and not exhausted.target_id,
        "selector_count_contradiction_rejected": malformed_rejected,
        "selector_execution_order_is_canonical": reordered_rejected,
        "policy_actor_owner_mismatch_blocked": not wrong_owner.resolved and wrong_owner.blocked_reason == "bounce_policy_actor_owner_mismatch",
        "primary_target_identity_and_relation_enforced": (
            not missing_primary.ok
            and missing_primary.error == "bounce_primary_target_missing"
            and not friendly_primary.ok
            and friendly_primary.error == "bounce_primary_target_not_opposing"
        ),
    }
    return {"checks": checks, "selected_targets": previous, "results": [result.to_json() for result in results], "exhausted": exhausted.to_json()}


def _runtime_rules(inventory: dict[str, Any], policy: Any) -> tuple[RuleBook, Any]:
    definition = next(
        item for item in inventory["definitions"]
        if item.action_id == policy.action_id and item.level == policy.level
    )
    canonical = inventory["lowering"].build_character_action_ability_slice(
        definition,
        snapshot=inventory["snapshot"],
        scope_catalog=inventory["scope"],
        source_graph_catalog=inventory["graph"],
    )
    registry = build_engine_rule_registry()
    canonical = replace(
        canonical,
        timeline_rules=registry.timeline_rules,
        resource_rules=registry.resource_rules,
        damage_formula_rules=registry.damage_formula_rules,
        damage_route_rules=registry.damage_route_rules,
        shield_priority_rules=registry.shield_priority_rules,
    )
    return RuleBook(canonical), definition


def _external_action_dependency(inventory: dict[str, Any], policy: Any) -> dict[str, Any]:
    rules, definition = _runtime_rules(inventory, policy)
    card = next(item for item in rules.ir.character_data_cards if item.card_id == policy.character_data_card_id)
    state = _state(card.entity_ref)
    targets = ActionTargetSelectionSystem(rules)
    query = targets.query(state, "ally:actor", definition.action_id, definition.level)
    accepted = targets.accept(state, query, (query.candidate_ids[0],)) if query.candidate_ids else None
    if accepted is None or not accepted.accepted or accepted.context is None:
        return {"checks": {"source_action_target_context_admitted": False}}
    command = ActionCommand(
        actor_id="ally:actor",
        action_id=definition.action_id,
        action_level=definition.level,
        target_ids=accepted.context.accepted.submitted_target_ids,
        source="manual",
    )
    event = rules.require_action_event(definition.action_id, definition.level)
    impact = targets.resolve_impact(state, command, accepted.context, event)
    transition = CombatExecutor(rules).execute(command, state, target_selection_context=accepted.context)[1]
    blocker = str(transition.coverage.get("blocked_reason") or "")
    parts = tuple(part for part in blocker.split(",") if part)
    external_only = bool(parts) and all(part.startswith(_ACTION_EXTERNAL_PREFIXES) for part in parts)
    checks = {
        "source_action_target_context_admitted": query.resolved and accepted.accepted,
        "source_bounce_impact_admitted": impact.ok,
        "source_action_formula_projection_closed": "skill_formula" not in blocker and bool(rules.ir.skill_formula_bindings),
        "full_action_dependency_is_external_to_s5": not transition.outcome.successor_eligible and external_only,
        "external_dependency_publishes_no_business_output": (
            transition.after.to_json() == state.snapshot().to_json()
            and not transition.transaction.mutations
            and not transition.rng_events
        ),
        "full_action_e2e_not_claimed_before_s6_s8": not transition.outcome.successor_eligible,
    }
    return {
        "checks": checks,
        "action_id": definition.action_id,
        "action_level": definition.level,
        "blocked_reason": blocker,
        "dependency_owner": "P9-S6/P9-S8",
        "target_impact": impact.to_json(),
    }


def _aggregate(inventory: dict[str, Any], policies: dict[str, Any]) -> dict[str, Any]:
    target_catalog, action_catalog = inventory["target_catalog"], inventory["action_catalog"]
    definitions = {(item.action_id, item.level): item for item in inventory["definitions"]}
    contracts = {(item.action_id, item.level): item for item in action_catalog.contracts}
    source_actions = _source_action_map(inventory["graph"])
    selector_keys = {
        _source_key(source)
        for policy in policies["rules"].ir.bounce_policies
        if policy.coverage_status == "executable"
        for source in policy.random_selector_sources
    }
    assignments: list[tuple[str, str]] = []
    gaps: list[dict[str, Any]] = []
    owners: Counter[str] = Counter()

    def assign(identity: str, owner: str) -> None:
        assignments.append((identity, owner))
        owners[owner] += 1

    def gap(item: Any, reason: str) -> str:
        gaps.append({"identity": getattr(item, "record_id", getattr(item, "definition_id", "")), "reason": reason, "source": item.source.to_json()})
        return "P9-S5:unresolved"

    for record in target_catalog.records:
        owner = ""
        if record.responsibility == "s5a_effect_target":
            if record.coverage_status == "executable":
                owner = "P9-S5A/S5B:executable"
            else:
                remaining = set(record.dependency_stages) - _RESOLVED_S5
                owner = "external:" + "+".join(sorted(remaining)) if remaining and remaining.issubset(_EXTERNAL) else gap(record, record.blocked_reason)
        elif record.responsibility == "s5c_input_target":
            action_ids = _actions_for_source(record.source, source_actions)
            related = tuple(contract for key, contract in contracts.items() if key[0] in action_ids)
            owner = "P9-S5C:action_contract" if action_ids and related and all(item.coverage_status == "lowered" for item in related) else gap(record, "input_target_not_closed_by_action_contract")
        elif record.responsibility == "s5d_random_target_task":
            if _source_key(record.source) in selector_keys:
                owner = "P9-S5D2:bounce_sampler"
            elif _actions_for_source(record.source, source_actions):
                owner = "P9-S8:ability_control_flow"
            else:
                owner = gap(record, "random_target_task_has_no_formal_owner")
        elif record.responsibility == "retired_non_gameplay":
            owner = "excluded:non_gameplay"
        elif record.responsibility == "existing_projection_consumer":
            owner = "existing_projection_consumer"
        else:
            owner = "P9-S17:source_scope_admission"
        assign(record.record_id, owner)
    for definition in target_catalog.language_definitions:
        owner = "source_language:executable" if definition.coverage_status == "executable" else "source_language:blocked:" + "+".join(definition.dependency_stages)
        assign(definition.definition_id, owner)

    action_assignments: list[tuple[str, str]] = []
    for contract in action_catalog.contracts:
        owner = "P9-S5C:lowered" if contract.coverage_status == "lowered" else f"external:{contract.gap_owner}"
        if contract.gap_owner == "p9_s5c2":
            gaps.append({"identity": contract.contract_id, "reason": contract.blocked_reason})
            owner = "P9-S5:unresolved"
        action_assignments.append((contract.contract_id, owner))
    dynamic = tuple(item for item in action_catalog.contracts if item.coverage_status == "lowered" and item.dynamic_target)
    dynamic_bounce = tuple(item for item in dynamic if definitions[(item.action_id, item.level)].target_mode == "bounce")
    nonbounce = tuple(item for item in dynamic if item not in dynamic_bounce)
    policy_keys = {
        (policy.action_id, policy.level)
        for policy in policies["rules"].ir.bounce_policies
    }
    random_records = tuple(item for item in target_catalog.records if item.responsibility == "s5d_random_target_task")
    consumed = tuple(item for item in random_records if _source_key(item.source) in selector_keys)
    deferred = tuple(item for item in random_records if _source_key(item.source) not in selector_keys)
    scope_by_id = {item.record_id: item for item in inventory["scope"].scope_records}
    selector_scope = tuple(scope_by_id.get(key[2]) for key in selector_keys)
    checks = {
        "target_source_denominator_assigned_once": len(assignments) == len(target_catalog.records) + len(target_catalog.language_definitions) == len({key for key, _ in assignments}),
        "action_contract_denominator_assigned_once": len(action_assignments) == len(action_catalog.contracts) == len({key for key, _ in action_assignments}),
        "current_character_action_contracts_all_lowered": all(item.coverage_status == "lowered" for item in action_catalog.contracts if item.source_action_source_ids),
        "all_selector_sources_exist_in_target_denominator": selector_keys == {_source_key(item.source) for item in consumed},
        "selector_sources_close_to_bounce_template_parent": bool(selector_scope) and all(
            item is not None
            and (parent := scope_by_id.get(item.parent_record_id)) is not None
            and parent.family == "IncludeTaskListTemplate"
            for item in selector_scope
        ),
        "remaining_random_tasks_have_exact_s8_owner": all(_actions_for_source(item.source, source_actions) for item in deferred),
        "bounce_policy_action_contracts_closed": bool(policy_keys) and all(
            key in contracts
            and key in definitions
            and contracts[key].coverage_status == "lowered"
            and definitions[key].target_mode == "bounce"
            and resolve_action_bounce_policy(
                policies["rules"], key[0], key[1]
            ).resolved
            for key in policy_keys
        ),
        "nonbounce_dynamic_remains_s8_owned": all(definitions[(item.action_id, item.level)].target_mode != "bounce" for item in nonbounce),
        "s5_owned_gap_count_zero": not gaps,
        "full_canonical_ir_build_count_zero": inventory["full_build_calls"] == 0,
    }
    return {
        "checks": checks,
        "target_assignment_count": len(assignments),
        "target_assignment_digest": _digest(assignments),
        "action_assignment_count": len(action_assignments),
        "action_assignment_digest": _digest(action_assignments),
        "owner_counts": dict(sorted(owners.items())),
        "random_target_tasks": {"denominator": len(random_records), "bounce_consumed": len(consumed), "s8_deferred": len(deferred)},
        "dynamic_actions": {"denominator": len(dynamic), "bounce": len(dynamic_bounce), "s8_deferred": len(nonbounce)},
        "s5_gaps": gaps,
    }


def _static_audit(core_root: Path) -> dict[str, bool]:
    target = (core_root / "systems" / "target.py").read_text(encoding="utf-8")
    executor = (core_root / "core" / "executor.py").read_text(encoding="utf-8")
    selection = (core_root / "systems" / "action_selection.py").read_text(encoding="utf-8")
    combined = target + executor + selection
    return {
        "bounce_has_no_private_rng_request": "RNGRequest(" not in target,
        "executor_consumes_typed_policy_not_copied_payload": "_bounce_policy_from_damage_plan" not in executor and '.get("bounce_policy")' not in executor,
        "ordinary_dynamic_target_has_precise_s8_owner": "action_dynamic_target_control_flow_deferred_to_p9_s8" in selection,
        "old_s5d_dynamic_blockers_absent": "action_dynamic_target_deferred_to_p9_s5d" not in selection and "action_bounce_impact_deferred_to_p9_s5d" not in selection,
        "no_character_or_action_specific_runtime_handler": not re.search(r"Welt|Xueyi|1100402|AvatarID", combined),
        "target_random_settlement_only_after_atomic_commit": "if atomic_commit.outcome.successor_eligible:" in executor and 'record_type="target_random_choice"' in executor,
    }


def run_validation(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    inventory = _inventory(tbgd_root)
    inventory["cards"] = build_character_card_ir(
        tbgd_root,
        max_records_per_table=None,
        skill_tables=CHARACTER_ACTION_DEFINITION_TABLES,
        ability_source_graph_catalog=inventory["graph"],
        ability_scope_catalog=inventory["scope"],
    )
    policies = _policy_matrix(inventory)
    selected = policies["selected"]
    if selected is None:
        direct = {"checks": {"source_structured_case_found": False}}
    else:
        card = next(item for item in inventory["cards"].character_data_cards if item.card_id == selected.character_data_card_id)
        direct = _direct_matrix(selected, card)
    inventory.pop("cards")
    gc.collect()
    inventory["action_catalog"] = build_action_target_contract_catalog(
        tbgd_root,
        definitions=inventory["definitions"],
        snapshot=inventory["snapshot"],
        source_graph_catalog=inventory["graph"],
        definition_scope_complete=True,
    )
    inventory["target_catalog"] = build_target_source_projection(
        tbgd_root, snapshot=inventory["snapshot"]
    )
    aggregate = _aggregate(inventory, policies)
    inventory.pop("action_catalog")
    inventory.pop("target_catalog")
    gc.collect()
    action = (
        _external_action_dependency(inventory, selected)
        if selected is not None
        else {"checks": {"source_structured_case_found": False}}
    )
    static = _static_audit(Path(__file__).resolve().parents[1])
    checks = {**policies["checks"], **direct["checks"], **action["checks"], **aggregate["checks"], **static}
    evidence = {
        "stage": STAGE,
        "acceptance_scope": "target_mechanism_accepted; full source action E2E deferred to P9-S6/P9-S8",
        "selection_rule": "first canonical source-linked executable bounce policy with more hits than the two-unit candidate pool",
        "selected_policy": selected.to_json() if selected else {},
        "policy_rows": policies["rows"],
        "direct_target": direct,
        "external_action_dependency": action,
        "aggregate": aggregate,
        "static": static,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "evidence.json", evidence)
    summary = {
        "stage": STAGE,
        "ok": bool(checks) and all(value is True for value in checks.values()),
        "acceptance_status": "mechanism_accepted_external_e2e_dependency",
        "check_count": len(checks),
        "failed_checks": sorted(key for key, value in checks.items() if value is not True),
        "checks": checks,
        "build_counters": {
            "full_canonical_ir_build_count": inventory["full_build_calls"],
            "target_source_projection_count": 1,
            "action_target_catalog_count": 1,
            "source_action_slice_count": 1 if selected else 0,
        },
        "resources": {
            "wall_seconds": time.monotonic() - started,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "evidence_bytes": (output_dir / "evidence.json").stat().st_size,
        },
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P9-S5D2 bounce target mechanism")
    parser.add_argument("--tbgd-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    core_root = Path(__file__).resolve().parents[1]
    result = run_validation(args.tbgd_root or find_tbgd_root(core_root.parent), args.output_dir)
    print(f"{STAGE} ok={result['ok']} checks={result['check_count']} failed={len(result['failed_checks'])}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
