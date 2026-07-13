from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.executor import CombatExecutor
from ..core.model import ActionCommand
from ..rules.ir import IRSource, TargetExpressionIR, TargetExpressionNodeIR
from ..systems.damage_formula import DamageFormulaInput, DirectDamageFormula
from ..systems.target import TargetSystem
from ..systems.rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    resolve_rng_request,
    validate_rng_choice_ledger,
)
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s15_rng_identity_replay"


def run_validation(output_dir: Path) -> dict[str, Any]:
    hit0 = _request("crit", _identity("damage_crit", hit_index=0, target_id="enemy:a"))
    hit1 = _request("crit", _identity("damage_crit", hit_index=1, target_id="enemy:a"))
    target_b = _request("crit", _identity("damage_crit", hit_index=0, target_id="enemy:b"))
    status = _request(
        "status_apply",
        {
            "decision_scope": "status_application",
            "decision_index": 0,
            "task_id": "effect:add_modifier",
            "status_id": "modifier:freeze",
            "target_id": "enemy:a",
            "derived_event_id": "status:source:freeze",
        },
    )
    random_target = _request(
        "target_random",
        {
            "decision_scope": "target_expression",
            "decision_index": 0,
            "target_expression_id": "target_expr:random_enemy",
            "target_id": "",
            "derived_event_id": "event:target:random:0",
        },
    )
    target_runtime_identity, target_runtime_event = _target_runtime_identity_case()
    executor_target_ledger = _executor_initial_target_ledger_case(target_runtime_event)
    real_damage_multi_hit = _real_damage_multi_hit_identity_case()
    cases = {
        "same_target_multi_hit": _distinct_case(hit0, hit1),
        "multi_target": _distinct_case(hit0, target_b),
        "status_identity": _single_resolution_case(status),
        "random_target_identity": _single_resolution_case(random_target),
        "target_runtime_identity": target_runtime_identity,
        "executor_initial_target_ledger": executor_target_ledger,
        "real_damage_multi_hit_identity": real_damage_multi_hit,
        "missing_choice": _missing_case(hit0),
        "extra_choice": _extra_case(hit0),
        "duplicate_provided_key": _duplicate_provided_case(hit0),
        "duplicate_consumed_identity": _duplicate_consumed_case(hit0),
        "wrong_and_broad_key": _wrong_key_case(hit0),
        "deterministic_replay": _deterministic_case(hit0),
        "incomplete_identity": _incomplete_identity_case(),
    }
    rows = {name: value["checks"] for name, value in cases.items()}
    ok = all(row.get("ok") is True for row in rows.values())
    result = {
        "version": VALIDATION_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "summary": {"row_count": len(rows), "passed": sum(row.get("ok") is True for row in rows.values())},
        "checks": rows,
        "evidence": cases,
        "resource_budget": {"tbgd_lowering_build_count": 0, "rulebook_build_count": 0},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s15_rng_identity_replay.json", result)
    write_json(output_dir / "p7_s15_rng_identity_matrix.json", {"rows": rows})
    write_json(output_dir / "p7_s15_rng_identity_evidence.json", cases)
    return result


def _target_runtime_identity_case() -> tuple[dict[str, Any], Any]:
    state = _base_state()
    expression = TargetExpressionIR(
        target_expression_id="validation:target_random_identity",
        expression_kind="TargetSequence",
        alias="",
        payload={"negative_fixture": True},
        source=IRSource("validation:target", "TargetSequence", "rng_identity"),
        node=TargetExpressionNodeIR(
            expression_kind="TargetSequence",
            children=(
                TargetExpressionNodeIR(expression_kind="TargetAlias", alias="AllEnemy"),
                TargetExpressionNodeIR(expression_kind="TargetShuffle"),
            ),
        ),
        coverage_status="executable",
    )
    common = {
        "rng_mode": "deterministic_seed",
        "actor_id": "ally:actor",
        "action_level": 1,
        "task_id": "validation:target_task",
        "hit_index": 0,
        "rng_decision_index": 0,
    }
    first = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**common, "action_id": "validation:action:first"},
    )
    second = TargetSystem().resolve_target_expression(
        state,
        expression,
        caster_id="ally:actor",
        event_payload={**common, "action_id": "validation:action:second"},
    )
    first_event = first.rng_events[0] if first.rng_events else None
    second_event = second.rng_events[0] if second.rng_events else None
    first_key = first_event.metadata.get("choice_key") if first_event is not None else ""
    second_key = second_event.metadata.get("choice_key") if second_event is not None else ""
    checks = _checks(
        {
            "both_resolved": first.ok and second.ok and first_event is not None and second_event is not None,
            "different_actions_have_distinct_event_ids": bool(first_event and second_event)
            and first_event.event_id != second_event.event_id,
            "different_actions_have_distinct_choice_keys": bool(first_key and second_key) and first_key != second_key,
            "identity_contains_actor_action_task_hit": bool(first_event)
            and all(
                key in first_event.metadata.get("decision_identity", {})
                for key in ("actor_id", "action_id", "task_id", "hit_index")
            ),
        }
    )
    return {
        "checks": checks,
        "first": first.to_json(),
        "second": second.to_json(),
    }, first_event


