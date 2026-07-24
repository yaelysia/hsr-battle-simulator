from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..core.compact_state import CompactSemanticState, CompactStateQuery, _semantic_payload
from ..core.model import BattleState, UnitState
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.summon import SummonSystem
from ..systems.timeline import TimelineSystem
from ..systems.wave import WaveSystem
from .io import write_json
from .validate_p7_s1_transition_trust_contract import _trust_rulebook
from .validate_p7_s11_queue_terminal_progress import _queue_audit_equivalence_case, _queue_rulebook


VALIDATION_VERSION = "p7_s18_compact_semantic_state"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    query = CompactStateQuery()
    base = _rich_state()
    before_snapshot = base.snapshot().to_json()
    compact = query.project(base)
    after_snapshot = base.snapshot().to_json()

    audit_variant = _audit_variant(base)
    audit_compact = query.project(audit_variant)
    equivalence = {
        "same_semantics_different_audit_same_key": compact.semantic_key == audit_compact.semantic_key,
        "audit_snapshot_still_distinct": base.snapshot().to_json() != audit_variant.snapshot().to_json(),
        "audit_materialization_on_demand": query.audit_details(base)["snapshot"] == before_snapshot,
    }
    equivalence["ok"] = all(equivalence.values())
    behavior_equivalence = _behavior_equivalence(base, audit_variant)

    variants: dict[str, Callable[[BattleState], BattleState]] = {
        "unit_hp": lambda state: _replace_unit(state, "ally:actor", hp=87.0),
        "status": lambda state: _replace_unit(state, "ally:actor", statuses=("status:a", "status:b")),
        "shield": lambda state: _replace_unit(
            state,
            "ally:actor",
            shield_instances=(_shield_instance(9.0),),
        ),
        "queue_window": lambda state: replace(
            state,
            queues={**state.queues, "insert": (*state.queues["insert"], {"entry_id": "queue:2", "window": "post_action"})},
        ),
        "timeline": lambda state: _flag(state, "global_av", 13.0),
        "rng_state": lambda state: replace(state, rng_state="seed:changed"),
        "rng_ledger": lambda state: _flag(
            state,
            "rng_choice_ledger",
            [{"choice_key": "choice:crit:1", "outcome_id": "miss", "consumed": True}],
        ),
        "wave": lambda state: replace(state, wave_index=2),
        "summon_relation": lambda state: _flag(
            state,
            "summon_runtime",
            {**state.global_flags["summon_runtime"], "by_owner": {"ally:other": ["summon:1"]}},
        ),
        "decision_phase": lambda state: _flag(state, "combat_phase", "action_execution"),
        "decision_identity": lambda state: _flag(
            state,
            "active_decision",
            {"decision_id": "decision:2", "actor_id": "ally:actor", "state_revision": "revision:1"},
        ),
        "dynamic_value": lambda state: _flag(
            state,
            "dynamic_value_store",
            {"entries": {"dynamic:1": 4.0}, "by_hash": {"1": "dynamic:1"}, "by_name": {"dynamic:1": 4.0}},
        ),
        "attached_ability": lambda state: _replace_unit(
            state,
            "ally:actor",
            flags={
                **state.units["ally:actor"].flags,
                "attached_ability_names": ["ability:semantic-variant"],
            },
        ),
    }
    non_equivalence = {
        name: query.project(change(base)).semantic_key != compact.semantic_key
        for name, change in variants.items()
    }
    non_equivalence["ok"] = all(non_equivalence.values())

    encoded = compact.to_json()
    round_trip = CompactSemanticState.from_json(json.loads(json.dumps(encoded, ensure_ascii=False, sort_keys=True)))
    detached = compact.payload_copy()
    detached["wave_index"] = 999
    immutable_error = ""
    try:
        compact._payload["wave_index"] = 999
    except TypeError as exc:
        immutable_error = str(exc)
    readonly = {
        "query_state_unchanged": before_snapshot == after_snapshot,
        "round_trip_key_stable": round_trip.semantic_key == compact.semantic_key,
        "round_trip_payload_stable": round_trip.payload_copy() == compact.payload_copy(),
        "stored_payload_immutable": immutable_error == "frozen JSON object cannot be mutated",
        "detached_copy_cannot_mutate_view": compact.payload_copy()["wave_index"] == base.wave_index,
    }
    readonly["ok"] = all(readonly.values())

    full_bytes = len(_canonical_bytes(before_snapshot))
    compact_bytes = compact.byte_size
    semantic_source = inspect.getsource(_semantic_payload)
    budget = {
        "full_snapshot_bytes": full_bytes,
        "compact_payload_bytes": compact_bytes,
        "compact_to_full_ratio": round(compact_bytes / full_bytes, 6),
        "bytes_saved": full_bytes - compact_bytes,
        "compact_smaller_than_full": compact_bytes < full_bytes,
        "source_graph_not_copied": "source_trace" not in compact.payload_copy()["global_flags"]
        and "source_trace" not in compact.payload_copy()["units"]["ally:actor"]["flags"],
        "semantic_projection_does_not_hash_snapshot": "snapshot(" not in semantic_source,
    }
    budget["ok"] = budget["compact_smaller_than_full"] and budget["source_graph_not_copied"] and budget[
        "semantic_projection_does_not_hash_snapshot"
    ]

    rows = {
        "semantic_equivalence": equivalence,
        "audit_trim_behavior_equivalence": behavior_equivalence,
        "semantic_non_equivalence": non_equivalence,
        "round_trip_and_readonly": readonly,
        "serialization_budget": budget,
    }
    result = {
        "schema_version": "p7_s18_compact_semantic_state_validation_v1",
        "ok": all(row["ok"] for row in rows.values()),
        "ready_for_review": all(row["ok"] for row in rows.values()),
        "rows": rows,
        "semantic_key": compact.semantic_key,
        "resource_budget": {
            "tbgd_build_count": 0,
            "full_transition_dump_written": False,
            "large_artifacts_written": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s18_compact_semantic_state.json", result)
    write_json(output_dir / "p7_s18_compact_semantic_state_matrix.json", {"rows": rows})
    write_json(
        output_dir / "p7_s18_compact_semantic_state_evidence.json",
        {
            "semantic_key": compact.semantic_key,
            "compact": compact.to_json(),
            "budget": budget,
            "audit_equivalent_key": audit_compact.semantic_key,
        },
    )
    return result


def _rich_state() -> BattleState:
    provenance = {
        "source_path": "ExcelOutput/Validation.json",
        "raw_id": "validation",
        "evidence": {"expanded": "x" * 4096},
    }
    actor = UnitState(
        unit_id="ally:actor",
        side="ally",
        template_id="avatar:validation",
        max_hp=100.0,
        hp=100.0,
        attack=50.0,
        defense=30.0,
        speed=120.0,
        energy=40.0,
        max_energy=100.0,
        toughness=60.0,
        max_toughness=60.0,
        action_value=25.0,
        statuses=("status:a",),
        shield_instances=(_shield_instance(10.0),),
        flags={
            "lifecycle_status": "active",
            "status_details": [{"instance_id": "status:a:1", "modifier_name": "status:a", "remaining": 2}],
            "owner_id": "ally:owner",
            "source_trace": provenance,
        },
        resources={"critical_chance": 0.2, "effect_hit_rate": 0.1},
    )
    enemy = UnitState(
        unit_id="enemy:target",
        side="enemy",
        template_id="monster:validation",
        max_hp=200.0,
        hp=200.0,
        speed=90.0,
        action_value=50.0,
        flags={"lifecycle_status": "active", "wave_member_kind": "stage_wave_enemy", "wave_index": 1},
    )
    summon = UnitState(
        unit_id="summon:1",
        side="summon",
        template_id="servant:validation",
        max_hp=50.0,
        hp=50.0,
        speed=100.0,
        action_value=40.0,
        flags={
            "lifecycle_status": "active",
            "summon_kind": "servant",
            "owner_id": "ally:actor",
            "lifecycle_source": {
                "admission_status": "executable",
                "presence": "field",
                "targetable": True,
                "actionable": True,
                "timeline_admitted": True,
                "source_trace": provenance,
            },
        },
    )
    return BattleState(
        units={unit.unit_id: unit for unit in (actor, enemy, summon)},
        wave_index=1,
        skill_points=3,
        max_skill_points=5,
        global_flags={
            "combat_phase": "awaiting_decision",
            "phase": "scenario",
            "current_window": "ordinary_action",
            "turn_owner_id": "ally:actor",
            "global_av": 12.0,
            "active_turn": {"actor_id": "ally:actor", "turn_sequence_index": 3},
            "active_decision": {
                "decision_id": "decision:1",
                "actor_id": "ally:actor",
                "state_revision": "revision:1",
            },
            "dynamic_value_store": {
                "entries": {"dynamic:1": 3.0},
                "by_hash": {"1": "dynamic:1"},
                "by_name": {"dynamic:1": 3.0},
            },
            "rng_choice_ledger": [{"choice_key": "choice:crit:1", "outcome_id": "hit", "consumed": True}],
            "wave_runtime": {
                "schema_version": "p1_2_wave_runtime_v1",
                "wave_definition_id": "wave:validation",
                "current_wave_index": 1,
                "status": "active",
                "current_wave_unit_ids": ["enemy:target"],
                "source_trace": provenance,
            },
            "summon_runtime": {
                "schema_version": "p3_summon_runtime_v2",
                "by_owner": {"ally:actor": ["summon:1"]},
                "entities": {"summon:1": {"owner_id": "ally:actor", "status": "active"}},
                "source_trace": provenance,
            },
            "pending_events": [{"event_type": "validation.pending", "event_id": "pending:1"}],
            "source_trace": provenance,
            "coverage": {"expanded": "y" * 4096},
            "settlement": {"records": [{"trace": provenance}]},
        },
        queues={
            "insert": (
                {
                    "entry_id": "queue:1",
                    "window": "pre_action",
                    "actor_id": "ally:actor",
                    "action_id": "action:validation",
                    "source_trace": provenance,
                },
            )
        },
        rng_state="seed:validation",
        event_index=7,
    )


def _audit_variant(state: BattleState) -> BattleState:
    flags = dict(state.global_flags)
    flags["source_trace"] = {"source_path": "expanded/other.json", "evidence": {"expanded": "z" * 8192}}
    flags["coverage"] = {"different": True}
    units = dict(state.units)
    actor = units["ally:actor"]
    units["ally:actor"] = replace(
        actor,
        flags={**actor.flags, "source_trace": {"source_path": "other", "evidence": {"line": 99}}},
    )
    summon = units["summon:1"]
    lifecycle_source = dict(summon.flags["lifecycle_source"])
    lifecycle_source["source_trace"] = {"source_path": "expanded/summon_other.json"}
    units["summon:1"] = replace(
        summon,
        flags={**summon.flags, "lifecycle_source": lifecycle_source},
    )
    flags["wave_runtime"] = {
        **flags["wave_runtime"],
        "source_trace": {"source_path": "expanded/wave_other.json"},
    }
    flags["summon_runtime"] = {
        **flags["summon_runtime"],
        "source_trace": {"source_path": "expanded/summon_runtime_other.json"},
    }
    return replace(state, units=units, global_flags=flags)


def _behavior_equivalence(base: BattleState, audit_variant: BattleState) -> dict[str, Any]:
    rules = _trust_rulebook()
    rule, reason = rules.select_timeline_rule()
    if rule is None:
        return {"ok": False, "blocked_reason": reason}
    timeline_base = TimelineSystem().plan_next_actor(base, rule)
    timeline_variant = TimelineSystem().plan_next_actor(audit_variant, rule)
    remove_admission = {"admission_status": "executable", "operation": "explicit_remove"}
    summon_base = SummonSystem(rules).plan_remove(
        base,
        "summon:1",
        "validation explicit remove",
        admission=remove_admission,
    )
    summon_variant = SummonSystem(rules).plan_remove(
        audit_variant,
        "summon:1",
        "validation explicit remove",
        admission=remove_admission,
    )
    wave_base = WaveSystem(rules).plan_transition(base)
    wave_variant = WaveSystem(rules).plan_transition(audit_variant)
    availability_base = ActionAvailabilitySystem(rules).view(base)
    availability_variant = ActionAvailabilitySystem(rules).view(audit_variant)
    queue_equivalence = _queue_audit_equivalence_case(_queue_rulebook())
    timeline_same = (
        timeline_base.ok,
        timeline_base.actor_id,
        timeline_base.advance_delta,
        timeline_base.blocked_reason,
        timeline_base.tied_actor_ids,
    ) == (
        timeline_variant.ok,
        timeline_variant.actor_id,
        timeline_variant.advance_delta,
        timeline_variant.blocked_reason,
        timeline_variant.tied_actor_ids,
    )
    summon_same = (
        summon_base.ok,
        summon_base.operation,
        summon_base.unit_ids,
        summon_base.blocked_reason,
    ) == (
        summon_variant.ok,
        summon_variant.operation,
        summon_variant.unit_ids,
        summon_variant.blocked_reason,
    )
    wave_same = (
        wave_base.status,
        wave_base.blocked_reason,
        wave_base.current_wave_index,
        wave_base.next_wave_index,
    ) == (
        wave_variant.status,
        wave_variant.blocked_reason,
        wave_variant.current_wave_index,
        wave_variant.next_wave_index,
    )
    availability_same = (
        availability_base.mode,
        availability_base.ordinary_input_blocked_reason,
        tuple((choice.actor_id, choice.action_id, choice.action_level) for choice in availability_base.choices),
    ) == (
        availability_variant.mode,
        availability_variant.ordinary_input_blocked_reason,
        tuple((choice.actor_id, choice.action_id, choice.action_level) for choice in availability_variant.choices),
    )
    checks = {
        "compact_keys_equal": CompactStateQuery().project(base).semantic_key
        == CompactStateQuery().project(audit_variant).semantic_key,
        "timeline_behavior_equal": timeline_same,
        "summon_behavior_equal": summon_same,
        "wave_behavior_equal": wave_same,
        "action_query_behavior_equal": availability_same,
        "queue_behavior_equal": queue_equivalence["ok"],
    }
    return {
        **checks,
        "ok": all(checks.values()),
        "timeline": [timeline_base.to_json(), timeline_variant.to_json()],
        "summon": [summon_base.to_json(), summon_variant.to_json()],
        "wave": [wave_base.to_json(), wave_variant.to_json()],
        "queue": queue_equivalence,
    }


def _replace_unit(state: BattleState, unit_id: str, **changes: Any) -> BattleState:
    return replace(state, units={**state.units, unit_id: replace(state.units[unit_id], **changes)})


def _flag(state: BattleState, key: str, value: Any) -> BattleState:
    return replace(state, global_flags={**state.global_flags, key: value})


def _shield_instance(remaining: float) -> dict[str, Any]:
    return {
        "instance_id": "shield:1:source:ally:actor:actor:ally:actor",
        "shield_id": "shield:1",
        "source_id": "ally:actor",
        "source_actor_id": "ally:actor",
        "source_kind": "status",
        "remaining": remaining,
        "capacity": 10.0,
        "priority": 1,
        "stack_policy": "replace",
        "absorb_families": ["direct", "dot", "break", "super_break", "true"],
        "created_event_index": 1,
        "source_trace": {"source_path": "validation"},
        "priority_audit": {"kind": "explicit", "value": 1},
        "priority_rule": {
            "shield_priority_rule_id": "shield_priority_rule:engine_convention:priority_then_creation_order_v1",
            "registry_version": "hsr_v8_engine_rules_v1",
        },
        "owner_modifier_name": "modifier:validation-shield",
        "status_instance_id": "status:validation-shield",
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S18 compact semantic state query.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={len(result['rows'])} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
