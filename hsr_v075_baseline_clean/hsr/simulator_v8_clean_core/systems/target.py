from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ..core.model import BattleState, JSONValue, RNGEvent, TargetResolution
from ..immutable_json import freeze_json, thaw_json
from ..rules.evaluator import (
    EvaluationContext,
    NumericEvaluationContext,
    RuleEvaluator,
    _condition_target_key,
)
from ..rules.expression_ir import (
    TARGET_EXPRESSION_NODE_SCHEMA,
    numeric_fixed_value,
)
from ..rules.ir import (
    BouncePolicyIR,
    CharacterDataCardIR,
    ConditionIR,
    HitProfileIR,
    TargetExpressionIR,
    TargetExpressionNodeIR,
)
from ..rules.rulebook import RuleBook
from ..unit_eligibility import runtime_unit_is_unselectable
from .rng import rng_choices_from_payload, rng_mode_from_payload
from .condition_state import CommittedConditionFactProvider
from .target_random import TargetRandomPlan, TargetRandomSampler
from .unit_relation import (
    EntityRelationResolver,
    TargetEvaluationContext,
    is_opposing_combat_team,
    is_light_team,
)
from .unit_lifecycle import UnitLifecycleSystem


@dataclass(frozen=True)
class BounceTargetResult:
    ok: bool
    target_id: str = ""
    rng_event: RNGEvent | None = None
    random_plan: TargetRandomPlan | None = None
    sequence_exhausted: bool = False
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if type(self) is not BounceTargetResult:
            raise TypeError("bounce target result must not be subclassed")
        if type(self.ok) is not bool:
            raise TypeError("bounce target result status must be boolean")
        if type(self.sequence_exhausted) is not bool:
            raise TypeError("bounce sequence exhaustion flag must be boolean")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("bounce target result metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(dict(self.metadata)))
        if self.random_plan is not None and type(self.random_plan) is not TargetRandomPlan:
            raise TypeError("bounce target random plan must be exact")
        if self.ok:
            if self.sequence_exhausted:
                if self.target_id or self.rng_event is not None or self.random_plan is not None:
                    raise ValueError("exhausted bounce sequence carries target output")
            elif not isinstance(self.target_id, str) or not self.target_id:
                raise ValueError("resolved bounce target requires an identity")
            if self.error:
                raise ValueError("resolved bounce target carries a blocker")
            if self.rng_event is not None and type(self.rng_event) is not RNGEvent:
                raise TypeError("bounce target RNG event must be exact")
        elif self.sequence_exhausted or self.target_id or self.rng_event is not None or not self.error:
            raise ValueError("blocked bounce target carries executable output")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "target_id": self.target_id,
            "rng_event": self.rng_event.to_json() if self.rng_event is not None else None,
            "random_plan": self.random_plan.to_json() if self.random_plan is not None else None,
            "sequence_exhausted": self.sequence_exhausted,
            "metadata": thaw_json(self.metadata),
            "error": self.error,
        }


@dataclass(frozen=True)
class BouncePolicyResolution:
    status: Literal["resolved", "blocked"]
    policy: BouncePolicyIR | None = None
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not BouncePolicyResolution:
            raise TypeError("bounce policy resolution must not be subclassed")
        if self.status == "resolved":
            if type(self.policy) is not BouncePolicyIR or self.blocked_reason:
                raise ValueError("resolved bounce policy result is inconsistent")
        elif self.status == "blocked":
            if self.policy is not None or not self.blocked_reason:
                raise ValueError("blocked bounce policy result is inconsistent")
        else:
            raise ValueError("bounce policy resolution status is invalid")

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


def resolve_action_bounce_policy(
    rules: Any,
    action_id: str,
    action_level: int,
    *,
    hit_profiles: tuple[HitProfileIR, ...] | None = None,
    actor_entity_ref: str | None = None,
) -> BouncePolicyResolution:
    if not isinstance(action_id, str) or not action_id:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_action_identity_invalid")
    if type(action_level) is not int or action_level <= 0:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_action_level_invalid")
    lookup = getattr(rules, "bounce_policies_for_action", None)
    if not callable(lookup):
        return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_query_missing")
    policies = tuple(lookup(action_id, action_level))
    if not policies:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_missing")
    if len(policies) != 1:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_ambiguous")
    policy = policies[0]
    if type(policy) is not BouncePolicyIR:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_type_invalid")
    if policy.action_id != action_id or policy.level != action_level:
        return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_action_binding_mismatch")
    if policy.coverage_status != "executable":
        return BouncePolicyResolution(
            "blocked",
            blocked_reason=policy.blocked_reason
            or f"bounce_policy_not_executable:{policy.coverage_status}",
        )
    if actor_entity_ref is not None:
        if not isinstance(actor_entity_ref, str) or not actor_entity_ref:
            return BouncePolicyResolution("blocked", blocked_reason="bounce_actor_entity_ref_invalid")
        card_lookup = getattr(rules, "character_data_card", None)
        card = card_lookup(policy.character_data_card_id) if callable(card_lookup) else None
        if type(card) is not CharacterDataCardIR:
            return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_owner_card_missing")
        if card.entity_ref != actor_entity_ref:
            return BouncePolicyResolution("blocked", blocked_reason="bounce_policy_actor_owner_mismatch")
    if hit_profiles is not None:
        if not isinstance(hit_profiles, tuple) or any(
            type(profile) is not HitProfileIR for profile in hit_profiles
        ):
            return BouncePolicyResolution("blocked", blocked_reason="bounce_hit_profiles_invalid")
        referenced = {
            profile.bounce_policy_id
            for profile in hit_profiles
            if profile.bounce_policy_id
        }
        if referenced != {policy.bounce_policy_id}:
            return BouncePolicyResolution(
                "blocked",
                blocked_reason=(
                    "bounce_hit_profile_policy_missing"
                    if not referenced
                    else "bounce_hit_profile_policy_mismatch"
                ),
            )
        bounce_profiles = tuple(
            profile for profile in hit_profiles if profile.target_group.startswith("bounce:")
        )
        if len(bounce_profiles) != policy.bounce_count:
            return BouncePolicyResolution(
                "blocked",
                blocked_reason="bounce_hit_profile_count_mismatch",
            )
        primary_profiles = tuple(
            profile for profile in hit_profiles
            if profile.target_group == policy.initial_target_group
        )
        expected_bounce_groups = {
            f"{policy.bounce_target_group}:{index}"
            for index in range(policy.bounce_count)
        }
        if len(primary_profiles) != 1 or {
            profile.target_group for profile in bounce_profiles
        } != expected_bounce_groups:
            return BouncePolicyResolution(
                "blocked",
                blocked_reason="bounce_hit_profile_sequence_mismatch",
            )
        if primary_profiles[0].coverage_status != "executable":
            return BouncePolicyResolution(
                "blocked",
                blocked_reason="bounce_primary_hit_profile_not_executable",
            )
        if any(profile.coverage_status != "executable" for profile in bounce_profiles):
            return BouncePolicyResolution(
                "blocked",
                blocked_reason="bounce_hit_profile_not_executable",
            )
    return BouncePolicyResolution("resolved", policy=policy)


@dataclass(frozen=True)
class TargetExpressionResult:
    status: Literal["resolved", "blocked"]
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    expression_id: str = ""
    expression_kind: str = ""
    alias: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    rng_events: tuple[RNGEvent, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "blocked"}:
            raise ValueError("target expression result status is invalid")
        if isinstance(self.target_ids, str):
            raise TypeError("target identifiers must be an iterable of strings")
        target_ids = tuple(self.target_ids)
        if any(not isinstance(target_id, str) or not target_id for target_id in target_ids):
            raise ValueError("resolved target identifiers must be non-empty strings")
        object.__setattr__(self, "target_ids", target_ids)
        if not isinstance(self.metadata, Mapping):
            raise TypeError("target result metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(dict(self.metadata)))
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("resolved target identifiers must be unique")
        if not isinstance(self.rng_events, tuple):
            raise TypeError("target result RNG events must be a tuple")
        if any(type(event) is not RNGEvent for event in self.rng_events):
            raise TypeError("target result RNG events must be exact RNGEvent values")
        if self.status == "resolved":
            if self.blocked_reason:
                raise ValueError("resolved target result carries a blocked payload")
        elif self.target_ids or self.rng_events or not self.blocked_reason:
            raise ValueError("blocked target result must carry only a reason")

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": self.status,
            "target_ids": list(self.target_ids),
            "blocked_reason": self.blocked_reason,
            "expression_id": self.expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "metadata": thaw_json(self.metadata),
            "rng_events": [event.to_json() for event in self.rng_events],
        }




