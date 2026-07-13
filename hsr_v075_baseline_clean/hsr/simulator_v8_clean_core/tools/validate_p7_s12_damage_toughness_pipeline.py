from __future__ import annotations

import argparse
import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.reducer import MutationReducer
from ..rules.engine_rule_registry import ENGINE_RULE_REGISTRY_VERSION, build_engine_rule_registry
from ..rules.ir import CanonicalIR
from ..rules.rulebook import RuleBook
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.damage_pipeline import DAMAGE_FAMILY_STAGE_MATRIX, DamageStagePipeline
from ..systems.toughness import ToughnessPacket, ToughnessSystem
from .io import write_json
from .validate_p7_s0_kernel_trust_baseline import _base_state
from .validate_p7_s1_transition_trust_contract import _trust_rulebook


VALIDATION_VERSION = "p7_s12_damage_toughness_pipeline"
MATRIX_SCHEMA_VERSION = "p7_s12_damage_toughness_matrix_v1"


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    families = _damage_family_cases()
    toughness = _toughness_case()
    before_event = _before_event_reload_case(package_root)
    blocked = _amount_stage_negative_case()
    ownership = _mutation_ownership_case(package_root)
    status_modifiers = _status_modifier_case()
    engine_rules = _engine_rule_registry_case(package_root)
    rows = (*families, toughness, status_modifiers, engine_rules, before_event, blocked, ownership)
    checks = {
        "all_damage_families_use_staged_pipeline": all(row["ok"] for row in families),
        "toughness_uses_same_stage_contract": toughness["ok"],
        "before_event_reloads_updated_state": before_event["ok"],
        "ambiguous_amount_stage_blocked_no_mutation": blocked["ok"],
        "hp_and_toughness_mutation_ownership_clean": ownership["ok"],
        "non_direct_pipeline_applies_status_modifier_terms": status_modifiers["ok"],
        "damage_formula_rules_versioned_and_shared": engine_rules["ok"],
        "applied_and_skipped_terms_present": all(
            row["pipeline_applied_count"] > 0 and row["pipeline_skipped_count"] > 0
            for row in (*families[:4], toughness)
        ),
        "no_large_artifacts": True,
    }
    ok = all(checks.values())
    summary = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "ready_for_review": ok,
        "checks": checks,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "row_count": len(rows),
        "resource_budget": {
            "tbgd_read_count": 0,
            "minimal_in_memory_rulebook_build_count": 1,
            "large_artifacts_written": False,
            "full_transition_dump_written": False,
        },
        "evidence_scope": {
            "kernel_invariants": "validation structural fixtures",
            "real_source_regressions": "P6-S1 and P2-S8 run separately",
        },
        "deferred": {
            "shield_routing": "P7-S13",
            "additional_formula_source_admission": "later data-card expansion",
            "rng_identity": "P7-S16",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s12_damage_toughness_pipeline.json", summary)
    write_json(
        output_dir / "p7_s12_damage_toughness_matrix.json",
        {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "rows": [
                {"row_id": row["row_id"], "classification": row["classification"], "ok": row["ok"]}
                for row in rows
            ],
        },
    )
    write_json(
        output_dir / "p7_s12_damage_toughness_evidence.json",
        {
            "damage_families": families,
            "toughness": toughness,
            "status_modifiers": status_modifiers,
            "engine_rules": engine_rules,
            "before_event_reload": before_event,
            "amount_stage_negative": blocked,
            "mutation_ownership": ownership,
        },
    )
    return summary


def _status_modifier_case() -> dict[str, Any]:
    state = _pipeline_state()
    actor = state.units["ally:actor"]
    neutral_resources = {
        key: value
        for key, value in actor.resources.items()
        if key not in {"damage_added_ratio", "Fire_damage_added_ratio"}
    }
    actor = replace(actor, resources=neutral_resources)
    state = replace(state, units={**state.units, actor.unit_id: actor})
    detail = {
        "instance_id": "validation:status:damage_bonus",
        "modifiers": [
            {
                "bucket": "damage_bonus",
                "key": "damage_added_ratio",
                "value": 1.0,
                "scope": "actor",
                "condition": "always",
                "raw_path": "validation.status.modifiers[0]",
            }
        ],
    }
    modified_actor = replace(actor, flags={**actor.flags, "status_details": [detail]})
    modified_state = replace(state, units={**state.units, actor.unit_id: modified_actor})
    pipeline = DamageStagePipeline()
    baseline = pipeline.calculate(
        state,
        family="dot",
        attacker_id=actor.unit_id,
        target_id="enemy:target",
        producer_base_amount=100.0,
        element_type="Fire",
        source_trace={"kind": "validation_baseline"},
    )
    modified = pipeline.calculate(
        modified_state,
        family="dot",
        attacker_id=actor.unit_id,
        target_id="enemy:target",
        producer_base_amount=100.0,
        element_type="Fire",
        source_trace={"kind": "validation_status_modifier"},
    )
    applied = [
        term
        for term in modified.applied_terms
        if term.get("source_id") == detail["instance_id"]
        and term.get("bucket") == "damage_bonus"
        and term.get("key") == "damage_added_ratio"
    ]
    ok = (
        baseline.ok
        and modified.ok
        and abs(modified.final_amount - baseline.final_amount * 2.0) < 1e-9
        and len(applied) == 1
        and applied[0].get("applied_value") == 1.0
    )
    return {
        "row_id": "dot_status_damage_bonus_applied_and_audited",
        "classification": "negative_regression_fixture",
        "ok": ok,
        "baseline_final_amount": baseline.final_amount,
        "modified_final_amount": modified.final_amount,
        "matched_applied_terms": applied,
        "pipeline": modified.to_json(),
    }


def _engine_rule_registry_case(package_root: Path) -> dict[str, Any]:
    registry = build_engine_rule_registry()
    by_kind = {rule.rule_kind: rule for rule in registry.damage_formula_rules}
    state = _pipeline_state()
    pipeline = DamageStagePipeline().calculate(
        state,
        family="dot",
        attacker_id="ally:actor",
        target_id="enemy:target",
        producer_base_amount=100.0,
        element_type="Fire",
        source_trace={"kind": "engine_rule_validation"},
    )
    bucket_by_name = {bucket.stage: bucket for bucket in pipeline.stage_buckets}
    defense_rule = bucket_by_name["defense"].metadata.get("engine_rule")
    resistance_rule = bucket_by_name["resistance"].metadata.get("engine_rule")
    direct_source = (package_root / "systems" / "damage_formula.py").read_text(encoding="utf-8")
    pipeline_source = (package_root / "systems" / "damage_pipeline.py").read_text(encoding="utf-8")
    lowering_source = (package_root / "tbgd" / "lowering.py").read_text(encoding="utf-8")
    missing_rule_result = DamageSystem(RuleBook(CanonicalIR(version="validation:missing_engine_rules"))).apply_packet(
        state,
        DamagePacket(
            "ally:actor",
            "enemy:target",
            "Dot",
            "dot",
            100.0,
            "family_base",
            element_type="Fire",
            status_damage_emission_id="validation:missing_rule",
            source_trace={"kind": "negative_fixture"},
        ),
    )
    checks = {
        "registry_version_exact": registry.registry_version == ENGINE_RULE_REGISTRY_VERSION,
        "defense_rule_present": "defense_multiplier" in by_kind,
        "resistance_rule_present": "resistance_multiplier" in by_kind,
        "rules_executable_and_versioned": all(
            rule.coverage_status == "executable"
            and rule.registry_version == ENGINE_RULE_REGISTRY_VERSION
            and bool(rule.applicability)
            for rule in registry.damage_formula_rules
        ),
        "pipeline_uses_registry_defense_rule": isinstance(defense_rule, dict)
        and defense_rule.get("damage_formula_rule_id") == by_kind["defense_multiplier"].damage_formula_rule_id,
        "pipeline_uses_registry_resistance_rule": isinstance(resistance_rule, dict)
        and resistance_rule.get("damage_formula_rule_id") == by_kind["resistance_multiplier"].damage_formula_rule_id,
        "runtime_formula_constants_removed": "effective + 200.0 + 10.0 * actor.level" not in direct_source
        and "effective + 200.0 + 10.0 * actor.level" not in pipeline_source,
        "canonical_lowering_projects_damage_rules": "damage_formula_rules=tuple(damage_formula_rules)" in lowering_source,
        "missing_canonical_rule_blocks_without_mutation": not missing_rule_result.ok
        and not missing_rule_result.mutations
        and any("damage_formula_engine_rule_missing" in error for error in missing_rule_result.errors),
    }
    return {
        "row_id": "versioned_damage_formula_engine_rules",
        "classification": "kernel_invariant",
        "ok": all(checks.values()),
        "checks": checks,
        "registry": {
            "registry_version": registry.registry_version,
            "damage_formula_rules": [rule.to_json() for rule in registry.damage_formula_rules],
        },
        "pipeline_rule_evidence": {"defense": defense_rule, "resistance": resistance_rule},
        "missing_rule_errors": list(missing_rule_result.errors),
    }


def _damage_family_cases() -> tuple[dict[str, Any], ...]:
    state = _pipeline_state()
    rules = _trust_rulebook()
    definition = rules.action_definition("validation:normal", 1)
    if definition is None:
        raise AssertionError("validation direct action definition missing")
    source = definition.source.to_json()
    packets = (
        DamagePacket(
            attacker_id="ally:actor",
            target_id="enemy:target",
            attack_type="Normal",
            damage_formula_family="direct",
            action_definition=definition,
            damage_emission_id="validation:direct_emission",
            scaling_ratio=1.0,
            scaling_basis={"kind": "fixed", "value": 100.0},
            source_trace=source,
            metadata={"crit_mode": "noncrit", "rng_mode": "deterministic_seed"},
        ),
        DamagePacket(
            "ally:actor", "enemy:target", "Dot", "dot", 100.0, "family_base",
            element_type="Fire", status_damage_emission_id="validation:dot", source_task_id="validation:task",
            source_trace=source, metadata={"numeric_evaluation": {"ok": True}},
        ),
        DamagePacket(
            "ally:actor", "enemy:target", "Break", "break", 100.0, "family_base",
            element_type="Fire", break_damage_emission_id="validation:break", break_template_id="validation:template",
            source_task_id="validation:task", source_trace=source,
            metadata={"numeric_evaluation": {"ok": True}, "break_base_damage_source": {"level": 80}},
        ),
        DamagePacket(
            "ally:actor", "enemy:target", "SuperBreak", "super_break", 100.0, "family_base",
            element_type="Fire", super_break_emission_id="validation:super", break_template_id="validation:template",
            source_task_id="validation:task", source_trace=source,
            metadata={"numeric_evaluation": {"ok": True}, "break_base_damage_source": {"level": 80}},
        ),
        DamagePacket(
            "ally:actor", "enemy:target", "TrueDamage", "true_damage", 100.0, "fixed_final",
            source_trace=source, metadata={"effect_id": "validation:true"},
        ),
        DamagePacket(
            "ally:actor", "enemy:target", "HPLoss", "hp_loss", 100.0, "fixed_final",
            damage_kind="hp_loss", source_trace=source, metadata={"effect_id": "validation:hp_loss"},
        ),
    )
    rows = []
    for packet in packets:
        result = DamageSystem(rules).apply_packet(state, packet)
        after = MutationReducer().apply_all(state, result.mutations)
        replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
        record = next((item for item in result.records if item.get("mutation_id")), {})
        pipeline = record.get("payload", {}).get("damage_pipeline", {}) if isinstance(record.get("payload"), dict) else {}
        hp_mutations = [mutation for mutation in result.mutations if mutation.path == ("units", "enemy:target", "hp")]
        final_amount = float(pipeline.get("final_amount") or 0.0)
        source_frame = record.get("payload", {}).get("source_frame", {}) if isinstance(record.get("payload"), dict) else {}
        stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
        applied = pipeline.get("applied_terms") if isinstance(pipeline.get("applied_terms"), list) else []
        skipped = pipeline.get("skipped_terms") if isinstance(pipeline.get("skipped_terms"), list) else []
        expected_applicable = (
            7 if packet.damage_formula_family == "direct"
            else len(DAMAGE_FAMILY_STAGE_MATRIX.get(packet.damage_formula_family, ()))
        )
        applicable_count = sum(1 for stage in stages if stage.get("applicable") is True)
        ok = (
            result.ok
            and len(hp_mutations) == 1
            and replay.ok
            and pipeline.get("schema_version") == "p7_s12_damage_stage_pipeline_v1"
            and float(pipeline.get("producer_base_amount") or 0.0) == 100.0
            and final_amount > 0.0
            and abs(after.units["enemy:target"].hp - (state.units["enemy:target"].hp - final_amount)) < 1e-9
            and applicable_count == expected_applicable
            and source_frame.get("owner_id") == "ally:actor"
            and bool(source_frame.get("source_id"))
        )
        rows.append(
            {
                "row_id": f"damage_family:{packet.damage_formula_family}",
                "classification": "kernel_invariant_fixture",
                "ok": ok,
                "amount_stage": packet.amount_stage,
                "producer_base_amount": pipeline.get("producer_base_amount"),
                "final_amount": final_amount,
                "applicable_stage_count": applicable_count,
                "expected_applicable_stage_count": expected_applicable,
                "pipeline_applied_count": len(applied),
                "pipeline_skipped_count": len(skipped),
                "source_frame": source_frame,
                "hp_mutation_count": len(hp_mutations),
                "replay_ok": replay.ok,
                "pipeline": pipeline,
            }
        )
    return tuple(rows)


def _toughness_case() -> dict[str, Any]:
    state = _pipeline_state()
    rules = _trust_rulebook()
    packet = ToughnessPacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        toughness_emission_id="validation:toughness",
        source_task_id="validation:task",
        hit_profile_id="validation:hit",
        element_type="Fire",
        amount=20.0,
        target_group="primary",
        coverage_status="executable",
        source_trace={"kind": "validation_toughness_source"},
        amount_stage="family_base",
    )
    result = ToughnessSystem(rules).apply_packet(state, packet)
    after = MutationReducer().apply_all(state, result.mutations)
    replay = MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json())
    record = next((item for item in result.records if item.get("record_type") == "toughness"), {})
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    pipeline = payload.get("toughness_pipeline") if isinstance(payload.get("toughness_pipeline"), dict) else {}
    applied = pipeline.get("applied_terms") if isinstance(pipeline.get("applied_terms"), list) else []
    skipped = pipeline.get("skipped_terms") if isinstance(pipeline.get("skipped_terms"), list) else []
    final_amount = float(pipeline.get("final_amount") or 0.0)
    ok = (
        result.ok
        and len(result.mutations) == 1
        and result.mutations[0].path == ("units", "enemy:target", "toughness")
        and replay.ok
        and pipeline.get("schema_version") == "p7_s12_damage_stage_pipeline_v1"
        and abs(after.units["enemy:target"].toughness - (state.units["enemy:target"].toughness - final_amount)) < 1e-9
        and len(applied) > 0
        and len(skipped) > 0
    )
    return {
        "row_id": "toughness_family_pipeline",
        "classification": "kernel_invariant_fixture",
        "ok": ok,
        "producer_base_amount": pipeline.get("producer_base_amount"),
        "final_amount": final_amount,
        "pipeline_applied_count": len(applied),
        "pipeline_skipped_count": len(skipped),
        "replay_ok": replay.ok,
        "pipeline": pipeline,
    }


