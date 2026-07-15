from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .. import BASELINE_VERSION
from ..core.model import BattleState, UnitState
from ..core.source_audit import RuntimeSourceAuditor
from ..rules.ir import CharacterDataCardIR, CharacterMechanismSlotIR, StatusCallbackIR
from ..rules.rulebook import RuleBook
from ..scenarios.build_state import ScenarioStateBuilder
from ..scenarios.schema import PanelInput, ScenarioSpec, UnitSpec
from ..systems.scheduler import CombatScheduler
from ..tbgd.lowering import TBGDLowering
from ..tbgd.paths import find_tbgd_root
from .io import write_json
from .static_checks import run_static_checks
from .validate_v0_254 import _transition_checks


VALIDATION_VERSION = "v0_271"

FOUNDATIONAL_CALLBACK_EVENTS = {
    "OnBeforeSkillUse",
    "OnBeforeHit",
    "OnAfterAttack",
    "OnActionEnd",
    "OnCreate",
    "OnDestroy",
    "OnEnterBattle",
    "OnListenTurnEnd",
    "OnBeforeInsertActionPrepare",
    "OnInsertActionStart",
    "OnInsertActionFinish",
    "OnListenInsertAbilityFinish",
    "OnCustomEvent",
    "OnWaveMonster",
}


def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, object]:
    ir = TBGDLowering(tbgd_root).build()
    rules = RuleBook(ir)
    static_result = run_static_checks(package_root)
    trace_case = _trace_static_stat_case(rules)
    eidolon_case = _eidolon_generic_case(rules)
    callback_case = _event_callback_case(rules)
    runtime_boundary = _runtime_boundary_case(package_root)
    checks = {
        "trace_static_stat": trace_case["checks"],
        "eidolon_generic": eidolon_case["checks"],
        "event_callbacks": callback_case["checks"],
        "runtime_boundary": runtime_boundary["checks"],
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
                "trace_static_stat": "Selected by executable CharacterMechanismSlotIR(kind=trace_static_stat_bonus), not by character name.",
                "eidolon_generic": "Selected by CharacterEidolonSlotIR semantics for prefix switch and SkillAddLevelList.",
                "event_callbacks": "Selected by StatusCallbackIR.event/opcode/coverage_status and executable runtime task evidence.",
            },
        },
        "checks": checks,
        "trace_static_stat_case": trace_case,
        "eidolon_generic_case": eidolon_case,
        "event_callback_case": callback_case,
        "runtime_boundary_case": runtime_boundary,
        "static_checks": static_result.to_json(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "validation_summary_v0_271.json", result)
    write_json(output_dir / "trace_static_stat_case_v0_271.json", trace_case)
    write_json(output_dir / "eidolon_generic_case_v0_271.json", eidolon_case)
    write_json(output_dir / "event_callback_matrix_v0_271.json", callback_case)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate v8 v0_271 trace, eidolon, and foundational event callback contract.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    hsr_root = package_root.parent
    tbgd_root = args.tbgd_root or find_tbgd_root(hsr_root)
    result = run_validation(package_root, tbgd_root, args.output_dir)
    print(f"v8 {VALIDATION_VERSION} validation ok={result['ok']}")
    return 0 if result["ok"] else 1