class TargetSystem:
    def __init__(self, rules: Any | None = None) -> None:
        self.lifecycle = UnitLifecycleSystem()
        self.relations = EntityRelationResolver()
        self.random_sampler = TargetRandomSampler()
        self.condition_facts = CommittedConditionFactProvider(
            rules if type(rules) is RuleBook else None
        )
        self.alias_definitions: dict[str, TargetExpressionIR] = {}
        self.scoped_alias_definitions: dict[tuple[str, str], TargetExpressionIR] = {}
        self.operation_definitions: dict[str, TargetExpressionIR] = {}
        self.ambiguous_definition_names: frozenset[str] = frozenset()
        if rules is not None:
            duplicate_names: set[str] = set()
            language_lookup = getattr(rules, "target_language_expressions", None)
            definitions = (
                language_lookup() if callable(language_lookup) else rules.target_expressions()
            )
            for definition in definitions:
                source_path = definition.source.source_path
                name = definition.source.evidence.get("source_raw_id")
                if not isinstance(name, str) or not name:
                    continue
                source_raw_type = definition.source.evidence.get("source_raw_type") or definition.source.raw_type
                if source_raw_type == "GlobalTargetAlias":
                    key = (source_path, name)
                    if key in self.scoped_alias_definitions:
                        duplicate_names.add(f"{source_path}:{name}")
                    self.scoped_alias_definitions[key] = definition
                elif source_path == "Config/GlobalConfig/TargetAliasConfig.json":
                    if name in self.alias_definitions:
                        duplicate_names.add(name)
                    self.alias_definitions[name] = definition
                elif source_path == "Config/GlobalConfig/TargetOperationConfig.json":
                    if name in self.operation_definitions:
                        duplicate_names.add(name)
                    self.operation_definitions[name] = definition
            self.ambiguous_definition_names = frozenset(
                duplicate_names
                | (self.alias_definitions.keys() & self.operation_definitions.keys())
            )

    def resolve_target_expression(
        self,
        state: BattleState,
        expression: TargetExpressionIR | TargetExpressionNodeIR,
        *,
        context: TargetEvaluationContext,
        target_resolution: TargetResolution | None = None,
        condition_event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> TargetExpressionResult:
        if type(expression) is TargetExpressionNodeIR:
            return self._resolve_expression_node(
                state,
                expression,
                context=context,
                target_resolution=target_resolution,
                condition_event_payload=condition_event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            )
        if type(expression) is not TargetExpressionIR:
            raise TypeError("target expression must be exact IR or node IR")
        metadata: dict[str, JSONValue] = {
            "target_expression": expression.to_json(),
            "caster_id": context.caster_id,
            "owner_id": context.effect_owner_id,
            "param_entity_ids": list(context.parameter_entity_ids),
            "selected_target_ids": list(context.selected_target_ids),
            "current_action_target_id": context.current_target_id,
            "target_resolution": target_resolution.to_json() if target_resolution else None,
        }
        context_validation = self.relations.resolve(state, "context.caster", context)
        if context_validation.blocked:
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=context_validation.blocked_reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        if expression.coverage_status != "executable":
            reason = expression.blocked_reason or f"target_expression_not_executable:{expression.coverage_status}"
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        result = _resolve_expression_payload(
            state,
            expression.node,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            caster_id=context.caster_id,
            owner_id=context.effect_owner_id,
            param_entity_id=context.parameter_entity_id,
            current_action_target_id=context.current_target_id,
            target_resolution=target_resolution,
            event_payload=condition_event_payload or {},
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            target_context=context,
            relations=self.relations,
            alias_definitions=self.alias_definitions,
            operation_definitions=self.operation_definitions,
            ambiguous_definition_names=self.ambiguous_definition_names,
            scoped_alias_definitions=self.scoped_alias_definitions,
            definition_source_path=expression.source.source_path,
            random_sampler=self.random_sampler,
            condition_facts=self.condition_facts,
        )
        metadata["resolution_steps"] = result.steps
        if result.blocked_reason:
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=result.blocked_reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
            )
        return TargetExpressionResult(
            status="resolved",
            target_ids=result.target_ids,
            expression_id=expression.target_expression_id,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            metadata=metadata,
            rng_events=result.rng_events,
        )

    def _resolve_expression_node(
        self,
        state: BattleState,
        node: TargetExpressionNodeIR,
        *,
        context: TargetEvaluationContext,
        target_resolution: TargetResolution | None = None,
        condition_event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> TargetExpressionResult:
        """Resolve an already-typed inline node for condition consumers."""

        metadata: dict[str, JSONValue] = {
            "target_expression_node": node.to_json(),
            "resolution_steps": [],
        }
        context_validation = self.relations.resolve(state, "context.caster", context)
        if context_validation.blocked:
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=context_validation.blocked_reason,
                expression_kind=node.expression_kind,
                alias=node.alias,
                metadata=metadata,
            )
        if node.runtime_blocked_reason:
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=node.runtime_blocked_reason,
                expression_kind=node.expression_kind,
                alias=node.alias,
                metadata=metadata,
            )
        result = _resolve_expression_payload(
            state,
            node,
            expression_kind=node.expression_kind,
            alias=node.alias,
            caster_id=context.caster_id,
            owner_id=context.effect_owner_id,
            param_entity_id=context.parameter_entity_id,
            current_action_target_id=context.current_target_id,
            target_resolution=target_resolution,
            event_payload=condition_event_payload or {},
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            target_context=context,
            relations=self.relations,
            alias_definitions=self.alias_definitions,
            operation_definitions=self.operation_definitions,
            scoped_alias_definitions=self.scoped_alias_definitions,
            definition_source_path=node.source.source_path,
            ambiguous_definition_names=self.ambiguous_definition_names,
            random_sampler=self.random_sampler,
            condition_facts=self.condition_facts,
        )
        metadata["resolution_steps"] = result.steps
        if result.blocked_reason:
            return TargetExpressionResult(
                status="blocked",
                blocked_reason=result.blocked_reason,
                expression_kind=node.expression_kind,
                alias=node.alias,
                metadata=metadata,
            )
        return TargetExpressionResult(
            status="resolved",
            target_ids=result.target_ids,
            expression_kind=node.expression_kind,
            alias=node.alias,
            metadata=metadata,
            rng_events=result.rng_events,
        )

    def resolve_condition_target_groups(
        self,
        state: BattleState,
        condition: ConditionIR,
        *,
        context: TargetEvaluationContext,
        target_resolution: TargetResolution | None = None,
        condition_event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
        """Resolve every typed target operand required by a condition.

        Condition evaluation itself remains pure and fail-closed. Consumers
        that own the target system use this method to provide the exact target
        groups, including composite aliases and TargetSequence operations.
        """

        resolved: dict[str, tuple[str, ...]] = {}
        errors: dict[str, str] = {}
        for node in _condition_target_nodes(condition):
            key = _condition_target_key(node)
            if key in resolved or key in errors:
                continue
            result = self.resolve_target_expression(
                state,
                node,
                context=context,
                target_resolution=target_resolution,
                condition_event_payload=condition_event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            )
            if result.resolved:
                resolved[key] = result.target_ids
            else:
                errors[key] = result.blocked_reason
        return resolved, errors

    def condition_evaluation_context(
        self,
        state: BattleState,
        condition: ConditionIR,
        *,
        context: TargetEvaluationContext,
        target_resolution: TargetResolution | None = None,
        condition_event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
        status_detail: dict[str, JSONValue] | None = None,
    ) -> EvaluationContext:
        """Build the one formal evaluator context from typed target identities."""

        resolved, errors = self.resolve_condition_target_groups(
            state,
            condition,
            context=context,
            target_resolution=target_resolution,
            condition_event_payload=condition_event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        return EvaluationContext(
            state=state,
            actor_id=context.caster_id,
            target_id=context.current_target_id,
            owner_id=context.effect_owner_id,
            param_entity_id=context.parameter_entity_id,
            current_action_target_id=context.current_target_id,
            status_detail=status_detail,
            event_payload=condition_event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            resolved_target_groups=resolved,
            target_resolution_errors=errors,
            committed_condition_provider=self.condition_facts,
        )

    def resolve_bounce_hit_target(
        self,
        state: BattleState,
        *,
        actor_id: str,
        primary_target_id: str,
        bounce_policy: BouncePolicyIR,
        hit_index: int,
        previous_hit_targets: tuple[str, ...],
        action_id: str,
        action_level: int,
        source_task_id: str,
        hit_profile_id: str,
        event_payload: dict[str, JSONValue] | None = None,
    ) -> BounceTargetResult:
        actor = state.units.get(actor_id)
        if actor is None:
            return BounceTargetResult(ok=False, error="unknown_actor")
        if not isinstance(primary_target_id, str) or not primary_target_id:
            return BounceTargetResult(ok=False, error="bounce_primary_target_identity_invalid")
        primary_target = state.units.get(primary_target_id)
        if primary_target is None:
            return BounceTargetResult(ok=False, error="bounce_primary_target_missing")
        if not is_opposing_combat_team(actor, primary_target):
            return BounceTargetResult(ok=False, error="bounce_primary_target_not_opposing")
        if type(bounce_policy) is not BouncePolicyIR:
            return BounceTargetResult(ok=False, error="bounce_policy_type_invalid")
        if (
            bounce_policy.coverage_status != "executable"
            or bounce_policy.action_id != action_id
            or bounce_policy.level != action_level
        ):
            return BounceTargetResult(
                ok=False,
                error=(
                    bounce_policy.blocked_reason
                    or "bounce_policy_action_binding_mismatch"
                ),
                metadata={"bounce_policy": bounce_policy.to_json()},
            )
        if type(hit_index) is not int or hit_index <= 0:
            return BounceTargetResult(ok=False, error="bounce_hit_index_invalid")
        if hit_index > bounce_policy.bounce_count:
            return BounceTargetResult(ok=False, error="bounce_hit_index_out_of_policy_range")
        if not isinstance(source_task_id, str) or not source_task_id:
            return BounceTargetResult(ok=False, error="bounce_source_task_identity_missing")
        if not isinstance(hit_profile_id, str) or not hit_profile_id:
            return BounceTargetResult(ok=False, error="bounce_hit_profile_identity_missing")
        if isinstance(previous_hit_targets, str) or any(
            not isinstance(target_id, str) or not target_id
            for target_id in previous_hit_targets
        ):
            return BounceTargetResult(ok=False, error="bounce_previous_target_identity_invalid")
        if bounce_policy.candidate_scope != "enemy_single":
            return BounceTargetResult(ok=False, error="bounce_candidate_scope_not_supported")
        if not bounce_policy.live_target_priority:
            return BounceTargetResult(ok=False, error="bounce_live_target_priority_not_admitted")
        live_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit)
            and self.lifecycle.can_target(state, unit_id)[0]
            and not runtime_unit_is_unselectable(unit)
        )
        selection_strategy = bounce_policy.selection_strategy
        if selection_strategy not in {"prefer_unhit_then_random", "random_live_targets"}:
            return BounceTargetResult(ok=False, error="bounce_selection_strategy_not_supported")
        candidate_pool = live_candidates
        candidate_pool_reason = "live_targets"
        if live_candidates and selection_strategy == "prefer_unhit_then_random":
            unhit = tuple(unit_id for unit_id in live_candidates if unit_id not in set(previous_hit_targets))
            if unhit:
                candidate_pool = unhit
                candidate_pool_reason = "live_unhit_targets"
            elif not bounce_policy.allow_repeat_after_all_hit:
                return BounceTargetResult(
                    ok=False,
                    error="bounce_repeat_after_all_hit_not_admitted",
                    metadata={"bounce_policy": bounce_policy.to_json()},
                )
            else:
                candidate_pool_reason = "live_targets_repeat_after_all_hit"
        if not candidate_pool:
            if not bounce_policy.continue_on_all_defeated:
                return BounceTargetResult(
                    ok=False,
                    error="bounce_no_live_target_and_continuation_not_admitted",
                    metadata={"bounce_policy": bounce_policy.to_json()},
                )
            return BounceTargetResult(
                ok=True,
                sequence_exhausted=True,
                metadata={
                    "candidate_pool_reason": "all_targets_defeated_sequence_complete",
                    "bounce_policy_id": bounce_policy.bounce_policy_id,
                    "hit_index": hit_index,
                },
            )
        if (
            bounce_policy.random_selector_sources
            and hit_index > len(bounce_policy.random_selector_sources)
        ):
            return BounceTargetResult(
                ok=False,
                error="bounce_random_selector_source_missing_for_hit",
            )
        selector_source = (
            bounce_policy.random_selector_sources[hit_index - 1]
            if bounce_policy.random_selector_sources
            and hit_index <= len(bounce_policy.random_selector_sources)
            else bounce_policy.source
        )
        selector_source_kind: Literal["bounce_policy", "random_select_task"] = (
            "random_select_task"
            if selector_source.raw_type == "RandomSelectInTargetList"
            else "bounce_policy"
        )
        selector_source_identity = (
            selector_source.raw_id
            if selector_source_kind == "random_select_task"
            else bounce_policy.bounce_policy_id
        )
        plan = TargetRandomPlan(
            mode="single",
            source_kind=selector_source_kind,
            source_identity=selector_source_identity,
            source_trace=selector_source.to_json(),
            evaluation_context={
                "actor_id": actor_id,
                "primary_target_id": primary_target_id,
                "action_id": action_id,
                "action_level": action_level,
                "source_task_id": source_task_id,
                "hit_profile_id": hit_profile_id,
                "hit_index": hit_index,
                "previous_hit_targets": list(previous_hit_targets),
                "candidate_pool_reason": candidate_pool_reason,
                "selection_strategy": selection_strategy,
                "live_target_priority": bounce_policy.live_target_priority,
                "continue_on_all_defeated": bounce_policy.continue_on_all_defeated,
                "allow_repeat_after_all_hit": bounce_policy.allow_repeat_after_all_hit,
                "bounce_policy_id": bounce_policy.bounce_policy_id,
                "bounce_policy_source": bounce_policy.source.to_json(),
            },
            invocation_identity=(
                f"bounce:{state.event_index}:{actor_id}:{action_id}:{action_level}:"
                f"{source_task_id}:{hit_profile_id}:{hit_index}"
            ),
            candidate_ids=candidate_pool,
            requested_count=1,
            before_state=state.rng_state,
            event_index=state.event_index,
        )
        resolution = self.random_sampler.resolve(
            plan,
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
        )
        if not resolution.resolved or not resolution.selected_ids:
            return BounceTargetResult(
                ok=False,
                error=resolution.blocked_reason or "bounce_target_resolution_blocked",
                metadata={
                    "plan": plan.to_json(),
                    "pending_request": thaw_json(resolution.pending_request),
                },
                random_plan=plan,
            )
        selected_target_id = resolution.selected_ids[0]
        event = resolution.rng_events[0] if resolution.rng_events else None
        return BounceTargetResult(
            ok=True,
            target_id=selected_target_id,
            rng_event=event,
            random_plan=plan,
            metadata={
                "selected_target_id": selected_target_id,
                "candidate_pool": list(candidate_pool),
                "candidate_pool_reason": candidate_pool_reason,
                "previous_hit_targets": list(previous_hit_targets),
                "bounce_policy_id": bounce_policy.bounce_policy_id,
                "random_selector_source": selector_source.to_json(),
                "source_task_id": source_task_id,
                "hit_profile_id": hit_profile_id,
                "hit_index": hit_index,
                "plan_fingerprint": plan.plan_fingerprint,
                "candidate_pool_fingerprint": plan.candidate_pool_fingerprint,
                "choice_key": (
                    str(event.metadata.get("choice_key") or "") if event is not None else ""
                ),
                "choice_source": (
                    str(event.metadata.get("choice_source") or "deterministic_singleton")
                    if event is not None
                    else "deterministic_singleton"
                ),
            },
        )