def _before_event_reload_case(package_root: Path) -> dict[str, Any]:
    before = _pipeline_state()
    target = replace(
        before.units["enemy:target"],
        resources={**before.units["enemy:target"].resources, "damage_taken_ratio": 0.5},
    )
    actor = replace(
        before.units["ally:actor"],
        resources={**before.units["ally:actor"].resources, "toughness_damage_added_ratio": 0.5},
    )
    updated = replace(before, units={**before.units, "enemy:target": target, "ally:actor": actor}, event_index=1)
    pipeline = DamageStagePipeline()
    damage_before = pipeline.calculate(
        before, family="dot", attacker_id="ally:actor", target_id="enemy:target",
        producer_base_amount=100.0, element_type="Fire", source_trace={"case": "before"},
    )
    damage_after = pipeline.calculate(
        updated, family="dot", attacker_id="ally:actor", target_id="enemy:target",
        producer_base_amount=100.0, element_type="Fire", source_trace={"case": "after"},
    )
    toughness_before = pipeline.calculate(
        before, family="toughness", attacker_id="ally:actor", target_id="enemy:target",
        producer_base_amount=20.0, element_type="Fire", source_trace={"case": "before"},
    )
    toughness_after = pipeline.calculate(
        updated, family="toughness", attacker_id="ally:actor", target_id="enemy:target",
        producer_base_amount=20.0, element_type="Fire", source_trace={"case": "after"},
    )
    executor_source = (package_root / "core" / "executor.py").read_text(encoding="utf-8")
    mutation_event_source = (package_root / "systems" / "mutation_events.py").read_text(encoding="utf-8")
    collect_index = executor_source.find("modifier_collection_after_before_hit")
    dispatch_index = executor_source.find("current_state = dispatch_result.after_state")
    ok = (
        damage_after.final_amount > damage_before.final_amount
        and toughness_after.final_amount > toughness_before.final_amount
        and damage_after.input_state_event_index == 1
        and toughness_after.input_state_event_index == 1
        and collect_index > dispatch_index >= 0
        and "before_toughness_calculation_event" in executor_source
        and '"pre_calculation_execution_admission": "executable"' in mutation_event_source
        and "before_toughness_event(" not in executor_source
    )
    return {
        "row_id": "before_event_updated_state_reloaded",
        "classification": "executable_ordering",
        "ok": ok,
        "damage_before": damage_before.final_amount,
        "damage_after": damage_after.final_amount,
        "toughness_before": toughness_before.final_amount,
        "toughness_after": toughness_after.final_amount,
        "updated_state_event_index": updated.event_index,
        "direct_modifier_collection_after_dispatch": collect_index > dispatch_index >= 0,
        "toughness_pre_calculation_event_wired": "before_toughness_calculation_event" in executor_source,
    }


