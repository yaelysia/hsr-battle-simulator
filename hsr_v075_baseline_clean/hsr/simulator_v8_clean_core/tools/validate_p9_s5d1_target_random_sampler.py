from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import BattleState, RNGEvent, UnitState
from ..ir_types import IRSource
from ..rules.expression_ir import numeric_fixed
from ..rules.ir import ConditionIR, TargetExpressionIR, TargetExpressionNodeIR
from ..systems.target import TargetSystem
from ..systems.target_random import (
    TargetRandomPlan,
    TargetRandomSampler,
    replay_target_random,
)
from ..systems.unit_relation import TargetEvaluationContext
from ..tbgd.character_ability_scope import build_character_ability_raw_snapshot
from ..tbgd.lowering import TBGDLowering
from ..tbgd.target_source import build_target_source_projection


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
CORE = Path(__file__).resolve().parents[1]


def _write(path: Path, value: object) -> int:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return len(encoded)


def _expect_error(callback: Any) -> bool:
    try:
        callback()
    except (TypeError, ValueError):
        return True
    return False


def _plan(
    *,
    mode: str = "shuffle",
    candidates: tuple[str, ...] = ("unit:c", "unit:a", "unit:b"),
    count: int | None = None,
    context: Mapping[str, Any] | None = None,
    invocation: str = "invocation:one",
    source_identity: str = "validation:target_random",
) -> TargetRandomPlan:
    requested = len(candidates) if count is None else count
    if mode == "single":
        requested = 1
    return TargetRandomPlan(
        mode=mode,  # type: ignore[arg-type]
        source_kind="validation_fixture",
        source_identity=source_identity,
        source_trace={},
        evaluation_context=dict(context or {"actor_id": "unit:actor", "event_index": 4}),
        invocation_identity=invocation,
        candidate_ids=candidates,
        requested_count=requested,
        before_state="rng:validation",
        event_index=4,
    )


def _pending_choice(result: Any, index: int = 0) -> tuple[str, str]:
    request = result.pending_request.get("rng_request", {})
    if not isinstance(request, Mapping):
        raise AssertionError("pending RNG request is missing")
    outcomes = request.get("outcomes", [])
    if not isinstance(outcomes, list) or not outcomes:
        raise AssertionError("pending RNG outcomes are missing")
    outcome = outcomes[index]
    if not isinstance(outcome, Mapping):
        raise AssertionError("pending RNG outcome is invalid")
    return str(request["choice_key"]), str(outcome["outcome_id"])


def _sampler_matrix() -> dict[str, Any]:
    sampler = TargetRandomSampler()
    single_empty = sampler.resolve(_plan(mode="single", candidates=()))
    single_one = sampler.resolve(_plan(mode="single", candidates=("unit:a",)))
    single_many = sampler.resolve(_plan(mode="single"))
    sample_empty = sampler.resolve(
        _plan(mode="sample_without_replacement", candidates=(), count=5)
    )
    sample_clamped = sampler.resolve(
        _plan(mode="sample_without_replacement", count=9)
    )
    shuffle_empty = sampler.resolve(_plan(candidates=()))
    shuffle_one = sampler.resolve(_plan(candidates=("unit:a",)))
    shuffle_many = sampler.resolve(_plan())
    checks = {
        "single_empty_blocked_without_rng": (
            not single_empty.resolved and not single_empty.rng_events
        ),
        "single_one_is_deterministic": (
            single_one.resolved
            and single_one.selected_ids == ("unit:a",)
            and not single_one.rng_events
        ),
        "single_many_draws_once": single_many.resolved and len(single_many.rng_events) == 1,
        "sample_empty_is_resolved": sample_empty.resolved and not sample_empty.selected_ids,
        "sample_count_clamps": (
            sample_clamped.resolved
            and set(sample_clamped.selected_ids) == {"unit:a", "unit:b", "unit:c"}
            and len(sample_clamped.rng_events) == 2
        ),
        "shuffle_empty_and_single_consume_no_rng": (
            shuffle_empty.resolved
            and shuffle_one.resolved
            and not shuffle_empty.rng_events
            and not shuffle_one.rng_events
        ),
        "shuffle_is_full_permutation": (
            shuffle_many.resolved
            and len(shuffle_many.selected_ids) == 3
            and set(shuffle_many.selected_ids) == {"unit:a", "unit:b", "unit:c"}
            and len(shuffle_many.rng_events) == 2
        ),
    }
    return {
        "checks": checks,
        "samples": {
            "single": single_many.to_json(),
            "sample": sample_clamped.to_json(),
            "shuffle": shuffle_many.to_json(),
        },
    }


