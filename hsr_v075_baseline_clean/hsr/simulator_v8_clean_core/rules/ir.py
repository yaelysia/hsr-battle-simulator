from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
CoverageStatus = Literal[
    "discovered_only",
    "lowered",
    "executable",
    "validated",
    "blocked",
    "supported_alias",
    "audit_only",
    "unsupported",
    "skipped_with_reason",
]


@dataclass(frozen=True)
class IRSource:
    source_path: str
    raw_type: str
    raw_id: str
    evidence: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_path": self.source_path,
            "raw_type": self.raw_type,
            "raw_id": self.raw_id,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FormulaIR:
    formula_id: str
    kind: str
    expression: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "formula_id": self.formula_id,
            "kind": self.kind,
            "expression": self.expression,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class ConditionIR:
    condition_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "condition_id": self.condition_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class EffectIR:
    effect_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class TriggerIR:
    trigger_id: str
    event: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trigger_id": self.trigger_id,
            "event": self.event,
            "conditions": list(self.conditions),
            "effects": list(self.effects),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class RuleEntity:
    entity_id: str
    entity_type: str
    fields: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "fields": self.fields,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class CombatantProfileIR:
    profile_id: str
    entity_id: str
    entity_type: str
    template_id: str
    base_stats: dict[str, JSONValue]
    toughness_profile: dict[str, JSONValue]
    weaknesses: tuple[str, ...]
    resistances: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "profile_id": self.profile_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "template_id": self.template_id,
            "base_stats": self.base_stats,
            "toughness_profile": self.toughness_profile,
            "weaknesses": list(self.weaknesses),
            "resistances": self.resistances,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AvatarProfileIR:
    avatar_profile_id: str
    avatar_id: str
    base_type: str
    damage_type: str
    skill_ids: tuple[str, ...]
    base_stats_by_promotion: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "avatar_profile_id": self.avatar_profile_id,
            "avatar_id": self.avatar_id,
            "base_type": self.base_type,
            "damage_type": self.damage_type,
            "skill_ids": list(self.skill_ids),
            "base_stats_by_promotion": self.base_stats_by_promotion,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterDataCardIR:
    card_id: str
    entity_ref: str
    profile_id: str
    skill_ids: tuple[str, ...]
    skill_formula_binding_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "card_id": self.card_id,
            "entity_ref": self.entity_ref,
            "profile_id": self.profile_id,
            "skill_ids": list(self.skill_ids),
            "skill_formula_binding_ids": list(self.skill_formula_binding_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionPhaseStepIR:
    kind: str
    phase: str
    canonical_window: str = ""
    tbgd_event: str = ""
    requires_action_enabled: bool = True
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    source: IRSource | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "canonical_window": self.canonical_window,
            "tbgd_event": self.tbgd_event,
            "requires_action_enabled": self.requires_action_enabled,
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "source": self.source.to_json() if self.source else None,
        }


@dataclass(frozen=True)
class HitProfileIR:
    hit_profile_id: str
    action_id: str
    level: int
    hit_index: int
    target_group: str
    multiplier_expr: dict[str, JSONValue]
    multiplier_source: dict[str, JSONValue]
    stance_expr: dict[str, JSONValue]
    stance_source: dict[str, JSONValue]
    damage_formula_family: str
    element_type: str | None
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    numeric_fidelity_status: str = "structural_only"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "hit_profile_id": self.hit_profile_id,
            "action_id": self.action_id,
            "level": self.level,
            "hit_index": self.hit_index,
            "target_group": self.target_group,
            "multiplier_expr": self.multiplier_expr,
            "multiplier_source": self.multiplier_source,
            "stance_expr": self.stance_expr,
            "stance_source": self.stance_source,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "numeric_fidelity_status": self.numeric_fidelity_status,
        }


