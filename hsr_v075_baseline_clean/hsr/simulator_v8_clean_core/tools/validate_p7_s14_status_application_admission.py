from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..core.model import BattleState, UnitState
from ..rules.expression_ir import NUMERIC_EXPRESSION_SCHEMA
from ..rules.ir import CanonicalIR, EffectIR, IRSource, RuleEntity
from ..rules.rulebook import RuleBook
from ..systems.status import (
    StatusSystem,
    _complete_status_admission_blocked_reason,
    _duration_admission_from_expr,
    _runtime_chance_admission,
    _runtime_dispel_count_admission,
    _runtime_stack_admission,
    _select_modifier_definition,
    _status_chance_check,
)
from .io import write_json


VALIDATION_VERSION = "p7_s14_status_application_admission"


def run_validation(output_dir: Path) -> dict[str, Any]:
    cases = {
        "positive_status": _decision_case("buff", chance=0.5, effect_resistance=0.9),
        "guaranteed_application": _guaranteed_case(),
        "ordinary_debuff": _decision_case("debuff", chance=0.5, effect_hit=0.2, effect_resistance=0.25),
        "multiply_before_clamp": _decision_case(
            "debuff", chance=0.8, effect_hit=1.0, effect_resistance=0.5
        ),
        "base_chance_above_one": _decision_case(
            "debuff", chance=1.5, effect_hit=0.0, effect_resistance=0.5
        ),
        "control_status": _decision_case(
            "control",
            chance=0.8,
            effect_resistance=0.1,
            control_resistance=0.2,
            specific_resistance=0.25,
            control_kind="freeze",
        ),
        "special_debuff": _special_case(),
        "immunity": _immunity_case(),
        "classification_missing": _classification_missing_case(),
        "omitted_semantics_missing": _omitted_semantics_missing_case(),
        "ambiguous_definition_link": _ambiguous_definition_case(),
        "partial_no_mutation_gate": _partial_gate_case(),
        "typed_program_numeric_fields": _typed_program_case(),
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
            "fixture_kind": "kernel_invariant_fixture",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_p7_s14_status_application_admission.json", result)
    write_json(output_dir / "p7_s14_status_application_matrix.json", {"rows": rows})
    write_json(output_dir / "p7_s14_status_application_evidence.json", cases)
    return result


def _decision_case(
    category: str,
    *,
    chance: float,
    effect_hit: float = 0.0,
    effect_resistance: float = 0.0,
    control_resistance: float = 0.0,
    specific_resistance: float = 0.0,
    control_kind: str = "",
) -> dict[str, Any]:
    state = _state(
        effect_hit=effect_hit,
        effect_resistance=effect_resistance,
        control_resistance=control_resistance,
        specific_resistance=specific_resistance,
        control_kind=control_kind,
    )
    admission = _runtime_chance_admission(
        {"modifier_name": "ValidationStatus", "chance": {"kind": "fixed", "value": chance}},
        _effect(),
        state,
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": category, "control_kind": control_kind},
    )
    check = _status_chance_check(
        state,
        _effect(),
        admission,
        caster_id="ally:caster",
        target_id="enemy:target",
        modifier_name="ValidationStatus",
        status_id="modifier:ValidationStatus",
        source_stack_key="validation:stack",
        event_payload=None,
    )
    expected = {
        "buff": chance,
        "debuff": min(1.0, chance * (1.0 + effect_hit) * (1.0 - effect_resistance)),
        "control": min(
            1.0,
            chance
            * (1.0 + effect_hit)
            * (1.0 - effect_resistance)
            * (1.0 - control_resistance)
            * (1.0 - specific_resistance),
        ),
    }[category]
    expected_classification = {"buff": "positive_status", "debuff": "debuff", "control": "control"}[category]
    checks = _checks(
        {
            "admitted": admission.get("admission_status") == "executable",
            "classification": admission.get("classification") == expected_classification,
            "final_probability": abs(float(admission.get("final_success_probability") or 0.0) - expected) < 1e-9,
            "single_final_decision": len(check.rng_events) == (1 if 0.0 < expected < 1.0 else 0),
            "final_decision_purpose": not check.rng_events
            or "final_status_application" in str(check.rng_events[0].to_json()),
            "no_separate_resist_rng": all(event.rng_type != "status_resist" for event in check.rng_events),
        }
    )
    return {"checks": checks, "admission": admission, "rng_events": [event.to_json() for event in check.rng_events]}


def _guaranteed_case() -> dict[str, Any]:
    state = _state(effect_resistance=1.0)
    admission = _runtime_chance_admission(
        {
            "modifier_name": "Guaranteed",
            "chance": {"kind": "missing"},
            "omitted_chance_semantics": "guaranteed_no_resistance",
            "omitted_chance_semantics_source": {"kind": "engine_rule", "rule_id": "validation"},
        },
        _effect(),
        state,
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "debuff", "control_kind": ""},
    )
    check = _chance_check(state, admission, "Guaranteed")
    checks = _checks(
        {
            "classification": admission.get("classification") == "guaranteed",
            "probability_one": admission.get("final_success_probability") == 1.0,
            "resistance_skipped": admission.get("effect_resistance") == 0.0,
            "no_rng": not check.rng_events,
            "allowed": check.allowed,
        }
    )
    return {"checks": checks, "admission": admission}


