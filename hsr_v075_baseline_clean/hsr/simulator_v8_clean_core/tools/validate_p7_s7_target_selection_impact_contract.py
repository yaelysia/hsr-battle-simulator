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
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.action_preflight import target_policy_for_action
from ..systems.target import TargetPolicy, TargetSystem
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state, _decision_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s7_target_selection_impact_contract"
MATRIX_SCHEMA_VERSION = "p7_s7_target_selection_impact_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    mode_matrix = _mode_matrix()
    relation_matrix = _relation_matrix()
    targetability = _targetability_matrix()
    executor = _executor_matrix()
    query_round_trip = _query_round_trip()
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
        + len(executor["negative_cases"]),
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
        returned, transition = CombatExecutor(rules).execute(
            ActionCommand("ally:actor", "validation:normal", 1, requested),
            state,
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
        returned, transition = CombatExecutor(rules).execute(
            ActionCommand("ally:actor", "validation:normal", 1, requested),
            before,
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
    returned, transition = CombatExecutor(rules).execute(
        ActionCommand(
            choice.actor_id,
            choice.action_id,
            choice.action_level,
            (primary,),
        ),
        state,
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
    preflight = (package_root / "systems/action_preflight.py").read_text(encoding="utf-8")
    target = (package_root / "systems/target.py").read_text(encoding="utf-8")
    model = (package_root / "core/model.py").read_text(encoding="utf-8")
    function = preflight[
        preflight.index("def target_policy_for_action(") : preflight.index(
            "def _target_relation_flags("
        )
    ]
    checks = {
        "no_damage_kind_relation_branch": "if action_definition.damage_kind" not in function,
        "policy_requires_target_relation": "target_relation=relation" in function,
        "single_cardinality_enforced": "target_selection_too_many" in target,
        "duplicate_selection_enforced": "duplicate_target_selection" in target,
        "aoe_explicit_injection_blocked": "auto_target_mode_rejects_explicit_targets" in target,
        "targetability_flags_consumed": "unit_untargetable" in target and "unit_off_field" in target,
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