@dataclass(frozen=True)
class SkillFormulaBindingIR:
    binding_id: str
    character_data_card_id: str
    formula_slot_id: str
    action_id: str
    level: int
    param_index: int
    sequence_order: int
    formula_role: str
    target_group_hint: str
    param_value: JSONValue
    scaling_basis_expr: dict[str, JSONValue]
    text_hash: str
    skill_text: str
    matched_text: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "character_data_card_id": self.character_data_card_id,
            "formula_slot_id": self.formula_slot_id,
            "action_id": self.action_id,
            "level": self.level,
            "param_index": self.param_index,
            "sequence_order": self.sequence_order,
            "formula_role": self.formula_role,
            "target_group_hint": self.target_group_hint,
            "param_value": self.param_value,
            "scaling_basis_expr": self.scaling_basis_expr,
            "text_hash": self.text_hash,
            "skill_text": self.skill_text,
            "matched_text": self.matched_text,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class DamageEmissionIR:
    damage_emission_id: str
    action_id: str
    level: int
    phase_id: str
    source_task_id: str
    hit_profile_id: str
    target_group: str
    damage_formula_family: str
    element_type: str | None
    scaling_ratio_expr: dict[str, JSONValue]
    scaling_basis_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_emission_id": self.damage_emission_id,
            "action_id": self.action_id,
            "level": self.level,
            "phase_id": self.phase_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "target_group": self.target_group,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_ratio_expr": self.scaling_ratio_expr,
            "scaling_basis_expr": self.scaling_basis_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ToughnessEmissionIR:
    toughness_emission_id: str
    action_id: str
    level: int
    phase_id: str
    source_task_id: str
    hit_profile_id: str
    target_group: str
    element_type: str | None
    toughness_amount_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "toughness_emission_id": self.toughness_emission_id,
            "action_id": self.action_id,
            "level": self.level,
            "phase_id": self.phase_id,
            "source_task_id": self.source_task_id,
            "hit_profile_id": self.hit_profile_id,
            "target_group": self.target_group,
            "element_type": self.element_type,
            "toughness_amount_expr": self.toughness_amount_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakBaseDamageIR:
    level: int
    break_base_damage: float
    hardness_base_damage: float | None
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "level": self.level,
            "break_base_damage": self.break_base_damage,
            "hardness_base_damage": self.hardness_base_damage,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakTemplateIR:
    template_id: str
    element_type: str | None
    task_names: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "template_id": self.template_id,
            "element_type": self.element_type,
            "task_names": list(self.task_names),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakDamageEmissionIR:
    break_damage_emission_id: str
    template_id: str
    source_task_id: str
    element_type: str | None
    damage_formula_family: str
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "break_damage_emission_id": self.break_damage_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "element_type": self.element_type,
            "damage_formula_family": self.damage_formula_family,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BreakStatusEmissionIR:
    break_status_emission_id: str
    template_id: str
    source_task_id: str
    effect_id: str
    opcode: str
    target_alias: str | None
    modifier_name: str | None
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "break_status_emission_id": self.break_status_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "target_alias": self.target_alias,
            "modifier_name": self.modifier_name,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StatusCallbackIR:
    callback_id: str
    modifier_name: str
    event: str
    task_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    scope_kind: str = "status_local"
    source_mode: str = "mainline"
    admission_status: CoverageStatus = "blocked"
    blocking_dependency: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "callback_id": self.callback_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "task_ids": list(self.task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "scope_kind": self.scope_kind,
            "source_mode": self.source_mode,
            "admission_status": self.admission_status,
            "blocking_dependency": self.blocking_dependency,
        }