def _special_case() -> dict[str, Any]:
    state = _state(specific_resistance=0.5, control_kind="special")
    standard = {
        "modifier_name": "Special",
        "chance": {"kind": "fixed", "value": 0.5},
        "special_resistance_key": "special_resistance:special",
        "special_resistance_source": {"kind": "status_definition", "id": "special"},
    }
    admission = _runtime_chance_admission(
        standard,
        _effect(),
        state,
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "other", "control_kind": ""},
    )
    checks = _checks(
        {
            "classification": admission.get("classification") == "special_debuff",
            "specific_resistance_applied": admission.get("specific_resistance") == 0.5,
            "final_probability": admission.get("final_success_probability") == 0.25,
        }
    )
    return {"checks": checks, "admission": admission}


def _immunity_case() -> dict[str, Any]:
    state = _state()
    target = state.units["enemy:target"]
    state = BattleState(
        units={
            **state.units,
            target.unit_id: UnitState(
                **{
                    **target.__dict__,
                    "flags": {
                        "status_immunities": {
                            "modifier:ValidationStatus": {
                                "admission_status": "executable",
                                "source_trace": {"kind": "validation"},
                            }
                        }
                    },
                }
            ),
        }
    )
    admission = _runtime_chance_admission(
        {"modifier_name": "ValidationStatus", "chance": {"kind": "fixed", "value": 0.5}},
        _effect(),
        state,
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "debuff", "control_kind": ""},
    )
    check = _chance_check(state, admission, "ValidationStatus")
    checks = _checks(
        {
            "not_allowed": not check.allowed,
            "no_rng": not check.rng_events,
            "immunity_record": bool(check.record) and check.record.get("record_type") == "status_immunity",
        }
    )
    return {"checks": checks, "record": check.record}


def _classification_missing_case() -> dict[str, Any]:
    admission = _runtime_chance_admission(
        {"modifier_name": "Unknown", "chance": {"kind": "fixed", "value": 0.5}},
        _effect(),
        _state(),
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "unknown", "control_kind": ""},
    )
    return {
        "checks": _checks(
            {
                "blocked": admission.get("admission_status") == "blocked",
                "reason": str(admission.get("blocked_reason") or "").startswith("status_probability_category_not_admitted"),
            }
        ),
        "admission": admission,
    }


def _omitted_semantics_missing_case() -> dict[str, Any]:
    admission = _runtime_chance_admission(
        {"modifier_name": "Unknown", "chance": {"kind": "missing"}},
        _effect(),
        _state(),
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "debuff", "control_kind": ""},
    )
    return {
        "checks": _checks(
            {
                "blocked": admission.get("admission_status") == "blocked",
                "reason": admission.get("blocked_reason") == "omitted_chance_semantics_source_missing",
            }
        ),
        "admission": admission,
    }


def _ambiguous_definition_case() -> dict[str, Any]:
    definition_a = _definition("a")
    definition_b = _definition("b")

    class Rules:
        def entity(self, _: str):
            return None

        def modifier_definitions(self, _: str):
            return (definition_a, definition_b)

    selected = _select_modifier_definition(Rules(), "ValidationStatus", _effect())  # type: ignore[arg-type]
    return {
        "checks": _checks({"ambiguous_link_blocked": selected is None, "no_first_match": selected is not definition_a}),
        "candidate_count": 2,
    }


def _partial_gate_case() -> dict[str, Any]:
    reason = _complete_status_admission_blocked_reason(
        standard={"dynamic_value_requests": {"missing": {}}},
        resolved_dynamic_values={},
        duration_admission={"admission_status": "executable"},
        stack_admission={"admission_status": "executable"},
        refresh_admission={"admission_status": "executable"},
        chance_admission={"admission_status": "executable"},
        trigger_ids_by_event={},
        unsupported=("unsupported_property:Validation",),
        require_listener_free=False,
    )
    state = _state()
    effect = EffectIR(
        effect_id="validation:legacy_target_blocked",
        opcode="AddModifier",
        payload={
            "standard": {
                "modifier_name": "ValidationStatus",
                "target_alias": "AbilityTargetEntity",
            }
        },
        source=_effect().source,
        coverage_status="executable",
        source_mode="mainline",
    )
    rules = RuleBook(CanonicalIR(version="validation", entities=(_definition("partial"),), effects=(effect,)))
    before = state.snapshot().to_json()
    result = StatusSystem(rules).apply_add_modifier(
        state,
        effect,
        caster_id="ally:caster",
        source_id="validation:partial",
        current_action_target_id="enemy:target",
    )
    after = state.snapshot().to_json()
    return {
        "checks": _checks(
            {
                "blocked_before_instance": bool(reason),
                "structured_reason": reason.startswith("status_dynamic_value_unresolved"),
                "legacy_target_alias_blocked": any("target_expression_id_missing" in item for item in result.unsupported),
                "mutation_count": len(result.mutations) == 0,
                "state_unchanged": before == after,
            }
        ),
        "blocked_reason": reason,
        "runtime_unsupported": list(result.unsupported),
        "mutations": [mutation.to_json() for mutation in result.mutations],
    }


