from __future__ import annotations

from typing import Any

from ..core.model import JSONValue
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from .resource import ResourcePlan
from .target import TargetPolicy


def action_skill_point_delta(bp_need: float, bp_add: float) -> int:
    if bp_need > 0:
        return -int(bp_need)
    if bp_add > 0:
        return int(bp_add)
    return 0


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


def target_policy_for_action(
    rules: RuleBook,
    action_definition: ActionDefinitionIR,
    target_mode: str,
) -> TargetPolicy:
    bounce_policy = bounce_policy_for_action(rules, action_definition.action_id, action_definition.level)
    if target_mode == "self_or_team":
        return TargetPolicy(
            policy_id="self_or_team",
            allow_enemy=False,
            allow_ally=True,
            allow_self=True,
            target_mode=target_mode,
            selection_mode="explicit_ally_or_self",
        )
    if action_definition.damage_kind == "hp_damage":
        return TargetPolicy(
            policy_id="enemy_damage",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_mode=target_mode,
            selection_mode=target_mode,
            bounce_policy=bounce_policy,
        )
    return TargetPolicy(
        policy_id="explicit_any",
        allow_enemy=True,
        allow_ally=True,
        allow_self=True,
        target_mode=target_mode,
        selection_mode=target_mode,
        bounce_policy=bounce_policy,
    )


def bounce_policy_for_action(rules: RuleBook, action_id: str, level: int) -> dict[str, JSONValue]:
    for profile in rules.hit_profiles_for_action(action_id, level):
        policy_id = getattr(profile, "bounce_policy_id", "")
        if not policy_id:
            continue
        policy = rules.bounce_policy(str(policy_id))
        if policy is not None:
            return policy.to_json()
    return {}


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
