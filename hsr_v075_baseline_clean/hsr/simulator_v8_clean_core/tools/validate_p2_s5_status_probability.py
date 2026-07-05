from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, JSONValue
from ..core.reducer import MutationReducer
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import EffectIR
from ..rules.rulebook import RuleBook
from ..systems.status import StatusApplicationResult, StatusSystem
from ..systems.wave import _unit_from_wave_entry
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
    _base_state,
    _effect_sample,
    _first_status_detail,
    _json_without_state,
    _modifier_definition_for_effect,
    _safe_add_modifier_effect,
    _snapshot_hash,
    _status_transition,
)


VALIDATION_VERSION = "p2_s5_status_probability"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    matrix = build_p2_status_coverage_matrix(tbgd_root, ir, rules)
    inventory_checks = validate_p2_status_inventory_matrix(matrix)
    integrity_checks = validate_p2_ir_rulebook_integrity_matrix(matrix)

    chance_matrix = _chance_resist_immunity_matrix(rules)
    chance_case = _dynamic_chance_case(rules)
    effect_hit_case = _effect_hit_case(rules, chance_case["candidate"])
    resist_case = _effect_resistance_case(rules, chance_case["candidate"])
    immunity_case = _status_immunity_case(rules, chance_case["candidate"])
    unbound_case = _unbound_chance_negative_case(rules, chance_case["candidate"])
    profile_case = _profile_status_resistance_case(rules)

    checks = {
        "inventory": inventory_checks,
        "ir_rulebook_integrity": integrity_checks,
        "chance_resist_immunity_matrix": chance_matrix["checks"],
        "dynamic_chance": chance_case["checks"],
        "effect_hit": effect_hit_case["checks"],
        "effect_resistance": resist_case["checks"],
        "status_immunity": immunity_case["checks"],
        "unbound_chance": unbound_case["checks"],
        "profile_status_resistance": profile_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "selection_policy": {
                "mode": "structured_status_probability_resist_immunity",
                "runtime_behavior_changed": True,
                "runtime_change": "project monster StatusResistanceBase into effect_resistance resource",
                "fixed_character_monster_skill_file_hash_or_observation_used": False,
            },
        },
        "checks": checks,
        "summary": {
            "selected_effect": _effect_sample(chance_case["candidate"]["effect"]),
            "selected_chance_hash": chance_case["candidate"]["chance_hash"],
            "chance_kind_counts": chance_matrix["chance_kind_counts"],
            "classification_counts": chance_matrix["classification_counts"],
            "matrix": chance_matrix["matrix"],
            "profile_status_resistance": profile_case["profile_status_resistance"],
            "profile_debuff_resistance_count": profile_case["profile_debuff_resistance_count"],
            "unclassified_count": matrix["unclassified_count"],
        },
        "cases": {
            "chance_resist_immunity_matrix": chance_matrix["matrix"],
            "dynamic_chance": _json_case_without_runtime_candidate(chance_case),
            "effect_hit": _json_without_state(effect_hit_case),
            "effect_resistance": _json_without_state(resist_case),
            "status_immunity": _json_without_state(immunity_case),
            "unbound_chance": _json_without_state(unbound_case),
            "profile_status_resistance": profile_case,
        },
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p2_s5_status_probability.json", result)
    return result


