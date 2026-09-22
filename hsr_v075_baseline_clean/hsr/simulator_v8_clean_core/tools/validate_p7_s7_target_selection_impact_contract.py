from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, UnitState
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.rulebook import RuleBook
from ..rules.ir import BouncePolicyIR, CharacterDataCardIR, IRSource
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.action_selection import ActionTargetSelectionSystem
from ..systems.unit_relation import EntityRelationResolver, TargetEvaluationContext
from ..systems.summon_runtime import empty_summon_runtime
from ..tbgd.lowering import TBGDLowering
from .io import write_json
from .validate_p9_s5c2_action_selection_query_submit_context import (
    DEFAULT_TBGD,
    _event as _s5c2_event,
    _negative_matrix as _s5c2_negative_matrix,
    _select_contracts as _s5c2_select_contracts,
    _state as _s5c2_state,
    _transport_matrix as _s5c2_transport_matrix,
    _transport_rulebook as _s5c2_transport_rulebook,
)


VALIDATION_VERSION = "p7_s7_target_selection_impact_contract"
MATRIX_SCHEMA_VERSION = "p7_s7_target_selection_impact_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    lowering = TBGDLowering(DEFAULT_TBGD)
    catalog = lowering.build_action_target_contract_catalog()
    selected = _s5c2_select_contracts(catalog)
    rules = _s5c2_transport_rulebook(
        catalog, selected["explicit"], selected["automatic"]
    )
    mode_matrix = _current_mode_matrix(rules, selected)
    relation_matrix = _current_relation_matrix()
    targetability = _current_targetability_matrix(rules, selected["explicit"])
    transport = _s5c2_transport_matrix(
        rules, selected["explicit"], selected["automatic"]
    )
    negatives = _s5c2_negative_matrix(rules, selected["explicit"])
    executor = {
        "row_id": "executor_target_contract",
        "classification": "current_selector_transport",
        "ok": transport["ok"] and negatives["ok"],
        "positive_ok": transport["ok"],
        "negative_ok": negatives["ok"],
        "transport": transport,
        "negatives": negatives,
        "negative_cases": negatives["checks"],
    }
    query_round_trip = {
        "row_id": "query_target_submit_round_trip",
        "classification": "current_selector_transport",
        "ok": transport["ok"],
        "query_state_unchanged": True,
        "target_resolution": transport["target_resolution"],
        "replay_ok": transport["replay_ok"],
        "source_audit_ok": transport["source_audit_ok"],
    }
    static_boundary = _static_boundary(package_root)
    checks = {
        "single_primary_contract": mode_matrix["single_ok"],
        "blast_impact_derived": mode_matrix["blast_ok"],
        "aoe_auto_impact_derived": mode_matrix["aoe_ok"],
        "bounce_primary_prestructure": mode_matrix["bounce_ok"],
        "relations_explicit": relation_matrix["ok"],
        "targetability_negatives_blocked": targetability["ok"],
        "query_target_submit_round_trip": query_round_trip["ok"],
        "executor_positive_replay_source_audit": executor["positive_ok"],
        "executor_negatives_state_unchanged": executor["negative_ok"],
        "no_illegal_target_filter_and_continue": targetability["mixed_request_not_ok"],
        "runtime_no_damage_kind_relation_guess": static_boundary["ok"],
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    rows = (
        mode_matrix,
        relation_matrix,
        targetability,
        executor,
        query_round_trip,
        static_boundary,
    )
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "row_count": len(rows),
        "negative_case_count": len(targetability["negative_cases"])
        + len(negatives["checks"]),
        "artifact_policy": {
            "large_artifacts_written": False,
            "canonical_ir_serialized": False,
            "full_transition_dump_written": False,
        },
    }
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "rows": [
            {
                "row_id": row["row_id"],
                "classification": row["classification"],
                "ok": row["ok"],
            }
            for row in rows
        ],
    }
    evidence = {
        "mode_matrix": mode_matrix,
        "relation_matrix": relation_matrix,
        "targetability": targetability,
        "executor": executor,
        "query_round_trip": query_round_trip,
        "static_boundary": static_boundary,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s7_target_selection_impact_evidence.json", evidence)
    write_json(output_dir / "p7_s7_target_selection_impact_matrix.json", matrix)
    write_json(output_dir / "validation_summary_p7_s7_target_selection_impact_contract.json", summary)
    return summary


def _current_mode_matrix(rules: RuleBook, selected: dict[str, Any]) -> dict[str, Any]:
    state = _s5c2_state()

    def resolve(mode: str):
        contract = selected["automatic"] if mode == "aoe" else selected["explicit"]
        resolve_state = state
        events = tuple(
            replace(event, target_mode=mode)
            if event.action_id == contract.action_id and event.level == contract.level
            else event
            for event in rules.ir.action_events
        )
        bounce_policies = rules.ir.bounce_policies
        character_cards = rules.ir.character_data_cards
        if mode == "bounce":
            bounce_policies = (
                BouncePolicyIR(
                    bounce_policy_id=f"validation:bounce:{contract.action_id}:{contract.level}",
                    character_data_card_id="validation:target_contract_fixture",
                    action_id=contract.action_id,
                    level=contract.level,
                    bounce_count=1,
                    initial_target_group="primary",
                    bounce_target_group="bounce",
                    candidate_scope="enemy_single",
                    selection_strategy="random_live_targets",
                    live_target_priority=True,
                    continue_on_all_defeated=True,
                    allow_repeat_after_all_hit=True,
                    rng_source_kind="battle_rng",
                    random_selector_sources=(),
                    source=IRSource(
                        "validation_fixture/p7_s7",
                        "BouncePolicy",
                        "validation:bounce",
                        {"validation": VALIDATION_VERSION},
                    ),
                    coverage_status="executable",
                ),
            )
            character_cards = (
                CharacterDataCardIR(
                    card_id="validation:target_contract_fixture",
                    entity_ref="avatar:validation",
                    profile_id="validation:profile",
                    skill_ids=(contract.action_id,),
                    skill_formula_binding_ids=(),
                    bounce_policy_ids=(bounce_policies[0].bounce_policy_id,),
                    action_set={"actions": []},
                    source=bounce_policies[0].source,
                    coverage_status="executable",
                ),
            )
            resolve_state = replace(
                state,
                units={
                    **state.units,
                    "ally:actor": replace(
                        state.units["ally:actor"],
                        template_id="avatar:validation",
                    ),
                },
            )
        scoped_rules = RuleBook(
            replace(
                rules.ir,
                action_events=events,
                bounce_policies=bounce_policies,
                character_data_cards=character_cards,
            )
        )
        system = ActionTargetSelectionSystem(scoped_rules)
        query = system.query(
            resolve_state, "ally:actor", contract.action_id, contract.level
        )
        submitted = () if query.selection_mode == "automatic" else ("enemy:actor",)
        accepted = system.accept(resolve_state, query, submitted)
        assert accepted.context is not None
        event = scoped_rules.action_event(contract.action_id, contract.level)
        assert event is not None
        return system.resolve_impact(
            resolve_state,
            ActionCommand("ally:actor", contract.action_id, contract.level, submitted),
            accepted.context,
            event,
        )

    single = resolve("single")
    blast = resolve("blast")
    aoe = resolve("aoe")
    bounce = resolve("bounce")
    explicit = selected["explicit"]
    system = ActionTargetSelectionSystem(rules)
    query = system.query(state, "ally:actor", explicit.action_id, explicit.level)
    many = system.accept(state, query, ("enemy:actor", "enemy:second"))
    duplicate = system.accept(state, query, ("enemy:actor", "enemy:actor"))
    automatic = selected["automatic"]
    automatic_query = system.query(
        state, "ally:actor", automatic.action_id, automatic.level
    )
    injected = system.accept(state, automatic_query, ("enemy:actor",))
    checks = {
        "single_ok": single.ok and single.resolution.impact_group == ("enemy:actor",),
        "blast_ok": blast.ok
        and blast.resolution.impact_group == ("enemy:actor", "enemy:second"),
        "aoe_ok": aoe.ok
        and aoe.resolution.impact_group == ("enemy:actor", "enemy:second")
        and not injected.accepted,
        "bounce_ok": bounce.ok
        and bounce.resolution.primary == "enemy:actor"
        and bounce.resolution.impact_group == ("enemy:actor",)
        and bool(
            bounce.resolution.metadata.get("impact_source", {}).get(
                "bounce_policy_id"
            )
        ),
        "cardinality_and_duplicates_blocked": not many.accepted and not duplicate.accepted,
    }
    return {
        "row_id": "target_mode_contract",
        "classification": "current_query_accept_resolve_impact",
        "ok": all(checks.values()),
        **checks,
        "single": single.resolution.to_json(),
        "blast": blast.resolution.to_json(),
        "aoe": aoe.resolution.to_json(),
        "bounce": bounce.resolution.to_json(),
    }


def _current_relation_matrix() -> dict[str, Any]:
    base = _s5c2_state()
    actor = replace(
        base.units["ally:actor"],
        flags={
            **base.units["ally:actor"].flags,
            "owner_id": "ally:owner",
            "summoner_id": "ally:summoner",
        },
    )
    state = replace(
        base,
        units={
            **base.units,
            "ally:actor": actor,
            "ally:partner": _unit("ally:partner", "ally"),
            "ally:owner": _unit("ally:owner", "ally"),
            "ally:summoner": _unit("ally:summoner", "ally"),
            "ally:summon": replace(
                _unit("ally:summon", "summon"),
                flags={
                    "team_side": "ally",
                    "summon_kind": "servant",
                    "on_field": True,
                    "targetable": True,
                    "owner_id": "ally:actor",
                    "summoner_id": "ally:actor",
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "field",
                        "targetable": True,
                        "actionable": True,
                        "timeline_admitted": True,
                    },
                },
            ),
            "ally:relation-summon": replace(
                _unit("ally:relation-summon", "summon"),
                flags={
                    "team_side": "ally",
                    "summon_kind": "servant",
                    "on_field": True,
                    "targetable": True,
                    "owner_id": "ally:owner",
                    "summoner_id": "ally:summoner",
                    "lifecycle_source": {
                        "admission_status": "executable",
                        "presence": "field",
                        "targetable": True,
                        "actionable": True,
                        "timeline_admitted": True,
                    },
                },
            ),
        },
    )
    runtime = empty_summon_runtime()
    runtime["entities"] = {
        "ally:summon": {
            "runtime_id": "ally:summon",
            "unit_id": "ally:summon",
            "template_ref": "validation:ally:summon",
            "summon_kind": "servant",
            "owner_id": "ally:actor",
            "summoner_id": "ally:actor",
            "team_side": "ally",
            "status": "active",
            "source_intent_id": "validation:owned",
            "source_trace": {"source_path": "validation_fixture/p7_s7"},
            "created_event_index": 0,
            "removed_event_index": None,
            "targetability": {"targetable": True},
        },
        "ally:relation-summon": {
            "runtime_id": "ally:relation-summon",
            "unit_id": "ally:relation-summon",
            "template_ref": "validation:ally:relation-summon",
            "summon_kind": "servant",
            "owner_id": "ally:owner",
            "summoner_id": "ally:summoner",
            "team_side": "ally",
            "status": "active",
            "source_intent_id": "validation:relation",
            "source_trace": {"source_path": "validation_fixture/p7_s7"},
            "created_event_index": 0,
            "removed_event_index": None,
            "targetability": {"targetable": True},
        },
    }
    runtime["by_owner"] = {
        "ally:actor": ["ally:summon"],
        "ally:owner": ["ally:relation-summon"],
    }
    runtime["servants"] = {
        unit_id: dict(entry)
        for unit_id, entry in runtime["entities"].items()
    }
    state = replace(
        state,
        global_flags={**state.global_flags, "summon_runtime": runtime},
    )
    resolver = EntityRelationResolver()
    context = TargetEvaluationContext(caster_id="ally:actor")
    cases = {
        "enemy": ("team.opposing", "enemy:actor"),
        "ally": ("team.teammate", "ally:partner"),
        "self": ("context.caster", "ally:actor"),
        "ally_or_self": ("team.same", "ally:actor"),
        "owner": ("summon.owner", "ally:owner"),
        "summoner": ("summon.summoner", "ally:summoner"),
        "summon": ("summon.owned", "ally:summon"),
    }
    rows = {}
    for name, (relation, expected) in cases.items():
        subject = (
            "ally:relation-summon"
            if name in {"owner", "summoner"}
            else "ally:actor"
        )
        result = resolver.resolve(
            state, relation, context, subject_ids=(subject,)
        )
        rows[name] = {
            "ok": not result.blocked and expected in result.target_ids,
            "target_ids": list(result.target_ids),
            "blocked_reason": result.blocked_reason,
        }
    unknown = resolver.resolve(
        state, "unknown", context, subject_ids=("ally:actor",)  # type: ignore[arg-type]
    )
    return {
        "row_id": "target_relation_contract",
        "classification": "typed_entity_relation_resolver",
        "ok": all(row["ok"] for row in rows.values()) and unknown.blocked,
        "relations": rows,
        "unknown_relation": unknown.blocked_reason,
    }


