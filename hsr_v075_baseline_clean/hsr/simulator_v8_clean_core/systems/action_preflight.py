from __future__ import annotations

from typing import Any

from ..core.model import JSONValue
from ..rules.ir import ActionDefinitionIR, ActionEventIR
from ..rules.rulebook import RuleBook
from .resource import ResourcePlan
from .target import TargetPolicy


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


def target_policy_for_action(
    rules: RuleBook,
    action_definition: ActionDefinitionIR,
    target_mode: str,
    *,
    action_event: ActionEventIR | None = None,
) -> TargetPolicy:
    bounce_policy = bounce_policy_for_action(rules, action_definition.action_id, action_definition.level)
    source_trace = _target_policy_source_trace(action_definition, target_mode, action_event, bounce_policy)
    metadata = {
        "action_id": action_definition.action_id,
        "action_level": action_definition.level,
        "definition_id": action_definition.definition_id,
        "action_event_id": action_event.action_event_id if action_event is not None else "",
        "target_mode": target_mode,
        "action_definition_target_mode": action_definition.target_mode,
        "damage_kind": action_definition.damage_kind,
        "source_mode": action_definition.source_mode,
        "target_relation": action_event.target_relation
        if action_event is not None
        else action_definition.target_relation,
    }
    relation = str(metadata["target_relation"] or "unknown")
    allow_enemy, allow_ally, allow_self = _target_relation_flags(relation)
    selection_min = 0 if target_mode == "aoe" else 1
    selection_max = 0 if target_mode == "aoe" else 1
    impact_mode = {
        "single": "primary_only",
        "self_or_team": "primary_only",
        "blast": "primary_plus_adjacent",
        "aoe": "all_relation_targets",
        "bounce": "primary_then_rng_bounce",
    }.get(target_mode, "unknown")
    return TargetPolicy(
        policy_id=f"{relation}:{target_mode}",
        allow_enemy=allow_enemy,
        allow_ally=allow_ally,
        allow_self=allow_self,
        target_mode=target_mode,
        selection_mode="automatic" if selection_max == 0 else "explicit_primary",
        target_relation=relation,
        selection_min=selection_min,
        selection_max=selection_max,
        impact_mode=impact_mode,
        bounce_policy=bounce_policy,
        source_trace=source_trace,
        metadata=metadata,
    )


def _target_relation_flags(relation: str) -> tuple[bool, bool, bool]:
    if relation == "enemy":
        return True, False, False
    if relation == "ally":
        return False, True, False
    if relation == "self":
        return False, False, True
    if relation == "ally_or_self":
        return False, True, True
    if relation == "any":
        return True, True, True
    if relation in {"owner", "summoner", "summon"}:
        return False, True, True
    return False, False, False


def bounce_policy_for_action(rules: RuleBook, action_id: str, level: int) -> dict[str, JSONValue]:
    for profile in rules.hit_profiles_for_action(action_id, level):
        policy_id = getattr(profile, "bounce_policy_id", "")
        if not policy_id:
            continue
        policy = rules.bounce_policy(str(policy_id))
        if policy is not None:
            return policy.to_json()
    return {}


def _target_policy_source_trace(
    action_definition: ActionDefinitionIR,
    target_mode: str,
    action_event: ActionEventIR | None,
    bounce_policy: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    source_trace: dict[str, JSONValue] = {
        "action_definition": action_definition.source.to_json(),
        "target_mode": {
            "value": target_mode,
            "source": "action_event" if action_event is not None else "action_definition",
        },
    }
    if action_event is not None:
        source_trace["action_event"] = action_event.source.to_json()
    bounce_source = bounce_policy.get("source")
    if isinstance(bounce_source, dict) and bounce_source:
        source_trace["bounce_policy"] = bounce_source
    return source_trace


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
