from __future__ import annotations

from dataclasses import dataclass

from ..rules.ir import ActionDefinitionIR


@dataclass(frozen=True)
class ActionEventStep:
    kind: str
    phase: str
    canonical_window: str = ""
    tbgd_event: str = ""
    requires_action_enabled: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "canonical_window": self.canonical_window,
            "tbgd_event": self.tbgd_event,
            "requires_action_enabled": self.requires_action_enabled,
        }


@dataclass(frozen=True)
class ActionEventPlan:
    action_id: str
    action_level: int
    skill_type: str
    attack_type: str
    damage_kind: str
    damage_formula_family: str
    has_attack_windows: bool
    has_damage_step: bool
    steps: tuple[ActionEventStep, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_level": self.action_level,
            "skill_type": self.skill_type,
            "attack_type": self.attack_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "has_attack_windows": self.has_attack_windows,
            "has_damage_step": self.has_damage_step,
            "steps": [step.to_json() for step in self.steps],
        }


@dataclass(frozen=True)
class TargetPlan:
    target_mode: str
    selection_mode: str
    requested_target_ids: tuple[str, ...]
    source: str = "action_definition"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "target_mode": self.target_mode,
            "selection_mode": self.selection_mode,
            "requested_target_ids": list(self.requested_target_ids),
            "source": self.source,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class HitPlan:
    hit_index: int
    target_group: str
    multiplier_source: object
    multi_hit_not_implemented: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "hit_index": self.hit_index,
            "target_group": self.target_group,
            "multiplier_source": self.multiplier_source,
            "multi_hit_not_implemented": self.multi_hit_not_implemented,
        }


@dataclass(frozen=True)
class DamagePlan:
    hit_index: int
    target_id: str
    target_group: str
    damage_formula_family: str
    multiplier_source: object
    primary_action_target_id: str | None = None
    blocked_reason: str = ""
    target_group_multiplier_not_implemented: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "hit_index": self.hit_index,
            "target_id": self.target_id,
            "target_group": self.target_group,
            "damage_formula_family": self.damage_formula_family,
            "multiplier_source": self.multiplier_source,
            "primary_action_target_id": self.primary_action_target_id,
            "blocked_reason": self.blocked_reason,
            "target_group_multiplier_not_implemented": self.target_group_multiplier_not_implemented,
        }


@dataclass(frozen=True)
class ActionExecutionPlan:
    action_id: str
    action_level: int
    event_steps: tuple[ActionEventStep, ...]
    target_plan: TargetPlan
    hit_plan: tuple[HitPlan, ...]
    damage_plan: tuple[DamagePlan, ...]
    source_trace: dict[str, object]
    derived_reason: str
    primary_action_target_id: str | None = None
    per_hit_target_context_not_implemented: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_level": self.action_level,
            "event_steps": [step.to_json() for step in self.event_steps],
            "target_plan": self.target_plan.to_json(),
            "hit_plan": [hit.to_json() for hit in self.hit_plan],
            "damage_plan": [damage.to_json() for damage in self.damage_plan],
            "source_trace": self.source_trace,
            "derived_reason": self.derived_reason,
            "derived_from_action_definition": True,
            "primary_action_target_id": self.primary_action_target_id,
            "per_hit_target_context_not_implemented": self.per_hit_target_context_not_implemented,
        }


def build_action_event_plan(action_definition: ActionDefinitionIR) -> ActionEventPlan:
    has_damage = action_definition.damage_kind == "hp_damage"
    has_attack_windows = has_damage or _is_explicit_attack(action_definition)
    steps: list[ActionEventStep] = [
        ActionEventStep(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
        )
    ]
    if has_attack_windows:
        steps.append(
            ActionEventStep(
                kind="trigger_window",
                phase="before_attack",
                canonical_window="before_attack",
                tbgd_event="OnBeforeAttack",
            )
        )
    if has_damage:
        steps.append(ActionEventStep(kind="damage", phase="damage"))
    if has_attack_windows:
        steps.append(
            ActionEventStep(
                kind="trigger_window",
                phase="after_attack",
                canonical_window="after_attack",
                tbgd_event="OnAfterAttack",
            )
        )
    steps.append(
        ActionEventStep(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
        )
    )
    return ActionEventPlan(
        action_id=action_definition.action_id,
        action_level=action_definition.level,
        skill_type=action_definition.skill_effect,
        attack_type=action_definition.attack_type,
        damage_kind=action_definition.damage_kind,
        damage_formula_family=action_definition.damage_formula_family,
        has_attack_windows=has_attack_windows,
        has_damage_step=has_damage,
        steps=tuple(steps),
    )