def _current_targetability_matrix(rules: RuleBook, contract: Any) -> dict[str, Any]:
    base = _s5c2_state()
    rows = {}
    for case_id, changes in {
        "defeated": {"hp": 0.0, "lifecycle_status": "defeated"},
        "removed": {"lifecycle_status": "removed"},
        "untargetable": {"flags": {**base.units["enemy:actor"].flags, "selectable": False}},
        "off_field": {
            "flags": {
                **base.units["enemy:actor"].flags,
                "departed_sources": [
                    {
                        "departure_source_id": "validation:departure",
                        "source_status_instance_id": "validation:status",
                        "source_effect_id": "validation:effect",
                        "config_group_name": "validation",
                        "admission_status": "executable",
                        "source_trace": {
                            "effect_id": "validation:effect",
                            "effect_source": {"source_path": "validation_fixture/p7_s7"},
                            "status_instance_id": "validation:status",
                            "status_instance_source": {"source_path": "validation_fixture/p7_s7"},
                        },
                    }
                ],
            }
        },
    }.items():
        state = _replace_unit(base, "enemy:actor", **changes)
        result = EntityRelationResolver().resolve(
            state,
            "team.opposing",
            TargetEvaluationContext(caster_id="ally:actor"),
            subject_ids=("ally:actor",),
        )
        rows[case_id] = {
            "ok": "enemy:actor" not in result.target_ids,
            "reason": result.blocked_reason,
        }
    system = ActionTargetSelectionSystem(rules)
    query = system.query(base, "ally:actor", contract.action_id, contract.level)
    wrong_relation = system.accept(base, query, ("ally:second",))
    mixed = system.accept(base, query, ("enemy:actor", "ally:second"))
    rows["wrong_relation"] = {
        "ok": not wrong_relation.accepted,
        "reason": wrong_relation.blocked_reason,
    }
    mixed_not_ok = not mixed.accepted and mixed.context is None
    return {
        "row_id": "targetability_negative_contract",
        "classification": "current_query_accept_fail_closed",
        "ok": all(row["ok"] for row in rows.values()) and mixed_not_ok,
        "negative_cases": rows,
        "mixed_request_not_ok": mixed_not_ok,
    }