def _real_damage_multi_hit_identity_case() -> dict[str, Any]:
    state = _base_state()
    definition = _trust_rulebook().action_definition("validation:normal", 1)
    if definition is None:
        return {"checks": _checks({"action_definition_present": False})}

    def calculate(hit_index: int, *, choices: dict[str, Any] | None = None, mode: str = "deterministic_seed"):
        return DirectDamageFormula().calculate(
            DamageFormulaInput(
                state=state,
                attacker_id="ally:actor",
                target_id="enemy:target",
                action_definition=definition,
                attack_type="Normal",
                element_type="Fire",
                scaling_ratio=1.0,
                scaling_basis={"kind": "fixed", "value": 100.0},
                source_trace=definition.source.to_json(),
                rng_choices=choices or {},
                rng_mode=mode,
                decision_identity={
                    "task_id": "validation:damage_task",
                    "phase_id": "validation:damage_phase",
                    "hit_index": hit_index,
                    "derived_event_id": f"validation:damage_hit:{hit_index}",
                },
            )
        )

    first = calculate(0)
    second = calculate(1)
    first_event = first.rng_events[0]
    second_event = second.rng_events[0]
    forced_first = calculate(0, choices={first_event.event_id: "crit"}, mode="explicit")
    forced_second = calculate(1, choices={second_event.event_id: "noncrit"}, mode="explicit")
    first_key = str(first_event.result.get("choice_key") or "") if isinstance(first_event.result, dict) else ""
    second_key = str(second_event.result.get("choice_key") or "") if isinstance(second_event.result, dict) else ""
    checks = _checks(
        {
            "event_ids_distinct": first_event.event_id != second_event.event_id,
            "choice_keys_distinct": bool(first_key) and bool(second_key) and first_key != second_key,
            "event_id_selects_first_hit": forced_first.crit_resolution.is_crit,
            "event_id_selects_second_hit": not forced_second.crit_resolution.is_crit,
            "identity_contains_hit_task_phase": all(
                isinstance(event.metadata.get("decision_identity"), dict)
                and event.metadata["decision_identity"].get("task_id") == "validation:damage_task"
                and event.metadata["decision_identity"].get("phase_id") == "validation:damage_phase"
                and event.metadata["decision_identity"].get("hit_index") == index
                for index, event in enumerate((first_event, second_event))
            ),
        }
    )
    return {
        "checks": checks,
        "events": [first_event.to_json(), second_event.to_json()],
        "forced_outcomes": [forced_first.crit_resolution.to_json(), forced_second.crit_resolution.to_json()],
    }


