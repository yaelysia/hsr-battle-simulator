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


def _ir_json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _ir_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ir_json_value(item) for item in value]
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return _ir_json_value(to_json())
    raise TypeError(f"unsupported IR JSON value: {type(value).__name__}")


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
    expression_schema_version: str = ""
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "condition_id": self.condition_id,
            "opcode": self.opcode,
            "payload": _ir_json_value(self.payload),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "expression_schema_version": self.expression_schema_version,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TargetExpressionNodeIR:
    expression_kind: str
    alias: str = ""
    children: tuple["TargetExpressionNodeIR", ...] = ()
    candidate: "TargetExpressionNodeIR | None" = None
    predicate: ConditionIR | None = None
    target: "TargetExpressionNodeIR | None" = None
    query_entity_type_mask: str = ""
    query_alive_state_mask: str = ""
    query_target: "TargetExpressionNodeIR | None" = None
    query_compare: "TargetExpressionNodeIR | None" = None
    fetch_kind: str = ""
    unique_name: str = ""
    name: str = ""
    adjacent_side: str = ""
    by_random: bool = False
    max_number_expr: dict[str, JSONValue] = field(default_factory=dict)
    count_expr: dict[str, JSONValue] = field(default_factory=dict)
    index_type: str = ""
    index_expr: dict[str, JSONValue] = field(default_factory=dict)
    sort_kind: str = ""
    sort_key: str = ""
    highest_first: bool = False
    schema_version: str = "hsr.target_expression_node.v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "children": [child.to_json() for child in self.children],
            "candidate": self.candidate.to_json() if self.candidate is not None else None,
            "predicate": self.predicate.to_json() if self.predicate is not None else None,
            "target": self.target.to_json() if self.target is not None else None,
            "query_entity_type_mask": self.query_entity_type_mask,
            "query_alive_state_mask": self.query_alive_state_mask,
            "query_target": self.query_target.to_json() if self.query_target is not None else None,
            "query_compare": self.query_compare.to_json() if self.query_compare is not None else None,
            "fetch_kind": self.fetch_kind,
            "unique_name": self.unique_name,
            "name": self.name,
            "adjacent_side": self.adjacent_side,
            "by_random": self.by_random,
            "max_number_expr": self.max_number_expr,
            "count_expr": self.count_expr,
            "index_type": self.index_type,
            "index_expr": self.index_expr,
            "sort_kind": self.sort_kind,
            "sort_key": self.sort_key,
            "highest_first": self.highest_first,
        }


@dataclass(frozen=True)
class TargetExpressionIR:
    target_expression_id: str
    expression_kind: str
    alias: str
    payload: dict[str, JSONValue]
    source: IRSource
    node: TargetExpressionNodeIR | None = None
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    admission_batch: str = ""
    runtime_scope: str = "effect_target"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "target_expression_id": self.target_expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "payload": self.payload,
            "node": self.node.to_json() if self.node is not None else None,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "admission_batch": self.admission_batch,
            "runtime_scope": self.runtime_scope,
        }


@dataclass(frozen=True)
class EffectIR:
    effect_id: str
    opcode: str
    payload: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "unsupported"
    modifier_definition_id: str = ""
    status_callback_ids: tuple[str, ...] = ()
    source_mode: str = "unclassified"
    link_blocked_reason: str = ""
    owner_modifier_name: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "effect_id": self.effect_id,
            "opcode": self.opcode,
            "payload": self.payload,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "modifier_definition_id": self.modifier_definition_id,
            "status_callback_ids": list(self.status_callback_ids),
            "source_mode": self.source_mode,
            "link_blocked_reason": self.link_blocked_reason,
            "owner_modifier_name": self.owner_modifier_name,
        }