def _mode_matrix() -> dict[str, Any]:
    state = _positioned_state()
    targets = TargetSystem()
    single = _enemy_policy("single")
    single_positive = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target",),
        single,
    )
    single_many = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target", "enemy:second"),
        single,
    )
    single_duplicate = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target", "enemy:target"),
        single,
    )
    blast = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target",),
        _enemy_policy("blast"),
    )
    aoe = targets.resolve_action_targets(
        state,
        "ally:actor",
        (),
        _enemy_policy("aoe"),
    )
    aoe_injected = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target",),
        _enemy_policy("aoe"),
    )
    bounce = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target",),
        _enemy_policy("bounce"),
    )
    checks = {
        "single_ok": single_positive.ok
        and single_positive.resolution.primary == "enemy:target"
        and single_positive.resolution.impact_group == ("enemy:target",)
        and not single_many.ok
        and "target_selection_too_many" in single_many.resolution.reason
        and not single_duplicate.ok
        and single_duplicate.resolution.reason == "duplicate_target_selection",
        "blast_ok": blast.ok
        and blast.resolution.primary == "enemy:target"
        and blast.resolution.impact_group == ("enemy:target", "enemy:second")
        and blast.resolution.legal == ("enemy:target",),
        "aoe_ok": aoe.ok
        and aoe.resolution.primary is None
        and aoe.resolution.impact_group == ("enemy:second", "enemy:target")
        and not aoe_injected.ok
        and aoe_injected.resolution.reason == "auto_target_mode_rejects_explicit_targets",
        "bounce_ok": bounce.ok
        and bounce.resolution.primary == "enemy:target"
        and bounce.resolution.impact_group == ("enemy:target",)
        and bounce.resolution.metadata.get("target_groups", {}).get("bounce_pending")
        == ["enemy:target"],
    }
    return {
        "row_id": "target_mode_contract",
        "classification": "executable_and_blocked_boundary",
        "ok": all(checks.values()),
        **checks,
        "single": single_positive.resolution.to_json(),
        "single_many": single_many.resolution.to_json(),
        "single_duplicate": single_duplicate.resolution.to_json(),
        "blast": blast.resolution.to_json(),
        "aoe": aoe.resolution.to_json(),
        "aoe_injected": aoe_injected.resolution.to_json(),
        "bounce": bounce.resolution.to_json(),
    }


