from __future__ import annotations

from dataclasses import asdict
from typing import Any

from simulator_v8_clean_core.core.model import ActionCommand, BattleState, BattleTransition, JSONValue
from simulator_v8_clean_core.core.reducer import MutationReducer
from simulator_v8_clean_core.core.settlement import SettlementTraceabilityValidator
from simulator_v8_clean_core.core.source_audit import RuntimeSourceAuditor
from simulator_v8_clean_core.core.transition_contract import TransitionContractValidator
from simulator_v8_clean_core.builds.manifest import (
    FORMAL_BUILD_MANIFEST_FLAG,
    BuildLockedReplayVerifier,
)
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.scenarios.schema import RouteStepSpec, ScenarioSpec


DAMAGE_RECORD_TYPES = {
    "damage",
    "dot_damage",
    "break_damage",
    "break_dot_tick",
    "super_break_damage",
    "hp_loss",
    "damage_blocked",
    "dot_damage_blocked",
    "break_dot_tick_blocked",
    "super_break_blocked",
    "damage_error",
    "damage_modifier",
}


def build_step_report(
    *,
    route_index: int,
    command: ActionCommand,
    before_state: BattleState,
    after_state: BattleState,
    transition: BattleTransition,
    child_transitions: tuple[BattleTransition, ...],
    rules: RuleBook,
    scenario_data: dict[str, Any],
    include_raw_transition: bool = True,
) -> dict[str, JSONValue]:
    transition_json = transition.to_json()
    before_snapshot = before_state.snapshot().to_json()
    after_snapshot = after_state.snapshot().to_json()
    records = settlement_records(transition_json)
    source_audit = RuntimeSourceAuditor(rules).validate_transition(transition).to_json()
    settlement_traceability = SettlementTraceabilityValidator().validate(
        transition.transaction.settlement,
        transition.transaction.mutations,
    ).to_json()
    if FORMAL_BUILD_MANIFEST_FLAG in before_state.global_flags:
        replay = BuildLockedReplayVerifier(rules).replay_snapshot(
            before_state,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
    else:
        replay = MutationReducer().replay_snapshot(
            before_state,
            transition.transaction.mutations,
            transition.after.to_json(),
        )
    contract = TransitionContractValidator().validate(transition).to_json()
    blocked = blocked_records(records, transition_json)
    coverage_gaps = coverage_gap_records(records, transition_json)
    process_notices = process_notice_records(records, transition_json)
    return {
        "route_index": route_index,
        "input_command": _command_to_json(command),
        "before_panel_summary": panel_summary(before_snapshot),
        "after_panel_summary": panel_summary(after_snapshot),
        "panel_source_breakdown": panel_source_breakdown(after_snapshot, scenario_data),
        "transition": transition_json if include_raw_transition else transition_summary(transition_json),
        "transition_outcome": transition_json.get("outcome"),
        "child_transitions": [
            child.to_json() if include_raw_transition else transition_summary(child.to_json())
            for child in child_transitions
        ],
        "damage_records": damage_records(records),
        "status_records": status_records(records, transition_json),
        "resource_records": resource_records(records, transition_json),
        "timeline_queue_records": timeline_queue_records(records, transition_json, before_snapshot, after_snapshot),
        "blocked_records": blocked,
        "coverage_gap_records": coverage_gaps,
        "process_notice_records": process_notices,
        "source_audit": source_audit,
        "settlement_traceability": settlement_traceability,
        "replay": _replay_to_json(replay),
        "contract": contract,
    }


def validation_blocked_step(
    *,
    route_index: int,
    route_step: RouteStepSpec,
    errors: tuple[str, ...],
) -> dict[str, JSONValue]:
    command = ActionCommand(
        actor_id=route_step.actor_id,
        action_id=route_step.action_ref,
        action_level=route_step.action_level,
        target_ids=route_step.target_ids,
        source=route_step.source,
        queue_name=route_step.queue_name,
        metadata=route_step.metadata,
    )
    records = [
        {
            "record_type": "route_validation_blocked",
            "source": "simulator_v8_ui.runner",
            "process_only": True,
            "mutation_id": None,
            "payload": {
                "route_index": route_index,
                "errors": list(errors),
                "command": _command_to_json(command),
            },
            "trace": {"source": "scenario_validation"},
        }
    ]
    return {
        "route_index": route_index,
        "input_command": _command_to_json(command),
        "before_panel_summary": {},
        "after_panel_summary": {},
        "panel_source_breakdown": {},
        "transition": None,
        "child_transitions": [],
        "damage_records": [],
        "status_records": [],
        "resource_records": [],
        "timeline_queue_records": [],
        "blocked_records": records,
        "coverage_gap_records": [],
        "process_notice_records": [],
        "source_audit": {"ok": False, "checked_mutations": 0, "checked_records": 0, "violations": [], "traces": []},
        "settlement_traceability": {
            "ok": False,
            "checked_records": 0,
            "process_only_records": 0,
            "mutation_linked_records": 0,
            "errors": list(errors),
        },
        "replay": {"ok": True, "expected": {}, "actual": {}, "errors": []},
        "contract": {"ok": False, "errors": list(errors)},
    }


def build_battlefield_view(
    snapshot: dict[str, JSONValue],
    scenario_data: dict[str, Any],
) -> dict[str, JSONValue]:
    timeline = _timeline_summary(_dict(snapshot.get("timeline")))
    units_by_id = _dict(snapshot.get("units"))
    scenario_units = {
        str(unit.get("unit_id")): unit
        for unit in _list(scenario_data.get("units"))
        if isinstance(unit, dict) and unit.get("unit_id")
    }
    unit_cards = [
        _battlefield_unit_card(
            unit_id=unit_id,
            unit_data=_dict(unit_data),
            scenario_unit=_dict(scenario_units.get(unit_id)),
            scenario_data=scenario_data,
        )
        for unit_id, unit_data in sorted(
            units_by_id.items(),
            key=lambda item: (_unit_sort_side(_dict(item[1]).get("side")), _dict(item[1]).get("position") or 0, item[0]),
        )
    ]
    return {
        "scenario_id": scenario_data.get("scenario_id", ""),
        "battle": _dict(snapshot.get("battle")),
        "resources": _dict(snapshot.get("resources")),
        "timeline": timeline,
        "current_unit_id": timeline.get("turn_owner_id") or _dict(timeline.get("active_turn")).get("owner_id") or "",
        "global_av": timeline.get("global_av"),
        "ally_units": [unit for unit in unit_cards if unit.get("side") == "ally"],
        "enemy_units": [unit for unit in unit_cards if unit.get("side") == "enemy"],
        "units": unit_cards,
    }


def build_action_prompt(
    snapshot: dict[str, JSONValue],
    scenario_data: dict[str, Any],
    action_slots_by_entity: dict[str, JSONValue],
    *,
    enemy_action_candidate: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    battlefield = build_battlefield_view(snapshot, scenario_data)
    current_unit_id = str(battlefield.get("current_unit_id") or "")
    units = _list(battlefield.get("units"))
    current_unit = next((_dict(unit) for unit in units if unit.get("unit_id") == current_unit_id), {})
    if not current_unit_id:
        return {
            "available": False,
            "current_unit_id": "",
            "reason": "当前没有可行动单位",
            "slots": [],
            "targets": [],
        }
    if current_unit.get("side") == "enemy":
        candidate = _dict(enemy_action_candidate)
        if candidate.get("status") == "available":
            action_ref = str(candidate.get("action_ref") or "")
            action_level = int(candidate.get("action_level") or 0)
            selectable_ids = set(str(item) for item in _list(candidate.get("selectable_target_ids")) if isinstance(item, str))
            auto_ids = set(str(item) for item in _list(candidate.get("auto_target_ids")) if isinstance(item, str))
            targets = [
                {
                    "unit_id": unit.get("unit_id"),
                    "display_name": unit.get("display_name"),
                    "side": unit.get("side"),
                    "hp": unit.get("hp"),
                    "max_hp": unit.get("max_hp"),
                    "selection_kind": "selectable" if unit.get("unit_id") in selectable_ids else "auto",
                }
                for unit in units
                if unit.get("unit_id") in selectable_ids or unit.get("unit_id") in auto_ids
            ]
            slot = {
                "slot": "enemy_sequence",
                "label": "固定序列动作",
                "display_label": _display_name(scenario_data, "actions", action_ref) or "固定序列动作",
                "available": True,
                "action_ref": action_ref,
                "action_level": action_level,
                "target_mode": candidate.get("target_mode") or "",
                "selectable_target_ids": list(selectable_ids),
                "auto_target_ids": list(auto_ids),
                "source_trace": candidate.get("source_trace") or {},
            }
            return {
                "available": True,
                "current_unit_id": current_unit_id,
                "current_unit_name": current_unit.get("display_name", current_unit_id),
                "entity_ref": current_unit.get("entity_ref") or "",
                "reason": "",
                "slots": [slot],
                "targets": targets,
                "enemy_action_candidate": candidate,
            }
        return {
            "available": False,
            "current_unit_id": current_unit_id,
            "current_unit_name": current_unit.get("display_name", current_unit_id),
            "reason": f"敌方固定序列候选不可用：{candidate.get('blocked_reason') or '未生成候选'}",
            "slots": [],
            "targets": [],
            "enemy_action_candidate": candidate,
        }
    if current_unit.get("side") != "ally":
        return {
            "available": False,
            "current_unit_id": current_unit_id,
            "current_unit_name": current_unit.get("display_name", current_unit_id),
            "reason": "第一版暂时跳过敌方回合，不弹出技能按钮",
            "slots": [],
            "targets": [],
        }
    entity_ref = str(current_unit.get("entity_ref") or "")
    raw_slots = _list(action_slots_by_entity.get(entity_ref))
    slots = [_action_prompt_slot(_dict(slot), scenario_data) for slot in raw_slots]
    if not slots:
        slots = [
            {
                "slot": slot,
                "label": label,
                "available": False,
                "action_ref": "",
                "action_level": 0,
                "blocked_reason": "动作槽位未接通：没有找到角色卡或头像档案动作列表",
            }
            for slot, label in (("basic", "普攻"), ("skill", "战技"), ("ultimate", "终结技"))
        ]
    targets = [
        {
            "unit_id": unit.get("unit_id"),
            "display_name": unit.get("display_name"),
            "side": unit.get("side"),
            "hp": unit.get("hp"),
            "max_hp": unit.get("max_hp"),
        }
        for unit in units
        if unit.get("side") == "enemy" and float(unit.get("hp") or 0) > 0
    ]
    return {
        "available": any(bool(_dict(slot).get("available")) for slot in slots),
        "current_unit_id": current_unit_id,
        "current_unit_name": current_unit.get("display_name", current_unit_id),
        "entity_ref": entity_ref,
        "reason": "" if any(bool(_dict(slot).get("available")) for slot in slots) else "当前单位没有可执行动作槽位",
        "slots": slots,
        "targets": targets,
    }


def build_event_replay_view(
    steps: list[dict[str, JSONValue]],
    *,
    auto_skip_records: tuple[dict[str, JSONValue], ...] | list[dict[str, JSONValue]] = (),
) -> list[dict[str, JSONValue]]:
    events: list[dict[str, JSONValue]] = []
    for step in steps:
        command = _dict(step.get("input_command"))
        transition = _dict(step.get("transition"))
        damage = _list(step.get("damage_records"))
        status = _list(step.get("status_records"))
        resources = _list(step.get("resource_records"))
        timeline = _list(step.get("timeline_queue_records"))
        blocked = _list(step.get("blocked_records"))
        coverage_gaps = _list(step.get("coverage_gap_records"))
        process_notices = _list(step.get("process_notice_records"))
        source_audit = _dict(step.get("source_audit"))
        replay = _dict(step.get("replay"))
        first_damage = _dict(damage[0]) if damage else {}
        events.append(
            {
                "event_kind": "route_step",
                "route_index": step.get("route_index"),
                "title": f"第 {int(step.get('route_index') or 0) + 1} 步",
                "actor_id": command.get("actor_id", ""),
                "action_id": command.get("action_id", ""),
                "action_level": command.get("action_level", 0),
                "target_ids": _list(command.get("target_ids")),
                "damage_count": len(damage),
                "first_damage": first_damage.get("final_damage"),
                "status_record_count": sum(len(_list(_dict(item).get("records"))) for item in status),
                "resource_record_count": sum(len(_list(_dict(item).get("records"))) for item in resources),
                "timeline_record_count": sum(len(_list(_dict(item).get("records"))) for item in timeline),
                "blocked_count": len(blocked),
                "coverage_gap_count": len(coverage_gaps),
                "process_notice_count": len(process_notices),
                "mutation_count": len(_list(transition.get("mutations"))),
                "event_count": len(_list(transition.get("events"))),
                "source_audit_ok": source_audit.get("ok"),
                "replay_ok": replay.get("ok"),
                "blocked_records": blocked,
                "coverage_gap_records": coverage_gaps,
                "process_notice_records": process_notices,
            }
        )
    for index, record in enumerate(auto_skip_records):
        item = _dict(record)
        events.append(
            {
                "event_kind": "auto_skip_enemy_turn",
                "route_index": None,
                "auto_skip_index": index,
                "title": "临时跳过敌方回合",
                "actor_id": item.get("actor_id", ""),
                "action_id": "ui:temporary_enemy_turn_skip",
                "action_level": 0,
                "target_ids": [],
                "damage_count": 0,
                "first_damage": None,
                "status_record_count": 0,
                "resource_record_count": 0,
                "timeline_record_count": 1,
                "blocked_count": 0,
                "coverage_gap_count": 0,
                "process_notice_count": 1,
                "mutation_count": item.get("mutation_count", 0),
                "event_count": 1,
                "source_audit_ok": True,
                "replay_ok": True,
                "blocked_records": [],
                "coverage_gap_records": [],
                "process_notice_records": [item],
                "temporary_until_enemy_ai": True,
                "todo": "enemy_ai",
            }
        )
    return events


def scenario_to_json(scenario: ScenarioSpec) -> dict[str, JSONValue]:
    return {
        "scenario_id": scenario.scenario_id,
        "version": scenario.version,
        "skill_points": scenario.skill_points,
        "max_skill_points": scenario.max_skill_points,
        "wave_index": scenario.wave_index,
        "wave_definition_ref": scenario.wave_definition_ref,
        "stage_ref": scenario.stage_ref,
        "rng_state": scenario.rng_state,
        "global_flags": scenario.global_flags,
        "battle_setup": asdict(scenario.battle_setup),
        "units": [
            {
                "unit_id": unit.unit_id,
                "side": unit.side,
                "entity_ref": unit.entity_ref,
                "level": unit.level,
                "eidolon_level": unit.eidolon_level,
                "position": unit.position,
                "build_mode": unit.build_mode,
                "panel": asdict(unit.panel) if unit.panel is not None else None,
                "character_build": (
                    unit.character_build.to_json() if unit.character_build is not None else None
                ),
                "initial_condition": (
                    unit.initial_condition.to_json() if unit.initial_condition is not None else None
                ),
            }
            for unit in scenario.units
        ],
        "route": [
            {
                "actor_id": step.actor_id,
                "action_ref": step.action_ref,
                "action_level": step.action_level,
                "target_ids": list(step.target_ids),
                "source": step.source,
                "queue_name": step.queue_name,
                "metadata": step.metadata,
            }
            for step in scenario.route
        ],
    }


def panel_summary(snapshot: dict[str, JSONValue]) -> dict[str, JSONValue]:
    units = _dict(snapshot.get("units"))
    return {
        "battle": _dict(snapshot.get("battle")),
        "resources": _dict(snapshot.get("resources")),
        "timeline": _timeline_summary(_dict(snapshot.get("timeline"))),
        "units": {
            unit_id: _unit_panel_summary(_dict(unit_data))
            for unit_id, unit_data in sorted(units.items())
        },
    }


def panel_source_breakdown(
    snapshot: dict[str, JSONValue],
    scenario_data: dict[str, Any],
) -> dict[str, JSONValue]:
    scenario_units = {
        str(unit.get("unit_id")): unit
        for unit in _list(scenario_data.get("units"))
        if isinstance(unit, dict) and unit.get("unit_id")
    }
    breakdown: dict[str, JSONValue] = {}
    for unit_id, unit_data in sorted(_dict(snapshot.get("units")).items()):
        unit = _dict(unit_data)
        flags = _dict(unit.get("flags"))
        scenario_unit = _dict(scenario_units.get(unit_id))
        breakdown[unit_id] = {
            "scenario_panel_input": _dict(scenario_unit.get("panel")),
            "scenario_unit": {
                "unit_id": scenario_unit.get("unit_id"),
                "side": scenario_unit.get("side"),
                "entity_ref": scenario_unit.get("entity_ref"),
                "level": scenario_unit.get("level"),
                "eidolon_level": scenario_unit.get("eidolon_level"),
                "position": scenario_unit.get("position"),
            },
            "template_source": unit.get("template_source"),
            "combatant_profile": {
                "profile_id": flags.get("combatant_profile_id"),
                "coverage_status": flags.get("combatant_profile_coverage_status"),
                "blocked_reason": flags.get("combatant_profile_blocked_reason"),
                "source_trace": flags.get("combatant_profile_source_trace"),
            },
            "panel_overrides": _list(flags.get("panel_overrides")),
            "trace_static_stat_bonus_terms": _list(flags.get("trace_static_stat_bonus_terms")),
            "trace_panel_adjustments": _dict(flags.get("trace_panel_adjustments")),
            "trace_resource_adjustments": _dict(flags.get("trace_resource_adjustments")),
            "trace_blocked_slots": _list(flags.get("trace_static_stat_blocked_slots")),
            "trace_source_traces": _list(flags.get("trace_source_traces")),
            "effective_skill_levels": _dict(
                flags.get("effective_skill_levels_by_action_id")
            ),
            "effective_skill_level_sources": _dict(
                flags.get("effective_skill_level_sources")
            ),
            "effective_skill_level_action_definitions": _dict(
                flags.get("effective_skill_level_action_definitions")
            ),
            "eidolon": {
                "character_data_card_id": flags.get("character_data_card_id"),
                "requested_level": flags.get("eidolon_level_requested"),
                "enabled_ranks": _list(flags.get("enabled_eidolon_ranks")),
                "enabled_slot_ids": _list(flags.get("enabled_eidolon_slot_ids")),
                "activation_policy": _dict(flags.get("eidolon_activation_policy")),
                "source_traces": _list(flags.get("eidolon_source_traces")),
                "skill_level_bonus": _dict(flags.get("eidolon_skill_level_bonus_by_action_id")),
                "skill_level_bonus_sources": _dict(flags.get("eidolon_skill_level_bonus_sources")),
            },
            "dynamic_value_store": _dict(_dict(snapshot.get("global_flags")).get("dynamic_value_store")),
        }
    return breakdown


def settlement_records(transition_json: dict[str, JSONValue]) -> list[dict[str, JSONValue]]:
    settlement = _dict(transition_json.get("settlement"))
    return [_dict(record) for record in _list(settlement.get("records"))]


def damage_records(records: list[dict[str, JSONValue]]) -> list[dict[str, JSONValue]]:
    result = []
    for record in records:
        record_type = str(record.get("record_type") or "")
        payload = _dict(record.get("payload"))
        if record_type in DAMAGE_RECORD_TYPES or "damage" in record_type or payload.get("damage_formula_family"):
            result.append(
                {
                    "record_type": record_type,
                    "mutation_id": record.get("mutation_id"),
                    "process_only": bool(record.get("process_only")),
                    "amount": payload.get("amount"),
                    "final_damage": payload.get("final_damage"),
                    "damage_formula_family": payload.get("damage_formula_family"),
                    "attack_type": payload.get("attack_type"),
                    "element_type": payload.get("element_type"),
                    "target_before_hp": payload.get("target_before_hp"),
                    "target_after_hp": payload.get("target_after_hp"),
                    "source_frame": payload.get("source_frame"),
                    "formula_result": payload.get("formula_result"),
                    "scaling": _dict(payload.get("formula_result")).get("scaling"),
                    "multipliers": _dict(payload.get("formula_result")).get("multipliers"),
                    "crit_resolution": payload.get("crit_resolution"),
                    "modifier_ledger": payload.get("modifier_ledger"),
                    "numeric_evaluation": payload.get("numeric_evaluation"),
                    "normal_multiplier_terms": payload.get("normal_multiplier_terms"),
                    "trace": record.get("trace"),
                    "raw_record": record,
                }
            )
    return result


def status_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    selected = [
        record
        for record in records
        if _record_type_contains(record, ("status", "modifier", "dynamic_value"))
    ]
    status_mutations = [
        mutation
        for mutation in _list(transition_json.get("mutations"))
        if _mutation_path_contains(_dict(mutation), ("statuses", "status_details", "modifiers"))
    ]
    return [{"records": selected, "mutations": status_mutations}]


def resource_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    selected = [
        record
        for record in records
        if _record_type_contains(record, ("resource", "energy", "skill_point", "heal", "shield", "hp_loss"))
    ]
    resource_mutations = [
        mutation
        for mutation in _list(transition_json.get("mutations"))
        if _mutation_path_contains(
            _dict(mutation),
            ("resources", "energy", "max_energy", "skill_points", "max_skill_points", "shield", "recoverable_hp"),
        )
    ]
    return [{"records": selected, "mutations": resource_mutations}]


def timeline_queue_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
    before_snapshot: dict[str, JSONValue],
    after_snapshot: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    selected = [
        record
        for record in records
        if _record_type_contains(
            record,
            ("queue", "timeline", "turn", "scheduler", "extra_turn", "action_delay", "ultimate_energy_cost"),
        )
    ]
    events = [
        event
        for event in _list(transition_json.get("events"))
        if any(token in str(_dict(event).get("event_type") or "") for token in ("queue", "timeline", "turn", "extra_turn"))
    ]
    mutations = [
        mutation
        for mutation in _list(transition_json.get("mutations"))
        if _mutation_path_contains(
            _dict(mutation),
            ("action_value", "queues", "global_av", "active_turn", "turn_owner_id", "current_window", "pending_turn_end"),
        )
    ]
    return [
        {
            "records": selected,
            "events": events,
            "mutations": mutations,
            "before_timeline": _timeline_summary(_dict(before_snapshot.get("timeline"))),
            "after_timeline": _timeline_summary(_dict(after_snapshot.get("timeline"))),
            "before_queues": _dict(before_snapshot.get("queues")),
            "after_queues": _dict(after_snapshot.get("queues")),
        }
    ]


def blocked_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    result: list[dict[str, JSONValue]] = []
    for record in records:
        if _is_true_blocking_record(record):
            result.append(_readable_record(record, category="真正阻塞", impact="本步骤无法按有效战斗变更继续执行。"))
    outcome = _dict(transition_json.get("outcome"))
    category = str(outcome.get("category") or "")
    reason_codes = [str(item) for item in _list(outcome.get("reason_codes")) if isinstance(item, str) and item]
    if category in {"blocked", "diagnostic"}:
        result.append(
            {
                "record_type": "transition_outcome_not_committed",
                "category": "真正阻塞" if category == "blocked" else "诊断性结果",
                "reason": reason_codes[0] if reason_codes else "transition_outcome_not_successor_eligible",
                "reason_codes": reason_codes,
                "path": "outcome",
                "impact": "该 transition 不可作为正式战斗后继。",
                "produced_mutation": bool(_list(transition_json.get("mutations"))),
            }
        )
    return result


def coverage_gap_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    gaps: list[dict[str, JSONValue]] = []
    for record in records:
        if _is_coverage_gap_record(record):
            gaps.append(_readable_record(record, category="覆盖缺口", impact=_record_gap_impact(record)))
    for item in _coverage_gap_items(_dict(transition_json.get("coverage"))):
        gaps.append(
            {
                "record_type": "coverage_gap",
                "category": "覆盖缺口",
                "path": item.get("path"),
                "status": item.get("status"),
                "reason": item.get("blocked_reason") or item.get("status") or "coverage_gap",
                "errors": item.get("errors"),
                "impact": _coverage_gap_impact(item),
                "produced_mutation": False,
            }
        )
    return gaps


def process_notice_records(
    records: list[dict[str, JSONValue]],
    transition_json: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    notices: list[dict[str, JSONValue]] = []
    for record in records:
        if _is_process_notice_record(record):
            notices.append(
                _readable_record(
                    record,
                    category="过程提示",
                    impact="该记录用于说明执行过程或当前 UI/模拟器覆盖边界，不代表来源审计失败。",
                )
            )
    for event in _list(transition_json.get("events")):
        event_data = _dict(event)
        event_type = str(event_data.get("event_type") or "")
        payload = _dict(event_data.get("payload"))
        if event_type == "scheduler.blocked" and payload.get("reason") == "enemy_ai_missing":
            notices.append(
                {
                    "record_type": "enemy_ai_missing",
                    "category": "过程提示",
                    "reason": "enemy_ai_missing",
                    "path": "events.scheduler.blocked",
                    "impact": "敌方 AI 尚未接通；UI 测试台会在 scheduler 模式下临时跳过敌方回合。",
                    "produced_mutation": False,
                    "temporary_until_enemy_ai": True,
                    "todo": "enemy_ai",
                    "payload": payload,
                }
            )
    return notices


def transition_summary(transition_json: dict[str, JSONValue]) -> dict[str, JSONValue]:
    settlement = _dict(transition_json.get("settlement"))
    return {
        "command": transition_json.get("command"),
        "target_resolution": transition_json.get("target_resolution"),
        "event_count": len(_list(transition_json.get("events"))),
        "rng_event_count": len(_list(transition_json.get("rng_events"))),
        "mutation_count": len(_list(transition_json.get("mutations"))),
        "settlement_record_count": len(_list(settlement.get("records"))),
        "outcome": transition_json.get("outcome"),
        "coverage": transition_json.get("coverage"),
        "contract_validation": transition_json.get("contract_validation"),
    }


def _unit_panel_summary(unit: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "identity": {
            "unit_id": unit.get("unit_id"),
            "side": unit.get("side"),
            "template_id": unit.get("template_id"),
            "template_source": unit.get("template_source"),
            "position": unit.get("position"),
            "level": unit.get("level"),
        },
        "hp": {"current": unit.get("hp"), "maximum": unit.get("max_hp")},
        "core_stats": {
            "attack": unit.get("attack"),
            "defense": unit.get("defense"),
            "speed": unit.get("speed"),
        },
        "base_stats": _dict(unit.get("base_stats")),
        "derived_stats": _dict(unit.get("derived_stats")),
        "energy": {"current": unit.get("energy"), "maximum": unit.get("max_energy")},
        "shield": unit.get("shield"),
        "recoverable_hp": unit.get("recoverable_hp"),
        "toughness_state": _dict(unit.get("toughness_state")),
        "action_value": unit.get("action_value"),
        "statuses": _list(unit.get("statuses")),
        "status_details": _list(unit.get("status_details")),
        "modifiers": _list(unit.get("modifiers")),
        "resources": _dict(unit.get("resources")),
    }


def _battlefield_unit_card(
    *,
    unit_id: str,
    unit_data: dict[str, JSONValue],
    scenario_unit: dict[str, Any],
    scenario_data: dict[str, Any],
) -> dict[str, JSONValue]:
    entity_ref = str(scenario_unit.get("entity_ref") or unit_data.get("template_id") or "")
    toughness = _dict(unit_data.get("toughness_state"))
    hp = unit_data.get("hp")
    max_hp = unit_data.get("max_hp")
    max_hp_number = float(max_hp or 0)
    return {
        "unit_id": unit_id,
        "display_name": _display_name(scenario_data, "units", unit_id)
        or _display_name(scenario_data, "entities", entity_ref)
        or unit_id,
        "side": unit_data.get("side") or scenario_unit.get("side"),
        "entity_ref": entity_ref,
        "position": unit_data.get("position") or scenario_unit.get("position"),
        "level": unit_data.get("level") or scenario_unit.get("level"),
        "hp": hp,
        "max_hp": max_hp,
        "hp_ratio": (float(hp or 0) / max_hp_number) if max_hp_number > 0 else 0,
        "energy": unit_data.get("energy"),
        "max_energy": unit_data.get("max_energy"),
        "shield": unit_data.get("shield"),
        "recoverable_hp": unit_data.get("recoverable_hp"),
        "toughness": toughness.get("current"),
        "max_toughness": toughness.get("maximum"),
        "action_value": unit_data.get("action_value"),
        "status_count": len(_list(unit_data.get("statuses"))),
        "status_detail_count": len(_list(unit_data.get("status_details"))),
        "modifier_count": len(_list(unit_data.get("modifiers"))),
        "panel": _unit_panel_summary(unit_data),
    }


def _action_prompt_slot(slot: dict[str, JSONValue], scenario_data: dict[str, Any]) -> dict[str, JSONValue]:
    action_ref = str(slot.get("action_ref") or "")
    return {
        **slot,
        "display_label": _display_name(scenario_data, "actions", action_ref) or slot.get("label") or action_ref,
    }


def _display_name(scenario_data: dict[str, Any], kind: str, key: str) -> str:
    metadata = _dict(scenario_data.get("metadata"))
    aliases = _dict(metadata.get("ui_aliases"))
    value = _dict(aliases.get(kind)).get(key)
    if isinstance(value, str) and value:
        return value
    ui = _dict(metadata.get("ui"))
    display_names = _dict(ui.get("display_names"))
    value = _dict(display_names.get(kind)).get(key)
    return value if isinstance(value, str) else ""


def _unit_sort_side(value: Any) -> int:
    return {"enemy": 0, "ally": 1}.get(str(value), 2)


def _timeline_summary(timeline: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        "global_av": timeline.get("global_av"),
        "turn_owner_id": timeline.get("turn_owner_id"),
        "active_turn": timeline.get("active_turn"),
        "last_advanced_delta": timeline.get("last_advanced_delta"),
        "turn_sequence_index": timeline.get("turn_sequence_index"),
        "action_values": _dict(timeline.get("action_values")),
        "queues": _dict(timeline.get("queues")),
    }


def _command_to_json(command: ActionCommand) -> dict[str, JSONValue]:
    return {
        "actor_id": command.actor_id,
        "action_id": command.action_id,
        "action_level": command.action_level,
        "target_ids": list(command.target_ids),
        "source": command.source,
        "queue_name": command.queue_name,
        "metadata": command.metadata,
    }


def _replay_to_json(replay: Any) -> dict[str, JSONValue]:
    return {
        "ok": bool(getattr(replay, "ok", False)),
        "expected": getattr(replay, "expected", {}),
        "actual": getattr(replay, "actual", {}),
        "errors": list(getattr(replay, "errors", ())),
    }


def _record_type_contains(record: dict[str, JSONValue], tokens: tuple[str, ...]) -> bool:
    record_type = str(record.get("record_type") or "").lower()
    return any(token in record_type for token in tokens)


def _mutation_path_contains(mutation: dict[str, JSONValue], tokens: tuple[str, ...]) -> bool:
    path = "/".join(str(item) for item in _list(mutation.get("path"))).lower()
    source = str(mutation.get("source") or "").lower()
    return any(token in path or token in source for token in tokens)


TRUE_BLOCKING_RECORD_TYPES = {
    "scheduler_blocked",
    "route_validation_blocked",
    "target_resolution_blocked",
    "action_definition_missing",
    "action_missing",
    "queue_resolution_missing",
    "queue_action_blocked",
}

PROCESS_NOTICE_RECORD_TYPES = {
    "listener_dispatch_blocked",
    "toughness_emission_blocked",
}


def _is_true_blocking_record(record: dict[str, JSONValue]) -> bool:
    record_type = str(record.get("record_type") or "")
    if record_type in TRUE_BLOCKING_RECORD_TYPES:
        payload = _dict(record.get("payload"))
        return payload.get("reason") != "enemy_ai_missing"
    lowered = record_type.lower()
    if any(token in lowered for token in ("validation_blocked", "target_missing", "action_missing", "queue_resolution_missing")):
        return True
    if "error" in lowered and not bool(record.get("process_only")):
        return True
    return False


def _is_coverage_gap_record(record: dict[str, JSONValue]) -> bool:
    record_type = str(record.get("record_type") or "").lower()
    payload = _dict(record.get("payload"))
    reason = str(payload.get("blocked_reason") or payload.get("reason") or "")
    if record_type in {item.lower() for item in PROCESS_NOTICE_RECORD_TYPES}:
        return True
    if any(token in record_type for token in ("unsupported", "audit_only", "discovered_only")):
        return True
    if "blocked" in record_type and bool(record.get("process_only")) and reason.startswith("dynamic_hash_unbound"):
        return True
    return False


def _is_process_notice_record(record: dict[str, JSONValue]) -> bool:
    record_type = str(record.get("record_type") or "").lower()
    payload = _dict(record.get("payload"))
    if record_type in {item.lower() for item in PROCESS_NOTICE_RECORD_TYPES}:
        return True
    if bool(record.get("process_only")) and payload.get("amount") is None and (
        payload.get("amount_expr") is not None or payload.get("numeric_evaluation") is not None
    ):
        return True
    if record_type == "scheduler_blocked" and payload.get("reason") == "enemy_ai_missing":
        return True
    return False


def _readable_record(
    record: dict[str, JSONValue],
    *,
    category: str,
    impact: str,
) -> dict[str, JSONValue]:
    payload = _dict(record.get("payload"))
    reason = payload.get("reason") or payload.get("blocked_reason") or payload.get("blocked_reason_detail") or ""
    source_trace = payload.get("source_trace") or _dict(record.get("trace")).get("source_trace") or record.get("trace")
    mutation_id = record.get("mutation_id")
    return {
        "record_type": record.get("record_type"),
        "category": category,
        "reason": reason,
        "source": record.get("source"),
        "process_only": bool(record.get("process_only")),
        "mutation_id": mutation_id,
        "produced_mutation": bool(mutation_id),
        "impact": impact,
        "payload_summary": _payload_summary(payload),
        "source_trace": source_trace,
        "raw_record": record,
    }


def _payload_summary(payload: dict[str, JSONValue]) -> dict[str, JSONValue]:
    keys = (
        "actor_id",
        "attacker_id",
        "target_id",
        "action_id",
        "reason",
        "blocked_reason",
        "amount",
        "amount_expr",
        "numeric_evaluation",
        "coverage_status",
        "source_kind",
        "raw_path",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _record_gap_impact(record: dict[str, JSONValue]) -> str:
    record_type = str(record.get("record_type") or "")
    payload = _dict(record.get("payload"))
    reason = str(payload.get("reason") or payload.get("blocked_reason") or "")
    if record_type == "toughness_emission_blocked" or reason.startswith("dynamic_hash_unbound"):
        return "韧性削减的数值来源尚未绑定，当前不会产生韧性 mutation；伤害主链可继续审计。"
    return "该机制或表现任务当前尚未进入可执行覆盖范围，本步骤保持 process-only 或跳过对应 mutation。"


def _coverage_gap_impact(item: dict[str, JSONValue]) -> str:
    reason = str(item.get("blocked_reason") or item.get("reason") or item.get("status") or "")
    if "effect_coverage_status" in reason:
        return "Ability task 已被 lowered，但该 opcode 当前只做覆盖记录；通常是动画、镜头、表现或尚未接通的任务。"
    if str(item.get("path") or "").startswith("unsupported_hooks"):
        return "对应事件 hook 或队列窗口尚未接入完整系统，本轮不产生 mutation。"
    return "该覆盖项当前不是可执行机制，报告中保留为缺口，避免伪装成已支持。"


def _coverage_gap_items(value: JSONValue, *, prefix: str = "") -> list[dict[str, JSONValue]]:
    findings: list[dict[str, JSONValue]] = []
    if isinstance(value, dict):
        status = value.get("status")
        blocked_reason = value.get("blocked_reason")
        errors = value.get("errors")
        if blocked_reason or status in {"blocked", "unsupported", "audit_only", "discovered_only"} or errors:
            findings.append(
                {
                    "path": prefix,
                    "status": status,
                    "blocked_reason": blocked_reason,
                    "errors": errors if isinstance(errors, list) else [],
                }
            )
        for key, item in value.items():
            findings.extend(_coverage_gap_items(item, prefix=f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_coverage_gap_items(item, prefix=f"{prefix}[{index}]"))
    return findings


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []
