from __future__ import annotations

from typing import Any

from ..core.model import JSONValue
from ..rules.ir import ActionDefinitionIR
from .resource import ResourcePlan


def action_skill_point_delta(bp_need: float, bp_add: float) -> int:
    if bp_need > 0:
        return -int(bp_need)
    if bp_add > 0:
        return int(bp_add)
    return 0


def action_resource_blocked_reason(errors: tuple[str, ...]) -> str:
    for error in errors:
        if error.startswith("insufficient skill points"):
            return "insufficient_skill_points"
        if error.startswith("unknown actor_id"):
            return "resource_unknown_actor"
    return "resource_plan_failed"


def action_resource_plan(
    action_definition: ActionDefinitionIR,
    *,
    source: str,
    metadata: dict[str, JSONValue] | None = None,
    queue_resource_policy: dict[str, JSONValue] | None = None,
) -> ResourcePlan:
    policy = queue_resource_policy or {}
    skill_point_delta = action_skill_point_delta(action_definition.bp_need, action_definition.bp_add)
    energy_gain = action_definition.sp_base
    if policy.get("ignore_skill_point_delta") is True:
        skill_point_delta = 0
    if policy.get("ignore_energy_gain") is True:
        energy_gain = 0.0
    return ResourcePlan(
        skill_point_delta=skill_point_delta,
        energy_gain=energy_gain,
        source=source,
        metadata=metadata or {},
    )


def action_binding_blocked_reason(action_binding: Any | None) -> str:
    if action_binding is None:
        return "action_ability_binding_missing"
    if getattr(action_binding, "coverage_status", "") != "executable":
        return str(
            getattr(action_binding, "blocked_reason", "")
            or f"action_ability_binding_not_executable:{getattr(action_binding, 'coverage_status', '')}"
        )
    if not getattr(action_binding, "phase_ids", ()):
        return "action_ability_binding_has_no_phase_ids"
    return ""


def action_event_blocked_reason(action_event_ir: Any | None) -> str:
    if action_event_ir is None:
        return "action_event_missing"
    blocked_reason = str(getattr(action_event_ir, "blocked_reason", "") or "")
    if blocked_reason:
        return blocked_reason
    event_source_status = str(getattr(action_event_ir, "event_source_status", "") or "")
    if event_source_status != "ability_phase_graph_bound":
        return f"action_event_source_not_bound:{event_source_status}"
    return ""


def combined_blocked_reason(*reasons: str) -> str:
    return ",".join(dict.fromkeys(reason for reason in reasons if reason))