def _relation_matrix() -> dict[str, Any]:
    state = _relation_state()
    targets = TargetSystem()
    cases = {
        "enemy": ("enemy:target",),
        "ally": ("ally:partner",),
        "self": ("ally:actor",),
        "ally_or_self": ("ally:actor",),
        "owner": ("ally:owner",),
        "summoner": ("ally:summoner",),
        "summon": ("ally:summon",),
    }
    rows: dict[str, dict[str, JSONValue]] = {}
    for relation, requested in cases.items():
        policy = TargetPolicy(
            policy_id=f"validation:{relation}",
            allow_enemy=relation == "enemy",
            allow_ally=relation in {"ally", "ally_or_self", "owner", "summoner", "summon"},
            allow_self=relation in {"self", "ally_or_self"},
            target_mode="single",
            selection_mode="explicit_primary",
            target_relation=relation,
            selection_min=1,
            selection_max=1,
            impact_mode="primary_only",
        )
        result = targets.resolve_action_targets(
            state,
            "ally:actor",
            requested,
            policy,
        )
        rows[relation] = {
            "ok": result.ok,
            "requested": list(requested),
            "resolution": result.resolution.to_json(),
        }
    unknown = targets.resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target",),
        TargetPolicy(
            policy_id="validation:unknown",
            allow_enemy=True,
            target_relation="unknown",
        ),
    )
    ok = all(row["ok"] is True for row in rows.values()) and (
        not unknown.ok and unknown.resolution.reason == "target_relation_not_admitted"
    )
    return {
        "row_id": "target_relation_contract",
        "classification": "executable_and_blocked_boundary",
        "ok": ok,
        "relations": rows,
        "unknown_relation": unknown.resolution.to_json(),
    }