@dataclass(frozen=True)
class DamageModifierIR:
    damage_modifier_id: str
    callback_id: str
    source_task_id: str
    modifier_name: str
    event: str
    target_alias: str
    modifier_terms: tuple[dict[str, JSONValue], ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_modifier_id": self.damage_modifier_id,
            "callback_id": self.callback_id,
            "source_task_id": self.source_task_id,
            "modifier_name": self.modifier_name,
            "event": self.event,
            "target_alias": self.target_alias,
            "modifier_terms": list(self.modifier_terms),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class TriggerIR:
    trigger_id: str
    event: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "audit_only"
    modifier_name: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trigger_id": self.trigger_id,
            "event": self.event,
            "conditions": list(self.conditions),
            "effects": list(self.effects),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "modifier_name": self.modifier_name,
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
    status_resistance: JSONValue = None
    debuff_resistances: tuple[JSONValue, ...] = ()
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
            "status_resistance": self.status_resistance,
            "debuff_resistances": list(self.debuff_resistances),
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
    bounce_policy_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "v0_265"
    action_set: dict[str, JSONValue] = field(default_factory=dict)
    mechanism_slot_ids: tuple[str, ...] = ()
    trace_node_ids: tuple[str, ...] = ()
    eidolon_slot_ids: tuple[str, ...] = ()
    card_contract: dict[str, JSONValue] = field(default_factory=dict)
    dynamic_value_bindings: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "card_id": self.card_id,
            "schema_version": self.schema_version,
            "entity_ref": self.entity_ref,
            "profile_id": self.profile_id,
            "skill_ids": list(self.skill_ids),
            "action_set": self.action_set,
            "skill_formula_binding_ids": list(self.skill_formula_binding_ids),
            "bounce_policy_ids": list(self.bounce_policy_ids),
            "mechanism_slot_ids": list(self.mechanism_slot_ids),
            "trace_node_ids": list(self.trace_node_ids),
            "eidolon_slot_ids": list(self.eidolon_slot_ids),
            "card_contract": self.card_contract,
            "dynamic_value_bindings": self.dynamic_value_bindings,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class MonsterDataCardIR:
    card_id: str
    entity_ref: str
    monster_id: str
    template_id: str
    rank: str
    profile_id: str
    action_set_id: str
    skill_ids: tuple[str, ...]
    skill_slots: tuple[dict[str, JSONValue], ...]
    ai_policy: dict[str, JSONValue]
    action_sequence: tuple[dict[str, JSONValue], ...]
    summon_refs: tuple[str, ...]
    raw_parameter_blocks: dict[str, JSONValue]
    card_contract: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "v0_277"
    display: dict[str, JSONValue] = field(default_factory=dict)
    passive_mechanism_slot_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "card_id": self.card_id,
            "schema_version": self.schema_version,
            "entity_ref": self.entity_ref,
            "monster_id": self.monster_id,
            "template_id": self.template_id,
            "rank": self.rank,
            "display": self.display,
            "profile_id": self.profile_id,
            "action_set_id": self.action_set_id,
            "skill_ids": list(self.skill_ids),
            "skill_slots": [dict(slot) for slot in self.skill_slots],
            "ai_policy": self.ai_policy,
            "action_sequence": [dict(step) for step in self.action_sequence],
            "passive_mechanism_slot_ids": list(self.passive_mechanism_slot_ids),
            "summon_refs": list(self.summon_refs),
            "raw_parameter_blocks": self.raw_parameter_blocks,
            "card_contract": self.card_contract,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonUnitDefinitionIR:
    summon_definition_id: str
    summon_unit_id: str
    summon_kind: str
    config_path: str
    unique_group: str
    max_summon_count: int | None
    destroy_on_enter_battle: bool | None
    remove_maze_buff_on_destroy: bool | None
    battle_admission: dict[str, JSONValue]
    skill_config: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_summon_unit_definition_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "summon_definition_id": self.summon_definition_id,
            "schema_version": self.schema_version,
            "summon_unit_id": self.summon_unit_id,
            "summon_kind": self.summon_kind,
            "config_path": self.config_path,
            "unique_group": self.unique_group,
            "max_summon_count": self.max_summon_count,
            "destroy_on_enter_battle": self.destroy_on_enter_battle,
            "remove_maze_buff_on_destroy": self.remove_maze_buff_on_destroy,
            "battle_admission": self.battle_admission,
            "skill_config": self.skill_config,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class UnitBirthTemplateIR:
    birth_template_id: str
    spawn_kind: Literal["summoned_monster", "servant", "wave_enemy"]
    entity_ref: str
    unit_field_specs: dict[str, JSONValue]
    flag_specs: dict[str, JSONValue]
    resource_specs: dict[str, JSONValue]
    request_contract: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p6_unit_birth_template_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "birth_template_id": self.birth_template_id,
            "schema_version": self.schema_version,
            "spawn_kind": self.spawn_kind,
            "entity_ref": self.entity_ref,
            "unit_field_specs": self.unit_field_specs,
            "flag_specs": self.flag_specs,
            "resource_specs": self.resource_specs,
            "request_contract": self.request_contract,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonMonsterEntryIR:
    entry_id: str
    monster_entity_ref: str
    monster_raw_id: str
    position_policy: dict[str, JSONValue]
    count: int
    level_policy: dict[str, JSONValue]
    wave_clear_policy: Literal["counts", "ignore", "blocked"]
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entry_id": self.entry_id,
            "monster_entity_ref": self.monster_entity_ref,
            "monster_raw_id": self.monster_raw_id,
            "position_policy": self.position_policy,
            "count": self.count,
            "level_policy": self.level_policy,
            "wave_clear_policy": self.wave_clear_policy,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class SummonMonsterIntentIR:
    summon_intent_id: str
    source_task_id: str
    owner_scope: str
    target_scope: str
    delay_policy: dict[str, JSONValue]
    entries: tuple[SummonMonsterEntryIR, ...]
    source_event: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_summon_monster_intent_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "summon_intent_id": self.summon_intent_id,
            "schema_version": self.schema_version,
            "source_task_id": self.source_task_id,
            "owner_scope": self.owner_scope,
            "target_scope": self.target_scope,
            "delay_policy": self.delay_policy,
            "entries": [entry.to_json() for entry in self.entries],
            "source_event": self.source_event,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class AssistantAbilityResolutionIR:
    assistant_resolution_id: str
    queue_intent_id: str
    assistant_ability_id: str
    owner_alias: str
    target_alias: str
    resolved_graph_id: str
    attribution_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_assistant_ability_resolution_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "assistant_resolution_id": self.assistant_resolution_id,
            "schema_version": self.schema_version,
            "queue_intent_id": self.queue_intent_id,
            "assistant_ability_id": self.assistant_ability_id,
            "owner_alias": self.owner_alias,
            "target_alias": self.target_alias,
            "resolved_graph_id": self.resolved_graph_id,
            "attribution_policy": self.attribution_policy,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ServantDefinitionIR:
    servant_definition_id: str
    servant_ref: str
    owner_entity_ref: str
    representation: Literal["unit", "component", "blocked"]
    ability_graph_ids: tuple[str, ...]
    action_set: dict[str, JSONValue]
    stat_source: dict[str, JSONValue]
    timeline_source: dict[str, JSONValue]
    lifecycle_source: dict[str, JSONValue]
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    schema_version: str = "p1_3_servant_definition_v1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "servant_definition_id": self.servant_definition_id,
            "schema_version": self.schema_version,
            "servant_ref": self.servant_ref,
            "owner_entity_ref": self.owner_entity_ref,
            "representation": self.representation,
            "ability_graph_ids": list(self.ability_graph_ids),
            "action_set": self.action_set,
            "stat_source": self.stat_source,
            "timeline_source": self.timeline_source,
            "lifecycle_source": self.lifecycle_source,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterMechanismSlotIR:
    mechanism_slot_id: str
    character_data_card_id: str
    mechanism_kind: str
    runtime_system: str
    linked_ir_ids: dict[str, JSONValue]
    activation: dict[str, JSONValue]
    semantics: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "mechanism_slot_id": self.mechanism_slot_id,
            "character_data_card_id": self.character_data_card_id,
            "mechanism_kind": self.mechanism_kind,
            "runtime_system": self.runtime_system,
            "linked_ir_ids": self.linked_ir_ids,
            "activation": self.activation,
            "semantics": self.semantics,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class PassiveMechanismSlotIR:
    passive_slot_id: str
    data_card_id: str
    data_card_kind: str
    owner_entity_ref: str
    mechanism_kind: str
    runtime_system: str
    linked_ir_ids: dict[str, JSONValue]
    activation: dict[str, JSONValue]
    semantics: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "passive_slot_id": self.passive_slot_id,
            "data_card_id": self.data_card_id,
            "data_card_kind": self.data_card_kind,
            "owner_entity_ref": self.owner_entity_ref,
            "mechanism_kind": self.mechanism_kind,
            "runtime_system": self.runtime_system,
            "linked_ir_ids": self.linked_ir_ids,
            "activation": self.activation,
            "semantics": self.semantics,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterTraceNodeIR:
    trace_node_id: str
    character_data_card_id: str
    avatar_id: str
    trace_id: str
    trace_kind: str
    linked_mechanism_slot_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "trace_node_id": self.trace_node_id,
            "character_data_card_id": self.character_data_card_id,
            "avatar_id": self.avatar_id,
            "trace_id": self.trace_id,
            "trace_kind": self.trace_kind,
            "linked_mechanism_slot_ids": list(self.linked_mechanism_slot_ids),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterEidolonSlotIR:
    eidolon_slot_id: str
    character_data_card_id: str
    avatar_id: str
    rank: int
    rank_id: str
    linked_mechanism_slot_ids: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = "eidolon_interface_reserved_v0_265"
    activation: dict[str, JSONValue] = field(default_factory=dict)
    semantics: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "eidolon_slot_id": self.eidolon_slot_id,
            "character_data_card_id": self.character_data_card_id,
            "avatar_id": self.avatar_id,
            "rank": self.rank,
            "rank_id": self.rank_id,
            "linked_mechanism_slot_ids": list(self.linked_mechanism_slot_ids),
            "activation": self.activation,
            "semantics": self.semantics,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class BouncePolicyIR:
    bounce_policy_id: str
    character_data_card_id: str
    action_id: str
    level: int
    bounce_count: int
    initial_target_group: str
    bounce_target_group: str
    candidate_scope: str
    selection_strategy: str
    live_target_priority: bool
    continue_on_all_defeated: bool
    allow_repeat_after_all_hit: bool
    rng_source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "bounce_policy_id": self.bounce_policy_id,
            "character_data_card_id": self.character_data_card_id,
            "action_id": self.action_id,
            "level": self.level,
            "bounce_count": self.bounce_count,
            "initial_target_group": self.initial_target_group,
            "bounce_target_group": self.bounce_target_group,
            "candidate_scope": self.candidate_scope,
            "selection_strategy": self.selection_strategy,
            "live_target_priority": self.live_target_priority,
            "continue_on_all_defeated": self.continue_on_all_defeated,
            "allow_repeat_after_all_hit": self.allow_repeat_after_all_hit,
            "rng_source_kind": self.rng_source_kind,
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
    bounce_policy_id: str = ""
    target_selection_policy: dict[str, JSONValue] = field(default_factory=dict)

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
            "bounce_policy_id": self.bounce_policy_id,
            "target_selection_policy": self.target_selection_policy,
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
    bounce_policy_id: str = ""
    data_card_id: str = ""
    data_card_kind: str = ""
    owner_entity_ref: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "binding_id": self.binding_id,
            "character_data_card_id": self.character_data_card_id,
            "data_card_id": self.data_card_id or self.character_data_card_id,
            "data_card_kind": self.data_card_kind or ("character" if self.character_data_card_id else ""),
            "owner_entity_ref": self.owner_entity_ref,
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
            "bounce_policy_id": self.bounce_policy_id,
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
    damage_custom_name: str = ""

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
            "damage_custom_name": self.damage_custom_name,
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
    execution_order: tuple[int, int]
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
            "execution_order": list(self.execution_order),
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
    task_payload: dict[str, JSONValue] = field(default_factory=dict)
    retarget_policy: dict[str, JSONValue] = field(default_factory=dict)

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
            "task_payload": self.task_payload,
            "retarget_policy": self.retarget_policy,
        }