@dataclass(frozen=True)
class StatusCallbackTaskIR:
    task_id: str
    callback_id: str
    modifier_name: str
    event: str
    task_index: int
    task_path: str
    branch: str
    opcode: str
    source: IRSource
    effect_id: str = ""
    condition_id: str = ""
    parent_task_id: str = ""
    child_task_ids: tuple[str, ...] = ()
    success_task_ids: tuple[str, ...] = ()
    failed_task_ids: tuple[str, ...] = ()
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "task_id": self.task_id,
            "callback_id": self.callback_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "task_index": self.task_index,
            "task_path": self.task_path,
            "branch": self.branch,
            "opcode": self.opcode,
            "effect_id": self.effect_id,
            "condition_id": self.condition_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "success_task_ids": list(self.success_task_ids),
            "failed_task_ids": list(self.failed_task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StatusDamageEmissionIR:
    status_damage_emission_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    attack_type: str
    damage_formula_family: str
    element_type: str | None
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_damage_emission_id": self.status_damage_emission_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "attack_type": self.attack_type,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionDelayEmissionIR:
    action_delay_emission_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    opcode: str
    target_alias: str | None
    delay_mode: str
    delay_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_delay_emission_id": self.action_delay_emission_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "opcode": self.opcode,
            "target_alias": self.target_alias,
            "delay_mode": self.delay_mode,
            "delay_expr": self.delay_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueIntentIR:
    queue_intent_id: str
    source_task_id: str
    callback_id: str
    phase_id: str
    opcode: str
    queue_kind: str
    priority_source: dict[str, JSONValue]
    actor_target_alias: str | None
    action_ref_or_ability_name: str
    skill_index_expr: dict[str, JSONValue]
    ability_target_alias: str | None
    auto_cast: bool
    abort_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_intent_id": self.queue_intent_id,
            "source_task_id": self.source_task_id,
            "callback_id": self.callback_id,
            "phase_id": self.phase_id,
            "opcode": self.opcode,
            "queue_kind": self.queue_kind,
            "priority_source": self.priority_source,
            "actor_target_alias": self.actor_target_alias,
            "action_ref_or_ability_name": self.action_ref_or_ability_name,
            "skill_index_expr": self.skill_index_expr,
            "ability_target_alias": self.ability_target_alias,
            "auto_cast": self.auto_cast,
            "abort_policy": self.abort_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SuperBreakEmissionIR:
    super_break_emission_id: str
    template_id: str
    source_task_id: str
    target_alias: str | None
    attack_type: str
    damage_formula_family: str
    element_type: str | None
    scaling_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "super_break_emission_id": self.super_break_emission_id,
            "template_id": self.template_id,
            "source_task_id": self.source_task_id,
            "target_alias": self.target_alias,
            "attack_type": self.attack_type,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "scaling_expr": self.scaling_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueResolutionIR:
    queue_resolution_id: str
    queue_intent_id: str
    action_or_ability_ref: str
    resolved_kind: str
    resolved_ids: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_resolution_id": self.queue_resolution_id,
            "queue_intent_id": self.queue_intent_id,
            "action_or_ability_ref": self.action_or_ability_ref,
            "resolved_kind": self.resolved_kind,
            "resolved_ids": self.resolved_ids,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueuePriorityIR:
    queue_priority_id: str
    priority_table: str
    priority_key: str
    priority_value: float
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_priority_id": self.queue_priority_id,
            "priority_table": self.priority_table,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueWindowIR:
    queue_window_id: str
    queue_intent_id: str
    queue_kind: str
    window_family: str
    priority_key: str
    priority_value: float | None
    window_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_window_id": self.queue_window_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_kind": self.queue_kind,
            "window_family": self.window_family,
            "priority_key": self.priority_key,
            "priority_value": self.priority_value,
            "window_policy": self.window_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class QueueLifecyclePolicyIR:
    queue_lifecycle_policy_id: str
    queue_window_id: str
    queue_intent_id: str
    window_family: str
    lifecycle_policy: dict[str, JSONValue]
    source_basis: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "queue_lifecycle_policy_id": self.queue_lifecycle_policy_id,
            "queue_window_id": self.queue_window_id,
            "queue_intent_id": self.queue_intent_id,
            "window_family": self.window_family,
            "lifecycle_policy": self.lifecycle_policy,
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ExtraActionPolicyIR:
    extra_action_policy_id: str
    queue_intent_id: str
    queue_window_id: str
    source_kind: str
    action_selection_kind: str
    allowed_action_kinds: tuple[str, ...]
    fixed_action_ref: str
    lifecycle_policy_id: str
    source_basis: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "extra_action_policy_id": self.extra_action_policy_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_window_id": self.queue_window_id,
            "source_kind": self.source_kind,
            "action_selection_kind": self.action_selection_kind,
            "allowed_action_kinds": list(self.allowed_action_kinds),
            "fixed_action_ref": self.fixed_action_ref,
            "lifecycle_policy_id": self.lifecycle_policy_id,
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class StandaloneAbilityGraphIR:
    standalone_ability_graph_id: str
    ability_name: str
    source_mode: str
    phase_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    executable_task_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "standalone_ability_graph_id": self.standalone_ability_graph_id,
            "ability_name": self.ability_name,
            "source_mode": self.source_mode,
            "phase_ids": list(self.phase_ids),
            "task_ids": list(self.task_ids),
            "executable_task_ids": list(self.executable_task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CombatantActionSetIR:
    combatant_action_set_id: str
    entity_ref: str
    skill_index_map: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "combatant_action_set_id": self.combatant_action_set_id,
            "entity_ref": self.entity_ref,
            "skill_index_map": self.skill_index_map,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AbilityPhaseIR:
    phase_id: str
    binding_id: str
    action_id: str
    level: int
    ability_name: str
    phase_index: int
    target_info: dict[str, JSONValue]
    opcode_summary: dict[str, JSONValue]
    callback_summaries: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    task_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "phase_id": self.phase_id,
            "binding_id": self.binding_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "phase_index": self.phase_index,
            "target_info": self.target_info,
            "opcode_summary": self.opcode_summary,
            "callback_summaries": self.callback_summaries,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "task_ids": list(self.task_ids),
        }


@dataclass(frozen=True)
class AbilityTaskIR:
    task_id: str
    phase_id: str
    action_id: str
    level: int
    ability_name: str
    callback_kind: str
    task_index: int
    task_path: str
    branch: str
    opcode: str
    source: IRSource
    effect_id: str = ""
    condition_id: str = ""
    parent_task_id: str = ""
    child_task_ids: tuple[str, ...] = ()
    success_task_ids: tuple[str, ...] = ()
    failed_task_ids: tuple[str, ...] = ()
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "callback_kind": self.callback_kind,
            "task_index": self.task_index,
            "task_path": self.task_path,
            "branch": self.branch,
            "opcode": self.opcode,
            "effect_id": self.effect_id,
            "condition_id": self.condition_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "success_task_ids": list(self.success_task_ids),
            "failed_task_ids": list(self.failed_task_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionAbilityBindingIR:
    binding_id: str
    action_id: str
    level: int
    skill_trigger_key: str
    skill_name: str
    entry_ability: str
    ability_names: tuple[str, ...]
    config_source: dict[str, JSONValue]
    phase_ids: tuple[str, ...]
    source_mode: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "action_id": self.action_id,
            "level": self.level,
            "skill_trigger_key": self.skill_trigger_key,
            "skill_name": self.skill_name,
            "entry_ability": self.entry_ability,
            "ability_names": list(self.ability_names),
            "config_source": self.config_source,
            "phase_ids": list(self.phase_ids),
            "source_mode": self.source_mode,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ActionEventIR:
    action_event_id: str
    action_id: str
    level: int
    target_mode: str
    selection_mode: str
    phase_steps: tuple[ActionPhaseStepIR, ...]
    hit_profile_ids: tuple[str, ...]
    derived_status: str
    derived_reason: str
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    blocked_reason: str = ""
    binding_id: str = ""
    phase_ids: tuple[str, ...] = ()
    source_mode: str = "derived"
    event_source_status: str = "derived_from_action_definition"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "action_event_id": self.action_event_id,
            "action_id": self.action_id,
            "level": self.level,
            "target_mode": self.target_mode,
            "selection_mode": self.selection_mode,
            "phase_steps": [step.to_json() for step in self.phase_steps],
            "hit_profile_ids": list(self.hit_profile_ids),
            "derived_status": self.derived_status,
            "derived_reason": self.derived_reason,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "binding_id": self.binding_id,
            "phase_ids": list(self.phase_ids),
            "source_mode": self.source_mode,
            "event_source_status": self.event_source_status,
        }


@dataclass(frozen=True)
class ActionDefinitionIR:
    definition_id: str
    action_id: str
    level: int
    attack_type: str
    skill_effect: str
    target_mode: str
    bp_need: float
    bp_add: float
    sp_base: float
    sp_multiple_ratio: float
    param_list: tuple[JSONValue, ...]
    show_stance_list: tuple[JSONValue, ...]
    show_damage_list: tuple[JSONValue, ...]
    stance_damage_type: str | None
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    damage_kind: str = "unknown"
    damage_formula_family: str = "unknown"
    element_type: str | None = None
    source_mode: str = "mainline"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "action_id": self.action_id,
            "level": self.level,
            "attack_type": self.attack_type,
            "skill_effect": self.skill_effect,
            "target_mode": self.target_mode,
            "bp_need": self.bp_need,
            "bp_add": self.bp_add,
            "sp_base": self.sp_base,
            "sp_multiple_ratio": self.sp_multiple_ratio,
            "param_list": list(self.param_list),
            "show_stance_list": list(self.show_stance_list),
            "show_damage_list": list(self.show_damage_list),
            "stance_damage_type": self.stance_damage_type,
            "damage_kind": self.damage_kind,
            "damage_formula_family": self.damage_formula_family,
            "element_type": self.element_type,
            "source_mode": self.source_mode,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }


@dataclass(frozen=True)
class SkillContinuationIR:
    continuation_id: str
    source_task_id: str
    phase_id: str
    action_id: str
    level: int
    ability_name: str
    opcode: str
    continuation_kind: str
    fixed_skill_type: str
    child_skill_index_expr: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "continuation_id": self.continuation_id,
            "source_task_id": self.source_task_id,
            "phase_id": self.phase_id,
            "action_id": self.action_id,
            "level": self.level,
            "ability_name": self.ability_name,
            "opcode": self.opcode,
            "continuation_kind": self.continuation_kind,
            "fixed_skill_type": self.fixed_skill_type,
            "child_skill_index_expr": self.child_skill_index_expr,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TimelineRuleIR:
    timeline_rule_id: str
    base_action_gauge: float
    initial_action_value_rule: str
    turn_reset_rule: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "timeline_rule_id": self.timeline_rule_id,
            "base_action_gauge": self.base_action_gauge,
            "initial_action_value_rule": self.initial_action_value_rule,
            "turn_reset_rule": self.turn_reset_rule,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ResourceRuleIR:
    resource_rule_id: str
    rule_kind: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resource_rule_id": self.resource_rule_id,
            "rule_kind": self.rule_kind,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CanonicalIR:
    version: str
    entities: tuple[RuleEntity, ...] = ()
    avatar_profiles: tuple[AvatarProfileIR, ...] = ()
    character_data_cards: tuple[CharacterDataCardIR, ...] = ()
    combatant_profiles: tuple[CombatantProfileIR, ...] = ()
    action_definitions: tuple[ActionDefinitionIR, ...] = ()
    action_ability_bindings: tuple[ActionAbilityBindingIR, ...] = ()
    ability_phases: tuple[AbilityPhaseIR, ...] = ()
    ability_tasks: tuple[AbilityTaskIR, ...] = ()
    action_events: tuple[ActionEventIR, ...] = ()
    hit_profiles: tuple[HitProfileIR, ...] = ()
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = ()
    damage_emissions: tuple[DamageEmissionIR, ...] = ()
    toughness_emissions: tuple[ToughnessEmissionIR, ...] = ()
    break_templates: tuple[BreakTemplateIR, ...] = ()
    break_base_damage: tuple[BreakBaseDamageIR, ...] = ()
    break_damage_emissions: tuple[BreakDamageEmissionIR, ...] = ()
    break_status_emissions: tuple[BreakStatusEmissionIR, ...] = ()
    status_callbacks: tuple[StatusCallbackIR, ...] = ()
    status_callback_tasks: tuple[StatusCallbackTaskIR, ...] = ()
    status_damage_emissions: tuple[StatusDamageEmissionIR, ...] = ()
    action_delay_emissions: tuple[ActionDelayEmissionIR, ...] = ()
    queue_intents: tuple[QueueIntentIR, ...] = ()
    queue_resolutions: tuple[QueueResolutionIR, ...] = ()
    queue_priorities: tuple[QueuePriorityIR, ...] = ()
    queue_windows: tuple[QueueWindowIR, ...] = ()
    queue_lifecycle_policies: tuple[QueueLifecyclePolicyIR, ...] = ()
    extra_action_policies: tuple[ExtraActionPolicyIR, ...] = ()
    skill_continuations: tuple[SkillContinuationIR, ...] = ()
    standalone_ability_graphs: tuple[StandaloneAbilityGraphIR, ...] = ()
    combatant_action_sets: tuple[CombatantActionSetIR, ...] = ()
    timeline_rules: tuple[TimelineRuleIR, ...] = ()
    resource_rules: tuple[ResourceRuleIR, ...] = ()
    super_break_emissions: tuple[SuperBreakEmissionIR, ...] = ()
    triggers: tuple[TriggerIR, ...] = ()
    effects: tuple[EffectIR, ...] = ()
    conditions: tuple[ConditionIR, ...] = ()
    formulas: tuple[FormulaIR, ...] = ()
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "version": self.version,
            "metadata": self.metadata,
            "entities": [entity.to_json() for entity in self.entities],
            "avatar_profiles": [profile.to_json() for profile in self.avatar_profiles],
            "character_data_cards": [card.to_json() for card in self.character_data_cards],
            "combatant_profiles": [profile.to_json() for profile in self.combatant_profiles],
            "action_definitions": [definition.to_json() for definition in self.action_definitions],
            "action_ability_bindings": [binding.to_json() for binding in self.action_ability_bindings],
            "ability_phases": [phase.to_json() for phase in self.ability_phases],
            "ability_tasks": [task.to_json() for task in self.ability_tasks],
            "action_events": [event.to_json() for event in self.action_events],
            "hit_profiles": [profile.to_json() for profile in self.hit_profiles],
            "skill_formula_bindings": [binding.to_json() for binding in self.skill_formula_bindings],
            "damage_emissions": [emission.to_json() for emission in self.damage_emissions],
            "toughness_emissions": [emission.to_json() for emission in self.toughness_emissions],
            "break_templates": [template.to_json() for template in self.break_templates],
            "break_base_damage": [item.to_json() for item in self.break_base_damage],
            "break_damage_emissions": [emission.to_json() for emission in self.break_damage_emissions],
            "break_status_emissions": [emission.to_json() for emission in self.break_status_emissions],
            "status_callbacks": [callback.to_json() for callback in self.status_callbacks],
            "status_callback_tasks": [task.to_json() for task in self.status_callback_tasks],
            "status_damage_emissions": [emission.to_json() for emission in self.status_damage_emissions],
            "action_delay_emissions": [emission.to_json() for emission in self.action_delay_emissions],
            "queue_intents": [intent.to_json() for intent in self.queue_intents],
            "queue_resolutions": [resolution.to_json() for resolution in self.queue_resolutions],
            "queue_priorities": [priority.to_json() for priority in self.queue_priorities],
            "queue_windows": [window.to_json() for window in self.queue_windows],
            "queue_lifecycle_policies": [policy.to_json() for policy in self.queue_lifecycle_policies],
            "extra_action_policies": [policy.to_json() for policy in self.extra_action_policies],
            "skill_continuations": [continuation.to_json() for continuation in self.skill_continuations],
            "standalone_ability_graphs": [graph.to_json() for graph in self.standalone_ability_graphs],
            "combatant_action_sets": [action_set.to_json() for action_set in self.combatant_action_sets],
            "timeline_rules": [rule.to_json() for rule in self.timeline_rules],
            "resource_rules": [rule.to_json() for rule in self.resource_rules],
            "super_break_emissions": [emission.to_json() for emission in self.super_break_emissions],
            "triggers": [trigger.to_json() for trigger in self.triggers],
            "effects": [effect.to_json() for effect in self.effects],
            "conditions": [condition.to_json() for condition in self.conditions],
            "formulas": [formula.to_json() for formula in self.formulas],
        }