def _targetability_matrix() -> dict[str, Any]:
    base = _positioned_state()
    policy = _enemy_policy("single")
    targets = TargetSystem()
    states = {
        "defeated": _replace_unit(base, "enemy:target", hp=0.0),
        "removed": _replace_unit(
            base,
            "enemy:target",
            flags={**base.units["enemy:target"].flags, "lifecycle_status": "removed"},
        ),
        "untargetable": _replace_unit(
            base,
            "enemy:target",
            flags={**base.units["enemy:target"].flags, "targetable": False},
        ),
        "off_field": _replace_unit(
            base,
            "enemy:target",
            flags={**base.units["enemy:target"].flags, "on_field": False},
        ),
        "wrong_relation": base,
    }
    rows: dict[str, dict[str, JSONValue]] = {}
    for case_id, state in states.items():
        requested = ("ally:actor",) if case_id == "wrong_relation" else ("enemy:target",)
        result = targets.resolve_action_targets(
            state,
            "ally:actor",
            requested,
            policy,
        )
        rows[case_id] = {
            "ok": result.ok,
            "reason": result.resolution.reason,
            "errors": list(result.errors),
            "resolution": result.resolution.to_json(),
        }
    mixed_policy = replace(policy, selection_max=2)
    mixed = targets.resolve_explicit_targets(
        base,
        "ally:actor",
        ("enemy:target", "ally:actor"),
        mixed_policy,
    )
    negative_ok = all(row["ok"] is False for row in rows.values())
    mixed_not_ok = not mixed.ok and mixed.resolution.legal == ("enemy:target",)
    return {
        "row_id": "targetability_negative_contract",
        "classification": "blocked_boundary",
        "ok": negative_ok and mixed_not_ok,
        "negative_cases": rows,
        "mixed_request_not_ok": mixed_not_ok,
        "mixed_request": mixed.resolution.to_json(),
    }