@dataclass(frozen=True)
class StatusEventFamilyIR:
    status_event_family_id: str
    callback_event: str
    event_family: str
    default_scope_kind: str
    runtime_event_sources: tuple[str, ...]
    source_basis: str
    source: IRSource
    callback_count: int = 0
    executable_callback_count: int = 0
    blocked_callback_count: int = 0
    task_count: int = 0
    task_opcode_counts: dict[str, JSONValue] = field(default_factory=dict)
    source_mode_counts: dict[str, JSONValue] = field(default_factory=dict)
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
    admission_status: CoverageStatus = "blocked"
    blocking_dependency: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status_event_family_id": self.status_event_family_id,
            "callback_event": self.callback_event,
            "event_family": self.event_family,
            "default_scope_kind": self.default_scope_kind,
            "runtime_event_sources": list(self.runtime_event_sources),
            "source_basis": self.source_basis,
            "source": self.source.to_json(),
            "callback_count": self.callback_count,
            "executable_callback_count": self.executable_callback_count,
            "blocked_callback_count": self.blocked_callback_count,
            "task_count": self.task_count,
            "task_opcode_counts": dict(sorted(self.task_opcode_counts.items())),
            "source_mode_counts": dict(sorted(self.source_mode_counts.items())),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "admission_status": self.admission_status,
            "blocking_dependency": self.blocking_dependency,
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
class ActionAdmissionIR:
    admission_id: str
    owner_entity_ref: str
    action_id: str
    action_level: int
    action_role: str
    submission_modes: tuple[str, ...]
    allowed_windows: tuple[str, ...]
    control_kind: str
    resource_gate_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "admission_id": self.admission_id,
            "owner_entity_ref": self.owner_entity_ref,
            "action_id": self.action_id,
            "action_level": self.action_level,
            "action_role": self.action_role,
            "submission_modes": list(self.submission_modes),
            "allowed_windows": list(self.allowed_windows),
            "control_kind": self.control_kind,
            "resource_gate_kind": self.resource_gate_kind,
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
    linked_standalone_graph_id: str = ""

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
            "linked_standalone_graph_id": self.linked_standalone_graph_id,
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
    target_relation: str = "unknown"

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
            "target_relation": self.target_relation,
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
    skill_trigger_key: str = ""
    target_relation: str = "unknown"

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
            "skill_trigger_key": self.skill_trigger_key,
            "target_relation": self.target_relation,
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
    registry_version: str = ""
    applicability: str = ""

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
            "registry_version": self.registry_version,
            "applicability": self.applicability,
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
    registry_version: str = ""
    applicability: str = ""
    numeric_value: float | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "resource_rule_id": self.resource_rule_id,
            "rule_kind": self.rule_kind,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
            "numeric_value": self.numeric_value,
        }