def _explicit_and_identity_matrix() -> dict[str, Any]:
    sampler = TargetRandomSampler()
    plan = _plan()
    first = sampler.resolve(plan, rng_mode="explicit", rng_choices={})
    first_key, first_choice = _pending_choice(first)
    second = sampler.resolve(
        plan, rng_mode="explicit", rng_choices={first_key: first_choice}
    )
    second_key, second_choice = _pending_choice(second)
    completed = sampler.resolve(
        plan,
        rng_mode="explicit",
        rng_choices={first_key: first_choice, second_key: second_choice},
    )
    mutations = {
        "candidate": _plan(candidates=("unit:a", "unit:b", "unit:d")),
        "context": _plan(context={"actor_id": "unit:other", "event_index": 4}),
        "invocation": _plan(invocation="invocation:two"),
        "source": _plan(source_identity="validation:other_source"),
    }
    changed_keys = {}
    stale_rejections = {}
    for name, changed in mutations.items():
        pending = sampler.resolve(changed, rng_mode="explicit", rng_choices={})
        changed_key, _choice = _pending_choice(pending)
        changed_keys[name] = changed_key != first_key
        stale = sampler.resolve(
            changed, rng_mode="explicit", rng_choices={first_key: first_choice}
        )
        stale_rejections[name] = (
            not stale.resolved
            and stale.blocked_reason == "requires_rng_choice"
            and _pending_choice(stale)[0] == changed_key
        )
    checks = {
        "first_missing_choice_has_no_event": not first.resolved and not first.rng_events,
        "partial_resolution_has_no_event": not second.resolved and not second.rng_events,
        "remaining_pool_changes_next_key": first_key != second_key,
        "all_choices_resolve_atomically": completed.resolved and len(completed.rng_events) == 2,
        "identity_dimensions_change_key": all(changed_keys.values()),
        "stale_choices_are_rejected": all(stale_rejections.values()),
    }
    return {
        "checks": checks,
        "first_key": first_key,
        "second_key": second_key,
        "changed_keys": changed_keys,
        "stale_rejections": stale_rejections,
        "completed": completed.to_json(),
    }


def _constructor_matrix() -> dict[str, Any]:
    mutable_source: dict[str, Any] = {}
    mutable_context: dict[str, Any] = {"actor_id": "unit:a"}
    isolated = TargetRandomPlan(
        mode="single",
        source_kind="validation_fixture",
        source_identity="validation:isolation",
        source_trace=mutable_source,
        evaluation_context=mutable_context,
        invocation_identity="invocation:isolation",
        candidate_ids=("unit:b",),
        requested_count=1,
        before_state="rng:0",
        event_index=0,
    )
    before = isolated.to_json()
    mutable_source["forged"] = True
    mutable_context["forged"] = True
    event = TargetRandomSampler().resolve(_plan(mode="single")).rng_events[0]
    cases = {
        "duplicate_candidates_rejected": _expect_error(
            lambda: _plan(candidates=("unit:a", "unit:a"))
        ),
        "bool_count_rejected": _expect_error(
            lambda: _plan(mode="sample_without_replacement", count=True)  # type: ignore[arg-type]
        ),
        "negative_count_rejected": _expect_error(
            lambda: _plan(mode="sample_without_replacement", count=-1)
        ),
        "shuffle_count_mismatch_rejected": _expect_error(
            lambda: _plan(mode="shuffle", count=1)
        ),
        "unknown_mode_rejected": _expect_error(lambda: _plan(mode="unknown")),
        "input_mutation_isolated": before == isolated.to_json(),
        "result_event_recursively_immutable": _expect_error(
            lambda: event.metadata.__setitem__("forged", True)
        ),
    }
    return {"checks": cases}


def _replay_matrix() -> dict[str, Any]:
    plan = _plan()
    resolved = TargetRandomSampler().resolve(plan)
    replay = replay_target_random(plan, resolved.rng_events)
    first = resolved.rng_events[0]
    tampered_result = dict(first.result) if isinstance(first.result, dict) else {}
    tampered_result["selected_target_id"] = "unit:forged"
    tampered = replace(first, result=tampered_result)
    tampered_replay = replay_target_random(plan, (tampered, *resolved.rng_events[1:]))
    reversed_replay = replay_target_random(plan, tuple(reversed(resolved.rng_events)))
    return {
        "checks": {
            "deterministic_replay_exact": replay.ok,
            "payload_tampering_rejected": not tampered_replay.ok,
            "draw_order_tampering_rejected": not reversed_replay.ok,
        },
        "event_count": len(resolved.rng_events),
    }


