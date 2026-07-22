from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.engine_rule_registry import (
    ENGINE_RULE_REGISTRY_VERSION,
    HP_LOSS_ROUTE_FAMILIES,
    NORMAL_DAMAGE_ROUTE_FAMILIES,
    SHIELD_PRIORITY_RULE_ID,
    build_engine_rule_registry,
)
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSourceFrame, DamageSystem
from ..systems.shield import ShieldSystem, aggregate_shield
from .io import write_json


VALIDATION_VERSION = "p7_s13_shield_hp_routing"


def run_validation(output_dir: Path) -> dict[str, Any]:
    cases = {
        "full_absorption": _absorption_case(50.0, 30.0),
        "partial_absorption": _absorption_case(20.0, 50.0),
        "multi_shield_priority": _multi_shield_case(),
        "opcode_policy": _opcode_policy_case(),
        "shield_exhaustion_event": _exhaustion_case(),
        "same_effect_different_casters": _cross_caster_identity_case(),
        "hp_loss_bypass": _hp_loss_bypass_case(),
        "legacy_aggregate_blocked": _legacy_aggregate_case(),
        "explicit_bypass_source_required": _missing_route_source_case(),
        "forged_route_rule_blocked": _forged_route_rule_case(),
        "forged_priority_rule_blocked": _forged_priority_rule_case(),
        "versioned_route_registry": _versioned_route_registry_case(),
        "missing_canonical_route_blocked": _missing_canonical_route_case(),
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
        "resource_budget": {
            "tbgd_lowering_build_count": 0,
            "rulebook_build_count": 0,
            "full_transition_dump_written": False,
            "fixture_kind": "kernel_invariant_fixture",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s13_shield_hp_routing.json", result)
    write_json(output_dir / "p7_s13_shield_hp_routing_matrix.json", {"rows": rows})
    write_json(output_dir / "p7_s13_shield_hp_routing_evidence.json", cases)
    return result


def _absorption_case(shield: float, damage: float) -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "a", shield, priority=0)
    result = DamageSystem().apply_packet(state, _damage_packet(damage))
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    after = reduction.after_state.units["enemy:target"]
    expected_absorbed = min(shield, damage)
    expected_hp = 100.0 - max(0.0, damage - shield)
    checks = _checks(
        {
            "damage_result_ok": result.ok,
            "reducer_ok": reduction.ok,
            "shield_reduced_first": aggregate_shield(after.shield_instances) == max(0.0, shield - damage),
            "hp_only_receives_remainder": after.hp == expected_hp,
            "absorption_record_present": any(record.get("record_type") == "shield_absorption" for record in result.records),
            "route_amounts_match": _route_amount(result.records, "absorbed_damage") == expected_absorbed,
        }
    )
    return {"checks": checks, "after": after.to_snapshot(), "mutations": [item.to_json() for item in result.mutations]}


def _multi_shield_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "low", 30.0, priority=0)
    state, _ = _apply_shield(state, "high", 10.0, priority=10)
    result = DamageSystem().apply_packet(state, _damage_packet(15.0))
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    after = reduction.after_state.units["enemy:target"]
    by_id = {str(item["shield_id"]): float(item["remaining"]) for item in after.shield_instances}
    consumed = _route_value(result.records, "consumed_instances")
    checks = _checks(
        {
            "damage_result_ok": result.ok,
            "reducer_ok": reduction.ok,
            "high_priority_consumed_first": isinstance(consumed, list)
            and bool(consumed)
            and consumed[0].get("shield_id") == "validation:high",
            "high_priority_exhausted": "validation:high" not in by_id,
            "remainder_consumed_from_low": by_id.get("validation:low") == 25.0,
            "hp_unchanged": after.hp == 100.0,
        }
    )
    return {"checks": checks, "instances": list(after.shield_instances), "consumed": consumed}