def _executor_initial_target_ledger_case(event: Any) -> dict[str, Any]:
    if event is None:
        return {"checks": _checks({"target_fixture_event_present": False})}
    rules = _trust_rulebook()
    state = _base_state()
    state = replace(
        state,
        global_flags={
            **state.global_flags,
            "turn_owner_id": "ally:actor",
            "current_window": "turn_active",
            "combat_phase": "awaiting_decision",
        },
    )
    executor = CombatExecutor(rules)
    delegate = executor.targets

    class _TargetResultWithInitialRNG:
        def resolve_action_targets(self, *args, **kwargs):
            result = delegate.resolve_action_targets(*args, **kwargs)
            return replace(result, rng_events=(event,))

    executor.targets = _TargetResultWithInitialRNG()
    _, transition = executor.execute(
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:normal",
            action_level=1,
            target_ids=("enemy:target",),
        ),
        state,
    )
    published_ids = [item.event_id for item in transition.rng_events]
    ledger_record = next(
        (
            record
            for record in (transition.transaction.settlement.records if transition.transaction.settlement else ())
            if record.get("record_type") == "rng_choice_ledger"
        ),
        {},
    )
    ledger = ledger_record.get("payload") if isinstance(ledger_record.get("payload"), dict) else {}
    checks = _checks(
        {
            "initial_target_event_published": event.event_id in published_ids,
            "initial_target_choice_consumed": event.metadata.get("choice_key") in ledger.get("consumed_keys", []),
        }
    )
    return {
        "checks": checks,
        "initial_event": event.to_json(),
        "published_event_ids": published_ids,
        "ledger": ledger,
        "outcome": transition.outcome.to_json(),
    }


def _distinct_case(first: RNGRequest, second: RNGRequest) -> dict[str, Any]:
    first_result = _resolve(first, "success")
    second_result = _resolve(second, "success")
    events = tuple(result.event for result in (first_result, second_result) if result.event is not None)
    payload = {
        "rng_mode": "explicit",
        "rng_choices": {first.choice_key: "success", second.choice_key: "success"},
    }
    ledger = validate_rng_choice_ledger(payload, events)
    checks = _checks(
        {
            "choice_keys_distinct": first.choice_key != second.choice_key,
            "event_ids_distinct": first.event_id != second.event_id,
            "both_resolved": first_result.ok and second_result.ok,
            "ledger_exact": ledger.ok,
            "identities_serialized": all(
                isinstance(event.metadata.get("decision_identity"), dict) for event in events
            ),
        }
    )
    return {"checks": checks, "requests": [first.to_json(), second.to_json()], "ledger": ledger.to_json()}


def _single_resolution_case(request: RNGRequest) -> dict[str, Any]:
    resolution = _resolve(request, "success")
    event = resolution.event
    ledger = validate_rng_choice_ledger(
        {"rng_mode": "explicit", "rng_choices": {request.choice_key: "success"}},
        (event,) if event else (),
    )
    checks = _checks(
        {
            "resolved": resolution.ok and event is not None,
            "exact_key_consumed": ledger.ok,
            "identity_round_trip": bool(event)
            and event.metadata.get("decision_identity") == request.identity,
        }
    )
    return {"checks": checks, "request": request.to_json(), "event": event.to_json() if event else None}


def _missing_case(request: RNGRequest) -> dict[str, Any]:
    deterministic = resolve_rng_request(request, rng_mode="deterministic_seed")
    event = deterministic.event
    ledger = validate_rng_choice_ledger(
        {"rng_mode": "explicit", "rng_choices": {}},
        (event,) if event else (),
    )
    explicit_resolution = resolve_rng_request(request, rng_mode="explicit", rng_choices={})
    return {
        "checks": _checks(
            {
                "resolution_blocked": not explicit_resolution.ok,
                "structured_reason": explicit_resolution.blocked_reason == "requires_rng_choice",
                "ledger_missing": not ledger.ok and ledger.missing_keys == (request.choice_key,),
            }
        ),
        "ledger": ledger.to_json(),
    }


def _extra_case(request: RNGRequest) -> dict[str, Any]:
    resolution = _resolve(request, "success")
    ledger = validate_rng_choice_ledger(
        {
            "rng_mode": "explicit",
            "rng_choices": {request.choice_key: "success", "rng:extra": "success"},
        },
        (resolution.event,) if resolution.event else (),
    )
    return {
        "checks": _checks({"blocked": not ledger.ok, "extra_detected": ledger.extra_keys == ("rng:extra",)}),
        "ledger": ledger.to_json(),
    }


def _duplicate_provided_case(request: RNGRequest) -> dict[str, Any]:
    resolution = _resolve(request, "success")
    ledger = validate_rng_choice_ledger(
        {
            "rng_mode": "explicit",
            "rng_choice_ledger": [
                {"choice_key": request.choice_key, "choice": "success"},
                {"choice_key": request.choice_key, "choice": "fail"},
            ],
        },
        (resolution.event,) if resolution.event else (),
    )
    return {
        "checks": _checks(
            {
                "blocked": not ledger.ok,
                "duplicate_key_detected": ledger.duplicate_provided_keys == (request.choice_key,),
            }
        ),
        "ledger": ledger.to_json(),
    }