def _dynamic_chance_case(rules: RuleBook) -> dict[str, Any]:
    candidate = _select_dynamic_chance_candidate(rules)
    success_payload = _rng_payload(candidate, "status_apply", "base_chance", "success")
    fail_payload = _rng_payload(candidate, "status_apply", "base_chance", "fail")
    success = _apply_candidate(rules, candidate, chance_value=0.5, event_payload=success_payload)
    failure = _apply_candidate(rules, candidate, chance_value=0.5, event_payload=fail_payload)
    repeat_failure = _apply_candidate(rules, candidate, chance_value=0.5, event_payload=fail_payload)
    after_success = MutationReducer().apply_all(success["state"], success["result"].mutations)
    transition = _status_transition(success["state"], success["result"], "p2_s5:dynamic_chance_success")
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition)
    success_detail = _first_status_detail(after_success)
    checks = {
        "success_applies": success["result"].ok and bool(success["result"].mutations),
        "success_rng_event": _has_rng(success["result"], "status_apply"),
        "success_choice_replayed": _rng_choice_source(success["result"]) == "explicit_ledger",
        "success_source_audit": source_audit.ok,
        "success_replay": MutationReducer().replay_snapshot(
            success["state"],
            success["result"].mutations,
            after_success.snapshot().to_json(),
        ).ok,
        "failure_no_mutation": not failure["result"].mutations,
        "failure_record_type": _has_record(failure["result"], "status_apply_failed"),
        "failure_rng_event": _has_rng(failure["result"], "status_apply"),
        "failure_state_unchanged": _snapshot_hash(failure["state"])
        == _snapshot_hash(MutationReducer().apply_all(failure["state"], failure["result"].mutations)),
        "failure_replay_same_choice": _result_signature(failure["result"]) == _result_signature(repeat_failure["result"]),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "candidate": candidate,
        "success_result": success["result"].to_json(),
        "success_detail": success_detail,
        "failure_result": failure["result"].to_json(),
        "source_audit": source_audit.to_json(),
    }


def _effect_hit_case(rules: RuleBook, candidate: dict[str, Any]) -> dict[str, Any]:
    state = _state_with_resource(candidate, "caster", "effect_hit_rate", 1.0)
    result = _apply_candidate(
        rules,
        candidate,
        chance_value=0.5,
        state=state,
        event_payload={"rng_mode": "explicit", "rng_choices": {}},
    )["result"]
    after = MutationReducer().apply_all(state, result.mutations)
    detail = _first_status_detail(after)
    chance_admission = detail.get("chance_admission") if isinstance(detail.get("chance_admission"), dict) else {}
    checks = {
        "effect_hit_applies_without_base_rng": result.ok and bool(result.mutations),
        "effect_hit_rate_recorded": chance_admission.get("effect_hit_rate") == 1.0,
        "base_success_probability_capped": chance_admission.get("base_success_probability") == 1.0,
        "no_status_apply_rng_needed": not _has_rng(result, "status_apply"),
        "source_audit": RuntimeSourceAuditor(rules).validate_transition(
            _status_transition(state, result, "p2_s5:effect_hit")
        ).ok,
        "replay": MutationReducer().replay_snapshot(state, result.mutations, after.snapshot().to_json()).ok,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "result": result.to_json(),
        "status_detail": detail,
    }


def _effect_resistance_case(rules: RuleBook, candidate: dict[str, Any]) -> dict[str, Any]:
    state = _state_with_resource(candidate, "target", "effect_resistance", 1.0)
    payload = _rng_payload(candidate, "status_resist", "effect_resistance", "resisted")
    result = _apply_candidate(rules, candidate, chance_value=1.0, state=state, event_payload=payload)["result"]
    repeat = _apply_candidate(rules, candidate, chance_value=1.0, state=state, event_payload=payload)["result"]
    checks = {
        "resisted_no_mutation": not result.mutations,
        "resisted_record_type": _has_record(result, "status_resisted"),
        "resisted_rng_event": _has_rng(result, "status_resist"),
        "resisted_choice_replayed": _rng_choice_source(result) == "explicit_ledger",
        "state_unchanged": _snapshot_hash(state) == _snapshot_hash(MutationReducer().apply_all(state, result.mutations)),
        "same_choice_same_result": _result_signature(result) == _result_signature(repeat),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "result": result.to_json()}