def _opcode_policy_case() -> dict[str, Any]:
    state = _state()
    state, init = _apply_shield(state, "same", 20.0, opcode="InitShield")
    state, replace_result = _apply_shield(state, "same", 10.0, opcode="InitShield")
    after_replace = aggregate_shield(state.units["enemy:target"].shield_instances)
    state, stack_result = _apply_shield(state, "same", 5.0, opcode="StackShield")
    after_stack = aggregate_shield(state.units["enemy:target"].shield_instances)
    modify = ShieldSystem().apply_effect(
        state,
        target_id="enemy:target",
        shield_id="validation:same",
        source_id="same",
        source_kind="validation",
        opcode="ModifyShield",
        amount=-15.0,
        source_trace=_source("same"),
        actor_id="ally:actor",
        event_source_id="validation:shield",
    )
    reduction = MutationReducer().apply_all_result(state, (modify.mutation,) if modify.mutation else ())
    checks = _checks(
        {
            "init_ok": init.ok,
            "same_source_init_replaces": replace_result.ok and after_replace == 10.0,
            "stack_opcode_adds_same_source": stack_result.ok and after_stack == 15.0,
            "modify_can_remove_instance": modify.ok
            and reduction.ok
            and not reduction.after_state.units["enemy:target"].shield_instances,
            "policies_are_structured": all(
                result.mutation is not None and bool(result.mutation.metadata.get("stack_policy"))
                for result in (init, replace_result, stack_result, modify)
            ),
        }
    )
    return {"checks": checks, "after_replace": after_replace, "after_stack": after_stack}


def _exhaustion_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "exhaust", 10.0)
    result = DamageSystem().apply_packet(state, _damage_packet(10.0))
    exhaustion = [event for event in result.events if event.event_type == "shield.exhausted"]
    shield_mutation = next((item for item in result.mutations if item.path[-1] == "shield_instances"), None)
    checks = _checks(
        {
            "exhaustion_event_present": len(exhaustion) == 1,
            "event_is_mutation_backed": bool(exhaustion)
            and shield_mutation is not None
            and exhaustion[0].payload.get("mutation_id") == shield_mutation.stable_id(),
            "exhausted_identity_preserved": bool(exhaustion)
            and exhaustion[0].payload.get("exhausted_instance_ids")
            == ["validation:exhaust:source:exhaust:actor:ally:actor"],
        }
    )
    return {"checks": checks, "events": [event.to_json() for event in result.events]}


def _cross_caster_identity_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "shared_effect", 30.0, actor_id="ally:actor")
    state, _ = _apply_shield(state, "shared_effect", 40.0, actor_id="ally:second")
    instances = state.units["enemy:target"].shield_instances
    actor_ids = {str(item.get("source_actor_id") or "") for item in instances}
    instance_ids = {str(item.get("instance_id") or "") for item in instances}
    checks = _checks(
        {
            "same_rule_identity_keeps_two_instances": len(instances) == 2,
            "source_actor_identity_preserved": actor_ids == {"ally:actor", "ally:second"},
            "instance_identity_unique": len(instance_ids) == 2 and all(instance_ids),
            "aggregate_keeps_both_sources": aggregate_shield(instances) == 70.0,
        }
    )
    return {"checks": checks, "instances": list(instances)}


def _hp_loss_bypass_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "bypass", 50.0)
    packet = replace(
        _damage_packet(30.0),
        damage_formula_family="hp_loss",
        damage_kind="hp_loss",
    )
    result = DamageSystem().apply_packet(state, packet)
    reduction = MutationReducer().apply_all_result(state, result.mutations)
    after = reduction.after_state.units["enemy:target"]
    checks = _checks(
        {
            "damage_result_ok": result.ok,
            "hp_loss_reaches_hp": after.hp == 70.0,
            "shield_unchanged": aggregate_shield(after.shield_instances) == 50.0,
            "no_shield_mutation": all(item.path[-1] != "shield_instances" for item in result.mutations),
            "route_has_engine_source": _route_value(result.records, "hp_route") is None
            and any(record.get("payload", {}).get("damage_formula_family") == "hp_loss" for record in result.records),
        }
    )
    return {"checks": checks, "records": list(result.records)}