def build_action_execution_plan(
    action_definition: ActionDefinitionIR,
    *,
    requested_target_ids: tuple[str, ...],
    resolved_target_groups: dict[str, tuple[str, ...]] | None = None,
    source_trace: dict[str, object] | None = None,
) -> ActionExecutionPlan:
    event_plan = build_action_event_plan(action_definition)
    target_mode = action_definition.target_mode
    target_plan = TargetPlan(
        target_mode=target_mode,
        selection_mode=_selection_mode(target_mode),
        requested_target_ids=requested_target_ids,
        blocked_reason=_target_plan_blocked_reason(target_mode),
    )
    multiplier_source = action_definition.param_list[0] if action_definition.param_list else None
    primary_action_target_id = _primary_action_target_id(resolved_target_groups or {})
    hit_plan = (
        HitPlan(
            hit_index=0,
            target_group="selected",
            multiplier_source=multiplier_source,
            multi_hit_not_implemented=True,
        ),
    )
    damage_targets = _damage_targets(action_definition, resolved_target_groups or {})
    damage_plan = tuple(
        DamagePlan(
            hit_index=0,
            target_id=target_id,
            target_group=group_name,
            damage_formula_family=action_definition.damage_formula_family,
            multiplier_source=multiplier_source,
            primary_action_target_id=primary_action_target_id,
            blocked_reason=target_plan.blocked_reason,
            target_group_multiplier_not_implemented=action_definition.target_mode in {"aoe", "blast"},
        )
        for group_name, target_ids in damage_targets
        for target_id in target_ids
    )
    return ActionExecutionPlan(
        action_id=action_definition.action_id,
        action_level=action_definition.level,
        event_steps=event_plan.steps,
        target_plan=target_plan,
        hit_plan=hit_plan,
        damage_plan=damage_plan,
        source_trace=source_trace or {},
        derived_reason="derived_from_action_definition_target_mode_and_damage_kind",
        primary_action_target_id=primary_action_target_id,
        per_hit_target_context_not_implemented=True,
    )


def _is_explicit_attack(action_definition: ActionDefinitionIR) -> bool:
    skill_effect = action_definition.skill_effect.lower()
    attack_type = action_definition.attack_type.lower()
    target_mode = action_definition.target_mode.lower()
    if target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type


def _selection_mode(target_mode: str) -> str:
    if target_mode == "single":
        return "primary"
    if target_mode == "aoe":
        return "all_enemies"
    if target_mode == "blast":
        return "primary_plus_adjacent"
    if target_mode == "bounce":
        return "blocked_random_bounce"
    if target_mode == "self_or_team":
        return "explicit_ally_or_self"
    return "unknown"


def _target_plan_blocked_reason(target_mode: str) -> str:
    if target_mode == "bounce":
        return "bounce_not_executable"
    if target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    return ""


def _damage_targets(
    action_definition: ActionDefinitionIR,
    target_groups: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if action_definition.damage_kind != "hp_damage":
        return ()
    if action_definition.target_mode == "bounce":
        return ()
    if action_definition.target_mode == "blast":
        groups: list[tuple[str, tuple[str, ...]]] = []
        primary = target_groups.get("primary", ())
        adjacent = target_groups.get("adjacent", ())
        if primary:
            groups.append(("primary", primary))
        if adjacent:
            groups.append(("adjacent", adjacent))
        return tuple(groups)
    selected = target_groups.get("selected", ())
    return (("selected", selected),) if selected else ()


def _primary_action_target_id(target_groups: dict[str, tuple[str, ...]]) -> str | None:
    primary = target_groups.get("primary", ())
    if primary:
        return primary[0]
    selected = target_groups.get("selected", ())
    if selected:
        return selected[0]
    return None