@dataclass(frozen=True)
class DamageFormulaRuleIR:
    damage_formula_rule_id: str
    rule_kind: str
    operation: str
    numeric_parameters: dict[str, float]
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_formula_rule_id": self.damage_formula_rule_id,
            "rule_kind": self.rule_kind,
            "operation": self.operation,
            "numeric_parameters": self.numeric_parameters,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class DamageRouteRuleIR:
    damage_route_rule_id: str
    damage_family: str
    route_policy: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "damage_route_rule_id": self.damage_route_rule_id,
            "damage_family": self.damage_family,
            "route_policy": self.route_policy,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class ShieldPriorityRuleIR:
    shield_priority_rule_id: str
    operation: str
    source_kind: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
    registry_version: str = ""
    applicability: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "shield_priority_rule_id": self.shield_priority_rule_id,
            "operation": self.operation,
            "source_kind": self.source_kind,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
            "registry_version": self.registry_version,
            "applicability": self.applicability,
        }


@dataclass(frozen=True)
class WaveMonsterEntryIR:
    entry_id: str
    stage_id: str
    wave_index: int
    position: int
    monster_entity_ref: str
    monster_raw_id: str
    source: IRSource
    birth_template_id: str = ""
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "entry_id": self.entry_id,
            "stage_id": self.stage_id,
            "wave_index": self.wave_index,
            "position": self.position,
            "monster_entity_ref": self.monster_entity_ref,
            "monster_raw_id": self.monster_raw_id,
            "birth_template_id": self.birth_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class WaveDefinitionIR:
    wave_definition_id: str
    stage_id: str
    wave_count: int
    entries: tuple[WaveMonsterEntryIR, ...]
    stage_ability_refs: tuple[str, ...]
    source: IRSource
    level: int | None = None
    hard_level_group: int | None = None
    level_policy: dict[str, JSONValue] = field(default_factory=dict)
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "wave_definition_id": self.wave_definition_id,
            "stage_id": self.stage_id,
            "wave_count": self.wave_count,
            "entries": [entry.to_json() for entry in self.entries],
            "stage_ability_refs": list(self.stage_ability_refs),
            "level": self.level,
            "hard_level_group": self.hard_level_group,
            "level_policy": self.level_policy,
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
    monster_data_cards: tuple[MonsterDataCardIR, ...] = ()
    summon_unit_definitions: tuple[SummonUnitDefinitionIR, ...] = ()
    unit_birth_templates: tuple[UnitBirthTemplateIR, ...] = ()
    summon_monster_intents: tuple[SummonMonsterIntentIR, ...] = ()
    assistant_ability_resolutions: tuple[AssistantAbilityResolutionIR, ...] = ()
    servant_definitions: tuple[ServantDefinitionIR, ...] = ()
    character_mechanism_slots: tuple[CharacterMechanismSlotIR, ...] = ()
    passive_mechanism_slots: tuple[PassiveMechanismSlotIR, ...] = ()
    character_trace_nodes: tuple[CharacterTraceNodeIR, ...] = ()
    character_eidolon_slots: tuple[CharacterEidolonSlotIR, ...] = ()
    bounce_policies: tuple[BouncePolicyIR, ...] = ()
    combatant_profiles: tuple[CombatantProfileIR, ...] = ()
    action_definitions: tuple[ActionDefinitionIR, ...] = ()
    action_ability_bindings: tuple[ActionAbilityBindingIR, ...] = ()
    ability_phases: tuple[AbilityPhaseIR, ...] = ()
    ability_tasks: tuple[AbilityTaskIR, ...] = ()
    action_events: tuple[ActionEventIR, ...] = ()
    hit_profiles: tuple[HitProfileIR, ...] = ()
    skill_formula_bindings: tuple[SkillFormulaBindingIR, ...] = ()
    damage_emissions: tuple[DamageEmissionIR, ...] = ()
    damage_modifiers: tuple[DamageModifierIR, ...] = ()
    toughness_emissions: tuple[ToughnessEmissionIR, ...] = ()
    break_templates: tuple[BreakTemplateIR, ...] = ()
    break_base_damage: tuple[BreakBaseDamageIR, ...] = ()
    break_damage_emissions: tuple[BreakDamageEmissionIR, ...] = ()
    break_status_emissions: tuple[BreakStatusEmissionIR, ...] = ()
    status_event_families: tuple[StatusEventFamilyIR, ...] = ()
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
    action_admissions: tuple[ActionAdmissionIR, ...] = ()
    timeline_rules: tuple[TimelineRuleIR, ...] = ()
    resource_rules: tuple[ResourceRuleIR, ...] = ()
    damage_formula_rules: tuple[DamageFormulaRuleIR, ...] = ()
    damage_route_rules: tuple[DamageRouteRuleIR, ...] = ()
    shield_priority_rules: tuple[ShieldPriorityRuleIR, ...] = ()
    super_break_emissions: tuple[SuperBreakEmissionIR, ...] = ()
    target_expressions: tuple[TargetExpressionIR, ...] = ()
    wave_definitions: tuple[WaveDefinitionIR, ...] = ()
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
            "monster_data_cards": [card.to_json() for card in self.monster_data_cards],
            "summon_unit_definitions": [definition.to_json() for definition in self.summon_unit_definitions],
            "unit_birth_templates": [template.to_json() for template in self.unit_birth_templates],
            "summon_monster_intents": [intent.to_json() for intent in self.summon_monster_intents],
            "assistant_ability_resolutions": [resolution.to_json() for resolution in self.assistant_ability_resolutions],
            "servant_definitions": [definition.to_json() for definition in self.servant_definitions],
            "character_mechanism_slots": [slot.to_json() for slot in self.character_mechanism_slots],
            "passive_mechanism_slots": [slot.to_json() for slot in self.passive_mechanism_slots],
            "character_trace_nodes": [node.to_json() for node in self.character_trace_nodes],
            "character_eidolon_slots": [slot.to_json() for slot in self.character_eidolon_slots],
            "bounce_policies": [policy.to_json() for policy in self.bounce_policies],
            "combatant_profiles": [profile.to_json() for profile in self.combatant_profiles],
            "action_definitions": [definition.to_json() for definition in self.action_definitions],
            "action_ability_bindings": [binding.to_json() for binding in self.action_ability_bindings],
            "ability_phases": [phase.to_json() for phase in self.ability_phases],
            "ability_tasks": [task.to_json() for task in self.ability_tasks],
            "action_events": [event.to_json() for event in self.action_events],
            "hit_profiles": [profile.to_json() for profile in self.hit_profiles],
            "skill_formula_bindings": [binding.to_json() for binding in self.skill_formula_bindings],
            "damage_emissions": [emission.to_json() for emission in self.damage_emissions],
            "damage_modifiers": [modifier.to_json() for modifier in self.damage_modifiers],
            "toughness_emissions": [emission.to_json() for emission in self.toughness_emissions],
            "break_templates": [template.to_json() for template in self.break_templates],
            "break_base_damage": [item.to_json() for item in self.break_base_damage],
            "break_damage_emissions": [emission.to_json() for emission in self.break_damage_emissions],
            "break_status_emissions": [emission.to_json() for emission in self.break_status_emissions],
            "status_event_families": [family.to_json() for family in self.status_event_families],
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
            "action_admissions": [admission.to_json() for admission in self.action_admissions],
            "timeline_rules": [rule.to_json() for rule in self.timeline_rules],
            "resource_rules": [rule.to_json() for rule in self.resource_rules],
            "damage_formula_rules": [rule.to_json() for rule in self.damage_formula_rules],
            "damage_route_rules": [rule.to_json() for rule in self.damage_route_rules],
            "shield_priority_rules": [rule.to_json() for rule in self.shield_priority_rules],
            "super_break_emissions": [emission.to_json() for emission in self.super_break_emissions],
            "target_expressions": [expression.to_json() for expression in self.target_expressions],
            "wave_definitions": [definition.to_json() for definition in self.wave_definitions],
            "triggers": [trigger.to_json() for trigger in self.triggers],
            "effects": [effect.to_json() for effect in self.effects],
            "conditions": [condition.to_json() for condition in self.conditions],
            "formulas": [formula.to_json() for formula in self.formulas],
        }