def _legacy_aggregate_case() -> dict[str, Any]:
    base = _state()
    target = replace(base.units["enemy:target"], resources={"shield": 50.0})
    state = replace(base, units={**base.units, target.unit_id: target})
    result = DamageSystem().apply_packet(state, _damage_packet(10.0))
    checks = _checks(
        {
            "blocked": not result.ok,
            "reason_structured": "aggregate_shield_without_source_instances" in result.errors,
            "no_mutations": not result.mutations,
            "state_unchanged": state.units["enemy:target"].hp == 100.0,
        }
    )
    return {"checks": checks, "errors": list(result.errors)}


def _missing_route_source_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "explicit", 50.0)
    packet = replace(_damage_packet(10.0), metadata={"shield_route": "bypass"})
    result = DamageSystem().apply_packet(state, packet)
    checks = _checks(
        {
            "blocked": not result.ok,
            "runtime_override_rejected": "damage_route_runtime_override_not_admitted" in result.errors,
            "no_mutations": not result.mutations,
        }
    )
    return {"checks": checks, "errors": list(result.errors)}


def _forged_route_rule_case() -> dict[str, Any]:
    state = _state()
    state, _ = _apply_shield(state, "forged_route", 25.0)
    route = ShieldSystem().route_damage(
        state,
        target_id="enemy:target",
        incoming_damage=10.0,
        damage_family="true_damage",
        damage_route_rule_id="damage_route_rule:forged",
        damage_route_rule_version=ENGINE_RULE_REGISTRY_VERSION,
        actor_id="ally:actor",
        source_id="validation:forged_route",
    )
    checks = _checks(
        {
            "blocked": not route.ok,
            "rule_identity_rejected": route.blocked_reason == "damage_route_engine_rule_id_mismatch",
            "no_shield_mutation": route.shield_mutation is None,
            "state_unchanged": aggregate_shield(state.units["enemy:target"].shield_instances) == 25.0,
        }
    )
    return {"checks": checks, "route": route.evidence, "blocked_reason": route.blocked_reason}


def _forged_priority_rule_case() -> dict[str, Any]:
    state = _state()
    result = ShieldSystem().apply_effect(
        state,
        target_id="enemy:target",
        shield_id="validation:forged_priority",
        source_id="forged_priority",
        source_kind="validation",
        opcode="InitShield",
        amount=10.0,
        source_trace=_source("forged_priority"),
        actor_id="ally:actor",
        event_source_id="validation:shield",
        priority_rule_id="shield_priority_rule:forged",
        priority_rule_version=ENGINE_RULE_REGISTRY_VERSION,
    )
    checks = _checks(
        {
            "blocked": not result.ok,
            "rule_identity_rejected": result.blocked_reason.startswith("shield_priority_engine_rule_missing"),
            "no_mutation": result.mutation is None,
            "state_unchanged": not state.units["enemy:target"].shield_instances,
        }
    )
    return {"checks": checks, "blocked_reason": result.blocked_reason}


def _versioned_route_registry_case() -> dict[str, Any]:
    registry = build_engine_rule_registry()
    routes = {rule.damage_family: rule for rule in registry.damage_route_rules}
    priority = registry.shield_priority_rules
    expected_families = {
        *NORMAL_DAMAGE_ROUTE_FAMILIES,
        *HP_LOSS_ROUTE_FAMILIES,
    }
    checks = _checks(
        {
            "registry_version_exact": registry.registry_version == ENGINE_RULE_REGISTRY_VERSION,
            "all_damage_families_have_exact_route": set(routes) == expected_families,
            "normal_families_absorb": all(
                routes[family].route_policy == "absorb" for family in expected_families - {"hp_loss"}
            ),
            "hp_loss_bypasses": routes["hp_loss"].route_policy == "bypass",
            "route_rules_versioned_and_scoped": all(
                rule.registry_version == ENGINE_RULE_REGISTRY_VERSION and bool(rule.applicability)
                for rule in routes.values()
            ),
            "single_priority_rule": len(priority) == 1
            and priority[0].shield_priority_rule_id == SHIELD_PRIORITY_RULE_ID
            and priority[0].registry_version == ENGINE_RULE_REGISTRY_VERSION,
        }
    )
    return {
        "checks": checks,
        "damage_route_rules": [rule.to_json() for rule in registry.damage_route_rules],
        "shield_priority_rules": [rule.to_json() for rule in priority],
    }