def _duplicate_consumed_case(request: RNGRequest) -> dict[str, Any]:
    resolution = _resolve(request, "success")
    assert resolution.event is not None
    ledger = validate_rng_choice_ledger(
        {"rng_mode": "explicit", "rng_choices": {request.choice_key: "success"}},
        (resolution.event, resolution.event),
    )
    return {
        "checks": _checks(
            {
                "blocked": not ledger.ok,
                "identity_collision_detected": ledger.duplicate_consumed_keys == (request.choice_key,),
            }
        ),
        "ledger": ledger.to_json(),
    }


def _wrong_key_case(request: RNGRequest) -> dict[str, Any]:
    broad = resolve_rng_request(request, rng_mode="explicit", rng_choices={request.rng_type: "success"})
    default = resolve_rng_request(request, rng_mode="explicit", rng_choices={"default": "success"})
    wrong = resolve_rng_request(request, rng_mode="explicit", rng_choices={"rng:wrong": "success"})
    return {
        "checks": _checks(
            {
                "rng_type_not_accepted": not broad.ok,
                "default_not_accepted": not default.ok,
                "wrong_key_not_accepted": not wrong.ok,
            }
        ),
        "reasons": [broad.blocked_reason, default.blocked_reason, wrong.blocked_reason],
    }


def _deterministic_case(request: RNGRequest) -> dict[str, Any]:
    first = resolve_rng_request(request, rng_mode="deterministic_seed")
    second = resolve_rng_request(request, rng_mode="deterministic_seed")
    checks = _checks(
        {
            "both_resolved": first.ok and second.ok,
            "same_event": first.event is not None
            and second.event is not None
            and first.event.to_json() == second.event.to_json(),
            "same_outcome": first.selected_outcome_id == second.selected_outcome_id,
            "same_roll": first.roll == second.roll,
        }
    )
    return {"checks": checks, "event": first.event.to_json() if first.event else None}


def _incomplete_identity_case() -> dict[str, Any]:
    request = RNGRequest(
        rng_type="crit",
        purpose="crit",
        event_id="rng:incomplete",
        choice_key="rng:incomplete",
        source="validation",
        before_state="seed",
        decision_kind="probability",
        outcomes=_outcomes(),
    )
    result = resolve_rng_request(request, rng_mode="deterministic_seed")
    return {
        "checks": _checks(
            {
                "blocked": not result.ok,
                "reason": result.blocked_reason == "rng_decision_identity_incomplete",
            }
        )
    }


def _resolve(request: RNGRequest, outcome: str):
    return resolve_rng_request(
        request,
        rng_mode="explicit",
        rng_choices={request.choice_key: outcome},
    )


def _request(rng_type: str, identity: dict[str, Any]) -> RNGRequest:
    choice_key = choice_key_for_identity(rng_type, identity)
    return RNGRequest(
        rng_type=rng_type,
        purpose=str(identity["decision_scope"]),
        event_id=f"event:{choice_key}",
        choice_key=choice_key,
        source="validation",
        before_state="seed:p7_s15",
        decision_kind="probability",
        outcomes=_outcomes(),
        source_trace={"kind": "kernel_invariant_fixture"},
        identity=identity,
    )


def _identity(scope: str, *, hit_index: int, target_id: str) -> dict[str, Any]:
    return {
        "decision_scope": scope,
        "decision_index": hit_index,
        "action_id": "action:validation",
        "task_id": "task:damage",
        "phase_id": "phase:damage",
        "hit_index": hit_index,
        "target_id": target_id,
        "derived_event_id": f"hit:{hit_index}:{target_id}",
    }


def _outcomes() -> tuple[RNGOutcome, ...]:
    return (
        RNGOutcome("success", {"success": True}, probability=0.5),
        RNGOutcome("fail", {"success": False}, probability=0.5),
    )


def _checks(values: dict[str, bool]) -> dict[str, Any]:
    return {"ok": all(values.values()), **values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S15 RNG identity and exact ledger replay.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['summary']['row_count']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