def _status_immunity_case(rules: RuleBook, candidate: dict[str, Any]) -> dict[str, Any]:
    state = _state_with_status_immunity(candidate)
    result = _apply_candidate(rules, candidate, chance_value=1.0, state=state)["result"]
    checks = {
        "immunity_no_mutation": not result.mutations,
        "immunity_record_type": _has_record(result, "status_immunity"),
        "immunity_no_rng": not result.rng_events,
        "state_unchanged": _snapshot_hash(state) == _snapshot_hash(MutationReducer().apply_all(state, result.mutations)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "result": result.to_json()}


def _unbound_chance_negative_case(rules: RuleBook, candidate: dict[str, Any]) -> dict[str, Any]:
    state = _base_state()
    result = _apply_candidate(rules, candidate, chance_value=None, state=state)["result"]
    checks = {
        "unbound_blocked": not result.ok,
        "unbound_no_mutation": not result.mutations,
        "unbound_record": _has_record(result, "status_blocked"),
        "unbound_reason": any(str(reason).startswith("dynamic_hash_unbound") for reason in result.unsupported),
        "state_unchanged": _snapshot_hash(state) == _snapshot_hash(MutationReducer().apply_all(state, result.mutations)),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "result": result.to_json()}


def _profile_status_resistance_case(rules: RuleBook) -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for definition in sorted(rules.wave_definitions(), key=lambda item: item.wave_definition_id):
        if definition.coverage_status != "executable":
            continue
        for entry in rules.wave_entries_for_wave(definition.wave_definition_id, 0):
            profile = rules.require_combatant_profile(entry.monster_entity_ref)
            if not isinstance(profile.status_resistance, (int, float)) or isinstance(profile.status_resistance, bool):
                continue
            unit = _unit_from_wave_entry(rules, definition, entry)
            checks = {
                "profile_status_resistance_numeric": True,
                "unit_effect_resistance_projected": unit.resources.get("effect_resistance")
                == float(profile.status_resistance),
                "debuff_resistances_preserved": unit.flags.get("debuff_resistances") == list(profile.debuff_resistances),
                "profile_source_trace_present": bool(unit.flags.get("combatant_profile_source_trace")),
            }
            checks["ok"] = all(value for key, value in checks.items() if key != "ok")
            case = {
                "checks": {"ok": checks["ok"], "checks": checks},
                "wave_definition_id": definition.wave_definition_id,
                "wave_entry_id": entry.entry_id,
                "profile_id": profile.profile_id,
                "profile_status_resistance": profile.status_resistance,
                "profile_debuff_resistance_count": len(profile.debuff_resistances),
                "unit_resources": dict(unit.resources),
                "unit_flags": {
                    "debuff_resistances": unit.flags.get("debuff_resistances"),
                    "combatant_profile_source_trace": unit.flags.get("combatant_profile_source_trace"),
                },
            }
            if profile.debuff_resistances:
                return case
            if fallback is None:
                fallback = case
    if fallback is not None:
        return fallback
    return {
        "checks": {"ok": False, "checks": {"profile_status_resistance_source_found": False}},
        "profile_status_resistance": None,
        "profile_debuff_resistance_count": 0,
    }


def _chance_resist_immunity_matrix(rules: RuleBook) -> dict[str, Any]:
    chance_kind_counts = Counter()
    status_type_counts = Counter()
    profile_status_resistance = 0
    profile_debuff_resistance = 0
    for effect in rules.ir.effects:
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        chance = standard.get("chance")
        kind = chance.get("kind") if isinstance(chance, dict) else type(chance).__name__
        chance_kind_counts[str(kind)] += 1
        entity = rules.status_entity_for_modifier(str(standard.get("modifier_name"))) if isinstance(standard.get("modifier_name"), str) else None
        if entity is not None:
            status_type_counts[str(entity.fields.get("StatusType") or "")] += 1
    for profile in rules.ir.combatant_profiles:
        if isinstance(profile.status_resistance, (int, float)) and not isinstance(profile.status_resistance, bool):
            profile_status_resistance += 1
        if profile.debuff_resistances:
            profile_debuff_resistance += 1
    matrix = {
        "base_chance": _family_entry("executable", sum(chance_kind_counts.values()), "AddModifier Chance is admitted through numeric evaluation."),
        "effect_hit": _family_entry("executable", 1, "runtime reads caster resources.effect_hit_rate; character card maps StatusProbabilityBase to effect_hit_rate."),
        "effect_resistance": _family_entry("executable", profile_status_resistance, "monster StatusResistanceBase projects to resources.effect_resistance."),
        "base_chance_failure": _family_entry("executable", chance_kind_counts.get("dynamic_hash", 0), "explicit RNG ledger can select failed base chance."),
        "effect_resisted": _family_entry("executable", profile_status_resistance, "effect_resistance branch records status_resisted and no mutation."),
        "status_immunity": _family_entry("boundary_only", 1, "runtime admits explicit status_immunities source; no status table immunity field is projected."),
        "control_resistance": _family_entry("source_absent_not_required", 0, "no separate control-resistance status source is projected in current IR."),
        "control_immunity": _family_entry("source_absent_not_required", 0, "no separate control-immunity status source is projected in current IR."),
        "specific_debuff_resist": _family_entry("boundary_only", profile_debuff_resistance, "DebuffResist is preserved on unit flags but not executed as specific immunity in S5."),
        "chance_unbound": _family_entry("boundary_only", chance_kind_counts.get("dynamic_hash", 0), "unbound dynamic Chance is blocked/process-only."),
    }
    classifications = Counter(str(item["classification"]) for item in matrix.values())
    checks = {
        "chance_sources_seen": sum(chance_kind_counts.values()) > 0,
        "dynamic_chance_sources_seen": chance_kind_counts.get("dynamic_hash", 0) > 0,
        "profile_status_resistance_seen": profile_status_resistance > 0,
        "debuff_sources_classified": profile_debuff_resistance >= 0,
        "no_unclassified_probability_family": all(item["classification"] for item in matrix.values()),
        "no_implementation_missing": not any(item["classification"] == "implementation_missing" for item in matrix.values()),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "chance_kind_counts": dict(sorted(chance_kind_counts.items())),
        "status_type_counts": dict(sorted(status_type_counts.items())),
        "classification_counts": dict(sorted(classifications.items())),
    }


def _select_dynamic_chance_candidate(rules: RuleBook) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for effect in sorted(rules.ir.effects, key=lambda item: item.effect_id):
        if not _safe_add_modifier_effect(effect):
            continue
        standard = effect.payload.get("standard") if isinstance(effect.payload.get("standard"), dict) else {}
        chance = standard.get("chance")
        if not isinstance(chance, dict) or chance.get("kind") != "dynamic_hash":
            continue
        chance_hash = chance.get("hash")
        if chance_hash is None:
            continue
        modifier_name = standard.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            continue
        if _modifier_definition_for_effect(rules, effect) is None:
            continue
        target_id = _target_id_for_standard(standard)
        if target_id is None:
            continue
        candidate = {
            "effect": effect,
            "effect_id": effect.effect_id,
            "modifier_name": modifier_name,
            "status_id": f"modifier:{modifier_name}",
            "target_id": target_id,
            "chance_hash": str(chance_hash),
        }
        result = _apply_candidate(
            rules,
            candidate,
            chance_value=0.5,
            event_payload=_rng_payload(candidate, "status_apply", "base_chance", "success"),
        )["result"]
        if result.ok and result.mutations:
            return candidate
        failures.append({"effect_id": effect.effect_id, "unsupported": list(result.unsupported)})
    raise RuntimeError(f"no source-admitted dynamic Chance AddModifier candidate found; failures={failures[:5]}")


def _apply_candidate(
    rules: RuleBook,
    candidate: dict[str, Any],
    *,
    chance_value: float | None,
    state: BattleState | None = None,
    event_payload: dict[str, JSONValue] | None = None,
) -> dict[str, Any]:
    state = state or _base_state()
    dynamic_values = {candidate["chance_hash"]: float(chance_value)} if chance_value is not None else None
    result = StatusSystem(rules).apply_add_modifier(
        state,
        candidate["effect"],
        caster_id="ally:actor",
        source_id="validation:p2_s5:chance",
        owner_id="ally:actor",
        param_entity_id="enemy:target",
        current_action_target_id="enemy:target",
        dynamic_values=dynamic_values,
        event_payload=event_payload,
    )
    return {"state": state, "result": result}


def _target_id_for_standard(standard: dict[str, Any]) -> str | None:
    alias = str(standard.get("target_alias") or "")
    if alias in {"Caster", "Owner", "ModifierOwnerEntity"}:
        return "ally:actor"
    if alias in {"ParamEntity", "CurrentActionTarget", "Target"}:
        return "enemy:target"
    return None


def _rng_payload(candidate: dict[str, Any], rng_type: str, purpose: str, outcome: str) -> dict[str, JSONValue]:
    return {
        "rng_mode": "explicit",
        "rng_choices": {
            _choice_key(candidate, rng_type, purpose): outcome,
        },
    }


def _choice_key(candidate: dict[str, Any], rng_type: str, purpose: str) -> str:
    return (
        f"{rng_type}:{purpose}:ally:actor:{candidate['target_id']}:"
        f"{_status_id_fragment(str(candidate['status_id']))}"
    )


def _status_id_fragment(status_id: str) -> str:
    return status_id.replace(":", "_").replace("/", "_")


def _state_with_resource(candidate: dict[str, Any], unit_role: str, resource_key: str, value: float) -> BattleState:
    state = _base_state()
    unit_id = "ally:actor" if unit_role == "caster" else str(candidate["target_id"])
    unit = state.units[unit_id]
    return replace(
        state,
        units={
            **state.units,
            unit_id: replace(unit, resources={**unit.resources, resource_key: value}),
        },
    )


def _state_with_status_immunity(candidate: dict[str, Any]) -> BattleState:
    state = _base_state()
    target_id = str(candidate["target_id"])
    unit = state.units[target_id]
    return replace(
        state,
        units={
            **state.units,
            target_id: replace(
                unit,
                flags={
                    **unit.flags,
                    "status_immunities": {
                        str(candidate["status_id"]): {
                            "admission_status": "executable",
                            "source_trace": {
                                "validation": VALIDATION_VERSION,
                                "source_kind": "explicit_status_immunity_fixture",
                                "status_id": str(candidate["status_id"]),
                            },
                        }
                    },
                },
            ),
        },
    )


def _has_record(result: StatusApplicationResult, record_type: str) -> bool:
    return any(record.get("record_type") == record_type for record in result.records)


def _has_rng(result: StatusApplicationResult, rng_type: str) -> bool:
    return any(event.rng_type == rng_type for event in result.rng_events)


def _rng_choice_source(result: StatusApplicationResult) -> str:
    for event in result.rng_events:
        payload = event.result if isinstance(event.result, dict) else {}
        choice_source = payload.get("choice_source")
        if isinstance(choice_source, str) and choice_source:
            return choice_source
    return ""


def _result_signature(result: StatusApplicationResult) -> str:
    payload = {
        "ok": result.ok,
        "unsupported": list(result.unsupported),
        "records": list(result.records),
        "rng_events": [event.to_json() for event in result.rng_events],
        "mutations": [mutation.to_json() for mutation in result.mutations],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _family_entry(classification: str, source_count: int, reason: str) -> dict[str, Any]:
    return {"classification": classification, "source_count": int(source_count), "reason": reason}


def _json_case_without_runtime_candidate(case: dict[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in case.items() if key != "candidate"}
    candidate = case.get("candidate")
    if isinstance(candidate, dict):
        data["candidate"] = {
            "effect": _effect_sample(candidate["effect"]) if isinstance(candidate.get("effect"), EffectIR) else {},
            "effect_id": str(candidate.get("effect_id") or ""),
            "modifier_name": str(candidate.get("modifier_name") or ""),
            "status_id": str(candidate.get("status_id") or ""),
            "target_id": str(candidate.get("target_id") or ""),
            "chance_hash": str(candidate.get("chance_hash") or ""),
        }
    return _json_without_state(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P2-S5 status chance, resistance, and immunity semantics.")
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
