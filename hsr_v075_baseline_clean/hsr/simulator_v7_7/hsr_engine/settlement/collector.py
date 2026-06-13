"""Phase 2: 结算收集器。

在引擎执行过程中收集各类结算记录，引擎状态变更与记录写入发生在同一代码位置。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import Any

from hsr_engine.kernel import ActionRequest, ActionTransition, ProcessEvent, RNGEvent, SourceRef, StateChange, TargetResolution
from hsr_engine.transition_reducer import validate_transition_replay

from .records import (
    DamageRecord,
    ShieldRecord,
    HPRecord,
    EnergyRecord,
    SPRecord,
    StatusRecord,
    AVRecord,
    TurnRecord,
    QueueRecord,
    TriggerUsageRecord,
    MechanicRecord,
    TargetRecord,
    BreakRecord,
    ToughnessRecord,
    DotRecord,
    SuperBreakRecord,
)


NUMERIC_TOLERANCE = 1e-5


def _settlement_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= NUMERIC_TOLERANCE
    return left == right


def _validate_resource_record_consistency(
    transition: dict[str, Any],
    *,
    target_record: dict[str, Any] | None,
    hp_records: list[dict[str, Any]],
    shield_records: list[dict[str, Any]],
    sp_records: list[dict[str, Any]],
    energy_records: list[dict[str, Any]],
    status_records: list[dict[str, Any]],
    av_records: list[dict[str, Any]],
    turn_records: list[dict[str, Any]],
    queue_records: list[dict[str, Any]],
    trigger_usage_records: list[dict[str, Any]],
    damage_records: list[dict[str, Any]],
    break_records: list[dict[str, Any]],
    toughness_records: list[dict[str, Any]],
    dot_records: list[dict[str, Any]],
    super_break_records: list[dict[str, Any]],
    diff_limit: int = 20,
) -> dict[str, Any]:
    changes = [row for row in (transition.get("state_changes") or []) if isinstance(row, dict)]
    issues: list[dict[str, Any]] = []
    issue_count = 0
    target_record_valid_count = 0
    hp_record_valid_count = 0
    shield_record_valid_count = 0
    sp_record_valid_count = 0
    energy_record_valid_count = 0
    status_record_valid_count = 0
    av_record_valid_count = 0
    turn_record_valid_count = 0
    queue_record_valid_count = 0
    trigger_usage_record_valid_count = 0
    damage_record_valid_count = 0
    break_record_valid_count = 0
    toughness_record_valid_count = 0
    dot_record_valid_count = 0
    super_break_record_valid_count = 0
    consumed_hp_changes: set[int] = set()
    consumed_shield_changes: set[int] = set()
    consumed_sp_changes: set[int] = set()
    consumed_energy_changes: set[int] = set()
    consumed_status_changes: set[int] = set()
    consumed_av_changes: set[int] = set()
    consumed_turn_changes: set[int] = set()
    consumed_queue_changes: set[int] = set()
    consumed_trigger_usage_changes: set[int] = set()
    consumed_damage_changes: set[int] = set()
    consumed_break_changes: set[int] = set()
    consumed_toughness_changes: set[int] = set()
    consumed_dot_changes: set[int] = set()
    consumed_super_break_changes: set[int] = set()

    def add_issue(path: str, message: str, *, actual: Any = None, expected: Any = None) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < diff_limit:
            issue = {"path": path, "message": message}
            if actual is not None or expected is not None:
                issue["actual"] = actual
                issue["expected"] = expected
            issues.append(issue)

    def compare(path: str, actual: Any, expected: Any) -> bool:
        if _settlement_equal(actual, expected):
            return True
        add_issue(path, "value_mismatch", actual=actual, expected=expected)
        return False

    def matching_state_change(
        *,
        consumed: set[int],
        field_path: str,
        subject_id: str,
        old_value: Any,
        new_value: Any,
        change_type: str | None = None,
    ) -> tuple[int | None, dict[str, Any] | None]:
        for change_index, change in enumerate(changes):
            if change_index in consumed:
                continue
            if change_type is not None and change.get("change_type") != change_type:
                continue
            if change.get("field_path") != field_path or change.get("subject_id") != subject_id:
                continue
            if not _settlement_equal(change.get("old_value"), old_value):
                continue
            if not _settlement_equal(change.get("new_value"), new_value):
                continue
            return change_index, change
        return None, None

    def matching_resource_change(**kwargs: Any) -> tuple[int | None, dict[str, Any] | None]:
        return matching_state_change(change_type="resource", **kwargs)

    def matching_payload_change(
        *,
        consumed: set[int],
        change_type: str,
        field_path: str,
        subject_id: str,
        payload: dict[str, Any],
    ) -> tuple[int | None, dict[str, Any] | None]:
        for change_index, change in enumerate(changes):
            if change_index in consumed:
                continue
            if change.get("change_type") != change_type:
                continue
            if change.get("field_path") != field_path or change.get("subject_id") != subject_id:
                continue
            if not _settlement_equal(change.get("payload"), payload):
                continue
            return change_index, change
        return None, None

    def status_stacks(value: Any) -> int:
        if isinstance(value, dict):
            try:
                return int(value.get("stacks") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def status_max_stacks(value: Any) -> int:
        if isinstance(value, dict):
            try:
                return int(value.get("max_stacks") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def status_duration_type(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("duration_type") or "")
        return ""

    def status_duration_value(value: Any) -> float:
        if isinstance(value, dict):
            raw = value.get("duration_value")
            if isinstance(raw, (int, float)):
                return float(raw)
        return 0.0

    if target_record is not None:
        before_issue_count = issue_count
        request = transition.get("request")
        if not isinstance(request, dict):
            request = {}
            add_issue("target_record.request", "missing_action_request", actual=transition.get("request"), expected="dict")
        resolution = transition.get("target_resolution")
        if not isinstance(resolution, dict):
            resolution = {}
            add_issue("target_record.target_resolution", "missing_target_resolution", actual=transition.get("target_resolution"), expected="dict")
        compare("target_record.actor_id", target_record.get("actor_id"), request.get("actor_id"))
        compare("target_record.action_id", target_record.get("action_id"), request.get("action_id"))
        compare("target_record.target_ids", target_record.get("target_ids") or [], resolution.get("resolved_target_ids") or [])
        compare("target_record.target_selection_reason", target_record.get("target_selection_reason"), resolution.get("method"))
        compare("target_record.target_resolution.actor_id", target_record.get("actor_id"), resolution.get("actor_id"))
        compare("target_record.target_resolution.action_id", target_record.get("action_id"), resolution.get("action_id"))
        if issue_count == before_issue_count:
            target_record_valid_count = 1

    for record_index, rec in enumerate(sp_records):
        before_issue_count = issue_count
        prefix = f"sp_records[{record_index}]"
        change_index, change = matching_resource_change(
            consumed=consumed_sp_changes,
            field_path="global.skill_points",
            subject_id="team",
            old_value=rec.get("old_sp"),
            new_value=rec.get("new_sp"),
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_skill_point_state_change",
                actual=None,
                expected={"old_value": rec.get("old_sp"), "new_value": rec.get("new_sp")},
            )
            continue
        consumed_sp_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("new_sp") - rec.get("old_sp"))
        payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}
        compare(f"{prefix}.state_change.payload.requested_delta", payload.get("requested_delta"), rec.get("delta"))
        if rec.get("source_id"):
            compare(f"{prefix}.state_change.source.owner_id", (change.get("source") or {}).get("owner_id"), rec.get("source_id"))
        if issue_count == before_issue_count:
            sp_record_valid_count += 1

    for record_index, rec in enumerate(energy_records):
        before_issue_count = issue_count
        prefix = f"energy_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_resource_change(
            consumed=consumed_energy_changes,
            field_path="unit.energy",
            subject_id=unit_id,
            old_value=rec.get("old_energy"),
            new_value=rec.get("new_energy"),
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_energy_state_change",
                actual=None,
                expected={"unit_id": unit_id, "old_value": rec.get("old_energy"), "new_value": rec.get("new_energy")},
            )
            continue
        consumed_energy_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("new_energy") - rec.get("old_energy"))
        payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}
        source_type = str(rec.get("source_type") or "")
        requested_delta = rec.get("delta")
        if source_type == "energy_cost":
            compare(f"{prefix}.state_change.payload.energy_cost", payload.get("energy_cost"), abs(float(requested_delta or 0.0)))
        elif source_type == "action_energy":
            compare(f"{prefix}.state_change.reason", change.get("reason"), f"energy:{rec.get('label')}")
            compare(f"{prefix}.state_change.payload.gain", payload.get("gain"), requested_delta)
        elif source_type == "effect_energy":
            compare(f"{prefix}.state_change.reason", change.get("reason"), "effect:modify_energy")
        else:
            add_issue(f"{prefix}.source_type", "unsupported_energy_record_source_type", actual=source_type, expected="energy_cost/action_energy/effect_energy")
        if rec.get("max_energy") is not None and isinstance(rec.get("new_energy"), (int, float)):
            if float(rec.get("new_energy")) - float(rec.get("max_energy") or 0.0) > NUMERIC_TOLERANCE:
                add_issue(f"{prefix}.new_energy", "new_energy_above_max_energy", actual=rec.get("new_energy"), expected=f"<= {rec.get('max_energy')}")
        if issue_count == before_issue_count:
            energy_record_valid_count += 1

    for record_index, rec in enumerate(hp_records):
        before_issue_count = issue_count
        prefix = f"hp_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_resource_change(
            consumed=consumed_hp_changes,
            field_path="unit.hp",
            subject_id=unit_id,
            old_value=rec.get("old_hp"),
            new_value=rec.get("new_hp"),
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_hp_state_change",
                actual=None,
                expected={"unit_id": unit_id, "old_value": rec.get("old_hp"), "new_value": rec.get("new_hp")},
            )
            continue
        consumed_hp_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        if issue_count == before_issue_count:
            hp_record_valid_count += 1

    for record_index, rec in enumerate(shield_records):
        before_issue_count = issue_count
        prefix = f"shield_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_resource_change(
            consumed=consumed_shield_changes,
            field_path="unit.shield",
            subject_id=unit_id,
            old_value=rec.get("old_shield"),
            new_value=rec.get("new_shield"),
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_shield_state_change",
                actual=None,
                expected={"unit_id": unit_id, "old_value": rec.get("old_shield"), "new_value": rec.get("new_shield")},
            )
            continue
        consumed_shield_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        if issue_count == before_issue_count:
            shield_record_valid_count += 1

    for record_index, rec in enumerate(av_records):
        before_issue_count = issue_count
        prefix = f"av_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_state_change(
            consumed=consumed_av_changes,
            field_path="unit.remaining_av",
            subject_id=unit_id,
            old_value=rec.get("old_remaining_av"),
            new_value=rec.get("new_remaining_av"),
            change_type="av",
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_av_state_change",
                actual=None,
                expected={"unit_id": unit_id, "old_value": rec.get("old_remaining_av"), "new_value": rec.get("new_remaining_av")},
            )
            continue
        consumed_av_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        if rec.get("source_id"):
            compare(f"{prefix}.state_change.source.source_id", (change.get("source") or {}).get("source_id"), rec.get("source_id"))
        if issue_count == before_issue_count:
            av_record_valid_count += 1

    for record_index, rec in enumerate(status_records):
        before_issue_count = issue_count
        prefix = f"status_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        status_id = str(rec.get("status_id") or "")
        change_type = str(rec.get("change_type") or "")
        change_index = None
        change = None
        for candidate_index, candidate in enumerate(changes):
            if candidate_index in consumed_status_changes:
                continue
            if candidate.get("change_type") != "status":
                continue
            if candidate.get("field_path") == f"unit.statuses.{status_id}" and candidate.get("subject_id") == unit_id:
                change_index, change = candidate_index, candidate
                break
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_status_state_change",
                actual=None,
                expected={"unit_id": unit_id, "status_id": status_id},
            )
            continue
        consumed_status_changes.add(change_index)
        old_value = change.get("old_value")
        new_value = change.get("new_value")
        expected_value = old_value if change_type == "remove" else new_value
        compare(f"{prefix}.state_change.delta", change.get("delta"), change_type)
        compare(f"{prefix}.old_stacks", rec.get("old_stacks"), status_stacks(old_value))
        compare(f"{prefix}.new_stacks", rec.get("new_stacks"), status_stacks(new_value))
        compare(f"{prefix}.max_stacks", rec.get("max_stacks"), status_max_stacks(expected_value))
        compare(f"{prefix}.duration_type", str(rec.get("duration_type") or ""), status_duration_type(expected_value))
        compare(f"{prefix}.duration_value", rec.get("duration_value"), status_duration_value(expected_value))
        if rec.get("source_id"):
            compare(f"{prefix}.state_change.source.owner_id", (change.get("source") or {}).get("owner_id"), rec.get("source_id"))
        if issue_count == before_issue_count:
            status_record_valid_count += 1

    for record_index, rec in enumerate(turn_records):
        before_issue_count = issue_count
        prefix = f"turn_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_payload_change(
            consumed=consumed_turn_changes,
            change_type="turn",
            field_path="unit.turn",
            subject_id=unit_id,
            payload=rec,
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_turn_state_change",
                actual=None,
                expected={"unit_id": unit_id, "payload": rec},
            )
            continue
        consumed_turn_changes.add(change_index)
        compare(f"{prefix}.state_change.reason", change.get("reason"), rec.get("event_type"))
        if issue_count == before_issue_count:
            turn_record_valid_count += 1

    for record_index, rec in enumerate(queue_records):
        before_issue_count = issue_count
        prefix = f"queue_records[{record_index}]"
        queue_name = str(rec.get("queue_name") or "")
        change_index, change = matching_state_change(
            consumed=consumed_queue_changes,
            field_path=f"battle.queues.{queue_name}",
            subject_id=queue_name,
            old_value=rec.get("old_queue") or [],
            new_value=rec.get("new_queue") or [],
            change_type="queue",
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_queue_state_change",
                actual=None,
                expected={"queue_name": queue_name, "old_value": rec.get("old_queue"), "new_value": rec.get("new_queue")},
            )
            continue
        consumed_queue_changes.add(change_index)
        delta = change.get("delta") if isinstance(change.get("delta"), dict) else {}
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        compare(f"{prefix}.operation", rec.get("operation"), delta.get("op") or "")
        compare(f"{prefix}.reason", change.get("reason"), rec.get("reason"))
        compare(f"{prefix}.payload", change.get("payload") or {}, rec.get("payload") or {})
        if rec.get("source_id"):
            compare(f"{prefix}.state_change.source.source_id", (change.get("source") or {}).get("source_id"), rec.get("source_id"))
        if issue_count == before_issue_count:
            queue_record_valid_count += 1

    for record_index, rec in enumerate(trigger_usage_records):
        before_issue_count = issue_count
        prefix = f"trigger_usage_records[{record_index}]"
        key = str(rec.get("key") or "")
        change_index, change = matching_state_change(
            consumed=consumed_trigger_usage_changes,
            field_path=f"battle.trigger_usage.{key}",
            subject_id=key,
            old_value=rec.get("old_count"),
            new_value=rec.get("new_count"),
            change_type="trigger_usage",
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_trigger_usage_state_change",
                actual=None,
                expected={"key": key, "old_value": rec.get("old_count"), "new_value": rec.get("new_count")},
            )
            continue
        consumed_trigger_usage_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        compare(f"{prefix}.reason", change.get("reason"), rec.get("reason"))
        compare(f"{prefix}.payload", change.get("payload") or {}, rec.get("payload") or {})
        if rec.get("source_id"):
            compare(f"{prefix}.state_change.source.source_id", (change.get("source") or {}).get("source_id"), rec.get("source_id"))
        if issue_count == before_issue_count:
            trigger_usage_record_valid_count += 1

    for record_index, rec in enumerate(damage_records):
        before_issue_count = issue_count
        prefix = f"damage_records[{record_index}]"
        target_id = str(rec.get("target_id") or "")
        change_index, change = matching_payload_change(
            consumed=consumed_damage_changes,
            change_type="damage",
            field_path="unit.hp_or_shield",
            subject_id=target_id,
            payload=rec,
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_damage_audit_state_change",
                actual=None,
                expected={"target_id": target_id, "payload": rec},
            )
            continue
        consumed_damage_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), -float(rec.get("damage_applied") or 0.0))
        if issue_count == before_issue_count:
            damage_record_valid_count += 1

    for record_index, rec in enumerate(break_records):
        before_issue_count = issue_count
        prefix = f"break_records[{record_index}]"
        target_id = str(rec.get("target_id") or "")
        change_index, change = matching_payload_change(
            consumed=consumed_break_changes,
            change_type="break",
            field_path="unit.toughness.break",
            subject_id=target_id,
            payload=rec,
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_break_audit_state_change",
                actual=None,
                expected={"target_id": target_id, "payload": rec},
            )
            continue
        consumed_break_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), -float(rec.get("damage_applied") or 0.0))
        if issue_count == before_issue_count:
            break_record_valid_count += 1

    for record_index, rec in enumerate(dot_records):
        before_issue_count = issue_count
        prefix = f"dot_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_payload_change(
            consumed=consumed_dot_changes,
            change_type="dot",
            field_path="unit.hp_or_shield",
            subject_id=unit_id,
            payload=rec,
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_dot_audit_state_change",
                actual=None,
                expected={"unit_id": unit_id, "payload": rec},
            )
            continue
        consumed_dot_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), -float(rec.get("damage_applied") or 0.0))
        if issue_count == before_issue_count:
            dot_record_valid_count += 1

    for record_index, rec in enumerate(super_break_records):
        before_issue_count = issue_count
        prefix = f"super_break_records[{record_index}]"
        target_id = str(rec.get("target_id") or "")
        change_index, change = matching_payload_change(
            consumed=consumed_super_break_changes,
            change_type="super_break",
            field_path="unit.hp_or_shield",
            subject_id=target_id,
            payload=rec,
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_super_break_audit_state_change",
                actual=None,
                expected={"target_id": target_id, "payload": rec},
            )
            continue
        consumed_super_break_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), -float(rec.get("damage_applied") or 0.0))
        if issue_count == before_issue_count:
            super_break_record_valid_count += 1

    for record_index, rec in enumerate(toughness_records):
        before_issue_count = issue_count
        prefix = f"toughness_records[{record_index}]"
        unit_id = str(rec.get("unit_id") or "")
        change_index, change = matching_state_change(
            consumed=consumed_toughness_changes,
            field_path="unit.toughness",
            subject_id=unit_id,
            old_value=rec.get("old_toughness"),
            new_value=rec.get("new_toughness"),
            change_type="toughness",
        )
        if change is None or change_index is None:
            add_issue(
                f"{prefix}.state_change",
                "missing_matching_toughness_state_change",
                actual=None,
                expected={"unit_id": unit_id, "old_value": rec.get("old_toughness"), "new_value": rec.get("new_toughness")},
            )
            continue
        consumed_toughness_changes.add(change_index)
        compare(f"{prefix}.state_change.delta", change.get("delta"), rec.get("delta"))
        if issue_count == before_issue_count:
            toughness_record_valid_count += 1

    resource_record_count = len(hp_records) + len(shield_records) + len(sp_records) + len(energy_records)
    resource_record_valid_count = hp_record_valid_count + shield_record_valid_count + sp_record_valid_count + energy_record_valid_count
    control_record_count = len(queue_records) + len(trigger_usage_records)
    control_record_valid_count = queue_record_valid_count + trigger_usage_record_valid_count
    audit_record_count = len(damage_records) + len(break_records) + len(toughness_records) + len(dot_records) + len(super_break_records)
    audit_record_valid_count = damage_record_valid_count + break_record_valid_count + toughness_record_valid_count + dot_record_valid_count + super_break_record_valid_count
    target_record_count = 1 if target_record is not None else 0
    settlement_checked_record_count = target_record_count + resource_record_count + len(status_records) + len(av_records) + len(turn_records) + control_record_count + audit_record_count
    settlement_checked_record_valid_count = target_record_valid_count + resource_record_valid_count + status_record_valid_count + av_record_valid_count + turn_record_valid_count + control_record_valid_count + audit_record_valid_count
    return {
        "settlement_checked_record_count": settlement_checked_record_count,
        "settlement_checked_record_valid_count": settlement_checked_record_valid_count,
        "target_record_count": target_record_count,
        "target_record_valid_count": target_record_valid_count,
        "resource_record_count": resource_record_count,
        "resource_record_valid_count": resource_record_valid_count,
        "hp_record_count": len(hp_records),
        "hp_record_valid_count": hp_record_valid_count,
        "shield_record_count": len(shield_records),
        "shield_record_valid_count": shield_record_valid_count,
        "sp_record_count": len(sp_records),
        "sp_record_valid_count": sp_record_valid_count,
        "energy_record_count": len(energy_records),
        "energy_record_valid_count": energy_record_valid_count,
        "status_record_count": len(status_records),
        "status_record_valid_count": status_record_valid_count,
        "av_record_count": len(av_records),
        "av_record_valid_count": av_record_valid_count,
        "turn_record_count": len(turn_records),
        "turn_record_valid_count": turn_record_valid_count,
        "control_record_count": control_record_count,
        "control_record_valid_count": control_record_valid_count,
        "queue_record_count": len(queue_records),
        "queue_record_valid_count": queue_record_valid_count,
        "trigger_usage_record_count": len(trigger_usage_records),
        "trigger_usage_record_valid_count": trigger_usage_record_valid_count,
        "audit_record_count": audit_record_count,
        "audit_record_valid_count": audit_record_valid_count,
        "damage_settlement_record_count": len(damage_records),
        "damage_settlement_record_valid_count": damage_record_valid_count,
        "break_settlement_record_count": len(break_records),
        "break_settlement_record_valid_count": break_record_valid_count,
        "toughness_settlement_record_count": len(toughness_records),
        "toughness_settlement_record_valid_count": toughness_record_valid_count,
        "dot_settlement_record_count": len(dot_records),
        "dot_settlement_record_valid_count": dot_record_valid_count,
        "super_break_settlement_record_count": len(super_break_records),
        "super_break_settlement_record_valid_count": super_break_record_valid_count,
        "settlement_record_match": issue_count == 0,
        "settlement_record_mismatch_count": issue_count,
        "settlement_record_mismatches": issues,
    }


@dataclass
class SettlementCollector:
    """结算收集器——在 resolve_route_step 中创建，通过 action_ctx 传递。

    可选注册表（text_map / status_registry / skill_registry）用于自动补全中文名。
    无注册表时 collector 仍正常工作，不抛异常。
    """

    # 按记录类型分组（保持发生顺序）
    damage_records: list[DamageRecord] = field(default_factory=list)
    shield_records: list[ShieldRecord] = field(default_factory=list)
    hp_records: list[HPRecord] = field(default_factory=list)
    energy_records: list[EnergyRecord] = field(default_factory=list)
    sp_records: list[SPRecord] = field(default_factory=list)
    status_records: list[StatusRecord] = field(default_factory=list)
    av_records: list[AVRecord] = field(default_factory=list)
    turn_records: list[TurnRecord] = field(default_factory=list)
    queue_records: list[QueueRecord] = field(default_factory=list)
    trigger_usage_records: list[TriggerUsageRecord] = field(default_factory=list)
    mechanic_records: list[MechanicRecord] = field(default_factory=list)
    break_records: list[BreakRecord] = field(default_factory=list)
    toughness_records: list[ToughnessRecord] = field(default_factory=list)
    dot_records: list[DotRecord] = field(default_factory=list)
    super_break_records: list[SuperBreakRecord] = field(default_factory=list)
    target_record: TargetRecord | None = None
    transition: ActionTransition = field(default_factory=ActionTransition)

    def __init__(
        self,
        text_map: Any = None,
        status_registry: Any = None,
        skill_registry: Any = None,
    ) -> None:
        self.damage_records = []
        self.shield_records = []
        self.hp_records = []
        self.energy_records = []
        self.sp_records = []
        self.status_records = []
        self.av_records = []
        self.turn_records = []
        self.queue_records = []
        self.trigger_usage_records = []
        self.mechanic_records = []
        self.break_records = []
        self.toughness_records = []
        self.dot_records = []
        self.super_break_records = []
        self.target_record = None
        self.transition = ActionTransition()
        self._text_map = text_map
        self._status_registry = status_registry
        self._skill_registry = skill_registry

    # ── 便捷记录方法 (主代码通过 _settle(ctx, record_type, **kwargs) 调用) ──

    def begin_action(self, request: ActionRequest) -> None:
        self.transition = ActionTransition(request=request)

    def capture_before_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.transition.capture_before(snapshot)

    def capture_after_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.transition.capture_after(snapshot)

    def record_state_change(self, change: StateChange) -> None:
        self.transition.append_change(change)

    def record_rng_event(self, event: RNGEvent) -> None:
        self.transition.append_rng_event(event)

    def record_process_event(self, event: ProcessEvent) -> None:
        self.transition.append_process_event(event)

    def _action_source(self, *, source_id: str = "", owner_id: str = "") -> SourceRef:
        request = self.transition.request
        return SourceRef.action(
            actor_id=owner_id or request.actor_id,
            action_id=source_id or request.action_id,
            origin_path=request.source.origin_path,
        )

    def _record_change(
        self,
        change_type: str,
        *,
        scope: str,
        subject_id: str = "",
        field_path: str = "",
        old_value: Any = None,
        new_value: Any = None,
        delta: Any = None,
        source: SourceRef | None = None,
        reason: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.transition.append_change(
            StateChange(
                change_type=change_type,
                scope=scope,
                subject_id=str(subject_id or ""),
                field_path=str(field_path or ""),
                old_value=old_value,
                new_value=new_value,
                delta=delta,
                source=source or self._action_source(),
                reason=str(reason or ""),
                payload=dict(payload or {}),
            )
        )

    def record_target(self, target_ids: list[str], method: str = "explicit") -> None:
        request = self.transition.request
        decision_trace = []
        if self.transition.target_resolution is not None:
            decision_trace = deepcopy(self.transition.target_resolution.decision_trace)
        self.target_record = TargetRecord(
            action_id=request.action_id, actor_id=request.actor_id,
            target_ids=list(target_ids), target_selection_reason=method,
        )
        resolution = TargetResolution(
            actor_id=request.actor_id,
            action_id=request.action_id,
            requested_target_ids=list(request.target_ids or []),
            resolved_target_ids=list(target_ids or []),
            method=str(method or ""),
            reason=str(method or ""),
            source=request.source,
            decision_trace=decision_trace,
        )
        self.transition.target_resolution = resolution
        self.transition.append_process_event(
            ProcessEvent(
                event_type="target_resolution",
                subject_id=request.actor_id,
                source=request.source,
                reason="target:resolution",
                payload={
                    "actor_id": resolution.actor_id,
                    "action_id": resolution.action_id,
                    "requested_target_ids": list(resolution.requested_target_ids or []),
                    "resolved_target_ids": list(resolution.resolved_target_ids or []),
                    "method": resolution.method,
                    "reason": resolution.reason,
                    "source": resolution.source.to_dict(),
                },
            )
        )

    def record_target_decision(self, decision: dict[str, Any]) -> None:
        request = self.transition.request
        if self.transition.target_resolution is None:
            self.transition.target_resolution = TargetResolution(
                actor_id=request.actor_id,
                action_id=request.action_id,
                requested_target_ids=list(request.target_ids or []),
                source=request.source,
            )
        decision_payload = deepcopy(decision)
        decision_index = len(self.transition.target_resolution.decision_trace) + 1
        self.transition.target_resolution.decision_trace.append(decision_payload)
        resolved_target_ids = decision_payload.get("resolved_target_ids")
        self.transition.append_process_event(
            ProcessEvent(
                event_type="target_decision",
                subject_id=str(decision_payload.get("actor_id") or request.actor_id or ""),
                source=request.source,
                reason="target:decision",
                payload={
                    "decision_index": decision_index,
                    "stage": str(decision_payload.get("stage") or ""),
                    "actor_id": str(decision_payload.get("actor_id") or request.actor_id or ""),
                    "action_id": str(decision_payload.get("action_id") or request.action_id or ""),
                    "resolved_target_ids": list(resolved_target_ids or []) if isinstance(resolved_target_ids, list) else [],
                    "decision": decision_payload,
                },
            )
        )

    def record_damage(self, **kwargs: Any) -> None:
        """kwargs 映射到 DamageRecord 字段名不匹配时做转换。"""
        mapped = {}
        for k, v in kwargs.items():
            if k == "crit_multiplier":
                mapped["crit_dmg_mult"] = v
            elif k == "dmg_bonus_multiplier":
                mapped["dmg_bonus_mult"] = v
            elif k == "def_multiplier":
                mapped["def_mult"] = v
            elif k == "res_multiplier":
                mapped["res_mult"] = v
            elif k == "damage_taken_multiplier":
                mapped["dmg_taken_mult"] = v
            elif k == "universal_reduction_multiplier" or k == "toughness_state_multiplier":
                mapped["toughness_mult"] = v
            elif k == "applied_damage":
                mapped["damage_applied"] = v
            elif k in DamageRecord.__dataclass_fields__:
                mapped[k] = v
        rec = DamageRecord(**mapped)
        self.damage_records.append(rec)
        self._record_change(
            "damage",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=self._action_source(source_id=rec.source_action_id, owner_id=rec.actor_id),
            reason=rec.damage_type,
            payload=asdict(rec),
        )

    def record_sp(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_sp"] = int(v)
            elif k == "new_value":
                mapped["new_sp"] = int(v)
            elif k == "max_value":
                mapped["sp_cap"] = int(v)
            elif k == "reason":
                mapped["reason"] = f"{v}: {kwargs.get('reason_detail', '')}"
            elif k == "source_unit_id":
                mapped["source_id"] = str(v)
            elif k in ("delta",):
                mapped[k] = int(v)
            elif k in SPRecord.__dataclass_fields__:
                mapped[k] = v
        rec = SPRecord(**mapped)
        self.sp_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="global",
                subject_id="team",
                field_path="global.skill_points",
                old_value=rec.old_sp,
                new_value=rec.new_sp,
                delta=rec.delta,
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_energy(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_energy"] = float(v)
            elif k == "new_value":
                mapped["new_energy"] = float(v)
            elif k == "source_detail":
                mapped["label"] = str(v)
            elif k in ("affected_by_err",):
                pass  # 元信息，不存入记录
            elif k in EnergyRecord.__dataclass_fields__:
                mapped[k] = v
        rec = EnergyRecord(**mapped)
        self.energy_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.energy",
                old_value=rec.old_energy,
                new_value=rec.new_energy,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id, owner_id=rec.unit_id),
                reason=rec.source_type or rec.label,
                payload=asdict(rec),
            )

    def record_shield(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_shield"] = float(v)
            elif k == "new_value":
                mapped["new_shield"] = float(v)
            elif k in ShieldRecord.__dataclass_fields__:
                mapped[k] = v
        rec = ShieldRecord(**mapped)
        self.shield_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.shield",
                old_value=rec.old_shield,
                new_value=rec.new_shield,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_hp(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_hp"] = float(v)
            elif k == "new_value":
                mapped["new_hp"] = float(v)
            elif k == "reason":
                mapped["reason"] = str(v)
            elif k in HPRecord.__dataclass_fields__:
                mapped[k] = v
        rec = HPRecord(**mapped)
        self.hp_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "resource",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.hp",
                old_value=rec.old_hp,
                new_value=rec.new_hp,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_status(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "target_unit_id":
                mapped["unit_id"] = str(v)
            elif k == "source_unit_id":
                mapped["source_id"] = str(v)
            elif k == "stacks_before":
                mapped["old_stacks"] = int(v)
            elif k == "stacks_after":
                mapped["new_stacks"] = int(v)
            elif k == "trigger_reason":
                mapped["reason"] = str(v)
            elif k == "modifier_keys":
                pass  # 摘要信息，不存入
            elif k in StatusRecord.__dataclass_fields__:
                mapped[k] = v
        rec = StatusRecord(**mapped)
        # Phase 2.5: 自动补中文名 / status_type
        if self._status_registry is not None and rec.status_id:
            try:
                info = self._status_registry.lookup(int(rec.status_id))
                if info is not None:
                    if not rec.status_name_cn:
                        rec.status_name_cn = info.name_cn
                    if not rec.status_type:
                        rec.status_type = info.status_type
            except (ValueError, TypeError):
                pass
        self.status_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "status",
                scope="unit",
                subject_id=rec.unit_id,
                field_path=f"unit.statuses.{rec.status_id}",
                old_value=rec.old_stacks,
                new_value=rec.new_stacks,
                delta=rec.new_stacks - rec.old_stacks,
                source=SourceRef.status(owner_id=rec.source_id or rec.unit_id, status_id=rec.status_id),
                reason=rec.change_type or rec.reason,
                payload=asdict(rec),
            )

    def record_av(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k in {"old_absolute_av", "new_absolute_av", "speed"}:
                mapped[k] = float(v)
            elif k == "action_interval":
                mapped[k] = None if v is None else float(v)
            elif k == "change_type":
                mapped["reason"] = str(v)
            elif k == "change_detail":
                mapped["detail"] = str(v)
                if "reason" not in mapped:
                    mapped["reason"] = str(v)
            elif k == "old_remaining_av":
                mapped["old_remaining_av"] = float(v)
            elif k == "new_remaining_av":
                new_val = float(v)
                mapped["new_remaining_av"] = new_val
                mapped["delta"] = new_val - float(kwargs.get("old_remaining_av", new_val))
            elif k in AVRecord.__dataclass_fields__:
                mapped[k] = v
        rec = AVRecord(**mapped)
        self.av_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "av",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.remaining_av",
                old_value=rec.old_remaining_av,
                new_value=rec.new_remaining_av,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_turn(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "event":
                mapped["event_type"] = str(v)
            elif k in TurnRecord.__dataclass_fields__:
                mapped[k] = v
        rec = TurnRecord(**mapped)
        self.turn_records.append(rec)
        self._record_change(
            "turn",
            scope="unit",
            subject_id=rec.unit_id,
            field_path="unit.turn",
            source=self._action_source(source_id=rec.action_id, owner_id=rec.unit_id),
            reason=rec.event_type,
            payload=asdict(rec),
        )

    def record_queue(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_queue"] = list(v or [])
            elif k == "new_value":
                mapped["new_queue"] = list(v or [])
            elif k in {"delta", "item", "payload"}:
                mapped[k] = deepcopy(v) if isinstance(v, dict) else {}
            elif k in QueueRecord.__dataclass_fields__:
                mapped[k] = v
        rec = QueueRecord(**mapped)
        self.queue_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "queue",
                scope="battle",
                subject_id=rec.queue_name,
                field_path=f"battle.queues.{rec.queue_name}",
                old_value=deepcopy(rec.old_queue),
                new_value=deepcopy(rec.new_queue),
                delta=deepcopy(rec.delta),
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=deepcopy(rec.payload),
            )

    def record_trigger_usage(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_count"] = int(v or 0)
            elif k == "new_value":
                mapped["new_count"] = None if v is None else int(v)
            elif k == "payload":
                mapped[k] = deepcopy(v) if isinstance(v, dict) else {}
            elif k in TriggerUsageRecord.__dataclass_fields__:
                mapped[k] = v
        rec = TriggerUsageRecord(**mapped)
        self.trigger_usage_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "trigger_usage",
                scope="battle",
                subject_id=rec.key,
                field_path=f"battle.trigger_usage.{rec.key}",
                old_value=rec.old_count,
                new_value=rec.new_count,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=deepcopy(rec.payload),
            )

    def record_mechanic(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k in MechanicRecord.__dataclass_fields__:
                mapped[k] = v
            elif k == "detail":
                mapped["description"] = str(v)
            elif k == "data":
                mapped["data"] = dict(v) if isinstance(v, dict) else {}
        rec = MechanicRecord(**mapped)
        self.mechanic_records.append(rec)
        self._record_change(
            "mechanic",
            scope="unit" if rec.unit_id else "battle",
            subject_id=rec.unit_id,
            field_path="mechanic",
            reason=rec.event_type,
            payload=asdict(rec),
        )

    def record_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "aftermath_status":
                mapped["aftermath_status_id"] = str(v)
            elif k in BreakRecord.__dataclass_fields__:
                mapped[k] = v
        rec = BreakRecord(**mapped)
        self.break_records.append(rec)
        self._record_change(
            "break",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.toughness.break",
            delta=-rec.damage_applied,
            source=self._action_source(owner_id=rec.actor_id),
            reason="weakness_break",
            payload=asdict(rec),
        )

    def record_toughness(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "old_value":
                mapped["old_toughness"] = float(v)
            elif k == "new_value":
                mapped["new_toughness"] = float(v)
            elif k in ToughnessRecord.__dataclass_fields__:
                mapped[k] = v
        rec = ToughnessRecord(**mapped)
        self.toughness_records.append(rec)
        if kwargs.get("record_state_change", True):
            self._record_change(
                "toughness",
                scope="unit",
                subject_id=rec.unit_id,
                field_path="unit.toughness",
                old_value=rec.old_toughness,
                new_value=rec.new_toughness,
                delta=rec.delta,
                source=self._action_source(source_id=rec.source_id),
                reason=rec.reason,
                payload=asdict(rec),
            )

    def record_dot(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "source_status":
                mapped["source_status_id"] = str(v)
            elif k in DotRecord.__dataclass_fields__:
                mapped[k] = v
        rec = DotRecord(**mapped)
        self.dot_records.append(rec)
        self._record_change(
            "dot",
            scope="unit",
            subject_id=rec.unit_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=SourceRef.status(owner_id=rec.unit_id, status_id=rec.source_status_id),
            reason=rec.kind,
            payload=asdict(rec),
        )

    def record_super_break(self, **kwargs: Any) -> None:
        mapped = {}
        for k, v in kwargs.items():
            if k == "break_effect":
                mapped["break_effect_mult"] = float(v)
            elif k == "super_break_bonus_mult":
                mapped["super_break_bonus"] = float(v)
            elif k in SuperBreakRecord.__dataclass_fields__:
                mapped[k] = v
        rec = SuperBreakRecord(**mapped)
        self.super_break_records.append(rec)
        self._record_change(
            "super_break",
            scope="unit",
            subject_id=rec.target_id,
            field_path="unit.hp_or_shield",
            delta=-rec.damage_applied,
            source=self._action_source(owner_id=rec.actor_id),
            reason="super_break",
            payload=asdict(rec),
        )

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典，供 run_route 写入 trace_entry。"""
        transition = self.transition.to_dict()
        damage_records = [asdict(r) for r in self.damage_records]
        shield_records = [asdict(r) for r in self.shield_records]
        hp_records = [asdict(r) for r in self.hp_records]
        energy_records = [asdict(r) for r in self.energy_records]
        sp_records = [asdict(r) for r in self.sp_records]
        status_records = [asdict(r) for r in self.status_records]
        av_records = [asdict(r) for r in self.av_records]
        turn_records = [asdict(r) for r in self.turn_records]
        queue_records = [asdict(r) for r in self.queue_records]
        trigger_usage_records = [asdict(r) for r in self.trigger_usage_records]
        mechanic_records = [asdict(r) for r in self.mechanic_records]
        break_records = [asdict(r) for r in self.break_records]
        toughness_records = [asdict(r) for r in self.toughness_records]
        dot_records = [asdict(r) for r in self.dot_records]
        super_break_records = [asdict(r) for r in self.super_break_records]
        replay_validation = validate_transition_replay(transition)
        settlement_validation = _validate_resource_record_consistency(
            transition,
            target_record=asdict(self.target_record) if self.target_record else None,
            hp_records=hp_records,
            shield_records=shield_records,
            sp_records=sp_records,
            energy_records=energy_records,
            status_records=status_records,
            av_records=av_records,
            turn_records=turn_records,
            queue_records=queue_records,
            trigger_usage_records=trigger_usage_records,
            damage_records=damage_records,
            break_records=break_records,
            toughness_records=toughness_records,
            dot_records=dot_records,
            super_break_records=super_break_records,
        )
        replay_validation.update(settlement_validation)
        replay_validation["ok"] = replay_validation.get("ok", False) and settlement_validation["settlement_record_match"]
        transition["replay_validation"] = replay_validation
        return {
            "damage_records": damage_records,
            "shield_records": shield_records,
            "hp_records": hp_records,
            "energy_records": energy_records,
            "sp_records": sp_records,
            "status_records": status_records,
            "av_records": av_records,
            "turn_records": turn_records,
            "queue_records": queue_records,
            "trigger_usage_records": trigger_usage_records,
            "mechanic_records": mechanic_records,
            "break_records": break_records,
            "toughness_records": toughness_records,
            "dot_records": dot_records,
            "super_break_records": super_break_records,
            "target_record": asdict(self.target_record) if self.target_record else None,
            "settlement_record_validation": settlement_validation,
            "transition": transition,
        }