def _trace_static_stat_case(rules: RuleBook) -> dict[str, Any]:
    sample = _select_trace_static_slot(rules)
    if sample is None:
        checks = {"trace_static_executable_slot_exists": False}
        return {"checks": {"ok": False, "checks": checks}, "blocking_dependency": "trace_static_stat_bonus_slot_missing"}
    card, slot, trace_node_id, term = sample
    key = str(term.get("target_key") or "")
    kind = str(term.get("application_kind") or "")
    value = float(term.get("value") or 0.0)
    base_panel = PanelInput(
        max_hp=1000.0,
        hp=None,
        attack=100.0,
        defense=100.0,
        speed=100.0,
        energy=0.0,
        max_energy=120.0,
        resources={"critical_chance": 0.0, "critical_damage": 0.5},
    )
    enabled = ScenarioStateBuilder(rules).build(
        ScenarioSpec(
            scenario_id="v0_271_trace_enabled",
            version=VALIDATION_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:trace",
                    side="ally",
                    build_mode="kernel_fixture",
                    entity_ref=card.entity_ref,
                    panel=_replace_panel_flags(base_panel, {"enabled_trace_node_ids": (trace_node_id,)}),
                ),
            ),
            route=(),
        )
    )
    disabled = ScenarioStateBuilder(rules).build(
        ScenarioSpec(
            scenario_id="v0_271_trace_disabled",
            version=VALIDATION_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:trace",
                    side="ally",
                    build_mode="kernel_fixture",
                    entity_ref=card.entity_ref,
                    panel=base_panel,
                ),
            ),
            route=(),
        )
    )
    enabled_unit = enabled.state.units["ally:trace"]
    disabled_unit = disabled.state.units["ally:trace"]
    if kind == "base_stat_ratio":
        before = _unit_stat(disabled_unit, key)
        after = _unit_stat(enabled_unit, key)
        expected = before * (1.0 + value)
        applied = abs(after - expected) < 1e-9
    elif kind == "base_stat_delta":
        before = _unit_stat(disabled_unit, key)
        after = _unit_stat(enabled_unit, key)
        expected = before + value
        applied = abs(after - expected) < 1e-9
    else:
        before = float(disabled_unit.resources.get(key, 0.0))
        after = float(enabled_unit.resources.get(key, 0.0))
        expected = before + value
        applied = abs(after - expected) < 1e-9
    flags = enabled_unit.flags
    checks = {
        "trace_static_executable_slot_exists": slot.coverage_status == "executable",
        "trace_enabled_flag_recorded": trace_node_id in tuple(flags.get("enabled_trace_node_ids", ())),
        "trace_disabled_has_no_bonus": not disabled_unit.flags.get("trace_static_stat_bonus_terms"),
        "trace_bonus_applied": applied,
        "trace_source_trace_recorded": bool(flags.get("trace_source_traces")),
        "trace_terms_recorded": bool(flags.get("trace_static_stat_bonus_terms")),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "sample": {
            "card_id": card.card_id,
            "trace_node_id": trace_node_id,
            "slot": slot.to_json(),
            "term": term,
            "expected": expected,
            "enabled_unit": enabled_unit.to_snapshot(),
            "disabled_unit": disabled_unit.to_snapshot(),
        },
    }


def _eidolon_generic_case(rules: RuleBook) -> dict[str, Any]:
    sample = _select_eidolon_skill_bonus_card(rules)
    if sample is None:
        checks = {"eidolon_skill_level_bonus_sample_exists": False}
        return {"checks": {"ok": False, "checks": checks}, "blocking_dependency": "eidolon_skill_add_level_slot_missing"}
    card, rank = sample
    e0 = _state_for_eidolon(rules, card, 0)
    e6 = _state_for_eidolon(rules, card, 6)
    flags0 = e0.state.units["ally:eidolon"].flags
    flags6 = e6.state.units["ally:eidolon"].flags
    skill_bonus = flags6.get("eidolon_skill_level_bonus_by_action_id", {})
    bonus_action_id = next(iter(skill_bonus), "") if isinstance(skill_bonus, dict) else ""
    effective_level_case = _effective_action_level_case(rules, e6.state, bonus_action_id)
    eidolon_slots = rules.character_eidolon_slots_for_card(card.card_id)
    effect_slots = [
        rules.character_mechanism_slot(slot_id)
        for slot in rules.character_mechanism_slots_for_card(card.card_id)[0:0]
    ]
    effect_slots = [
        slot
        for slot in rules.character_mechanism_slots_for_card(card.card_id)
        if slot.mechanism_kind.startswith("eidolon_")
    ]
    checks = {
        "eidolon_prefix_e0_empty": tuple(flags0.get("enabled_eidolon_ranks", ())) == (),
        "eidolon_prefix_e6_all_previous": tuple(flags6.get("enabled_eidolon_ranks", ())) == tuple(range(1, 7)),
        "eidolon_level_single_switch_policy": flags6.get("eidolon_activation_policy", {}).get("independent_rank_toggle_allowed") is False,
        "skill_level_bonus_flags_present": isinstance(skill_bonus, dict) and bool(skill_bonus),
        "skill_level_bonus_sources_present": bool(flags6.get("eidolon_skill_level_bonus_sources")),
        "skill_level_bonus_affects_effective_action_level": effective_level_case["ok"],
        "eidolon_slots_have_sources": len(eidolon_slots) == 6 and all(slot.source.source_path for slot in eidolon_slots),
        "eidolon_effect_slots_classified": all(
            (
                slot.coverage_status == "executable"
                and slot.runtime_system
                and not slot.blocked_reason
            )
            or (
                slot.coverage_status != "executable"
                and bool(slot.blocked_reason)
            )
            for slot in effect_slots
        ),
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "sample": {
            "card_id": card.card_id,
            "rank_with_skill_bonus": rank,
            "e0_flags": _eidolon_flag_sample(flags0),
            "e6_flags": _eidolon_flag_sample(flags6),
            "effective_action_level_case": effective_level_case,
        },
    }


def _event_callback_case(rules: RuleBook) -> dict[str, Any]:
    matrix = _foundational_callback_matrix(rules)
    turn_end_case = _turn_end_dispatch_case(rules)
    checks = {
        "foundational_events_have_matrix_entries": set(matrix) == FOUNDATIONAL_CALLBACK_EVENTS,
        "at_least_one_foundational_executable_callback": any(item["executable_count"] > 0 for item in matrix.values()),
        "known_missing_events_have_blocker": all(
            item["executable_count"] > 0 or bool(item["blocking_dependency"])
            for item in matrix.values()
        ),
        "turn_end_listener_executes_through_dispatcher": turn_end_case["checks"]["ok"],
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "matrix": matrix,
        "turn_end_dispatch_case": turn_end_case,
    }


def _runtime_boundary_case(package_root: Path) -> dict[str, Any]:
    runtime_dirs = [package_root / "core", package_root / "systems", package_root / "rules"]
    forbidden = ("TextMap", "turnbasedgamedata-main", "model_pack_v3_0", "simulator_v7", "action_ctx")
    hits: list[dict[str, str]] = []
    for directory in runtime_dirs:
        for path in directory.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append({"path": path.relative_to(package_root).as_posix(), "token": token})
    checks = {
        "runtime_no_textmap_or_raw_tbgd": not hits,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {"checks": {"ok": checks["ok"], "checks": checks}, "hits": hits}


def _select_trace_static_slot(rules: RuleBook) -> tuple[CharacterDataCardIR, CharacterMechanismSlotIR, str, dict[str, Any]] | None:
    for card in rules.ir.character_data_cards:
        if card.coverage_status != "executable":
            continue
        for slot in rules.character_mechanism_slots_for_card(card.card_id):
            if slot.mechanism_kind != "trace_static_stat_bonus" or slot.coverage_status != "executable":
                continue
            trace_node_id = str(slot.activation.get("trace_node_id") or "")
            terms = slot.semantics.get("mapped_terms")
            if not isinstance(terms, list) or not terms:
                continue
            first = terms[0]
            if isinstance(first, dict):
                return card, slot, trace_node_id, first
    return None


def _replace_panel_flags(panel: PanelInput, flags: dict[str, Any]) -> PanelInput:
    return PanelInput(
        explicit_fields=panel.explicit_fields,
        max_hp=panel.max_hp,
        hp=panel.hp,
        attack=panel.attack,
        defense=panel.defense,
        speed=panel.speed,
        energy=panel.energy,
        max_energy=panel.max_energy,
        toughness=panel.toughness,
        max_toughness=panel.max_toughness,
        action_value=panel.action_value,
        resources=dict(panel.resources),
        flags={**panel.flags, **flags},
        statuses=panel.statuses,
    )


def _unit_stat(unit: UnitState, key: str) -> float:
    if key == "max_hp":
        return float(unit.max_hp)
    if key == "attack":
        return float(unit.attack)
    if key == "defense":
        return float(unit.defense)
    if key == "speed":
        return float(unit.speed)
    return float(unit.resources.get(key, 0.0))


def _select_eidolon_skill_bonus_card(rules: RuleBook) -> tuple[CharacterDataCardIR, int] | None:
    for card in rules.ir.character_data_cards:
        slots = rules.character_eidolon_slots_for_card(card.card_id)
        if len(slots) != 6:
            continue
        for slot in slots:
            skill_add_level_list = slot.semantics.get("skill_add_level_list")
            if isinstance(skill_add_level_list, dict) and skill_add_level_list:
                return card, slot.rank
    return None


def _state_for_eidolon(rules: RuleBook, card: CharacterDataCardIR, eidolon_level: int):
    return ScenarioStateBuilder(rules).build(
        ScenarioSpec(
            scenario_id=f"v0_271_eidolon_{eidolon_level}",
            version=VALIDATION_VERSION,
            units=(
                UnitSpec(
                    unit_id="ally:eidolon",
                    side="ally",
                    build_mode="kernel_fixture",
                    entity_ref=card.entity_ref,
                    eidolon_level=eidolon_level,
                    panel=PanelInput(max_hp=1000, attack=100, defense=100, speed=100, energy=0, max_energy=120),
                ),
            ),
            route=(),
        )
    )


def _effective_action_level_case(rules: RuleBook, state: BattleState, action_id: str) -> dict[str, Any]:
    if not action_id:
        return {"ok": False, "reason": "bonus_action_id_missing"}
    from ..core.executor import _command_with_character_card_level_bonus
    from ..core.model import ActionCommand

    levels = rules.action_levels(action_id)
    if not levels or len(levels) < 2:
        return {"ok": False, "reason": "action_levels_missing_or_single_level", "action_id": action_id}
    requested = min(levels)
    command = ActionCommand(actor_id="ally:eidolon", action_id=action_id, action_level=requested, target_ids=())
    effective = _command_with_character_card_level_bonus(command, state, rules)
    return {
        "ok": effective.action_level > requested
        and effective.metadata.get("effective_action_level_source", {}).get("source_kind") == "character_data_card_eidolon_skill_level_bonus",
        "action_id": action_id,
        "requested_level": requested,
        "effective_level": effective.action_level,
        "metadata": effective.metadata,
    }


def _eidolon_flag_sample(flags: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled_eidolon_ranks": list(flags.get("enabled_eidolon_ranks", ())),
        "enabled_eidolon_rank_ids": list(flags.get("enabled_eidolon_rank_ids", ())),
        "enabled_eidolon_mechanism_slot_ids": list(flags.get("enabled_eidolon_mechanism_slot_ids", ())),
        "eidolon_skill_level_bonus_by_action_id": flags.get("eidolon_skill_level_bonus_by_action_id", {}),
        "eidolon_skill_level_bonus_sources": flags.get("eidolon_skill_level_bonus_sources", {}),
        "eidolon_activation_policy": flags.get("eidolon_activation_policy", {}),
    }


def _foundational_callback_matrix(rules: RuleBook) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in sorted(FOUNDATIONAL_CALLBACK_EVENTS):
        callbacks = [callback for callback in rules.ir.status_callbacks if callback.event == event]
        executable = [callback for callback in callbacks if callback.coverage_status == "executable"]
        blocked_reasons = sorted({callback.blocked_reason for callback in callbacks if callback.blocked_reason})
        result[event] = {
            "total_count": len(callbacks),
            "executable_count": len(executable),
            "blocked_reason_counts": {
                reason: sum(1 for callback in callbacks if callback.blocked_reason == reason)
                for reason in blocked_reasons[:12]
            },
            "sample_executable": executable[0].to_json() if executable else None,
            "blocking_dependency": "" if executable else (blocked_reasons[0] if blocked_reasons else "callback_source_missing"),
        }
    return result


def _turn_end_dispatch_case(rules: RuleBook) -> dict[str, Any]:
    callback = _select_turn_end_dynamic_callback(rules)
    if callback is None:
        checks = {"turn_end_dynamic_callback_exists": False}
        return {"checks": {"ok": False, "checks": checks}, "blocking_dependency": "on_listen_turn_end_dynamic_value_callback_missing"}
    detail = {
        "instance_id": "status:v0_271_turn_end",
        "status_id": f"modifier:{callback.modifier_name}",
        "modifier_name": callback.modifier_name,
        "owner_id": "ally:listener",
        "caster_id": "ally:listener",
        "source_trace": callback.source.to_json(),
        "trigger_ids_by_event": {callback.event: [callback.callback_id]},
        "dynamic_values": {},
        "dynamic_values_by_hash": {},
    }
    state = BattleState(
        units={
            "ally:listener": UnitState(
                unit_id="ally:listener",
                side="ally",
                template_id="avatar:listener",
                max_hp=1000,
                hp=1000,
                attack=100,
                defense=100,
                speed=100,
                flags={
                    "status_details": (detail,),
                },
            )
        },
        global_flags={
            "phase": "turn",
            "turn_owner_id": "ally:listener",
            "active_turn": {"actor_id": "ally:listener", "turn_kind": "regular"},
            "admit_turn_end_listener_dispatch": True,
        },
    )
    result = CombatScheduler(rules).end_current_turn(state)
    transition_checks = _transition_checks(result.transition, state)
    audit = RuntimeSourceAuditor(rules).validate_transition(result.transition)
    dynamic_mutations = [mutation for mutation in result.transition.transaction.mutations if mutation.source == "effect_system"]
    listener_records = [
        record
        for record in (result.transition.transaction.settlement.records if result.transition.transaction.settlement else ())
        if record.get("record_type") in {"listener_match", "dynamic_value_store", "status_callback"}
    ]
    checks = {
        "turn_end_dynamic_callback_exists": callback.coverage_status == "executable",
        "dispatcher_produced_effect_mutation": bool(dynamic_mutations),
        "listener_records_present": bool(listener_records),
        "source_audit": audit.ok,
        **transition_checks,
    }
    checks["ok"] = all(value for key, value in checks.items() if key != "ok")
    return {
        "checks": {"ok": checks["ok"], "checks": checks},
        "callback": callback.to_json(),
        "mutation_count": len(result.transition.transaction.mutations),
        "effect_mutations": [mutation.to_json() for mutation in dynamic_mutations],
        "listener_records": listener_records[-8:],
        "source_audit": audit.to_json(),
    }


def _select_turn_end_dynamic_callback(rules: RuleBook) -> StatusCallbackIR | None:
    for callback in rules.ir.status_callbacks:
        if callback.event != "OnListenTurnEnd" or callback.coverage_status != "executable":
            continue
        tasks = [rules.status_callback_task(task_id) for task_id in callback.task_ids]
        if any(task and task.opcode == "SetDynamicValue" and task.coverage_status == "executable" for task in tasks):
            return callback
    return None


if __name__ == "__main__":
    raise SystemExit(main())