def _missing_canonical_route_case() -> dict[str, Any]:
    state = _state()
    empty_registry = RuleBook(CanonicalIR(version="validation:missing_engine_rules")).engine_rule_registry()
    route = ShieldSystem(empty_registry).route_damage(
        state,
        target_id="enemy:target",
        incoming_damage=10.0,
        damage_family="true_damage",
        damage_route_rule_id="damage_route_rule:engine_convention:true_damage_v1",
        damage_route_rule_version=ENGINE_RULE_REGISTRY_VERSION,
        actor_id="ally:actor",
        source_id="validation:missing_route",
    )
    checks = _checks(
        {
            "blocked": not route.ok,
            "structured_reason": route.blocked_reason == "damage_route_engine_rule_missing:true_damage",
            "no_mutation": route.shield_mutation is None,
            "state_unchanged": state.units["enemy:target"].hp == 100.0,
        }
    )
    return {"checks": checks, "blocked_reason": route.blocked_reason}


def _apply_shield(
    state: BattleState,
    name: str,
    amount: float,
    *,
    opcode: str = "InitShield",
    priority: int = 0,
    actor_id: str = "ally:actor",
):
    result = ShieldSystem().apply_effect(
        state,
        target_id="enemy:target",
        shield_id=f"validation:{name}",
        source_id=name,
        source_kind="validation",
        opcode=opcode,
        amount=amount,
        source_trace=_source(name),
        actor_id=actor_id,
        event_source_id="validation:shield",
        priority=priority,
        priority_source={"kind": "validation_policy", "priority": priority},
    )
    if not result.ok or result.mutation is None:
        raise AssertionError(result.blocked_reason)
    return MutationReducer().apply(state, result.mutation), result


def _state() -> BattleState:
    return BattleState(
        units={
            "ally:actor": UnitState("ally:actor", "ally", "validation:actor", hp=100.0, max_hp=100.0),
            "ally:second": UnitState("ally:second", "ally", "validation:actor", hp=100.0, max_hp=100.0),
            "enemy:target": UnitState("enemy:target", "enemy", "validation:target", hp=100.0, max_hp=100.0),
        }
    )


def _damage_packet(amount: float) -> DamagePacket:
    return DamagePacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        attack_type="validation",
        damage_formula_family="true_damage",
        amount=amount,
        amount_stage="fixed_final",
        source_frame=DamageSourceFrame(
            owner_id="ally:actor",
            source_id="validation:damage",
            source_kind="kernel_invariant_fixture",
            sequence_id="validation:shield_route",
            target_id="enemy:target",
            source_trace=_source("damage"),
        ),
        source_trace=_source("damage"),
        metadata={"fixture_kind": "kernel_invariant_fixture"},
    )


def _source(name: str) -> dict[str, Any]:
    return {"kind": "kernel_invariant_fixture", "id": name, "not_tbgd_positive": True}


def _route_amount(records: tuple[dict[str, Any], ...], key: str) -> float | None:
    value = _route_value(records, key)
    return float(value) if isinstance(value, (int, float)) else None


def _route_value(records: tuple[dict[str, Any], ...], key: str):
    for record in records:
        if record.get("record_type") == "shield_absorption":
            return record.get("payload", {}).get(key)
    return None


def _checks(values: dict[str, bool]) -> dict[str, Any]:
    return {"ok": all(values.values()), **values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S13 first-class shield and HP routing.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_validation(args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} "
        f"rows={result['summary']['row_count']} ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