def _source(path: str, raw_id: str, json_path: str) -> IRSource:
    return IRSource(path, "ValidationTargetExpression", raw_id, {"json_path": json_path})


def _expression_fixtures() -> tuple[TargetExpressionIR, TargetExpressionIR]:
    path = "validation/p9_s5d1_target_random"
    shuffle_root_source = _source(path, "shuffle", "$")
    fetch = TargetExpressionNodeIR.build(
        "TargetFetchTeamEntity",
        _source(path, "shuffle:fetch", "$.Sequence[0]"),
        {"team_type": "TeamDark"},
    )
    shuffle = TargetExpressionNodeIR.build(
        "TargetShuffle",
        _source(path, "shuffle:shuffle", "$.Sequence[1]"),
        {},
    )
    shuffle_root = TargetExpressionNodeIR.build(
        "TargetSequence", shuffle_root_source, {"children": (fetch, shuffle)}
    )
    shuffle_expression = TargetExpressionIR(
        "validation:shuffle",
        "TargetSequence",
        "",
        shuffle_root_source,
        shuffle_root,
        "executable",
        "",
        "p9_s5d1_validation_fixture",
    )

    retarget_source = _source(path, "retarget", "$")
    retarget_fetch = TargetExpressionNodeIR.build(
        "TargetFetchTeamEntity",
        _source(path, "retarget:fetch", "$.TargetType"),
        {"team_type": "TeamDark"},
    )
    retarget_root = TargetExpressionNodeIR.build(
        "Retarget",
        retarget_source,
        {
            "target": retarget_fetch,
            "predicate": None,
            "by_random": True,
            "max_number_expr": numeric_fixed(2),
            "include_limbo": False,
        },
    )
    retarget_expression = TargetExpressionIR(
        "validation:retarget",
        "Retarget",
        "",
        retarget_source,
        retarget_root,
        "executable",
        "",
        "p9_s5d1_validation_fixture",
    )
    return shuffle_expression, retarget_expression


def _expression_matrix() -> dict[str, Any]:
    state = BattleState(
        units={
            "ally:actor": UnitState("ally:actor", "ally", "validation:actor"),
            "enemy:a": UnitState("enemy:a", "enemy", "validation:enemy"),
            "enemy:b": UnitState("enemy:b", "enemy", "validation:enemy"),
            "enemy:c": UnitState("enemy:c", "enemy", "validation:enemy"),
        },
        rng_state="rng:p9_s5d1",
    )
    context = TargetEvaluationContext(caster_id="ally:actor", effect_owner_id="ally:actor")
    shuffle_expression, retarget_expression = _expression_fixtures()
    system = TargetSystem()
    shuffle = system.resolve_target_expression(state, shuffle_expression, context=context)
    retarget = system.resolve_target_expression(state, retarget_expression, context=context)
    return {
        "checks": {
            "shuffle_runtime_returns_full_permutation": (
                shuffle.resolved
                and set(shuffle.target_ids) == {"enemy:a", "enemy:b", "enemy:c"}
                and len(shuffle.rng_events) == 2
            ),
            "retarget_runtime_applies_random_cap": (
                retarget.resolved
                and len(retarget.target_ids) == 2
                and len(retarget.rng_events) == 2
            ),
            "both_runtime_paths_use_shared_rng_type": all(
                event.rng_type == "target_random"
                for event in (*shuffle.rng_events, *retarget.rng_events)
            ),
        },
        "shuffle": shuffle.to_json(),
        "retarget": retarget.to_json(),
    }


def _walk(value: object) -> tuple[TargetExpressionNodeIR, ...]:
    found: list[TargetExpressionNodeIR] = []
    seen: set[str] = set()

    def visit(item: object) -> None:
        if type(item) is TargetExpressionNodeIR:
            if item.node_id in seen:
                return
            seen.add(item.node_id)
            found.append(item)
            visit(item.payload)
        elif type(item) is ConditionIR:
            visit(item.payload)
        elif isinstance(item, Mapping):
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(found)