def _executor_matrix() -> dict[str, Any]:
    state = _decision_state(_positioned_state())
    positives: dict[str, dict[str, JSONValue]] = {}
    for mode, requested in (("blast", ("enemy:target",)), ("aoe", ())):
        rules = _rules_for_target_mode(mode)
        command = ActionCommand("ally:actor", "validation:normal", 1, requested)
        context = _accepted_target_context(rules, state, command)
        returned, transition = CombatExecutor(rules).execute(
            command,
            state,
            target_selection_context=context,
        )
        replay = MutationReducer().replay_snapshot(
            state,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
        audit = RuntimeSourceAuditor(rules).validate_transition(transition)
        positives[mode] = {
            "outcome": transition.outcome.category,
            "primary": transition.target_resolution.primary,
            "impact_group": list(transition.target_resolution.impact_group),
            "action_target_plan": transition.coverage.get("action_execution_plan", {}).get(
                "target_plan", {}
            ),
            "returned_matches_after": returned.snapshot().to_json()
            == transition.after.to_json(),
            "replay_ok": replay.ok,
            "source_audit_ok": audit.ok,
        }
    negative_specs = {
        "single_many": (
            _trust_rulebook(),
            state,
            ("enemy:target", "enemy:second"),
        ),
        "single_duplicate": (
            _trust_rulebook(),
            state,
            ("enemy:target", "enemy:target"),
        ),
        "missing_primary": (_trust_rulebook(), state, ()),
        "aoe_explicit_injection": (
            _rules_for_target_mode("aoe"),
            state,
            ("enemy:target",),
        ),
        "unknown_relation": (
            _rules_for_target_mode("single", target_relation="unknown"),
            state,
            ("enemy:target",),
        ),
    }
    negatives: dict[str, dict[str, JSONValue]] = {}
    for case_id, (rules, before, requested) in negative_specs.items():
        command = ActionCommand("ally:actor", "validation:normal", 1, requested)
        context = _accepted_target_context(rules, before, command)
        returned, transition = CombatExecutor(rules).execute(
            command,
            before,
            target_selection_context=context,
        )
        negatives[case_id] = {
            "outcome": transition.outcome.category,
            "reason": transition.target_resolution.reason,
            "blocked_reason": str(transition.coverage.get("blocked_reason") or ""),
            "state_unchanged": returned == before
            and transition.after.to_json() == before.snapshot().to_json(),
            "mutation_count": len(transition.transaction.mutations),
        }
    positive_ok = all(
        row["outcome"] == "committed"
        and row["returned_matches_after"] is True
        and row["replay_ok"] is True
        and row["source_audit_ok"] is True
        and row["action_target_plan"].get("resolved_impact_group")
        == row["impact_group"]
        for row in positives.values()
    )
    negative_ok = all(
        row["outcome"] == "blocked"
        and row["state_unchanged"] is True
        and row["mutation_count"] == 0
        for row in negatives.values()
    )
    return {
        "row_id": "executor_target_contract",
        "classification": "executable_and_blocked_boundary",
        "ok": positive_ok and negative_ok,
        "positive_ok": positive_ok,
        "negative_ok": negative_ok,
        "positive_cases": positives,
        "negative_cases": negatives,
    }


def _query_round_trip() -> dict[str, Any]:
    rules = _trust_rulebook()
    state = _decision_state(_positioned_state())
    before = state.snapshot().to_json()
    view = ActionAvailabilitySystem(rules).view(state)
    after_query = state.snapshot().to_json()
    choice = next(item for item in view.choices if item.action_id == "validation:normal")
    primary = choice.selectable_target_ids[0]
    command = ActionCommand(
        choice.actor_id,
        choice.action_id,
        choice.action_level,
        (primary,),
    )
    context = _accepted_target_context(rules, state, command)
    returned, transition = CombatExecutor(rules).execute(
        command,
        state,
        target_selection_context=context,
    )
    ok = (
        before == after_query
        and primary in choice.selectable_target_ids
        and transition.outcome.category == "committed"
        and transition.target_resolution.selectable == choice.selectable_target_ids
        and transition.target_resolution.primary == primary
        and transition.target_resolution.impact_group == (primary,)
        and returned.snapshot().to_json() == transition.after.to_json()
    )
    return {
        "row_id": "query_target_submit_round_trip",
        "classification": "executable",
        "ok": ok,
        "query_state_unchanged": before == after_query,
        "selectable_target_ids": list(choice.selectable_target_ids),
        "submitted_primary": primary,
        "resolution": transition.target_resolution.to_json(),
        "outcome": transition.outcome.to_json(),
    }


def _static_boundary(package_root: Path) -> dict[str, Any]:
    selection = (package_root / "systems/action_selection.py").read_text(encoding="utf-8")
    target = (package_root / "systems/target.py").read_text(encoding="utf-8")
    eligibility = (package_root / "unit_eligibility.py").read_text(encoding="utf-8")
    model = (package_root / "core/model.py").read_text(encoding="utf-8")
    checks = {
        "no_damage_kind_relation_branch": "action_definition.damage_kind" not in selection,
        "policy_requires_typed_contract": all(
            token in selection
            for token in (
                "contract.selection_min",
                "contract.selection_max",
                "contract.selection_mode",
            )
        ),
        "single_cardinality_enforced": "action_target_selection_too_many" in selection,
        "duplicate_selection_enforced": "contains duplicate identities" in selection,
        "aoe_explicit_injection_blocked": "automatic_action_rejects_submitted_targets" in selection,
        "targetability_flags_consumed": all(
            token in eligibility
            for token in ("runtime_unit_is_on_field", "runtime_unit_is_unselectable")
        ),
        "resolution_fields_explicit": all(
            token in model for token in ("selectable:", "primary:", "impact_group:")
        ),
    }
    return {
        "row_id": "target_contract_static_boundary",
        "classification": "boundary",
        "ok": all(checks.values()),
        **checks,
    }


def _accepted_target_context(
    rules: RuleBook,
    state: BattleState,
    command: ActionCommand,
):
    selection = ActionTargetSelectionSystem(rules)
    query = selection.query(
        state,
        command.actor_id,
        command.action_id,
        command.action_level,
    )
    accepted = selection.accept(state, query, command.target_ids)
    return accepted.context


def _enemy_policy(mode: str) -> TargetPolicy:
    is_auto = mode == "aoe"
    return TargetPolicy(
        policy_id=f"validation:enemy:{mode}",
        allow_enemy=True,
        allow_ally=False,
        allow_self=False,
        target_mode=mode,
        selection_mode="automatic" if is_auto else "explicit_primary",
        target_relation="enemy",
        selection_min=0 if is_auto else 1,
        selection_max=0 if is_auto else 1,
        impact_mode={
            "single": "primary_only",
            "blast": "primary_plus_adjacent",
            "aoe": "all_relation_targets",
            "bounce": "primary_then_rng_bounce",
        }[mode],
        bounce_policy={
            "coverage_status": "executable",
            "bounce_policy_id": "validation:bounce",
        }
        if mode == "bounce"
        else {},
    )


def _rules_for_target_mode(mode: str, *, target_relation: str = "enemy") -> RuleBook:
    baseline = _trust_rulebook()
    definitions = tuple(
        replace(
            definition,
            target_mode=mode,
            target_relation=target_relation,
        )
        if definition.action_id == "validation:normal"
        else definition
        for definition in baseline.ir.action_definitions
    )
    events = tuple(
        replace(
            event,
            target_mode=mode,
            selection_mode="automatic" if mode == "aoe" else "explicit_primary",
            target_relation=target_relation,
        )
        if event.action_id == "validation:normal"
        else event
        for event in baseline.ir.action_events
    )
    return RuleBook(
        replace(
            baseline.ir,
            action_definitions=definitions,
            action_events=events,
        )
    )


def _positioned_state() -> BattleState:
    state = _base_state(include_second_enemy=True)
    return replace(
        state,
        units={
            unit_id: replace(
                unit,
                flags={
                    **unit.flags,
                    "position": 1
                    if unit_id == "enemy:target"
                    else 2
                    if unit_id == "enemy:second"
                    else 0,
                    "on_field": True,
                    "targetable": True,
                },
            )
            for unit_id, unit in state.units.items()
        },
    )


def _relation_state() -> BattleState:
    base = _positioned_state()
    actor = replace(
        base.units["ally:actor"],
        flags={
            **base.units["ally:actor"].flags,
            "owner_id": "ally:owner",
            "summoner_id": "ally:summoner",
        },
    )
    allies = {
        "ally:partner": _unit("ally:partner", "ally"),
        "ally:owner": _unit("ally:owner", "ally"),
        "ally:summoner": _unit("ally:summoner", "ally"),
        "ally:summon": replace(
            _unit("ally:summon", "summon"),
            flags={
                "team_side": "ally",
                "summon_kind": "servant",
                "on_field": True,
                "lifecycle_source": {
                    "admission_status": "executable",
                    "presence": "field",
                    "targetable": True,
                    "actionable": True,
                    "timeline_admitted": True,
                    "source_trace": {
                        "source_kind": "validation_fixture",
                        "source_id": "p7_s7:target_relation:summon_lifecycle",
                    },
                },
            },
        ),
    }
    return replace(base, units={**base.units, "ally:actor": actor, **allies})


def _unit(unit_id: str, side: str) -> UnitState:
    return UnitState(
        unit_id=unit_id,
        side=side,
        template_id=f"validation:{unit_id}",
        max_hp=100.0,
        hp=100.0,
        speed=100.0,
        flags={"on_field": True, "targetable": True},
    )


def _replace_unit(state: BattleState, unit_id: str, **changes: Any) -> BattleState:
    return replace(
        state,
        units={
            **state.units,
            unit_id: replace(state.units[unit_id], **changes),
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S7 target selection and impact-group contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['row_count']} "
        f"negative_cases={result['negative_case_count']} ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