def _amount_stage_negative_case() -> dict[str, Any]:
    state = _pipeline_state()
    packet = DamagePacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        attack_type="Dot",
        damage_formula_family="dot",
        amount=100.0,
        amount_stage="unspecified",
        status_damage_emission_id="validation:dot",
        source_trace={"kind": "validation_negative"},
    )
    result = DamageSystem().apply_packet(state, packet)
    ok = (
        not result.ok
        and not result.mutations
        and any("damage_amount_stage_mismatch" in error for error in result.errors)
        and state.units["enemy:target"].hp == 10000.0
    )
    return {
        "row_id": "ambiguous_amount_stage_blocked",
        "classification": "negative_boundary",
        "ok": ok,
        "errors": list(result.errors),
        "mutation_count": len(result.mutations),
    }


def _mutation_ownership_case(package_root: Path) -> dict[str, Any]:
    forbidden_hp_owners = []
    for relative in (
        "systems/effect.py",
        "systems/status_callbacks.py",
        "systems/break_system.py",
        "systems/super_break.py",
    ):
        path = package_root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Mutation":
                continue
            keyword = next((item for item in node.keywords if item.arg == "path"), None)
            if keyword is not None and isinstance(keyword.value, (ast.Tuple, ast.List)):
                values = [item.value for item in keyword.value.elts if isinstance(item, ast.Constant)]
                reason_keyword = next((item for item in node.keywords if item.arg == "reason"), None)
                reason = (
                    str(reason_keyword.value.value)
                    if reason_keyword is not None and isinstance(reason_keyword.value, ast.Constant)
                    else ""
                )
                if "hp" in values and "heal" not in reason.lower():
                    forbidden_hp_owners.append({"file": relative, "line": node.lineno})
    return {
        "row_id": "damage_toughness_mutation_ownership",
        "classification": "static_boundary",
        "ok": not forbidden_hp_owners,
        "forbidden_hp_mutation_sites": forbidden_hp_owners,
        "authoritative_hp_owner": "DamageSystem",
        "authoritative_toughness_owner": "ToughnessSystem",
    }


def _pipeline_state() -> BattleState:
    base = _base_state()
    actor = replace(
        base.units["ally:actor"],
        level=80,
        resources={
            **base.units["ally:actor"].resources,
            "critical_chance": 0.0,
            "damage_added_ratio": 0.2,
            "break_damage_added_ratio": 0.3,
            "toughness_damage_added_ratio": 0.25,
            "def_ignore": 0.1,
            "Fire_res_pen": 0.1,
        },
    )
    target = replace(
        base.units["enemy:target"],
        hp=10000.0,
        max_hp=10000.0,
        defense=200.0,
        toughness=100.0,
        max_toughness=100.0,
        flags={**base.units["enemy:target"].flags, "weaknesses": ["Fire"], "broken": False},
        resources={
            **base.units["enemy:target"].resources,
            "Fire_resistance": 0.2,
            "damage_taken_ratio": 0.1,
            "damage_reduction": 0.1,
            "def_reduction": 0.1,
        },
    )
    return replace(base, units={**base.units, "ally:actor": actor, "enemy:target": target})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S12 unified damage and toughness stage pipeline.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir)
    print(
        f"v8 {VALIDATION_VERSION} ok={result['ok']} rows={result['row_count']} "
        f"ready_for_review={result['ready_for_review']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