@dataclass(frozen=True)
class _ExpressionResolution:
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    steps: list[JSONValue] = field(default_factory=list)
    rng_events: tuple[RNGEvent, ...] = ()


@dataclass(frozen=True)
class _TargetRelationRuntime:
    context: TargetEvaluationContext
    relations: EntityRelationResolver
    alias_definitions: Mapping[str, TargetExpressionIR]
    operation_definitions: Mapping[str, TargetExpressionIR]
    scoped_alias_definitions: Mapping[tuple[str, str], TargetExpressionIR]
    definition_source_path: str
    random_sampler: TargetRandomSampler
    condition_facts: CommittedConditionFactProvider
    ambiguous_definition_names: frozenset[str] = frozenset()
    alias_stack: tuple[str, ...] = ()
    include_limbo: bool = False

    def entering_alias(self, alias: str) -> "_TargetRelationRuntime":
        return replace(self, alias_stack=(*self.alias_stack, alias))


def _target_random_plan(
    state: BattleState,
    node: TargetExpressionNodeIR,
    *,
    mode: Literal["single", "sample_without_replacement", "shuffle"],
    requested_count: int,
    candidate_ids: tuple[str, ...],
    path: str,
    event_payload: dict[str, JSONValue],
    relation_runtime: _TargetRelationRuntime,
) -> TargetRandomPlan:
    event_context: dict[str, JSONValue] = {}
    for key in (
        "action_id",
        "action_level",
        "task_id",
        "hit_index",
        "rng_decision_index",
        "event_id",
        "status_instance_id",
        "callback_id",
    ):
        value = event_payload.get(key)
        if isinstance(value, str) and value:
            event_context[key] = value
        elif type(value) is int and value >= 0:
            event_context[key] = value
    context = relation_runtime.context
    evaluation_context: dict[str, JSONValue] = {
        "state_event_index": state.event_index,
        "caster_id": context.caster_id,
        "effect_owner_id": context.effect_owner_id,
        "parameter_entity_ids": list(context.parameter_entity_ids),
        "selected_target_ids": list(context.selected_target_ids),
        "current_target_id": context.current_target_id,
        "event_source_id": context.event_source_id,
        "event_subject_id": context.event_subject_id,
        "event_target_id": context.event_target_id,
        "damage_attacker_id": context.damage_attacker_id,
        "damage_defender_id": context.damage_defender_id,
        "turn_owner_id": context.turn_owner_id,
        "event_context": event_context,
    }
    invocation_payload = {
        "source_identity": node.node_id,
        "path": path,
        "evaluation_context": evaluation_context,
    }
    invocation_raw = json.dumps(
        invocation_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    invocation_identity = (
        "target_random_invocation:"
        + hashlib.sha256(invocation_raw).hexdigest()
    )
    return TargetRandomPlan(
        mode=mode,
        source_kind="target_expression",
        source_identity=node.node_id,
        source_trace=node.source.to_json(),
        evaluation_context=evaluation_context,
        invocation_identity=invocation_identity,
        candidate_ids=candidate_ids,
        requested_count=requested_count,
        before_state=state.rng_state,
        event_index=state.event_index,
    )


def _resolve_expression_payload(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    expression_kind: str,
    alias: str,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    target_context: TargetEvaluationContext,
    relations: EntityRelationResolver,
    alias_definitions: Mapping[str, TargetExpressionIR],
    operation_definitions: Mapping[str, TargetExpressionIR],
    scoped_alias_definitions: Mapping[tuple[str, str], TargetExpressionIR],
    definition_source_path: str,
    ambiguous_definition_names: frozenset[str],
    random_sampler: TargetRandomSampler,
    condition_facts: CommittedConditionFactProvider,
) -> _ExpressionResolution:
    if raw is None or raw.schema_version != TARGET_EXPRESSION_NODE_SCHEMA:
        return _ExpressionResolution(blocked_reason="target_expression_typed_node_missing")
    return _resolve_inline_expression(
        state,
        raw,
        expression_kind=expression_kind,
        alias=alias,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path="$",
        relation_runtime=_TargetRelationRuntime(
            context=target_context,
            relations=relations,
            alias_definitions=alias_definitions,
            operation_definitions=operation_definitions,
            scoped_alias_definitions=scoped_alias_definitions,
            definition_source_path=definition_source_path,
            random_sampler=random_sampler,
            condition_facts=condition_facts,
            ambiguous_definition_names=ambiguous_definition_names,
        ),
    )


def _resolve_inline_expression(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    expression_kind: str,
    alias: str,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    previous_targets: tuple[str, ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is not None:
        expression_kind = _inline_expression_kind(raw) or expression_kind
        alias = _inline_target_alias(raw) or alias
    if expression_kind == "TargetAlias":
        alias_result = _resolve_target_alias_resolution(
            state,
            alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
            relation_runtime=relation_runtime,
        )
        return _inline_result(
            path,
            expression_kind,
            alias,
            alias_result.target_ids,
            alias_result.blocked_reason,
            alias_result.steps,
            alias_result.rng_events,
        )
    if expression_kind == "TargetSelector":
        if raw is None or raw.predicate is None or len(raw.children) != 2:
            return _inline_result(path, expression_kind, alias, (), "target_selector_payload_missing")
        probe_id = param_entity_id or caster_id
        predicate_result = _resolve_filter_candidates(
            state,
            raw.predicate,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=(probe_id,),
            path=f"{path}.predicate",
            steps=(),
            rng_events=(),
            relation_runtime=relation_runtime,
        )
        if predicate_result.blocked_reason:
            return _inline_result(path, expression_kind, alias, (), predicate_result.blocked_reason, predicate_result.steps)
        branch_index = 0 if predicate_result.target_ids else 1
        branch = raw.children[branch_index]
        return _resolve_inline_expression(
            state,
            branch,
            expression_kind=branch.expression_kind,
            alias=branch.alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            previous_targets=previous_targets,
            path=f"{path}.{'success' if branch_index == 0 else 'failure'}",
            relation_runtime=relation_runtime,
        )
    if expression_kind in {"TargetConcat", "TargetCompute"}:
        children = raw.children if raw is not None else ()
        if not children:
            return _inline_result(path, expression_kind, alias, (), f"target_expression_children_missing:{expression_kind}")
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        rng_events: list[RNGEvent] = []
        for index, child in enumerate(children):
            child_result = _resolve_inline_expression(
                state,
                child,
                expression_kind=_inline_expression_kind(child),
                alias=_inline_target_alias(child),
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=(),
                path=f"{path}.{expression_kind}[{index}]",
                relation_runtime=relation_runtime,
            )
            steps.extend(child_result.steps)
            rng_events.extend(child_result.rng_events)
            if child_result.blocked_reason:
                return _inline_result(path, expression_kind, alias, (), child_result.blocked_reason, steps, tuple(rng_events))
            selected = _dedupe((*selected, *child_result.target_ids))
        return _inline_result(path, expression_kind, alias, selected, "", steps, tuple(rng_events))
    if expression_kind == "TargetSequence":
        children = _inline_children(raw, expression_kind)
        if not children:
            return _inline_result(path, expression_kind, alias, (), f"target_expression_children_missing:{expression_kind}")
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        rng_events: list[RNGEvent] = []
        for index, child in enumerate(children):
            child_kind = _inline_expression_kind(child)
            child_path = f"{path}.{expression_kind}[{index}]"
            if child_kind == "TargetFilter" and index > 0 and not selected:
                child_result = _inline_result(
                    child_path,
                    "TargetFilter",
                    "",
                    (),
                    "",
                    [{"operation": "filter_empty_input", "selected_targets": []}],
                )
            elif child_kind == "TargetFilter":
                child_result = _resolve_filter_expression(
                    state,
                    child,
                    caster_id=caster_id,
                    owner_id=owner_id,
                    param_entity_id=param_entity_id,
                    current_action_target_id=current_action_target_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    candidate_targets=selected,
                    path=child_path,
                    relation_runtime=relation_runtime,
                )
            elif _is_transform_expression_kind(child_kind):
                child_result = _resolve_transform_expression(
                    state,
                    child,
                    expression_kind=child_kind,
                    caster_id=caster_id,
                    owner_id=owner_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    candidate_targets=selected,
                    path=child_path,
                    relation_runtime=relation_runtime,
                )
            else:
                child_result = _resolve_inline_expression(
                    state,
                    child,
                    expression_kind=child_kind,
                    alias=_inline_target_alias(child),
                    caster_id=caster_id,
                    owner_id=owner_id,
                    param_entity_id=param_entity_id,
                    current_action_target_id=current_action_target_id,
                    target_resolution=target_resolution,
                    event_payload=event_payload,
                    dynamic_values=dynamic_values,
                    binding_sources=binding_sources,
                    previous_targets=selected,
                    path=child_path,
                    relation_runtime=relation_runtime,
                )
            steps.extend(child_result.steps)
            rng_events.extend(child_result.rng_events)
            if child_result.blocked_reason:
                return _inline_result(path, expression_kind, alias, (), child_result.blocked_reason, steps, tuple(rng_events))
            selected = child_result.target_ids
        return _inline_result(path, expression_kind, alias, selected, "", steps, tuple(rng_events))
    if expression_kind == "TargetFilter":
        return _resolve_filter_expression(
            state,
            raw,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=previous_targets,
            path=path,
            relation_runtime=relation_runtime,
        )
    if expression_kind == "Retarget":
        return _resolve_retarget_expression(
            state,
            raw,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
            relation_runtime=relation_runtime,
        )
    if expression_kind.startswith("TargetFetch"):
        return _resolve_fetch_expression(
            state,
            raw,
            expression_kind=expression_kind,
            caster_id=caster_id,
            owner_id=owner_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            previous_targets=previous_targets,
            path=path,
            relation_runtime=relation_runtime,
        )
    if expression_kind == "TargetQuery":
        return _resolve_target_query(
            state,
            raw,
            caster_id=caster_id,
            owner_id=owner_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
            relation_runtime=relation_runtime,
        )
    if _is_transform_expression_kind(expression_kind):
        return _resolve_transform_expression(
            state,
            raw,
            expression_kind=expression_kind,
            caster_id=caster_id,
            owner_id=owner_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=previous_targets,
            path=path,
            relation_runtime=relation_runtime,
        )
    return _inline_result(path, expression_kind, alias, (), f"target_expression_kind_not_supported:{expression_kind}")


def _resolve_target_query(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    caster_id: str,
    owner_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, "TargetQuery", "", (), "target_query_payload_missing")
    entity_type = raw.query_entity_type_mask
    if entity_type != "Servant":
        return _inline_result(path, "TargetQuery", "", (), f"target_query_entity_type_not_supported:{entity_type or 'missing'}")
    servant_result = relation_runtime.relations.resolve(
        state,
        "entity.servant",
        relation_runtime.context,
        options={"mask": raw.query_alive_state_mask or "Mask_AliveOnly"},
    )
    candidates = servant_result.target_ids
    reason = servant_result.blocked_reason
    steps: list[JSONValue] = [
        {
            "operation": "TargetQuery",
            "entity_type_mask": entity_type,
            "alive_state_mask": raw.query_alive_state_mask,
            "candidate_pool_before": list(candidates),
            "candidate_source": "summon_runtime.servants",
        }
    ]
    if reason:
        return _inline_result(path, "TargetQuery", "", (), reason, steps)
    if raw.query_target is None and raw.query_compare is None:
        return _inline_result(path, "TargetQuery", "", candidates, "", steps)
    if raw.query_target is None or raw.query_compare is None:
        return _inline_result(path, "TargetQuery", "", (), "target_query_compare_target_missing", steps)
    selected: list[str] = []
    predicate_steps: list[JSONValue] = []
    for candidate_id in candidates:
        predicate_result = _evaluate_target_query_compare_predicate(
            state,
            raw,
            candidate_id=candidate_id,
            caster_id=caster_id,
            owner_id=owner_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=f"{path}.Predicate[{candidate_id}]",
            relation_runtime=relation_runtime,
        )
        predicate_steps.append(predicate_result)
        if predicate_result.get("blocked_reason"):
            return _inline_result(
                path,
                "TargetQuery",
                "",
                (),
                f"target_query_predicate_blocked:{predicate_result['blocked_reason']}",
                [*steps, {"predicate_results": predicate_steps}],
            )
        if predicate_result.get("matched") is True:
            selected.append(candidate_id)
    if not selected:
        return _inline_result(path, "TargetQuery", "", (), "", [*steps, {"predicate_results": predicate_steps}])
    return _inline_result(path, "TargetQuery", "", tuple(selected), "", [*steps, {"predicate_results": predicate_steps}])


def _evaluate_target_query_compare_predicate(
    state: BattleState,
    predicate: TargetExpressionNodeIR,
    *,
    candidate_id: str,
    caster_id: str,
    owner_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> dict[str, JSONValue]:
    left_raw = predicate.query_target
    right_raw = predicate.query_compare
    left = _resolve_inline_expression(
        state,
        left_raw,
        expression_kind=_inline_expression_kind(left_raw),
        alias=_inline_target_alias(left_raw),
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=candidate_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload={**event_payload, "param_entity_id": candidate_id, "target_id": candidate_id},
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path=f"{path}.left",
        relation_runtime=replace(
            relation_runtime,
            context=relation_runtime.context.with_parameter(candidate_id),
        ),
    )
    if left.blocked_reason:
        return {
            "candidate_id": candidate_id,
            "blocked_reason": left.blocked_reason,
            "left_steps": left.steps,
        }
    right = _resolve_inline_expression(
        state,
        right_raw,
        expression_kind=_inline_expression_kind(right_raw),
        alias=_inline_target_alias(right_raw),
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=candidate_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload={**event_payload, "param_entity_id": candidate_id, "target_id": candidate_id},
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path=f"{path}.right",
        relation_runtime=replace(
            relation_runtime,
            context=relation_runtime.context.with_parameter(candidate_id),
        ),
    )
    if right.blocked_reason:
        return {
            "candidate_id": candidate_id,
            "blocked_reason": right.blocked_reason,
            "left_targets": list(left.target_ids),
            "right_steps": right.steps,
        }
    matched = bool(set(left.target_ids) & set(right.target_ids))
    return {
        "candidate_id": candidate_id,
        "left_targets": list(left.target_ids),
        "right_targets": list(right.target_ids),
        "matched": matched,
    }


def _condition_target_nodes(condition: ConditionIR) -> tuple[TargetExpressionNodeIR, ...]:
    nodes: list[TargetExpressionNodeIR] = []

    def visit(value: object) -> None:
        if isinstance(value, TargetExpressionNodeIR):
            nodes.append(value)
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(condition.payload)
    return tuple(nodes)


def _resolve_filter_expression(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    candidate_targets: tuple[str, ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, "TargetFilter", "", (), "target_filter_payload_missing")
    explicit_target = raw.candidate
    steps: list[JSONValue] = []
    if explicit_target is not None:
        source_result = _resolve_inline_expression(
            state,
            explicit_target,
            expression_kind=_inline_expression_kind(explicit_target),
            alias=_inline_target_alias(explicit_target),
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            previous_targets=(),
            path=f"{path}.source",
            relation_runtime=relation_runtime,
        )
        steps.extend(source_result.steps)
        if source_result.blocked_reason:
            return _inline_result(path, "TargetFilter", "", (), source_result.blocked_reason, steps, source_result.rng_events)
        candidate_targets = source_result.target_ids
    if not candidate_targets:
        return _inline_result(path, "TargetFilter", "", (), "", steps)
    condition = raw.predicate
    if condition is None:
        return _inline_result(path, "TargetFilter", "", (), "target_filter_predicate_missing", steps)
    return _resolve_filter_candidates(
        state,
        condition,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        candidate_targets=candidate_targets,
        path=path,
        steps=tuple(steps),
        rng_events=source_result.rng_events if explicit_target is not None else (),
        relation_runtime=relation_runtime,
    )


def _resolve_filter_candidates(
    state: BattleState,
    condition: ConditionIR,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    candidate_targets: tuple[str, ...],
    path: str,
    steps: tuple[JSONValue, ...],
    rng_events: tuple[RNGEvent, ...],
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if not candidate_targets:
        return _inline_result(path, "TargetFilter", "", (), "", list(steps), rng_events)
    evaluator = RuleEvaluator()
    selected: list[str] = []
    condition_results: list[JSONValue] = []
    for candidate_id in candidate_targets:
        condition_event_payload = {
            **event_payload,
            "target_id": candidate_id,
            "param_entity_id": candidate_id,
        }
        candidate_runtime = replace(
            relation_runtime,
            context=relation_runtime.context.with_parameter(candidate_id),
        )
        resolved_target_groups: dict[str, tuple[str, ...]] = {}
        target_resolution_errors: dict[str, str] = {}
        for node in _condition_target_nodes(condition):
            key = _condition_target_key(node)
            if key in resolved_target_groups or key in target_resolution_errors:
                continue
            target_result = _resolve_inline_expression(
                state,
                node,
                expression_kind=node.expression_kind,
                alias=node.alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=candidate_id,
                current_action_target_id=current_action_target_id or candidate_id,
                target_resolution=target_resolution,
                event_payload=condition_event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=(),
                path=f"{path}.condition_target.{key}",
                relation_runtime=candidate_runtime,
            )
            if target_result.blocked_reason:
                target_resolution_errors[key] = target_result.blocked_reason
            else:
                resolved_target_groups[key] = target_result.target_ids
        result = evaluator.evaluate_condition_result(
            condition,
            EvaluationContext(
                state=state,
                actor_id=caster_id,
                target_id=candidate_id,
                owner_id=owner_id,
                param_entity_id=candidate_id,
                current_action_target_id=current_action_target_id or candidate_id,
                event_payload=condition_event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                resolved_target_groups=resolved_target_groups,
                target_resolution_errors=target_resolution_errors,
                committed_condition_provider=relation_runtime.condition_facts,
            ),
        )
        condition_results.append(result.to_json())
        if not result.ok or result.result is None:
            return _inline_result(
                path,
                "TargetFilter",
                "",
                (),
                f"target_filter_condition_blocked:{result.reason}",
                [*steps, {"condition_results": condition_results}],
                rng_events,
            )
        if result.result:
            selected.append(candidate_id)
    return _inline_result(
        path,
        "TargetFilter",
        "",
        tuple(selected),
        "",
        [*steps, {"condition_results": condition_results}],
        rng_events,
    )


def _resolve_retarget_expression(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, "Retarget", "", (), "retarget_payload_missing")
    target_expr = raw.target
    if target_expr is None:
        return _inline_result(path, "Retarget", "", (), "retarget_target_type_missing")
    source_result = _resolve_inline_expression(
        state,
        target_expr,
        expression_kind=_inline_expression_kind(target_expr),
        alias=_inline_target_alias(target_expr),
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path=f"{path}.TargetType",
        relation_runtime=replace(relation_runtime, include_limbo=raw.include_limbo),
    )
    if source_result.blocked_reason:
        return _inline_result(path, "Retarget", "", (), source_result.blocked_reason, source_result.steps, source_result.rng_events)
    candidate_targets = source_result.target_ids
    steps = list(source_result.steps)
    rng_events = list(source_result.rng_events)
    if raw.predicate is not None:
        filter_result = _resolve_filter_candidates(
            state,
            raw.predicate,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            candidate_targets=candidate_targets,
            path=f"{path}.predicate",
            steps=tuple(steps),
            rng_events=tuple(rng_events),
            relation_runtime=relation_runtime,
        )
        if filter_result.blocked_reason:
            return _inline_result(
                path,
                "Retarget",
                "",
                (),
                filter_result.blocked_reason,
                list(filter_result.steps),
                filter_result.rng_events,
            )
        candidate_targets = filter_result.target_ids
        steps = list(filter_result.steps)
        rng_events = list(filter_result.rng_events)
    max_number_expr = raw.max_number_expr
    if max_number_expr:
        max_number, max_step, max_reason = _non_negative_int_from_numeric(
            max_number_expr,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace={"target_expression_path": path, "field": "MaxNumber"},
        )
    else:
        max_number = len(candidate_targets)
        max_step = {
            "operation": "numeric_default",
            "value": max_number,
            "source_trace": {"target_expression_path": path, "field": "MaxNumber"},
        }
        max_reason = ""
    steps.append(max_step)
    if max_reason:
        return _inline_result(path, "Retarget", "", (), f"retarget_max_number_blocked:{max_reason}", steps, tuple(rng_events))
    if raw.include_limbo:
        lifecycle_result = relation_runtime.relations.resolve(
            state,
            "lifecycle.filter",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={"mask": "Mask_AliveOrLimbo"},
        )
        if lifecycle_result.blocked:
            return _inline_result(path, "Retarget", "", (), lifecycle_result.blocked_reason, steps, tuple(rng_events))
        candidate_targets = lifecycle_result.target_ids
    if raw.by_random:
        random_result = relation_runtime.random_sampler.resolve(
            _target_random_plan(
                state,
                raw,
                mode="sample_without_replacement",
                requested_count=max_number,
                candidate_ids=candidate_targets,
                path=path,
                event_payload=event_payload,
                relation_runtime=relation_runtime,
            ),
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
        )
        steps.append({"operation": "target_random", "result": random_result.to_json()})
        if not random_result.resolved:
            return _inline_result(
                path,
                "Retarget",
                "",
                (),
                random_result.blocked_reason,
                steps,
            )
        return _inline_result(
            path,
            "Retarget",
            "",
            random_result.selected_ids,
            "",
            steps,
            tuple((*rng_events, *random_result.rng_events)),
        )
    selected = candidate_targets[: max_number]
    if not selected:
        return _inline_result(path, "Retarget", "", (), "", steps, tuple(rng_events))
    return _inline_result(path, "Retarget", "", selected, "", steps, tuple(rng_events))


def _is_transform_expression_kind(kind: str) -> bool:
    return kind in {
        "TargetMapAdjoinEntity",
        "TargetMapAllTeamMember",
        "TargetMapEnemyTeamEntity",
        "TargetMapCreator",
        "TargetMapAllTeamMemberFromFirstEntity",
        "TargetMapSummoner",
        "TargetMapSummonedMinions",
        "TargetRemoveUnselectable",
        "TargetFilterAliveState",
        "TargetFilterUnselectable",
        "TargetFilterEntityType",
        "TargetReverse",
        "TargetShuffle",
        "TargetTake",
        "TargetIndex",
        "TargetPresentationOrderIgnored",
    } or kind.startswith("TargetSort")


def _resolve_fetch_expression(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    expression_kind: str,
    caster_id: str,
    owner_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    previous_targets: tuple[str, ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, expression_kind, "", (), "target_fetch_payload_missing")
    if expression_kind == "TargetFetchCaster":
        return _resolve_context_relation(state, expression_kind, "context.caster", path, relation_runtime)
    if expression_kind in {"TargetFetchModifierOwner", "TargetFetchOwner"}:
        return _resolve_context_relation(state, expression_kind, "context.owner", path, relation_runtime)
    if expression_kind in {"TargetFetchAbilityTarget", "TargetFetchCurrentActionTarget"}:
        relation = "context.current" if expression_kind == "TargetFetchCurrentActionTarget" else "context.selected"
        return _resolve_context_relation(state, expression_kind, relation, path, relation_runtime)
    if expression_kind == "TargetFetchParamEntity":
        return _resolve_context_relation(state, expression_kind, "context.parameter", path, relation_runtime)
    if expression_kind == "TargetFetchParamEntityList":
        return _resolve_context_relation(state, expression_kind, "context.parameter", path, relation_runtime)
    if expression_kind == "TargetFetchActualOwner":
        if not previous_targets:
            return _inline_result(path, expression_kind, "", (), "target_fetch_actual_owner_input_missing")
        selected: list[str] = []
        for target_id in previous_targets:
            result = relation_runtime.relations.resolve(
                state, "summon.owner", relation_runtime.context, subject_ids=(target_id,)
            )
            if result.blocked:
                return _inline_result(path, expression_kind, "", (), result.blocked_reason)
            if result.target_ids:
                selected.extend(result.target_ids)
            else:
                selected.append(target_id)
        return _inline_result(path, expression_kind, "", _dedupe(tuple(selected)), "")
    if expression_kind == "TargetFetchTeamEntity":
        relation = "team.light" if raw.team_type == "TeamLight" else "team.dark"
        result = relation_runtime.relations.resolve(
            state,
            relation,
            relation_runtime.context,
            subject_ids=(relation_runtime.context.caster_id,),
            options={"include_limbo": relation_runtime.include_limbo},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFetchBattleEventEntityList":
        result = relation_runtime.relations.resolve(
            state, "entity.battle_event", relation_runtime.context
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFetchTurnOwnerEntity":
        result = relation_runtime.relations.resolve(
            state, "context.turn_owner", relation_runtime.context
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFetchNone":
        return _inline_result(path, expression_kind, "", (), "")
    if expression_kind in {"TargetFetchAllUnselectable", "TargetFetchAllCustomUnselectable"}:
        candidates = tuple(sorted(state.units))
        if raw.candidate is not None:
            candidate_result = _resolve_inline_expression(
                state,
                raw.candidate,
                expression_kind=raw.candidate.expression_kind,
                alias=raw.candidate.alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=relation_runtime.context.parameter_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=previous_targets,
                path=f"{path}.source_entity",
                relation_runtime=relation_runtime,
            )
            if candidate_result.blocked_reason:
                return _inline_result(
                    path, expression_kind, "", (), candidate_result.blocked_reason,
                    candidate_result.steps, candidate_result.rng_events,
                )
            if not candidate_result.target_ids:
                return _inline_result(path, expression_kind, "", (), "")
            team_result = relation_runtime.relations.resolve(
                state,
                "team.same",
                relation_runtime.context,
                subject_ids=(candidate_result.target_ids[0],),
                options={"allow_unselectable": True, "include_limbo": True},
            )
            if team_result.blocked:
                return _inline_result(path, expression_kind, "", (), team_result.blocked_reason)
            candidates = team_result.target_ids
        result = relation_runtime.relations.resolve(
            state, "entity.unselectable", relation_runtime.context, subject_ids=candidates
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFetchPartner":
        result = relation_runtime.relations.resolve(
            state,
            "entity.partner",
            relation_runtime.context,
            options={"name": raw.name},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFetchUniqueNameEntity":
        unique_name = raw.unique_name
        if not unique_name:
            return _inline_result(path, expression_kind, "", (), "unique_entity_key_missing")
        result = relation_runtime.relations.resolve(
            state,
            "entity.unique_name",
            relation_runtime.context,
            options={"unique_name": unique_name},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    return _inline_result(path, expression_kind, "", (), f"target_fetch_not_supported:{expression_kind}")


def _resolve_context_relation(
    state: BattleState,
    expression_kind: str,
    relation: str,
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    result = relation_runtime.relations.resolve(state, relation, relation_runtime.context)
    return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)


def _resolve_transform_expression(
    state: BattleState,
    raw: TargetExpressionNodeIR | None,
    *,
    expression_kind: str,
    caster_id: str,
    owner_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    candidate_targets: tuple[str, ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, expression_kind, "", (), "target_transform_payload_missing")
    if expression_kind == "TargetPresentationOrderIgnored":
        return _inline_result(
            path,
            expression_kind,
            "",
            candidate_targets,
            "",
            [{
                "operation": "presentation_order_ignored",
                "original_kind": raw.payload["original_kind"],
                "presentation_key": raw.payload["presentation_key"],
            }],
        )
    if not candidate_targets and expression_kind not in {"TargetTake", "TargetIndex"}:
        return _inline_result(path, expression_kind, "", (), "")
    if expression_kind == "TargetReverse":
        return _inline_result(
            path,
            expression_kind,
            "",
            tuple(reversed(candidate_targets)),
            "",
            [{"operation": "reverse", "candidate_pool_before": list(candidate_targets)}],
        )
    if expression_kind in {"TargetTake", "TargetIndex"}:
        return _resolve_take_expression(
            candidate_targets,
            raw,
            expression_kind=expression_kind,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=path,
        )
    if expression_kind == "TargetMapAdjoinEntity":
        selected: tuple[str, ...] = ()
        for target_id in candidate_targets:
            result = relation_runtime.relations.resolve(
                state,
                "formation.adjacent",
                relation_runtime.context,
                subject_ids=(target_id,),
                options={"side": raw.adjacent_side, "counting_option": raw.adjacent_counting_option},
            )
            if result.blocked:
                return _inline_result(path, expression_kind, "", (), result.blocked_reason)
            selected = _dedupe((*selected, *result.target_ids))
        return _inline_result(path, expression_kind, "", selected, "")
    if expression_kind == "TargetMapAllTeamMember":
        result = relation_runtime.relations.resolve(
            state,
            "team.same",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={
                "allow_unselectable": raw.allow_unselectable,
                "include_limbo": relation_runtime.include_limbo,
            },
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetMapEnemyTeamEntity":
        result = relation_runtime.relations.resolve(
            state,
            "team.opposing",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={"include_limbo": relation_runtime.include_limbo},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetMapAllTeamMemberFromFirstEntity":
        relation = "team.opposing" if raw.select_enemy_team else "team.same"
        result = relation_runtime.relations.resolve(
            state,
            relation,
            relation_runtime.context,
            subject_ids=(candidate_targets[0],),
            options={"allow_unselectable": True, "include_limbo": True},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetMapCreator":
        selected: tuple[str, ...] = ()
        for target_id in candidate_targets:
            result = relation_runtime.relations.resolve(
                state,
                "entity.creator",
                relation_runtime.context,
                subject_ids=(target_id,),
            )
            if result.blocked:
                return _inline_result(path, expression_kind, "", (), result.blocked_reason)
            selected = _dedupe((*selected, *result.target_ids))
        return _inline_result(path, expression_kind, "", selected, "")
    if expression_kind == "TargetRemoveUnselectable":
        result = relation_runtime.relations.resolve(
            state,
            "lifecycle.filter",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={"mask": "Mask_AliveOnly", "require_targetable": True},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFilterAliveState":
        result = relation_runtime.relations.resolve(
            state,
            "lifecycle.filter",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={"mask": raw.alive_state_mask},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetFilterUnselectable":
        unselectable = relation_runtime.relations.resolve(
            state, "entity.unselectable", relation_runtime.context, subject_ids=candidate_targets
        )
        if unselectable.blocked:
            return _inline_result(path, expression_kind, "", (), unselectable.blocked_reason)
        unselectable_ids = frozenset(unselectable.target_ids)
        selected = tuple(target_id for target_id in candidate_targets
            if (target_id in unselectable_ids) is not raw.inverse)
        return _inline_result(path, expression_kind, "", selected, "")
    if expression_kind == "TargetFilterEntityType":
        relation = {"BattleEvent": "entity.battle_event", "Servant": "entity.servant"}.get(raw.entity_type_mask)
        if relation is None:
            return _inline_result(path, expression_kind, "", (), "target_entity_type_filter_invalid")
        typed = relation_runtime.relations.resolve(
            state, relation, relation_runtime.context, options={"mask": "Anyone"}
        )
        if typed.blocked:
            return _inline_result(path, expression_kind, "", (), typed.blocked_reason)
        typed_ids = frozenset(typed.target_ids)
        selected = [target_id for target_id in candidate_targets
            if (target_id in typed_ids) is not raw.inverse]
        return _inline_result(path, expression_kind, "", tuple(selected), "")
    if expression_kind == "TargetMapSummoner":
        result = relation_runtime.relations.resolve(
            state,
            "summon.summoner",
            relation_runtime.context,
            subject_ids=candidate_targets,
            options={"recursive": raw.recursive_summoner},
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetMapSummonedMinions":
        result = relation_runtime.relations.resolve(
            state, "summon.owned", relation_runtime.context, subject_ids=candidate_targets
        )
        return _inline_result(path, expression_kind, "", result.target_ids, result.blocked_reason)
    if expression_kind == "TargetShuffle":
        result = relation_runtime.random_sampler.resolve(
            _target_random_plan(
                state,
                raw,
                mode="shuffle",
                requested_count=len(candidate_targets),
                candidate_ids=candidate_targets,
                path=path,
                event_payload=event_payload,
                relation_runtime=relation_runtime,
            ),
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
        )
        if not result.resolved:
            return _inline_result(
                path,
                expression_kind,
                "",
                (),
                result.blocked_reason,
                [{"operation": "target_random", "result": result.to_json()}],
            )
        return _inline_result(
            path,
            expression_kind,
            "",
            result.selected_ids,
            "",
            [{"operation": "target_random", "result": result.to_json()}],
            result.rng_events,
        )
    if expression_kind.startswith("TargetSort"):
        return _resolve_sort_expression(state, candidate_targets, raw, expression_kind=expression_kind, path=path)
    return _inline_result(path, expression_kind, "", (), f"target_transform_not_supported:{expression_kind}")


def _resolve_target_alias_resolution(
    state: BattleState,
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
    relation_runtime: _TargetRelationRuntime,
) -> _ExpressionResolution:
    if not alias:
        return _inline_result(path, "TargetAlias", "", (), "target_alias_missing")
    if alias in relation_runtime.alias_stack:
        return _inline_result(path, "TargetAlias", alias, (), f"target_alias_cycle:{alias}")
    if alias.startswith("(") and ")." in alias:
        closing = alias.find(").")
        inner_alias = alias[1:closing]
        operations = tuple(alias[closing + 2:].split("."))
        if not _safe_set_alias(inner_alias) or any(not item for item in operations):
            return _inline_result(path, "TargetAlias", alias, (), "target_alias_group_syntax_invalid")
        base = _resolve_target_alias_resolution(
            state,
            inner_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=f"{path}.alias_group",
            relation_runtime=relation_runtime.entering_alias(alias),
        )
        if base.blocked_reason:
            return _inline_result(path, "TargetAlias", alias, (), base.blocked_reason, base.steps, base.rng_events)
        current = base.target_ids
        steps = list(base.steps)
        rng_events = list(base.rng_events)
        for index, operation_name in enumerate(operations):
            definition = relation_runtime.operation_definitions.get(operation_name)
            if operation_name in relation_runtime.ambiguous_definition_names or definition is None:
                return _inline_result(path, "TargetAlias", alias, (), f"target_operation_definition_missing:{operation_name}", steps)
            if definition.coverage_status != "executable" or definition.node is None:
                return _inline_result(path, "TargetAlias", alias, (), definition.blocked_reason or f"target_operation_definition_blocked:{operation_name}", steps)
            operation_context = replace(relation_runtime.context, parameter_entity_ids=current)
            result = _resolve_inline_expression(
                state,
                definition.node,
                expression_kind=definition.expression_kind,
                alias=definition.alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=operation_context.parameter_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=current,
                path=f"{path}.alias_group_op[{index}]",
                relation_runtime=replace(
                    relation_runtime.entering_alias(alias), context=operation_context,
                    definition_source_path=definition.source.source_path,
                ),
            )
            steps.extend(result.steps)
            rng_events.extend(result.rng_events)
            if result.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), result.blocked_reason, steps, tuple(rng_events))
            current = result.target_ids
        return _inline_result(path, "TargetAlias", alias, current, "", steps, tuple(rng_events))
    parsed_set = _safe_set_alias(alias)
    if parsed_set:
        steps: list[JSONValue] = []
        selected: tuple[str, ...] = ()
        for index, (operator, child_alias) in enumerate(parsed_set):
            child = _resolve_target_alias_resolution(
                state,
                child_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                path=f"{path}.alias_set[{index}]",
                relation_runtime=relation_runtime.entering_alias(alias),
            )
            steps.extend(child.steps)
            if child.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), child.blocked_reason, steps)
            if index == 0 or operator in {"+", "|"}:
                selected = _dedupe((*selected, *child.target_ids))
            elif operator == "-":
                remove = set(child.target_ids)
                selected = tuple(target_id for target_id in selected if target_id not in remove)
            steps.append(
                {
                    "operation": "alias_set",
                    "operator": operator,
                    "operand_alias": child_alias,
                    "operand_targets": list(child.target_ids),
                    "selected_targets": list(selected),
                }
            )
        if not selected:
            return _inline_result(path, "TargetAlias", alias, (), "", steps)
        return _inline_result(path, "TargetAlias", alias, selected, "", steps)

    if "." in alias:
        parts = tuple(alias.split("."))
        if any(not part for part in parts):
            return _inline_result(path, "TargetAlias", alias, (), "target_alias_dot_syntax_invalid")
        base_alias, operations = parts[0], parts[1:]
        base = _resolve_target_alias_resolution(
            state,
            base_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            path=f"{path}.alias_base",
            relation_runtime=relation_runtime.entering_alias(alias),
        )
        steps = list(base.steps)
        rng_events = list(base.rng_events)
        if base.blocked_reason:
            return _inline_result(path, "TargetAlias", alias, (), base.blocked_reason, steps)
        current = base.target_ids
        for index, operation_name in enumerate(operations):
            if operation_name in relation_runtime.ambiguous_definition_names:
                return _inline_result(
                    path, "TargetAlias", alias, (),
                    f"target_language_definition_name_ambiguous:{operation_name}", steps,
                )
            definition = relation_runtime.operation_definitions.get(operation_name)
            if definition is None:
                return _inline_result(
                    path, "TargetAlias", alias, (),
                    f"target_operation_definition_missing:{operation_name}", steps,
                )
            if definition.coverage_status != "executable" or definition.node is None:
                return _inline_result(
                    path, "TargetAlias", alias, (),
                    definition.blocked_reason or f"target_operation_definition_blocked:{operation_name}", steps,
                )
            operation_context = replace(
                relation_runtime.context,
                parameter_entity_ids=current,
            )
            result = _resolve_inline_expression(
                state,
                definition.node,
                expression_kind=definition.expression_kind,
                alias=definition.alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=operation_context.parameter_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                previous_targets=current,
                path=f"{path}.alias_op[{index}]",
                relation_runtime=replace(
                    relation_runtime.entering_alias(alias),
                    context=operation_context,
                    definition_source_path=definition.source.source_path,
                ),
            )
            steps.extend(result.steps)
            rng_events.extend(result.rng_events)
            if result.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), result.blocked_reason, steps, tuple(rng_events))
            current = result.target_ids
        return _inline_result(path, "TargetAlias", alias, current, "", steps, tuple(rng_events))
    if alias in relation_runtime.ambiguous_definition_names:
        return _inline_result(
            path, "TargetAlias", alias, (),
            f"target_language_definition_name_ambiguous:{alias}",
        )
    definition = relation_runtime.scoped_alias_definitions.get(
        (relation_runtime.definition_source_path, alias)
    ) or relation_runtime.alias_definitions.get(alias)
    if definition is None:
        return _inline_result(
            path, "TargetAlias", alias, (), f"target_alias_definition_missing:{alias}"
        )
    if definition.coverage_status != "executable" or definition.node is None:
        return _inline_result(
            path,
            "TargetAlias",
            alias,
            (),
            definition.blocked_reason or f"target_alias_definition_blocked:{alias}",
        )
    return _resolve_inline_expression(
        state,
        definition.node,
        expression_kind=definition.expression_kind,
        alias=definition.alias,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        previous_targets=(),
        path=f"{path}.alias_definition[{alias}]",
        relation_runtime=replace(
            relation_runtime.entering_alias(alias),
            definition_source_path=definition.source.source_path,
        ),
    )


def _validated_target_result(
    state: BattleState,
    path: str,
    expression_kind: str,
    target_ids: tuple[str, ...],
    operation: str,
    *,
    allow_defeated: bool = False,
    metadata: dict[str, JSONValue] | None = None,
) -> _ExpressionResolution:
    selected: list[str] = []
    skipped: list[JSONValue] = []
    lifecycle = UnitLifecycleSystem()
    for target_id in target_ids:
        if target_id not in state.units:
            skipped.append({"target_id": target_id, "reason": "unit_missing"})
            continue
        ok, reason = lifecycle.can_target(state, target_id, allow_defeated=allow_defeated)
        if not ok:
            skipped.append({"target_id": target_id, "reason": reason})
            continue
        selected.append(target_id)
    step = {
        "operation": operation,
        "candidate_pool_before": list(target_ids),
        "selected_targets": selected,
        "skipped_targets": skipped,
        "allow_defeated": allow_defeated,
    }
    if metadata:
        step.update(metadata)
    if skipped:
        return _inline_result(path, expression_kind, "", (), f"target_lifecycle_blocked:{operation}", [step])
    if not selected:
        return _inline_result(path, expression_kind, "", (), f"target_candidates_empty:{operation}", [step])
    return _inline_result(path, expression_kind, "", _dedupe(tuple(selected)), "", [step])


def _resolve_sort_expression(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    payload: Any,
    *,
    expression_kind: str,
    path: str,
) -> _ExpressionResolution:
    values: dict[str, float] = {}
    skipped: list[JSONValue] = []
    sort_key = ""
    if expression_kind == "TargetSortByProperty":
        sort_key = payload.sort_key
        value_getter = _property_sort_value
    elif expression_kind == "TargetSortByPropertyRatio":
        sort_key = payload.sort_key
        value_getter = _property_ratio_sort_value
    elif expression_kind == "TargetSortByFormation":
        sort_key = "formation_position"
        value_getter = _formation_sort_value
    elif expression_kind == "TargetSortByBreakDamageAddedRatio":
        sort_key = "break_damage_added_ratio"
        value_getter = _break_damage_added_ratio_sort_value
    elif expression_kind == "TargetSortMonsterRank":
        sort_key = "monster_rank_score"
        rank_scores = state.global_flags.get("monster_rank_scores")
        if not isinstance(rank_scores, dict) or not rank_scores:
            return _inline_result(path, expression_kind, "", (), "monster_rank_scores_missing")
        maximum = rank_scores.get(payload.max_rank) if payload.max_rank else None
        if payload.max_rank and (
            isinstance(maximum, bool) or not isinstance(maximum, (int, float))
            or not math.isfinite(float(maximum))
        ):
            return _inline_result(path, expression_kind, "", (), "monster_rank_maximum_missing")
        value_getter = lambda unit, key: _monster_rank_sort_value(
            unit, key, maximum=float(maximum) if maximum is not None else None
        )
    elif expression_kind == "TargetSortByModifierValue":
        sort_key = f"modifier_value:{payload.modifier_name}:{payload.value_type}"
        value_getter = lambda unit, _key: _modifier_value_sort_value(
            unit, payload.modifier_name, payload.value_type
        )
    elif expression_kind == "TargetSortByModifierStatusCount":
        sort_key = f"modifier_status_count:{payload.buff_status}"
        value_getter = lambda unit, _key: _modifier_status_count_sort_value(
            unit, payload.buff_status
        )
    elif expression_kind == "TargetSortByActionOrder":
        sort_key = "action_value"
        value_getter = lambda unit, _key: (float(unit.action_value), "")
    else:
        return _inline_result(path, expression_kind, "", (), f"target_sort_not_supported:{expression_kind}")
    for target_id in candidate_targets:
        unit = state.units.get(target_id)
        if unit is None:
            skipped.append({"target_id": target_id, "reason": "unit_missing"})
            continue
        value, reason = value_getter(unit, sort_key)
        if not reason and not math.isfinite(value):
            reason = "sort_value_not_finite"
        if reason:
            skipped.append({"target_id": target_id, "reason": reason})
            continue
        values[target_id] = value
    step = {
        "operation": "target_sort",
        "sort_kind": expression_kind,
        "sort_key": sort_key,
        "candidate_pool_before": list(candidate_targets),
        "sort_values": values,
        "skipped_targets": skipped,
        "tie_breaker": "source_order_then_unit_id",
    }
    if skipped:
        return _inline_result(path, expression_kind, "", (), f"target_sort_value_blocked:{sort_key or 'missing'}", [step])
    if not values:
        return _inline_result(path, expression_kind, "", (), "target_sort_candidate_missing", [step])
    highest_first = payload.highest_first
    step["direction"] = "desc" if highest_first else "asc"
    source_order = {target_id: index for index, target_id in enumerate(candidate_targets)}
    ordered = tuple(
        sorted(
            candidate_targets,
            key=lambda target_id: (
                -values[target_id] if highest_first else values[target_id],
                source_order[target_id],
                target_id,
            ),
        )
    )
    step["selected_targets"] = list(ordered)
    return _inline_result(path, expression_kind, "", ordered, "", [step])


def _monster_rank_sort_value(
    unit: Any, _sort_key: str, *, maximum: float | None
) -> tuple[float, str]:
    value = unit.flags.get("monster_rank_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0, "monster_rank_score_missing"
    numeric = float(value)
    return min(numeric, maximum) if maximum is not None else numeric, ""


def _validated_status_details_for_sort(unit: Any) -> tuple[tuple[dict[str, JSONValue], ...], str]:
    raw_details = unit.flags.get("status_details", ())
    if not isinstance(raw_details, (list, tuple)):
        return (), "status_details_invalid"
    details: list[dict[str, JSONValue]] = []
    for detail in raw_details:
        if not isinstance(detail, dict):
            return (), "status_detail_invalid"
        details.append(detail)
    return tuple(details), ""


def _modifier_value_sort_value(unit: Any, modifier_name: str, value_type: str) -> tuple[float, str]:
    if value_type not in {"", "Layer"}:
        return 0.0, f"modifier_value_type_not_supported:{value_type}"
    details, reason = _validated_status_details_for_sort(unit)
    if reason:
        return 0.0, reason
    value = 0.0
    for detail in details:
        if detail.get("modifier_name") != modifier_name:
            continue
        stacks = detail.get("stacks")
        if isinstance(stacks, bool) or not isinstance(stacks, (int, float)):
            return 0.0, "modifier_stack_invalid"
        value += float(stacks)
    return value, ""


def _modifier_status_count_sort_value(unit: Any, buff_status: str) -> tuple[float, str]:
    details, reason = _validated_status_details_for_sort(unit)
    if reason:
        return 0.0, reason
    expected = buff_status.lower()
    count = 0
    for detail in details:
        status_type = detail.get("status_type", "")
        status_category = detail.get("status_category", "")
        if not isinstance(status_type, str) or not isinstance(status_category, str):
            return 0.0, "modifier_status_type_invalid"
        if not status_type and not status_category:
            return 0.0, "modifier_status_type_missing"
        if expected in {status_type.lower(), status_category.lower()}:
            count += 1
    return float(count), ""


def _property_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    if sort_key == "CurrentHP":
        return float(unit.hp), ""
    if sort_key == "MaxHP":
        if unit.max_hp <= 0:
            return 0.0, "max_hp_non_positive"
        return float(unit.max_hp), ""
    if sort_key == "CurrentStance":
        return float(unit.toughness), ""
    if sort_key == "MaxStance":
        if unit.max_toughness <= 0:
            return 0.0, "max_toughness_non_positive"
        return float(unit.max_toughness), ""
    if sort_key == "Shield":
        return sum(float(item["remaining"]) for item in unit.shield_instances), ""
    if sort_key == "BreakDamageAddedRatio":
        return _break_damage_added_ratio_sort_value(unit, sort_key)
    return 0.0, f"target_sort_property_not_admitted:{sort_key or 'missing'}"


def _property_ratio_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    if sort_key == "HPRatio":
        if unit.max_hp <= 0:
            return 0.0, "max_hp_non_positive"
        return float(unit.hp) / float(unit.max_hp), ""
    if sort_key == "StanceRatio":
        if unit.max_toughness <= 0:
            return 0.0, "max_toughness_non_positive"
        return float(unit.toughness) / float(unit.max_toughness), ""
    return 0.0, f"target_sort_ratio_not_admitted:{sort_key or 'missing'}"


def _formation_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    position = _position(unit.flags.get("position"))
    if position is None:
        return 0.0, "target_position_missing"
    return float(position), ""


def _break_damage_added_ratio_sort_value(unit: Any, sort_key: str) -> tuple[float, str]:
    for source in (getattr(unit, "resources", {}), getattr(unit, "flags", {})):
        if not isinstance(source, dict):
            continue
        for key in ("break_damage_added_ratio", "break_damage_added", "break_damage_bonus_ratio"):
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value), ""
    return 0.0, "break_damage_added_ratio_missing"


def _resolve_take_expression(
    candidate_targets: tuple[str, ...],
    payload: Any,
    *,
    expression_kind: str,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    path: str,
) -> _ExpressionResolution:
    if expression_kind == "TargetTake":
        count, numeric_step, reason = _positive_int_from_numeric(
            payload.count_expr or None,
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace={"target_expression_path": path, "field": "Count"},
            missing_default=None,
        )
        if reason:
            return _inline_result(path, expression_kind, "", (), f"target_take_count_blocked:{reason}", [numeric_step])
        selected = candidate_targets[:count]
        return _inline_result(
            path,
            expression_kind,
            "",
            selected,
            "",
            [{"operation": "target_take", "count": count, "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected), "numeric_evaluation": numeric_step}],
        )
    index_type = payload.index_type or "IndexStrict"
    if index_type == "Last":
        index = len(candidate_targets) - 1
        numeric_step = {"operation": "target_index", "index_type": index_type, "index": index}
    elif index_type == "First":
        index = 0
        numeric_step = {"operation": "target_index", "index_type": index_type, "index": index}
    else:
        index_value = payload.index_expr
        if not index_value:
            index = 0
            numeric_step = {"operation": "target_index", "index_type": index_type, "index": index, "index_source": "tbgd_select1_default_zero"}
        else:
            index, numeric_step, reason = _non_negative_int_from_numeric(
                index_value,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
                source_trace={"target_expression_path": path, "field": "IndexValue"},
            )
            if reason:
                return _inline_result(path, expression_kind, "", (), f"target_index_blocked:{reason}", [numeric_step])
    if not candidate_targets:
        return _inline_result(
            path,
            expression_kind,
            "",
            (),
            "",
            [numeric_step],
        )
    if index < 0 or index >= len(candidate_targets):
        return _inline_result(path, expression_kind, "", (), "target_index_out_of_range", [numeric_step])
    selected = (candidate_targets[index],)
    return _inline_result(
        path,
        expression_kind,
        "",
        selected,
        "",
        [{"operation": "target_index", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected), "index": index, "index_type": index_type, "numeric_evaluation": numeric_step}],
    )


def _positive_int_from_numeric(
    value: JSONValue,
    *,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
    missing_default: int | None,
) -> tuple[int, dict[str, JSONValue], str]:
    if value is None and missing_default is not None:
        return missing_default, {"operation": "numeric_default", "value": missing_default, "source_trace": source_trace}, ""
    result = RuleEvaluator().evaluate_numeric(
        value,
        NumericEvaluationContext(
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace=source_trace,
        ),
    )
    step = {"operation": "numeric_evaluation", "numeric_evaluation": result.to_json()}
    if not result.ok or result.value is None:
        return 0, step, result.blocked_reason or "numeric_not_executable"
    if not math.isfinite(float(result.value)) or int(result.value) != float(result.value) or result.value <= 0:
        return 0, step, "numeric_not_positive_integer"
    return int(result.value), step, ""


def _non_negative_int_from_numeric(
    value: JSONValue,
    *,
    dynamic_values: dict[str, float] | None,
    binding_sources: tuple[dict[str, JSONValue], ...],
    source_trace: dict[str, JSONValue],
) -> tuple[int, dict[str, JSONValue], str]:
    result = RuleEvaluator().evaluate_numeric(
        value,
        NumericEvaluationContext(
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
            source_trace=source_trace,
        ),
    )
    step = {"operation": "numeric_evaluation", "numeric_evaluation": result.to_json()}
    if not result.ok or result.value is None:
        return 0, step, result.blocked_reason or "numeric_not_executable"
    if not math.isfinite(float(result.value)) or int(result.value) != float(result.value) or result.value < 0:
        return 0, step, "numeric_not_non_negative_integer"
    return int(result.value), step, ""


def _safe_set_alias(alias: str) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    operator = "+"
    current: list[str] = []
    for ch in alias:
        if ch in {"+", "|", "-"}:
            operand = "".join(current).strip()
            if not operand:
                return ()
            parsed.append((operator, operand))
            operator = ch
            current = []
            continue
        current.append(ch)
    operand = "".join(current).strip()
    if not operand:
        return ()
    parsed.append((operator, operand))
    return tuple(parsed) if len(parsed) >= 2 else ()


def _inline_expression_kind(raw: TargetExpressionNodeIR | None) -> str:
    return raw.expression_kind if raw is not None else ""


def _inline_target_alias(raw: TargetExpressionNodeIR | None) -> str:
    return raw.alias if raw is not None else ""


def _inline_children(
    raw: TargetExpressionNodeIR | None,
    expression_kind: str,
) -> tuple[TargetExpressionNodeIR, ...]:
    if raw is None or raw.expression_kind != expression_kind:
        return ()
    return raw.children


def _dedupe(target_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target_ids))


def _fixed_positive_int(value: JSONValue) -> int | None:
    fixed = numeric_fixed_value(value)
    if fixed is not None and fixed > 0 and fixed.is_integer():
        return int(fixed)
    return None


def _inline_result(
    path: str,
    expression_kind: str,
    alias: str,
    target_ids: tuple[str, ...],
    blocked_reason: str,
    steps: list[JSONValue] | None = None,
    rng_events: tuple[RNGEvent, ...] = (),
) -> _ExpressionResolution:
    step: dict[str, JSONValue] = {
        "path": path,
        "expression_kind": expression_kind,
        "alias": alias,
        "target_ids": list(target_ids),
        "blocked_reason": blocked_reason,
    }
    return _ExpressionResolution(
        target_ids=target_ids,
        blocked_reason=blocked_reason,
        steps=[*(steps or []), step],
        rng_events=rng_events,
    )


def _position(value: JSONValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
