from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import GameEvent
from ..rules.ir import CharacterDataCardIR, CharacterMechanismSlotIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from ..systems.effect import EffectRegistry
from ..systems.event_dispatch import EventDispatchSystem
from ..systems.status import StatusSystem
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks


VALIDATION_VERSION = "v0_276"
SEELE_ENTITY_REF = "avatar:1102"
ADVANCED_TRACE_ID = "11102101"
BASE_TRACE_ID = "1102101"
STARTUP_MODIFIER = "MAvatar_Seele_00_SkillTree01"
KILL_DAMAGE_MODIFIER = "MAvatar_Advanced_Seele_00_SkillTree01_KillDamageRatio"


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    card = _seele_card(rules)
    admission_case = _advanced_trace_admission_case(rules, card)
    startup_case = _advanced_trace_startup_case(rules, card)
    trigger_case = _advanced_trace_death_trigger_case(rules, card)
    blocked_case = _base_trace_remains_blocked_case(rules, card)
    checks = {
        "advanced_trace_admission": admission_case["checks"],
        "advanced_trace_startup": startup_case["checks"],
        "advanced_trace_death_trigger": trigger_case["checks"],
        "base_trace_blocked_negative": blocked_case["checks"],
        "static": {"ok": static_result.ok, "checks": {"static_checks": static_result.ok}},
    }
    result = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": all(item["ok"] for item in checks.values()),
        "build": {
            "tbgd_root": tbgd_root.as_posix(),
            "sampled": ir.metadata.get("sampled", {}),
            "selection_policy": {
                "card": "Seele is the user-requested enhanced-card example; core/runtime remains free of Seele special cases.",
                "trace": "Selected from CharacterTraceNodeIR source.evidence.enhanced_id and trace_id, then verified through CharacterMechanismSlotIR startup admission.",
                "runtime": "Runtime executes only admitted standalone ability graph + AddModifier through generic StatusSystem/EventDispatchSystem.",
                "negative": "Base trace ability hook remains blocked and does not apply a startup status.",
            },
        },
        "checks": checks,
        "advanced_trace_admission_case": admission_case,
        "advanced_trace_startup_case": startup_case,
        "advanced_trace_death_trigger_case": trigger_case,
        "base_trace_blocked_negative_case": blocked_case,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_276.json", result)
    write_json(output_dir / "advanced_trace_admission_case_v0_276.json", admission_case)
    write_json(output_dir / "advanced_trace_startup_case_v0_276.json", startup_case)
    write_json(output_dir / "advanced_trace_death_trigger_case_v0_276.json", trigger_case)
    write_json(output_dir / "base_trace_blocked_negative_case_v0_276.json", blocked_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_276 enhanced Seele trace startup ability hook.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _seele_card(rules: RuleBook) -> CharacterDataCardIR:
    card = rules.character_data_card_for_entity(SEELE_ENTITY_REF)
    if card is None:
        raise RuntimeError("Seele character data card missing")
    return card


def _advanced_trace_admission_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    slot = _trace_ability_slot(rules, card, trace_id=ADVANCED_TRACE_ID)
    admission = slot.semantics.get("startup_admission") if slot else None
    admitted_tasks = admission.get("admitted_tasks") if isinstance(admission, dict) else None
    binding = {}
    if isinstance(admitted_tasks, list) and admitted_tasks:
        first = admitted_tasks[0]
        if isinstance(first, dict):
            binding = first.get("dynamic_value_binding") if isinstance(first.get("dynamic_value_binding"), dict) else {}
    bindings = binding.get("bindings") if isinstance(binding, dict) else None
    value_by_name = {
        str(item.get("name")): float(item.get("value"))
        for item in bindings or ()
        if isinstance(item, dict) and isinstance(item.get("value"), (int, float))
    }
    checks = {
        "slot_exists": slot is not None,
        "slot_is_enhanced_trace": bool(slot and slot.source.evidence.get("enhanced_id") is not None),
        "slot_executable": bool(slot and slot.coverage_status == "executable"),
        "startup_admission_executable": isinstance(admission, dict) and admission.get("admission_status") == "executable",
        "on_start_add_modifier_task_admitted": isinstance(admitted_tasks, list) and bool(admitted_tasks),
        "dynamic_values_bound_from_skill_tree_param": isinstance(bindings, list)
        and all(
            isinstance(item, dict)
            and item.get("binding_source", {}).get("read_info", {}).get("Type") == "SkillTreeParam"
            for item in bindings
        ),
        "dynamic_values_match_trace_params": value_by_name
        == {"MDF_DamageRatio": 0.5, "MDF_MaxLayer": 3.0, "MDF_LiftTime": 3.0},
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "slot": slot.to_json() if slot else {},
        "dynamic_value_values": value_by_name,
    }


def _advanced_trace_startup_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    built = _state_with_trace(rules, card, trace_id=ADVANCED_TRACE_ID)
    unit = built.state.units["ally:seele"]
    startup_detail = _detail_by_modifier(unit.flags.get("status_details", ()), STARTUP_MODIFIER)
    dynamic = startup_detail.get("dynamic_values", {}) if startup_detail else {}
    by_name = dynamic.get("__by_name") if isinstance(dynamic, dict) else {}
    traces = [trace for trace in built.source_traces if trace.get("kind") == "trace_startup_ability"]
    checks = {
        "startup_modifier_present": f"modifier:{STARTUP_MODIFIER}" in unit.statuses,
        "startup_detail_present": startup_detail is not None,
        "startup_dynamic_values_present": by_name
        == {"MDF_DamageRatio": 0.5, "MDF_MaxLayer": 3.0, "MDF_LiftTime": 3.0},
        "startup_trigger_registered": bool(
            startup_detail
            and "OnTriggerDeath" in (startup_detail.get("trigger_ids_by_event") or {})
        ),
        "startup_source_trace_applied": any(trace.get("status") == "applied" for trace in traces),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "unit_snapshot": unit.to_snapshot(),
        "startup_source_traces": traces,
    }


def _advanced_trace_death_trigger_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    built = _state_with_trace(rules, card, trace_id=ADVANCED_TRACE_ID, target_hp=0.0)
    event = GameEvent(
        "unit.defeated",
        source_id="ally:seele",
        target_id="enemy:target",
        window="OnTriggerDeath",
        process_only=True,
        payload={
            "actor_id": "ally:seele",
            "target_id": "enemy:target",
            "defeated_unit_id": "enemy:target",
        },
    )
    result = EventDispatchSystem(rules, EffectRegistry(StatusSystem(rules))).dispatch_event(built.state, event=event)
    unit = result.after_state.units["ally:seele"]
    kill_detail = _detail_by_modifier(unit.flags.get("status_details", ()), KILL_DAMAGE_MODIFIER)
    dynamic = kill_detail.get("dynamic_values", {}) if kill_detail else {}
    nonfatal_stack_partial = bool(result.errors) and all(
        str(error) == "stack_partial:layer_add_when_stack_missing" for error in result.errors
    )
    checks = {
        "dispatch_errors_empty_or_nonfatal_stack_partial": not result.errors or nonfatal_stack_partial,
        "death_trigger_mutated_state": len(result.mutations) >= 2,
        "kill_damage_modifier_present": f"modifier:{KILL_DAMAGE_MODIFIER}" in unit.statuses,
        "kill_damage_detail_present": kill_detail is not None,
        "kill_damage_duration_from_trace": kill_detail is not None and kill_detail.get("duration") == 3.0,
        "kill_damage_ratio_from_trace": isinstance(dynamic, dict)
        and dynamic.get("__by_name", {}).get("MDF_DamageRatio") == 0.5,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "events": [item.to_json() for item in result.events],
        "records": list(result.records),
        "dispatch_errors": list(result.errors),
        "mutations": [mutation.to_json() for mutation in result.mutations],
        "after_unit_snapshot": unit.to_snapshot(),
    }


def _base_trace_remains_blocked_case(rules: RuleBook, card: CharacterDataCardIR) -> dict[str, Any]:
    slot = _trace_ability_slot(rules, card, trace_id=BASE_TRACE_ID)
    built = _state_with_trace(rules, card, trace_id=BASE_TRACE_ID)
    unit = built.state.units["ally:seele"]
    blocked_slots = unit.flags.get("trace_static_stat_blocked_slots", ())
    checks = {
        "base_slot_exists": slot is not None,
        "base_slot_not_executable": bool(slot and slot.coverage_status != "executable"),
        "base_startup_modifier_not_applied": not any(
            str(status).startswith("modifier:MAvatar_Seele_00_LowHP_AggroDown")
            for status in unit.statuses
        ),
        "base_blocked_recorded": isinstance(blocked_slots, (list, tuple)) and bool(blocked_slots),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "slot": slot.to_json() if slot else {},
        "unit_snapshot": unit.to_snapshot(),
    }


def _state_with_trace(
    rules: RuleBook,
    card: CharacterDataCardIR,
    *,
    trace_id: str,
    target_hp: float = 1000.0,
):
    trace_node_id = _trace_node_id(rules, card, trace_id)
    if not trace_node_id:
        raise RuntimeError(f"trace node missing: {trace_id}")
    scenario = ScenarioSpec(
        scenario_id=f"{VALIDATION_VERSION}_trace_{trace_id}",
        version=VALIDATION_VERSION,
        units=(
            UnitSpec(
                unit_id="ally:seele",
                side="ally",
                build_mode="kernel_fixture",
                entity_ref=card.entity_ref,
                level=80,
                eidolon_level=0,
                panel=PanelInput(
                    max_hp=3000.0,
                    hp=3000.0,
                    attack=1000.0,
                    defense=500.0,
                    speed=115.0,
                    energy=0.0,
                    max_energy=120.0,
                    flags={"enabled_trace_node_ids": (trace_node_id,)},
                ),
            ),
            UnitSpec(
                unit_id="enemy:target",
                side="enemy",
                build_mode="kernel_fixture",
                entity_ref="monster:1002011",
                level=80,
                panel=PanelInput(
                    max_hp=1000.0,
                    hp=target_hp,
                    attack=100.0,
                    defense=100.0,
                    speed=100.0,
                    toughness=90.0,
                    max_toughness=90.0,
                ),
            ),
        ),
        route=(),
    )
    return ScenarioStateBuilder(rules).build(scenario)


def _trace_ability_slot(
    rules: RuleBook,
    card: CharacterDataCardIR,
    *,
    trace_id: str,
) -> CharacterMechanismSlotIR | None:
    trace_node_id = _trace_node_id(rules, card, trace_id)
    if not trace_node_id:
        return None
    for slot in rules.character_mechanism_slots_for_card(card.card_id):
        if (
            slot.mechanism_kind == "trace_ability_hook"
            and slot.linked_ir_ids.get("trace_node_id") == trace_node_id
        ):
            return slot
    return None


def _trace_node_id(rules: RuleBook, card: CharacterDataCardIR, trace_id: str) -> str:
    for node in rules.character_trace_nodes_for_card(card.card_id):
        if node.trace_id == trace_id:
            return node.trace_node_id
    return ""


def _detail_by_modifier(details: object, modifier_name: str) -> dict[str, Any] | None:
    if not isinstance(details, (list, tuple)):
        return None
    for detail in details:
        if isinstance(detail, dict) and detail.get("modifier_name") == modifier_name:
            return detail
    return None


if __name__ == "__main__":
    raise SystemExit(main())