def _typed_program_case() -> dict[str, Any]:
    chance = _program(0.25, 0.25, "add")
    max_layer = _program(2.0, 1.0, "add")
    layer_add = _program(0.5, 0.5, "add")
    duration = _program(1.0, 1.0, "add")
    dispel_count = _program(0.5, 0.5, "add")
    state = _state()
    chance_admission = _runtime_chance_admission(
        {"modifier_name": "ValidationStatus", "chance": chance},
        _effect(),
        state,
        caster_id="ally:caster",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
        status_metadata={"status_category": "debuff", "control_kind": ""},
    )
    stack_admission = _runtime_stack_admission(
        {
            "modifier_name": "ValidationStatus",
            "max_layer": max_layer,
            "layer_add_when_stack": layer_add,
        },
        _effect(),
        binding_sources=(),
    )
    duration_admission = _duration_admission_from_expr(
        duration,
        "ModifierPhase1End",
        source_kind="effect",
        source_trace={"kind": "validation"},
        binding_sources=(),
        modifier_name="ValidationStatus",
    )
    dispel_admission = _runtime_dispel_count_admission(
        {"numbers": dispel_count},
        _effect(),
        dynamic_values=None,
        binding_sources=(),
    )
    checks = _checks(
        {
            "chance_program_executable": chance_admission.get("admission_status") == "executable"
            and chance_admission.get("base_chance") == 0.5,
            "stack_program_executable": stack_admission.get("admission_status") == "executable"
            and stack_admission.get("max_stacks") == 3
            and stack_admission.get("layer_delta") == 1,
            "duration_program_executable": duration_admission.get("admission_status") == "executable"
            and duration_admission.get("remaining_duration") == 2.0,
            "dispel_program_executable": dispel_admission.get("admission_status") == "executable"
            and dispel_admission.get("count") == 1,
            "all_evaluations_report_program": all(
                admission.get("numeric_evaluation", {}).get("expression_kind") == "program"
                for admission in (chance_admission, duration_admission, dispel_admission)
            ),
        }
    )
    return {
        "checks": checks,
        "chance": chance_admission,
        "stack": stack_admission,
        "duration": duration_admission,
        "dispel": dispel_admission,
    }


def _program(lhs: float, rhs: float, opcode: str) -> dict[str, Any]:
    return {
        "schema_version": NUMERIC_EXPRESSION_SCHEMA,
        "kind": "program",
        "supported": True,
        "instructions": [
            {"opcode": "push_fixed", "value": lhs},
            {"opcode": "push_fixed", "value": rhs},
            {"opcode": opcode},
            {"opcode": "end"},
        ],
    }


def _chance_check(state: BattleState, admission: dict[str, Any], modifier_name: str):
    return _status_chance_check(
        state,
        _effect(),
        admission,
        caster_id="ally:caster",
        target_id="enemy:target",
        modifier_name=modifier_name,
        status_id=f"modifier:{modifier_name}",
        source_stack_key="validation:stack",
        event_payload=None,
    )


def _state(
    *,
    effect_hit: float = 0.0,
    effect_resistance: float = 0.0,
    control_resistance: float = 0.0,
    specific_resistance: float = 0.0,
    control_kind: str = "",
) -> BattleState:
    return BattleState(
        units={
            "ally:caster": UnitState(
                "ally:caster",
                "ally",
                "validation:caster",
                resources={"effect_hit_rate": effect_hit},
            ),
            "enemy:target": UnitState(
                "enemy:target",
                "enemy",
                "validation:target",
                resources={
                    "effect_resistance": effect_resistance,
                    "control_resistance": control_resistance,
                    f"control_resistance:{control_kind}": specific_resistance,
                    f"special_resistance:{control_kind}": specific_resistance,
                },
            ),
        }
    )


def _effect() -> EffectIR:
    return EffectIR(
        effect_id="validation:add_modifier",
        opcode="AddModifier",
        payload={"standard": {}},
        source=IRSource("validation/status.json", "AddModifier", "validation", {"fixture": True}),
        coverage_status="executable",
        source_mode="mainline",
    )


def _definition(suffix: str) -> RuleEntity:
    return RuleEntity(
        entity_id=f"modifier_definition:{suffix}",
        entity_type="modifier_definition",
        fields={"modifier_name": "ValidationStatus"},
        source=IRSource(f"validation/{suffix}.json", "ModifierDefinition", suffix),
        coverage_status="executable",
    )


def _checks(values: dict[str, bool]) -> dict[str, Any]:
    return {"ok": all(values.values()), **values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate P7-S14 status application admission.")
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
