from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..systems.scheduler import CombatScheduler
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .p2_status_coverage import (
    build_p2_status_coverage_matrix,
    validate_p2_ir_rulebook_integrity_matrix,
    validate_p2_status_inventory_matrix,
)
from .static_checks import run_static_checks
from .validate_p1_4_status_system import (
    _action_after_duration_case,
    _base_state,
    _chance_is_guaranteed_or_missing,
    _effect_sample,
    _expire_remove_case,
    _first_status_detail,
    _fixed_value,
    _json_without_state,
    _modifier_definition_for_effect,
    _replace_detail,
    _safe_add_modifier_effect,
    _select_duration_effect,
    _snapshot_hash,
    _status_transition,
    _sweep_transition,
    _wave_cleanup_case,
    _LifecycleResultAdapter,
)


VALIDATION_VERSION = "p2_s4_status_lifecycle"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    lifecycle_matrix = _lifecycle_moment_matrix(rules)
    owner_tick_case = _holder_tick_case(rules)
    modifier_phase_case = _modifier_phase_duration_case(rules)
    action_after_case = _action_after_duration_case(rules)
    expire_case = _expire_remove_case(rules)
    wave_cleanup_case = _wave_cleanup_case(rules)
    inactive_case = _inactive_unit_tick_negative_case(rules)
    missing_source_case = _missing_duration_negative_case(rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "lifecycle_moment_matrix": lifecycle_matrix["checks"],
        "holder_tick": owner_tick_case["checks"],
        "modifier_phase_sweep": modifier_phase_case["checks"],
        "action_phase_end_sweep": action_after_case["checks"],
        "expire_remove": expire_case["checks"],
        "wave_cleanup": wave_cleanup_case["checks"],
        "inactive_unit_tick_blocked": inactive_case["checks"],
        "missing_duration_blocked": missing_source_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_lifecycle_semantics",
                "runtime_behavior_changed": True,
                "runtime_change": "block status lifecycle tick for defeated or removed units",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "observed_life_step_moment_counts": lifecycle_matrix["observed_life_step_moment_counts"],
            "lifecycle_classification_counts": lifecycle_matrix["classification_counts"],
            "modifier_phase_effect": _effect_sample(modifier_phase_case["effect_ir"]),
            "action_phase_effect": action_after_case["effect"],
            "inactive_reasons": inactive_case["blocked_reasons"],
            "missing_duration_reasons": missing_source_case["blocked_reasons"],
            "wave_cleanup_status": "coverage_gap" if wave_cleanup_case.get("coverage_gap") else "executable",
            "classification_counts": matrix["classification_counts"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "lifecycle_moment_matrix": lifecycle_matrix["matrix"],
            "holder_tick": _json_without_state(owner_tick_case),
            "modifier_phase_sweep": _json_without_state(modifier_phase_case),
            "action_phase_end_sweep": _json_without_state(action_after_case),
            "expire_remove": _json_without_state(expire_case),
            "wave_cleanup": _json_without_state(wave_cleanup_case),
            "inactive_unit_tick_blocked": inactive_case,
            "missing_duration_blocked": missing_source_case,
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s4_status_lifecycle.json", result)
    return result


def _holder_tick_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s4:holder_tick",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    result = system.apply_lifecycle_tick(after_add, owner_id, detail, str(detail.get("life_step_moment") or ""))
    after_tick = MutationReducer().apply_all(after_add, result.mutations)
    transition = _status_transition(after_add, _LifecycleResultAdapter(result), "p2_s4:holder_tick")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    after_detail = _first_status_detail(after_tick)
    wrong_owner = "enemy:target" if owner_id != "enemy:target" else "ally:actor"
    wrong_result = system.apply_lifecycle_tick(after_add, wrong_owner, detail, str(detail.get("life_step_moment") or ""))
    checks = {
        "add_duration_status_ok": add_result.ok and bool(add_result.mutations),
        "holder_tick_mutates": result.ok and bool(result.mutations),
        "remaining_duration_decremented": after_detail.get("remaining_duration")
        == float(detail.get("remaining_duration") or 0) - 1.0,
        "wrong_owner_blocked": not wrong_result.ok and not wrong_result.mutations,
        "wrong_owner_reason": "duration_tick_owner_mismatch" in tuple(wrong_result.unsupported),
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(after_add, result.mutations, after_tick.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "before_detail": detail,
        "after_detail": after_detail,
        "tick_result": result.to_json(),
        "wrong_owner_result": wrong_result.to_json(),
        "source_audit": source_audit.to_json(),
    }


def _modifier_phase_duration_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s4:modifier_phase",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    sweep = CombatScheduler(rules)._apply_status_lifecycle_tick(after_add, "ModifierPhase1End", actor_id=owner_id)
    transition = _sweep_transition(after_add, sweep.after_state, sweep, "p2_s4:modifier_phase", actor_id=owner_id)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    after_detail = _first_status_detail(sweep.after_state)
    checks = {
        "add_modifier_phase_duration_ok": add_result.ok and bool(add_result.mutations),
        "modifier_phase_moment_recorded": detail.get("life_step_moment") == "ModifierPhase1End",
        "scheduler_sweep_mutates": bool(sweep.mutations),
        "duration_tick_operation": any(
            mutation.source == "status_system"
            and isinstance(mutation.metadata.get("lifecycle_plan"), dict)
            and mutation.metadata["lifecycle_plan"].get("operation") == "tick"
            for mutation in sweep.mutations
        ),
        "remaining_duration_decremented": after_detail.get("remaining_duration")
        == float(detail.get("remaining_duration") or 0) - 1.0,
        "source_audit": source_audit.ok,
        "replay": MutationReducer().replay_snapshot(after_add, sweep.mutations, sweep.after_state.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect_ir": effect,
        "effect": _effect_sample(effect),
        "before_detail": detail,
        "after_detail": after_detail,
        "events": [event.to_json() for event in sweep.events],
        "records": list(sweep.records),
        "mutations": [mutation.to_json() for mutation in sweep.mutations],
        "source_audit": source_audit.to_json(),
    }


def _inactive_unit_tick_negative_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s4:inactive_unit",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    life_step_moment = str(detail.get("life_step_moment") or "")
    defeated_state = _unit_with_lifecycle_status(after_add, owner_id, "defeated")
    removed_state = _unit_with_lifecycle_status(after_add, owner_id, "removed")
    defeated = system.apply_lifecycle_tick(defeated_state, owner_id, detail, life_step_moment)
    removed = system.apply_lifecycle_tick(removed_state, owner_id, detail, life_step_moment)
    checks = {
        "defeated_blocked": not defeated.ok and not defeated.mutations,
        "defeated_reason": any(
            str(reason).startswith("unit_not_active_for_status_lifecycle") for reason in defeated.unsupported
        ),
        "defeated_state_unchanged": _snapshot_hash(defeated_state)
        == _snapshot_hash(MutationReducer().apply_all(defeated_state, defeated.mutations)),
        "removed_blocked": not removed.ok and not removed.mutations,
        "removed_reason": any(
            str(reason).startswith("unit_not_active_for_status_lifecycle") for reason in removed.unsupported
        ),
        "removed_state_unchanged": _snapshot_hash(removed_state)
        == _snapshot_hash(MutationReducer().apply_all(removed_state, removed.mutations)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "blocked_reasons": {
            "defeated": list(defeated.unsupported),
            "removed": list(removed.unsupported),
        },
        "defeated_result": defeated.to_json(),
        "removed_result": removed.to_json(),
    }


def _missing_duration_negative_case(rules: RuleBook) -> dict[str, Any]:
    effect = _select_duration_effect(rules)
    system = StatusSystem(rules)
    state = _base_state()
    add_result = system.apply_add_modifier(
        state,
        effect,
        caster_id="ally:actor",
        source_id="validation:p2_s4:missing_duration",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
    )
    after_add = MutationReducer().apply_all(state, add_result.mutations)
    detail = _first_status_detail(after_add)
    owner_id = str(detail.get("owner_id") or "")
    life_step_moment = str(detail.get("life_step_moment") or "")

    missing_remaining = dict(detail)
    missing_remaining.pop("remaining_duration", None)
    missing_remaining_state = _replace_detail(after_add, missing_remaining)
    missing_remaining_result = system.apply_lifecycle_tick(
        missing_remaining_state,
        owner_id,
        missing_remaining,
        life_step_moment,
    )

    missing_source = dict(detail)
    missing_source.pop("duration_admission", None)
    source_trace = dict(missing_source.get("source_trace") or {}) if isinstance(missing_source.get("source_trace"), dict) else {}
    source_trace.pop("duration_admission", None)
    missing_source["source_trace"] = source_trace
    missing_source_state = _replace_detail(after_add, missing_source)
    missing_source_result = system.apply_lifecycle_tick(
        missing_source_state,
        owner_id,
        missing_source,
        life_step_moment,
    )
    checks = {
        "missing_remaining_blocked": not missing_remaining_result.ok and not missing_remaining_result.mutations,
        "missing_remaining_reason": "remaining_duration_missing" in tuple(missing_remaining_result.unsupported),
        "missing_remaining_state_unchanged": _snapshot_hash(missing_remaining_state)
        == _snapshot_hash(MutationReducer().apply_all(missing_remaining_state, missing_remaining_result.mutations)),
        "missing_source_blocked": not missing_source_result.ok and not missing_source_result.mutations,
        "missing_source_reason": "duration_admission_not_executable" in tuple(missing_source_result.unsupported),
        "missing_source_state_unchanged": _snapshot_hash(missing_source_state)
        == _snapshot_hash(MutationReducer().apply_all(missing_source_state, missing_source_result.mutations)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "effect": _effect_sample(effect),
        "blocked_reasons": {
            "missing_remaining": list(missing_remaining_result.unsupported),
            "missing_source": list(missing_source_result.unsupported),
        },
        "missing_remaining_result": missing_remaining_result.to_json(),
        "missing_source_result": missing_source_result.to_json(),
    }


def _unit_with_lifecycle_status(state, unit_id: str, lifecycle_status: str):
    unit = state.units[unit_id]
    flags = {
        **unit.flags,
        "lifecycle_status": lifecycle_status,
        f"{'defeat' if lifecycle_status == 'defeated' else 'removed'}_record": {
            "reason": f"validation_{lifecycle_status}",
        },
    }
    return replace(state, units={**state.units, unit_id: replace(unit, hp=0.0, flags=flags)})


def _lifecycle_moment_matrix(rules: RuleBook) -> dict[str, Any]:
    observed = Counter()
    duration_source_count = 0
    missing_lifetime_count = 0
    samples: dict[str, dict[str, Any]] = {}
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        definition = _modifier_definition_for_effect(rules, effect)
        standard_moment = str(standard.get("life_step_moment") or "")
        definition_moment = str(definition.fields.get("life_step_moment") or "") if definition is not None else ""
        standard_lifetime = standard.get("lifetime")
        definition_lifetime = definition.fields.get("lifetime_expr") if definition is not None else None
        has_duration_source = _fixed_value(standard_lifetime) is not None or definition_lifetime is not None
        if not has_duration_source:
            missing_lifetime_count += 1
            continue
        duration_source_count += 1
        moment = standard_moment or definition_moment or "<missing>"
        observed[moment] += 1
        samples.setdefault(moment, _effect_sample(effect))

    missing_default_count = int(observed.get("<missing>", 0))
    explicit_modifier_count = int(observed.get("ModifierPhase1End", 0))
    action_phase_count = int(observed.get("ActionPhaseEnd", 0))
    matrix = {
        "ModifierPhase1End": _moment_entry(
            "executable",
            missing_default_count + explicit_modifier_count,
            "missing LifeStepMoment buff/debuff defaults and explicit ModifierPhase1End sources tick on holder.",
        ),
        "ActionPhaseEnd": _moment_entry(
            "executable",
            action_phase_count,
            "explicit ActionPhaseEnd sources tick through scheduler action-after hook.",
        ),
        "TurnStart": _moment_entry(
            _absent_or_missing(observed.get("TurnStart", 0)),
            int(observed.get("TurnStart", 0)),
            "no current duration source declares TurnStart.",
        ),
        "ActionPhaseStart": _moment_entry(
            _absent_or_missing(observed.get("ActionPhaseStart", 0)),
            int(observed.get("ActionPhaseStart", 0)),
            "no current duration source declares action-before tick.",
        ),
        "WaveStart": _moment_entry("source_absent_not_required", 0, "no status duration source declares wave-start tick."),
        "WaveEnd": _moment_entry("source_absent_not_required", 0, "no status duration source declares wave-end tick."),
        "holder_tick_owner": _moment_entry("executable", duration_source_count, "duration admission records holder tick owner policy."),
        "caster_tick_owner": _moment_entry("source_absent_not_required", 0, "no caster-owned duration decrement source is projected."),
        "action_count_duration": _moment_entry("source_absent_not_required", 0, "no action-count duration source is projected."),
        "permanent_or_missing_duration": _moment_entry(
            "boundary_only",
            missing_lifetime_count,
            "statuses without executable duration source do not enter lifecycle tick mutation.",
        ),
        "wave_status_cleanup": _moment_entry(
            "executable",
            1,
            "wave transition clears statuses and status_details for removed wave units.",
        ),
    }
    classification_counts = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "duration_sources_seen": duration_source_count > 0,
        "modifier_phase_sources_seen": matrix["ModifierPhase1End"]["source_count"] > 0,
        "action_phase_end_sources_seen": matrix["ActionPhaseEnd"]["source_count"] > 0,
        "no_unclassified_lifecycle_family": all(item["classification"] for item in matrix.values()),
        "no_implementation_missing": not any(
            item["classification"] == "implementation_missing" for item in matrix.values()
        ),
        "unsupported_declared_moments_absent": not any(
            observed.get(moment, 0) for moment in ("TurnStart", "ActionPhaseStart", "WaveStart", "WaveEnd")
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "observed_life_step_moment_counts": dict(sorted(observed.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "samples_by_moment": samples,
    }


def _moment_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def _absent_or_missing(count: int) -> str:
    return "implementation_missing" if int(count) > 0 else "source_absent_not_required"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S4 status duration, tick, expire, and cleanup semantics.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