def _source_matrix(tbgd_root: Path) -> tuple[dict[str, Any], int]:
    snapshot = build_character_ability_raw_snapshot(tbgd_root)
    full_build_calls = 0
    original = TBGDLowering.build

    def forbidden(_self: TBGDLowering) -> object:
        nonlocal full_build_calls
        full_build_calls += 1
        raise AssertionError("S5D1 invoked full Canonical IR lowering")

    TBGDLowering.build = forbidden
    try:
        catalog = build_target_source_projection(tbgd_root, snapshot=snapshot)
    finally:
        TBGDLowering.build = original
    expressions = [
        record.expression for record in catalog.records if record.expression is not None
    ] + [definition.expression for definition in catalog.language_definitions]
    nodes = {node.node_id: node for expression in expressions for node in _walk(expression.node)}
    retarget_nodes = [
        node for node in nodes.values() if node.expression_kind == "Retarget" and node.by_random
    ]
    shuffle_nodes = [node for node in nodes.values() if node.expression_kind == "TargetShuffle"]
    random_tasks = [
        record for record in catalog.records if record.family == "RandomSelectInTargetList"
    ]
    sampler = TargetRandomSampler()
    source_probes = []
    for node in (*retarget_nodes, *shuffle_nodes):
        mode = "shuffle" if node.expression_kind == "TargetShuffle" else "sample_without_replacement"
        plan = TargetRandomPlan(
            mode=mode,
            source_kind="target_expression",
            source_identity=node.node_id,
            source_trace=node.source.to_json(),
            evaluation_context={"source_probe": True},
            invocation_identity=f"source_probe:{node.node_id}",
            candidate_ids=("candidate:a", "candidate:b"),
            requested_count=2,
            before_state="rng:source_probe",
            event_index=0,
        )
        source_probes.append(sampler.resolve(plan).resolved)
    counts = Counter(
        ["Retarget.ByRandom"] * len(retarget_nodes)
        + ["TargetShuffle"] * len(shuffle_nodes)
        + ["RandomSelectInTargetList"] * len(random_tasks)
    )
    checks = {
        "all_three_real_source_families_present": all(counts[name] > 0 for name in (
            "Retarget.ByRandom", "TargetShuffle", "RandomSelectInTargetList"
        )),
        "all_expression_random_sources_admitted_by_sampler": all(source_probes),
        "random_task_sources_remain_delegated_to_s5d2": all(
            record.responsibility == "s5d_random_target_task"
            and record.coverage_status == "delegated"
            for record in random_tasks
        ),
        "source_catalog_complete": catalog.source_catalog_complete,
        "full_canonical_ir_build_count_zero": full_build_calls == 0,
    }
    representatives = {
        "Retarget.ByRandom": retarget_nodes[0].source.to_json() if retarget_nodes else {},
        "TargetShuffle": shuffle_nodes[0].source.to_json() if shuffle_nodes else {},
        "RandomSelectInTargetList": random_tasks[0].source.to_json() if random_tasks else {},
    }
    return {
        "checks": checks,
        "counts": dict(sorted(counts.items())),
        "representative_sources": representatives,
        "catalog": catalog.summary_json(),
    }, full_build_calls


def _static_audit() -> dict[str, bool]:
    target_text = (CORE / "systems" / "target.py").read_text(encoding="utf-8")
    random_text = (CORE / "systems" / "target_random.py").read_text(encoding="utf-8")
    return {
        "legacy_random_pending_blocker_absent": "random_target_pending_s5d" not in target_text,
        "retarget_and_shuffle_use_shared_sampler": target_text.count("random_sampler.resolve(") >= 2,
        "shared_sampler_has_single_rng_request_constructor": random_text.count("RNGRequest(") == 1,
        "no_character_specific_random_handler": not any(
            token in target_text + random_text for token in ("Bailu", "Xueyi", "Welt", "AvatarID")
        ),
    }


def _run(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    sampler = _sampler_matrix()
    explicit = _explicit_and_identity_matrix()
    constructors = _constructor_matrix()
    replay = _replay_matrix()
    expressions = _expression_matrix()
    source, full_build_calls = _source_matrix(tbgd_root)
    static = _static_audit()
    checks = {
        **sampler["checks"],
        **explicit["checks"],
        **constructors["checks"],
        **replay["checks"],
        **expressions["checks"],
        **source["checks"],
        **static,
    }
    evidence = {
        "sampler": sampler,
        "explicit_and_identity": explicit,
        "constructors": constructors,
        "replay": replay,
        "expressions": expressions,
        "source": source,
        "static_audit": static,
    }
    evidence_bytes = _write(output_dir / "evidence.json", evidence)
    return {
        "stage": "P9-S5D1",
        "ok": all(checks.values()),
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "build_counters": {
            "full_canonical_ir_build_count": full_build_calls,
            "target_source_projection_count": 1,
            "sampler_fixture_world_count": 1,
        },
        "resources": {
            "wall_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "evidence_bytes": evidence_bytes,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = _run(args.tbgd_root.resolve(), args.output_dir)
    _write(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
