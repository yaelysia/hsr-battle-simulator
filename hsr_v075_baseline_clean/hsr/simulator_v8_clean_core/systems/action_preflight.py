from __future__ import annotations

from typing import Any, Mapping

from ..core.model import JSONValue
from ..rules.ir import ActionDefinitionIR
from ..rules.rulebook import RuleBook
from .action_event_contract import condition_skill_type
from .resource import ResourcePlan
from .skill_properties import (
    resolve_skill_property_overrides,
    skill_property_override_evidence,
    skill_property_override_plan,
)


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
        if error.startswith("ultimate_energy_"):
            return error
        if error.startswith("resource_skill_property_override_blocked:"):
            return error
    return "resource_plan_failed"


def action_resource_plan(
    action_definition: ActionDefinitionIR,
    *,
    source: str,
    metadata: dict[str, JSONValue] | None = None,
    queue_resource_policy: dict[str, JSONValue] | None = None,
    rules: RuleBook | None = None,
    state: Any | None = None,
    actor_id: str = "",
) -> ResourcePlan:
    policy = queue_resource_policy or {}
    overrides = (
        resolve_skill_property_overrides(state, actor_id, condition_skill_type(action_definition))
        if state is not None and actor_id
        else None
    )
    override_values = skill_property_override_plan(
        action_definition,
        overrides.values if overrides is not None and overrides.ok else {},
    )
    bp_need = override_values.get("bp_need", action_definition.bp_need)
    skill_point_delta = action_skill_point_delta(bp_need, action_definition.bp_add)
    energy_gain = action_energy_gain(rules, action_definition, override_values)
    if policy.get("ignore_skill_point_delta") is True:
        skill_point_delta = 0
    if policy.get("ignore_energy_gain") is True:
        energy_gain = 0.0
    blocked_reason = ""
    if overrides is not None:
        metadata = {
            **(metadata or {}),
            "skill_property_override_plan": override_values,
            "skill_property_overrides": skill_property_override_evidence(overrides),
        }
        if not overrides.ok:
            # An unresolved or conflicting override must fail the resource
            # admission itself; formatting a fallback plan would let the body
            # charge a cost the source no longer declares.
            blocked_reason = (
                "resource_skill_property_override_blocked:" + overrides.blocked_reason
            )
            metadata["skill_property_override_blocked_reason"] = overrides.blocked_reason
    return ResourcePlan(
        skill_point_delta=skill_point_delta,
        energy_gain=energy_gain,
        energy_cost=action_definition.sp_need if action_definition.attack_type == "Ultra" else 0.0,
        source=source,
        metadata=metadata or {},
        blocked_reason=blocked_reason,
    )


def action_energy_gain(
    rules: RuleBook | None,
    definition: ActionDefinitionIR,
    override_values: Mapping[str, float] | None = None,
    *,
    base_value: float | None = None,
) -> float:
    """Single producer for one action's energy gain.

    An explicit source request (ModifySPNew scaled by action_sp_base) owns the
    body grant, so the resource plan must stay zero even when a skill property
    override changes that body value. Otherwise the plan grants the override
    and the body grants it again.
    """

    if rules is not None and action_ability_grants_base_energy(rules, definition):
        return 0.0
    values = override_values or {}
    fallback = definition.sp_base if base_value is None else base_value
    return float(values.get("sp_base", fallback))


def action_ability_grants_base_energy(rules: RuleBook, definition: ActionDefinitionIR) -> bool:
    # Explicit source requests own their timing and ERR sample; do not pre-grant SPBase.
    for task in rules.ability_tasks_for_action(definition.action_id, definition.level):
        effect = rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None
        if (
            isinstance(standard, dict) and standard.get("resource") == "energy"
            and standard.get("scale_basis") == "action_sp_base"
        ):
            return True
    return False


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
