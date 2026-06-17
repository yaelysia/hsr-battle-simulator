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


def _is_explicit_attack(action_definition: ActionDefinitionIR) -> bool:
    skill_effect = action_definition.skill_effect.lower()
    attack_type = action_definition.attack_type.lower()
    target_mode = action_definition.target_mode.lower()
    if target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type
