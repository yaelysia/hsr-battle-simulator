from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any

from ..core.model import BattleState, JSONValue, RNGEvent, TargetResolution
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
from ..rules.ir import ConditionIR, TargetExpressionIR, TargetExpressionNodeIR
from ..unit_eligibility import runtime_unit_is_unselectable
from .rng import (
    RNGOutcome,
    RNGRequest,
    choice_key_for_identity,
    resolve_rng_request,
    rng_choices_from_payload,
    rng_mode_from_payload,
)
from .unit_relation import is_dark_team, is_light_team, is_opposing_combat_team, is_same_combat_team
from .unit_lifecycle import UnitLifecycleSystem
from .unit_stats import effective_unit_stat


SUPPORTED_SUMMON_RUNTIME_SCHEMA_VERSIONS = {"p1_3_summon_runtime_v1", "p3_summon_runtime_v2"}


@dataclass(frozen=True)
class TargetingResult:
    resolution: TargetResolution
    ok: bool
    errors: tuple[str, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()


@dataclass(frozen=True)
class BounceTargetResult:
    ok: bool
    target_id: str = ""
    rng_event: RNGEvent | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class TargetPolicy:
    policy_id: str = "enemy"
    allow_enemy: bool = True
    allow_ally: bool = False
    allow_self: bool = False
    allow_defeated: bool = False
    target_mode: str = "single"
    selection_mode: str = "explicit"
    target_relation: str = "unknown"
    selection_min: int = 1
    selection_max: int = 1
    impact_mode: str = "primary_only"
    allow_off_field: bool = False
    bounce_policy: dict[str, JSONValue] = field(default_factory=dict)
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetEnumerationResult:
    ok: bool
    selectable_target_ids: tuple[str, ...] = ()
    auto_target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    policy: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "selectable_target_ids": list(self.selectable_target_ids),
            "auto_target_ids": list(self.auto_target_ids),
            "blocked_reason": self.blocked_reason,
            "policy": self.policy,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class TargetExpressionResult:
    ok: bool
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    expression_id: str = ""
    expression_kind: str = ""
    alias: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    rng_events: tuple[RNGEvent, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "target_ids": list(self.target_ids),
            "blocked_reason": self.blocked_reason,
            "expression_id": self.expression_id,
            "expression_kind": self.expression_kind,
            "alias": self.alias,
            "metadata": self.metadata,
            "rng_events": [event.to_json() for event in self.rng_events],
        }


class TargetSystem:
    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

    def resolve_target_expression(
        self,
        state: BattleState,
        expression: TargetExpressionIR,
        *,
        caster_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        target_resolution: TargetResolution | None = None,
        event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> TargetExpressionResult:
        metadata: dict[str, JSONValue] = {
            "target_expression": expression.to_json(),
            "caster_id": caster_id,
            "owner_id": owner_id,
            "param_entity_id": param_entity_id,
            "current_action_target_id": current_action_target_id,
            "target_resolution": target_resolution.to_json() if target_resolution else None,
            "event_payload": event_payload or {},
        }
        if expression.coverage_status != "executable":
            reason = expression.blocked_reason or f"target_expression_not_executable:{expression.coverage_status}"
            return TargetExpressionResult(
                ok=False,
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
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload or {},
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        metadata["resolution_steps"] = result.steps
        if result.blocked_reason:
            return TargetExpressionResult(
                ok=False,
                blocked_reason=result.blocked_reason,
                expression_id=expression.target_expression_id,
                expression_kind=expression.expression_kind,
                alias=expression.alias,
                metadata=metadata,
                rng_events=result.rng_events,
            )
        return TargetExpressionResult(
            ok=True,
            target_ids=result.target_ids,
            expression_id=expression.target_expression_id,
            expression_kind=expression.expression_kind,
            alias=expression.alias,
            metadata=metadata,
            rng_events=result.rng_events,
        )

    def resolve_expression_node(
        self,
        state: BattleState,
        node: TargetExpressionNodeIR,
        *,
        caster_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        target_resolution: TargetResolution | None = None,
        event_payload: dict[str, JSONValue] | None = None,
        dynamic_values: dict[str, float] | None = None,
        binding_sources: tuple[dict[str, JSONValue], ...] = (),
    ) -> TargetExpressionResult:
        """Resolve an already-typed inline node for condition consumers."""

        result = _resolve_expression_payload(
            state,
            node,
            expression_kind=node.expression_kind,
            alias=node.alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload or {},
            dynamic_values=dynamic_values,
            binding_sources=binding_sources,
        )
        metadata: dict[str, JSONValue] = {
            "target_expression_node": node.to_json(),
            "resolution_steps": result.steps,
        }
        if result.blocked_reason:
            return TargetExpressionResult(
                ok=False,
                blocked_reason=result.blocked_reason,
                expression_kind=node.expression_kind,
                alias=node.alias,
                metadata=metadata,
                rng_events=result.rng_events,
            )
        return TargetExpressionResult(
            ok=True,
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
        caster_id: str,
        owner_id: str | None = None,
        param_entity_id: str | None = None,
        current_action_target_id: str | None = None,
        event_payload: dict[str, JSONValue] | None = None,
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
            result = self.resolve_expression_node(
                state,
                node,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                event_payload=event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            )
            if result.ok:
                resolved[key] = result.target_ids
            else:
                errors[key] = result.blocked_reason
        return resolved, errors

    def enumerate_action_targets(
        self,
        state: BattleState,
        actor_id: str,
        policy: TargetPolicy | None = None,
    ) -> TargetEnumerationResult:
        policy = policy or TargetPolicy()
        actor = state.units.get(actor_id)
        policy_payload = _policy_metadata(policy)
        if actor is None:
            return TargetEnumerationResult(
                ok=False,
                blocked_reason="unknown_actor",
                policy=policy_payload,
                metadata={"actor_id": actor_id},
            )
        blocked_reason = _target_mode_blocked_reason(policy)
        if blocked_reason:
            return TargetEnumerationResult(
                ok=False,
                blocked_reason=blocked_reason,
                policy=policy_payload,
                metadata={"actor_id": actor_id},
            )
        candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if _targetability_reason(state, unit_id, policy, self.lifecycle) == ""
            and _policy_allows(actor_id, actor, unit_id, unit, policy)
        )
        if policy.selection_max == 0:
            auto_targets = candidates
            if not auto_targets:
                return TargetEnumerationResult(
                    ok=False,
                    blocked_reason="target_candidates_empty",
                    policy=policy_payload,
                    metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
                )
            return TargetEnumerationResult(
                ok=True,
                auto_target_ids=auto_targets,
                policy=policy_payload,
                metadata=_target_enumeration_metadata(
                    state,
                    actor_id,
                    auto_targets,
                    policy.target_mode,
                ),
            )
        if policy.selection_min == 1 and policy.selection_max == 1:
            selectable = candidates
            if not selectable:
                return TargetEnumerationResult(
                    ok=False,
                    blocked_reason="target_candidates_empty",
                    policy=policy_payload,
                    metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
                )
            return TargetEnumerationResult(
                ok=True,
                selectable_target_ids=selectable,
                policy=policy_payload,
                metadata=_target_enumeration_metadata(
                    state,
                    actor_id,
                    selectable,
                    policy.target_mode,
                ),
            )
        return TargetEnumerationResult(
            ok=False,
            blocked_reason=f"unsupported_target_mode:{policy.target_mode}",
            policy=policy_payload,
            metadata={"actor_id": actor_id, "target_mode": policy.target_mode},
        )

    def resolve_action_targets(
        self,
        state: BattleState,
        actor_id: str,
        target_ids: tuple[str, ...],
        policy: TargetPolicy | None = None,
    ) -> TargetingResult:
        policy = policy or TargetPolicy()
        requested = target_ids
        enumeration = self.enumerate_action_targets(state, actor_id, policy)
        if not enumeration.ok:
            resolution = TargetResolution(
                requested=requested,
                selectable=enumeration.selectable_target_ids,
                rejected=requested,
                reason=enumeration.blocked_reason,
                metadata={
                    "policy": _policy_metadata(policy),
                    "target_groups": {},
                    "blocked_reason": enumeration.blocked_reason,
                },
            )
            return TargetingResult(
                resolution=resolution,
                ok=False,
                errors=(enumeration.blocked_reason,),
            )
        blocked_reason = _target_mode_blocked_reason(policy)
        if blocked_reason:
            resolution = TargetResolution(
                requested=requested,
                selectable=enumeration.selectable_target_ids,
                selected=(),
                rejected=requested,
                reason=blocked_reason,
                source="target_system",
                metadata={
                    "policy": _policy_metadata(policy),
                    "target_groups": {},
                    "blocked_reason": blocked_reason,
                },
            )
            return TargetingResult(resolution=resolution, ok=False, errors=(blocked_reason,))
        if policy.selection_max == 0:
            if requested:
                reason = "auto_target_mode_rejects_explicit_targets"
                return TargetingResult(
                    resolution=TargetResolution(
                        requested=requested,
                        impact_group=(),
                        rejected=requested,
                        reason=reason,
                        metadata={
                            "policy": _policy_metadata(policy),
                            "target_groups": {},
                            "blocked_reason": reason,
                        },
                    ),
                    ok=False,
                    errors=(reason,),
                )
            impact_group = enumeration.auto_target_ids
            target_groups = {"selected": impact_group, "impact": impact_group}
            return TargetingResult(
                resolution=TargetResolution(
                    requested=(),
                    selectable=(),
                    legal=(),
                    primary=None,
                    impact_group=impact_group,
                    selected=impact_group,
                    reason="action_targets_resolved",
                    metadata={
                        "policy": _policy_metadata(policy),
                        "target_groups": {
                            key: list(value) for key, value in sorted(target_groups.items())
                        },
                    },
                ),
                ok=True,
            )
        explicit = self.resolve_explicit_targets(state, actor_id, requested, policy=policy)
        if not explicit.ok:
            return replace(
                explicit,
                resolution=replace(
                    explicit.resolution,
                    selectable=enumeration.selectable_target_ids,
                ),
            )
        primary = explicit.resolution.legal[0]
        target_groups = _target_groups(state, actor_id, primary, policy)
        impact_group = target_groups.get("impact", target_groups.get("selected", ()))
        resolution = TargetResolution(
            requested=requested,
            selectable=enumeration.selectable_target_ids,
            legal=explicit.resolution.legal,
            primary=primary,
            impact_group=impact_group,
            selected=impact_group,
            rejected=explicit.resolution.rejected,
            reason="action_targets_resolved",
            source="target_system",
            metadata={
                **explicit.resolution.metadata,
                "target_groups": {key: list(value) for key, value in sorted(target_groups.items())},
            },
        )
        return TargetingResult(resolution=resolution, ok=True)

    def resolve_explicit_targets(
        self,
        state: BattleState,
        actor_id: str,
        target_ids: tuple[str, ...],
        policy: TargetPolicy | None = None,
    ) -> TargetingResult:
        policy = policy or TargetPolicy()
        errors: list[str] = []
        legal: list[str] = []
        rejected: list[str] = []
        metadata: dict[str, JSONValue] = {"policy": _policy_metadata(policy)}

        actor = state.units.get(actor_id)
        if actor is None:
            errors.append(f"unknown actor_id: {actor_id}")
            rejected.extend(target_ids)
            return TargetingResult(
                resolution=TargetResolution(
                    requested=target_ids,
                    legal=(),
                    selected=(),
                    rejected=tuple(rejected),
                    reason="unknown_actor",
                    source="target_system",
                    metadata={"errors": list(errors)},
                ),
                ok=False,
                errors=tuple(errors),
            )

        cardinality_reason = _selection_cardinality_blocked_reason(target_ids, policy)
        if cardinality_reason:
            return TargetingResult(
                resolution=TargetResolution(
                    requested=target_ids,
                    rejected=target_ids,
                    reason=cardinality_reason,
                    source="target_system",
                    metadata={
                        "policy": _policy_metadata(policy),
                        "errors": [cardinality_reason],
                    },
                ),
                ok=False,
                errors=(cardinality_reason,),
            )

        for target_id in target_ids:
            target = state.units.get(target_id)
            if target is None:
                reason = f"unknown:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            targetability_reason = _targetability_reason(
                state,
                target_id,
                policy,
                self.lifecycle,
            )
            if targetability_reason:
                reason = f"{targetability_reason}:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            if not _policy_allows(actor_id, actor, target_id, target, policy):
                reason = f"policy_rejected:{policy.policy_id}:{target_id}"
                errors.append(reason)
                rejected.append(target_id)
                continue
            legal.append(target_id)

        ok = not errors
        if errors:
            metadata["errors"] = list(errors)
        return TargetingResult(
            resolution=TargetResolution(
                requested=target_ids,
                legal=tuple(legal),
                selected=tuple(legal),
                rejected=tuple(rejected),
                reason="explicit_targets_resolved" if ok else "explicit_targets_rejected",
                source="target_system",
                metadata=metadata,
            ),
            ok=ok,
            errors=tuple(errors),
        )

    def enemies_of(self, state: BattleState, actor_id: str, *, allow_defeated: bool = False) -> tuple[str, ...]:
        actor = state.units[actor_id]
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit) and self.lifecycle.can_target(state, unit_id, allow_defeated=allow_defeated)[0]
        )

    def resolve_bounce_hit_target(
        self,
        state: BattleState,
        *,
        actor_id: str,
        primary_target_id: str,
        bounce_policy: dict[str, JSONValue],
        hit_index: int,
        previous_hit_targets: tuple[str, ...],
        action_id: str,
        action_level: int,
        event_payload: dict[str, JSONValue] | None = None,
    ) -> BounceTargetResult:
        actor = state.units.get(actor_id)
        if actor is None:
            return BounceTargetResult(ok=False, error="unknown_actor")
        if str(bounce_policy.get("coverage_status") or "") != "executable":
            return BounceTargetResult(ok=False, error="bounce_policy_not_executable", metadata={"bounce_policy": bounce_policy})
        live_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit) and self.lifecycle.can_target(state, unit_id)[0]
        )
        all_candidates = tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            if is_opposing_combat_team(actor, unit)
        )
        selection_strategy = str(bounce_policy.get("selection_strategy") or "")
        candidate_pool = live_candidates
        candidate_pool_reason = "live_targets"
        if live_candidates and selection_strategy == "prefer_unhit_then_random":
            unhit = tuple(unit_id for unit_id in live_candidates if unit_id not in set(previous_hit_targets))
            if unhit:
                candidate_pool = unhit
                candidate_pool_reason = "live_unhit_targets"
        if not candidate_pool:
            if not bool(bounce_policy.get("continue_on_all_defeated")):
                return BounceTargetResult(
                    ok=False,
                    error="bounce_no_live_target_and_continuation_not_admitted",
                    metadata={"bounce_policy": bounce_policy},
                )
            candidate_pool = all_candidates or (primary_target_id,)
            candidate_pool_reason = "all_targets_defeated_continue_sequence"
        event_id = f"rng:{state.event_index}:{actor_id}:{action_id}:{action_level}:bounce:{hit_index}"
        outcomes = tuple(
            RNGOutcome(
                outcome_id=str(unit_id),
                payload={
                    "selected_target_id": unit_id,
                    "selected_index": index,
                    "candidate_pool": list(candidate_pool),
                    "candidate_pool_reason": candidate_pool_reason,
                    "hit_index": hit_index,
                    "selection_strategy": selection_strategy,
                    "live_target_priority": bool(bounce_policy.get("live_target_priority")),
                    "continue_on_all_defeated": bool(bounce_policy.get("continue_on_all_defeated")),
                    "previous_hit_targets": list(previous_hit_targets),
                    "bounce_policy_id": str(bounce_policy.get("bounce_policy_id") or ""),
                    "value": unit_id,
                },
                weight=1.0,
            )
            for index, unit_id in enumerate(candidate_pool)
        )
        identity = {
            "decision_scope": "bounce_target",
            "decision_index": hit_index,
            "action_id": action_id,
            "action_level": action_level,
            "task_id": str(bounce_policy.get("source_task_id") or "bounce_policy"),
            "hit_index": hit_index,
            "target_id": primary_target_id,
            "derived_event_id": event_id,
        }
        request = RNGRequest(
            rng_type="bounce_target",
            purpose="bounce_target",
            event_id=event_id,
            choice_key=choice_key_for_identity("bounce_target", identity),
            source="target_system",
            before_state=state.rng_state,
            decision_kind="choice",
            outcomes=outcomes,
            source_trace=bounce_policy.get("source", {}) if isinstance(bounce_policy.get("source"), dict) else {},
            metadata={
                "actor_id": actor_id,
                "action_id": action_id,
                "action_level": action_level,
                "primary_target_id": primary_target_id,
                "candidate_pool": list(candidate_pool),
                "candidate_pool_reason": candidate_pool_reason,
                "previous_hit_targets": list(previous_hit_targets),
            },
            invalid_choice_reason="bounce_target_choice_invalid",
            identity=identity,
        )
        resolution = resolve_rng_request(
            request,
            rng_choices=rng_choices_from_payload(event_payload),
            rng_mode=rng_mode_from_payload(event_payload, default="deterministic_seed"),
        )
        if not resolution.ok or resolution.selected_outcome is None or resolution.event is None:
            return BounceTargetResult(ok=False, error=resolution.blocked_reason, metadata=resolution.blocked_payload())
        result = dict(resolution.selected_outcome.payload)
        if resolution.roll is not None:
            result["roll"] = resolution.roll
        result["rng_event_id"] = resolution.event.event_id
        result["choice_key"] = request.choice_key
        result["choice_source"] = resolution.choice_source
        return BounceTargetResult(
            ok=True,
            target_id=str(result.get("selected_target_id") or ""),
            rng_event=resolution.event,
            metadata=result,
        )


def _policy_allows(actor_id: str, actor: Any, target_id: str, target: Any, policy: TargetPolicy) -> bool:
    relation = policy.target_relation
    if relation == "self":
        return target_id == actor_id and policy.allow_self
    if relation == "enemy":
        return is_opposing_combat_team(actor, target) and policy.allow_enemy
    if relation == "ally":
        return target_id != actor_id and is_same_combat_team(actor, target) and policy.allow_ally
    if relation == "ally_or_self":
        return is_same_combat_team(actor, target) and (
            policy.allow_self if target_id == actor_id else policy.allow_ally
        )
    if relation == "any":
        if target_id == actor_id:
            return policy.allow_self
        if is_same_combat_team(actor, target):
            return policy.allow_ally
        return is_opposing_combat_team(actor, target) and policy.allow_enemy
    if relation == "owner":
        return target_id == str(actor.flags.get("owner_id") or "")
    if relation == "summoner":
        return target_id == str(actor.flags.get("summoner_id") or "")
    if relation == "summon":
        return bool(target.flags.get("summon_kind")) and is_same_combat_team(actor, target)
    return False


@dataclass(frozen=True)
class _ExpressionResolution:
    target_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    steps: list[JSONValue] = field(default_factory=list)
    rng_events: tuple[RNGEvent, ...] = ()


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
            path=path,
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
    if expression_kind == "TargetConcat":
        children = _inline_children(raw, expression_kind)
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
            previous_targets=previous_targets,
            path=path,
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
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, "TargetQuery", "", (), "target_query_payload_missing")
    entity_type = raw.query_entity_type_mask
    if entity_type != "Servant":
        return _inline_result(path, "TargetQuery", "", (), f"target_query_entity_type_not_supported:{entity_type or 'missing'}")
    candidates, reason = _servant_entity_list(state)
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
        return _inline_result(path, "TargetQuery", "", (), "target_query_empty", [*steps, {"predicate_results": predicate_steps}])
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
        )
        steps.extend(source_result.steps)
        if source_result.blocked_reason:
            return _inline_result(path, "TargetFilter", "", (), source_result.blocked_reason, steps, source_result.rng_events)
        candidate_targets = source_result.target_ids
    if not candidate_targets:
        return _inline_result(path, "TargetFilter", "", (), "target_filter_candidate_missing", steps)
    condition = raw.predicate
    if condition is None:
        return _inline_result(path, "TargetFilter", "", (), "target_filter_predicate_missing", steps)
    evaluator = RuleEvaluator()
    selected: list[str] = []
    condition_results: list[JSONValue] = []
    for candidate_id in candidate_targets:
        condition_event_payload = {
            **event_payload,
            "target_id": candidate_id,
            "param_entity_id": candidate_id,
        }
        resolved_target_groups, target_resolution_errors = (
            TargetSystem().resolve_condition_target_groups(
                state,
                condition,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=candidate_id,
                current_action_target_id=current_action_target_id or candidate_id,
                event_payload=condition_event_payload,
                dynamic_values=dynamic_values,
                binding_sources=binding_sources,
            )
        )
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
                source_result.rng_events if explicit_target is not None else (),
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
        source_result.rng_events if explicit_target is not None else (),
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
    )
    if source_result.blocked_reason:
        return _inline_result(path, "Retarget", "", (), source_result.blocked_reason, source_result.steps, source_result.rng_events)
    candidate_targets = source_result.target_ids
    steps = list(source_result.steps)
    rng_events = list(source_result.rng_events)
    if raw.predicate is not None:
        filter_result = _resolve_filter_expression(
            state,
            TargetExpressionNodeIR(
                expression_kind="TargetFilter",
                predicate=raw.predicate,
            ),
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
        )
        steps.extend(filter_result.steps)
        rng_events.extend(filter_result.rng_events)
        if filter_result.blocked_reason:
            return _inline_result(path, "Retarget", "", (), filter_result.blocked_reason, steps, tuple(rng_events))
        candidate_targets = filter_result.target_ids
    max_number_expr = raw.max_number_expr
    if (
        isinstance(max_number_expr, dict)
        and max_number_expr.get("kind") == "missing"
    ):
        # TBGD omits MaxNumber for the ordinary Retarget form.  The typed
        # node retains that omission as evidence; runtime applies the schema
        # default (the whole deterministic set, or the one result selected by
        # ByRandom) instead of attempting to evaluate a synthetic number.
        max_number_expr = None
    max_number, max_step, max_reason = _positive_int_from_numeric(
        max_number_expr or None,
        dynamic_values=dynamic_values,
        binding_sources=binding_sources,
        source_trace={"target_expression_path": path, "field": "MaxNumber"},
        missing_default=len(candidate_targets),
    )
    steps.append(max_step)
    if max_reason:
        return _inline_result(path, "Retarget", "", (), f"retarget_max_number_blocked:{max_reason}", steps, tuple(rng_events))
    if raw.by_random:
        random_result = _select_random_targets(
            state,
            candidate_targets,
            event_payload=event_payload,
            path=f"{path}.ByRandom",
            source_trace={"target_expression_path": path, "expression_kind": "Retarget"},
        )
        steps.extend(random_result.steps)
        rng_events.extend(random_result.rng_events)
        if random_result.blocked_reason:
            return _inline_result(path, "Retarget", "", (), random_result.blocked_reason, steps, tuple(rng_events))
        candidate_targets = random_result.target_ids
    selected = candidate_targets[: max_number]
    if not selected:
        return _inline_result(path, "Retarget", "", (), "retarget_candidate_missing", steps, tuple(rng_events))
    return _inline_result(path, "Retarget", "", selected, "", steps, tuple(rng_events))


def _is_transform_expression_kind(kind: str) -> bool:
    return kind in {
        "TargetMapAdjoinEntity",
        "TargetMapSummoner",
        "TargetMapSummonedMinions",
        "TargetReverse",
        "TargetShuffle",
        "TargetTake",
        "TargetIndex",
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
    previous_targets: tuple[str, ...],
    path: str,
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, expression_kind, "", (), "target_fetch_payload_missing")
    if expression_kind == "TargetFetchCaster":
        return _validated_target_result(state, path, expression_kind, (caster_id,), "target_fetch_caster")
    if expression_kind in {"TargetFetchModifierOwner", "TargetFetchOwner"}:
        if not owner_id:
            return _inline_result(path, expression_kind, "", (), "target_fetch_owner_missing")
        return _validated_target_result(state, path, expression_kind, (owner_id,), "target_fetch_owner")
    if expression_kind in {"TargetFetchAbilityTarget", "TargetFetchCurrentActionTarget"}:
        target_ids: tuple[str, ...] = ()
        if current_action_target_id:
            target_ids = (current_action_target_id,)
        elif target_resolution is not None and target_resolution.selected:
            target_ids = tuple(target_resolution.selected)
        if not target_ids:
            return _inline_result(path, expression_kind, "", (), "target_fetch_ability_target_missing")
        return _validated_target_result(state, path, expression_kind, target_ids, "target_fetch_ability_target")
    if expression_kind == "TargetFetchParamEntityList":
        target_ids, reason = _target_ids_from_payload(
            state,
            event_payload,
            ("param_entity_ids", "param_entity_list", "param_entities"),
            missing_reason="param_entity_list_missing",
        )
        if reason:
            return _inline_result(path, expression_kind, "", (), reason)
        return _validated_target_result(state, path, expression_kind, target_ids, "target_fetch_param_entity_list")
    if expression_kind == "TargetFetchActualOwner":
        if not previous_targets:
            return _inline_result(path, expression_kind, "", (), "target_fetch_actual_owner_input_missing")
        selected, reason, steps = _actual_owners_for_targets(state, previous_targets)
        return _inline_result(path, expression_kind, "", selected, reason, steps)
    if expression_kind == "TargetFetchPartner":
        return _resolve_partner_fetch(state, raw.name, caster_id=caster_id, path=path)
    if expression_kind == "TargetFetchUniqueNameEntity":
        unique_name = raw.unique_name
        if not unique_name:
            return _inline_result(path, expression_kind, "", (), "unique_entity_key_missing")
        return _resolve_unique_entity(state, unique_name, path=path)
    return _inline_result(path, expression_kind, "", (), f"target_fetch_not_supported:{expression_kind}")


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
) -> _ExpressionResolution:
    if raw is None:
        return _inline_result(path, expression_kind, "", (), "target_transform_payload_missing")
    if not candidate_targets:
        return _inline_result(path, expression_kind, "", (), f"target_transform_candidate_missing:{expression_kind}")
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
        return _resolve_adjacent_expression(state, candidate_targets, raw, path=path)
    if expression_kind == "TargetMapSummoner":
        selected, reason, steps = _summoners_for_targets(state, candidate_targets)
        return _inline_result(path, expression_kind, "", selected, reason, steps)
    if expression_kind == "TargetMapSummonedMinions":
        selected, reason, steps = _summoned_minions_for_targets(state, candidate_targets)
        return _inline_result(path, expression_kind, "", selected, reason, steps)
    if expression_kind == "TargetShuffle":
        return _select_random_targets(
            state,
            candidate_targets,
            event_payload=event_payload,
            path=path,
            source_trace={"target_expression_path": path, "expression_kind": expression_kind},
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
    path: str,
) -> _ExpressionResolution:
    set_alias = _safe_set_alias(alias)
    if set_alias:
        steps: list[JSONValue] = []
        selected: tuple[str, ...] = ()
        for index, (operator, child_alias) in enumerate(set_alias):
            child = _resolve_target_alias_resolution(
                state,
                child_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                path=f"{path}.alias_set[{index}]",
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
            return _inline_result(path, "TargetAlias", alias, (), "target_alias_set_empty", steps)
        return _inline_result(path, "TargetAlias", alias, selected, "", steps)

    concat_alias = _safe_concat_alias(alias)
    if concat_alias:
        selected: tuple[str, ...] = ()
        steps: list[JSONValue] = []
        for index, child_alias in enumerate(concat_alias):
            child = _resolve_target_alias_resolution(
                state,
                child_alias,
                caster_id=caster_id,
                owner_id=owner_id,
                param_entity_id=param_entity_id,
                current_action_target_id=current_action_target_id,
                target_resolution=target_resolution,
                event_payload=event_payload,
                path=f"{path}.alias_concat[{index}]",
            )
            steps.extend(child.steps)
            if child.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), child.blocked_reason, steps)
            selected = _dedupe((*selected, *child.target_ids))
        return _inline_result(path, "TargetAlias", alias, selected, "", steps)

    expanded = _safe_alias_expansion(alias)
    if expanded is not None:
        base_alias, operations = expanded
        base = _resolve_target_alias_resolution(
            state,
            base_alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
            path=f"{path}.alias_base",
        )
        steps = list(base.steps)
        rng_events = list(base.rng_events)
        if base.blocked_reason:
            return _inline_result(path, "TargetAlias", alias, (), base.blocked_reason, steps)
        current = base.target_ids
        for index, operation in enumerate(operations):
            result = _apply_alias_operation(
                state,
                current,
                operation,
                event_payload=event_payload,
                path=f"{path}.alias_op[{index}]",
            )
            steps.extend(result.steps)
            rng_events.extend(result.rng_events)
            if result.blocked_reason:
                return _inline_result(path, "TargetAlias", alias, (), result.blocked_reason, steps, tuple(rng_events))
            current = result.target_ids
        return _inline_result(path, "TargetAlias", alias, current, "", steps, tuple(rng_events))

    target_ids, reason = _resolve_target_alias_ids(
        state,
        alias,
        caster_id=caster_id,
        owner_id=owner_id,
        param_entity_id=param_entity_id,
        current_action_target_id=current_action_target_id,
        target_resolution=target_resolution,
        event_payload=event_payload,
    )
    return _inline_result(path, "TargetAlias", alias, target_ids, reason)


def _resolve_target_alias_ids(
    state: BattleState,
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[str, ...], str]:
    if alias in {
        "AbilityTargetEntity",
        "Caster",
        "CurrentActionTarget",
        "CurrentTurnOwnerEntity",
        "DamageAttackerEntity",
        "DamageDefenderEntity",
        "LevelEntity",
        "ModifierOwnerEntity",
        "ParamEntity",
        "ParamEntity2",
    }:
        target_id = _resolve_single_alias(
            alias,
            caster_id=caster_id,
            owner_id=owner_id,
            param_entity_id=param_entity_id,
            current_action_target_id=current_action_target_id,
            target_resolution=target_resolution,
            event_payload=event_payload,
        )
        if target_id is None:
            return (), f"unsupported_or_missing_target_alias:{alias}"
        if target_id not in state.units:
            return (), f"target unit {target_id!r} is not in state"
        return (target_id,), ""
    if alias in {
        "AttackTargetList",
        "ParamEntityAttackTargetList",
        "ParamEntitySkillTargetEntityList",
        "ModifierOwnerSkillTargetEntityList",
        "SkillSubTargetEntityList",
        "SkillTargetEntityList",
        "TurnActionEntitySkillTarget",
    }:
        if alias in {
            "SkillTargetEntityList",
            "ParamEntitySkillTargetEntityList",
            "ModifierOwnerSkillTargetEntityList",
            "TurnActionEntitySkillTarget",
        }:
            return _target_ids_from_resolution_or_payload(state, target_resolution, event_payload)
        keys = {
            "AttackTargetList": ("attack_target_ids", "selected_target_ids", "target_ids"),
            "ParamEntityAttackTargetList": ("param_entity_attack_target_ids", "attack_target_ids", "selected_target_ids"),
            "SkillSubTargetEntityList": ("skill_sub_target_ids", "sub_target_ids"),
        }[alias]
        return _target_ids_from_payload(
            state,
            event_payload,
            keys,
            missing_reason=f"{alias}_missing",
        )
    if alias == "ParamEntityList":
        return _target_ids_from_payload(
            state,
            event_payload,
            ("param_entity_ids", "param_entity_list", "param_entities"),
            missing_reason="param_entity_list_missing",
        )
    if alias == "BattleEventEntityList":
        return _battle_event_entity_list(state)
    if alias in {"GridFight_AllBackEnd", "GridFight_AllBackEndRoleOnly", "GridFight_AllBackEndActivedRoleOnly"}:
        return _grid_fight_entity_list(state, alias)
    if alias in {
        "AllEnemy",
        "AllTeamMember",
        "AllTeamMemberWithUnselectable",
        "AllLightTeam",
        "AllLightTeamWithUnselectable",
        "AllDarkTeam",
        "AllDarkTeamWithUnselectable",
        "AllTeammate",
        "AllTeammateWithUnselectable",
        "TeamFormation",
        "AllEnemyWithUnSelectable",
    }:
        return _resolve_group_alias(state, caster_id, alias)
    if alias == "AllUnselectable":
        return (
            tuple(
                unit_id
                for unit_id in sorted(state.units)
                if _is_unselectable_unit(state, unit_id)
                and UnitLifecycleSystem().view(state, unit_id).is_active
            ),
            "",
        )
    if alias == "LastSummonMonsters":
        return _last_summon_monsters(state)
    if alias == "CasterSummonedMinions":
        return _caster_summoned_minions(state, caster_id)
    if alias == "ServantEntityList":
        return _servant_entity_list(state)
    if alias == "CasterServant":
        return _caster_servants(state, caster_id)
    if alias == "FriendServantSelect":
        return _friend_servant_select(state, caster_id)
    return (), f"target_alias_not_admitted:{alias or 'missing'}"


def _resolve_single_alias(
    alias: str,
    *,
    caster_id: str,
    owner_id: str | None,
    param_entity_id: str | None,
    current_action_target_id: str | None,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
) -> str | None:
    if alias == "Caster":
        return caster_id
    if alias == "ModifierOwnerEntity":
        return owner_id
    if alias == "LevelEntity":
        return _first_payload_target(event_payload, ("level_entity_id",)) or "level:global"
    if alias == "ParamEntity":
        return param_entity_id
    if alias == "ParamEntity2":
        return _first_payload_target(
            event_payload,
            ("param_entity_2_id", "param_entity2_id", "secondary_target_id"),
        )
    if alias == "DamageDefenderEntity":
        return _first_payload_target(
            event_payload,
            ("current_hit_target_id", "damage_defender_id", "primary_target_id", "target_id", "event_target_id"),
        ) or current_action_target_id
    if alias == "DamageAttackerEntity":
        return _first_payload_target(
            event_payload,
            ("damage_attacker_id", "actor_id", "source_id", "event_source_id"),
        ) or caster_id
    if alias == "CurrentTurnOwnerEntity":
        return _first_payload_target(
            event_payload,
            ("turn_owner_id", "actor_id", "event_source_id"),
        )
    if alias in {"CurrentActionTarget", "AbilityTargetEntity"}:
        if current_action_target_id:
            return current_action_target_id
        if alias == "AbilityTargetEntity" and target_resolution is not None and target_resolution.selected:
            return target_resolution.selected[0]
    return None


def _first_payload_target(
    payload: dict[str, JSONValue],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _resolve_group_alias(
    state: BattleState,
    caster_id: str,
    alias: str,
) -> tuple[tuple[str, ...], str]:
    caster = state.units.get(caster_id)
    if caster is None:
        return (), "caster_missing_for_group_target"
    targets: list[str] = []
    for unit_id, unit in sorted(state.units.items()):
        if not UnitLifecycleSystem().can_target(state, unit_id)[0]:
            continue
        if unit_is_unselectable(state, unit_id) and alias not in {
            "AllEnemyWithUnSelectable",
            "AllLightTeamWithUnselectable",
            "AllDarkTeamWithUnselectable",
            "AllTeamMemberWithUnselectable",
            "AllTeammateWithUnselectable",
        }:
            continue
        if alias in {"AllEnemy", "AllEnemyWithUnSelectable"} and is_opposing_combat_team(caster, unit):
            targets.append(unit_id)
        elif alias in {
            "AllTeamMember",
            "AllTeamMemberWithUnselectable",
            "TeamFormation",
        } and is_same_combat_team(caster, unit):
            targets.append(unit_id)
        elif alias in {"AllLightTeam", "AllLightTeamWithUnselectable"} and is_light_team(unit):
            targets.append(unit_id)
        elif alias in {"AllDarkTeam", "AllDarkTeamWithUnselectable"} and is_dark_team(unit):
            targets.append(unit_id)
        elif alias in {"AllTeammate", "AllTeammateWithUnselectable"} and is_same_combat_team(caster, unit) and unit_id != caster_id:
            targets.append(unit_id)
    if not targets:
        return (), f"target group empty:{alias}"
    return tuple(dict.fromkeys(targets)), ""


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


def _resolve_partner_fetch(state: BattleState, name: str, *, caster_id: str, path: str) -> _ExpressionResolution:
    registry = state.global_flags.get("target_partner_registry")
    if not isinstance(registry, dict):
        return _inline_result(path, "TargetFetchPartner", "", (), "target_partner_registry_missing")
    lookup_keys = (name, f"{caster_id}:{name}") if name else (caster_id,)
    matched_key = ""
    target_ids: tuple[str, ...] = ()
    for key in lookup_keys:
        if not key:
            continue
        candidate_ids = _ids_from_registry_value(registry.get(key))
        if candidate_ids:
            matched_key = key
            target_ids = candidate_ids
            break
    step = {
        "operation": "target_fetch_partner",
        "name": name,
        "lookup_keys": list(lookup_keys),
        "matched_registry_key": matched_key,
        "candidate_pool_before": list(target_ids),
    }
    if not target_ids:
        return _inline_result(path, "TargetFetchPartner", "", (), "target_partner_missing", [step])
    return _validated_target_result(
        state,
        path,
        "TargetFetchPartner",
        target_ids,
        "target_fetch_partner",
        metadata={
            "name": name,
            "lookup_keys": list(lookup_keys),
            "matched_registry_key": matched_key,
        },
    )


def _resolve_unique_entity(state: BattleState, unique_name: str, *, path: str) -> _ExpressionResolution:
    registry = state.global_flags.get("target_unique_entity_registry")
    if not isinstance(registry, dict):
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "target_unique_entity_registry_missing")
    target_ids = _ids_from_registry_value(registry.get(unique_name))
    step = {"operation": "target_fetch_unique_entity", "unique_name": unique_name, "candidate_pool_before": list(target_ids)}
    if not target_ids:
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "unique_entity_missing", [step])
    if len(target_ids) > 1:
        return _inline_result(path, "TargetFetchUniqueNameEntity", "", (), "unique_entity_ambiguous", [step])
    return _validated_target_result(state, path, "TargetFetchUniqueNameEntity", target_ids, "target_fetch_unique_entity")


def _ids_from_registry_value(value: JSONValue) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if isinstance(item, str) and item)
    if isinstance(value, dict):
        unit_id = value.get("unit_id")
        if isinstance(unit_id, str) and unit_id:
            return (unit_id,)
        unit_ids = value.get("unit_ids")
        if isinstance(unit_ids, list):
            return tuple(str(item) for item in unit_ids if isinstance(item, str) and item)
    return ()


def _resolve_sort_expression(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    payload: TargetExpressionNodeIR,
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
    else:
        return _inline_result(path, expression_kind, "", (), f"target_sort_not_supported:{expression_kind}")
    for target_id in candidate_targets:
        unit = state.units.get(target_id)
        if unit is None:
            skipped.append({"target_id": target_id, "reason": "unit_missing"})
            continue
        value, reason = value_getter(unit, sort_key)
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
        "tie_breaker": "unit_id",
    }
    if skipped:
        return _inline_result(path, expression_kind, "", (), f"target_sort_value_blocked:{sort_key or 'missing'}", [step])
    if not values:
        return _inline_result(path, expression_kind, "", (), "target_sort_candidate_missing", [step])
    highest_first = payload.highest_first
    step["direction"] = "desc" if highest_first else "asc"
    ordered = tuple(
        sorted(
            candidate_targets,
            key=lambda target_id: (
                -values[target_id] if highest_first else values[target_id],
                target_id,
            ),
        )
    )
    step["selected_targets"] = list(ordered)
    return _inline_result(path, expression_kind, "", ordered, "", [step])


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
    payload: TargetExpressionNodeIR,
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
            "" if selected else "target_take_selected_empty",
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


def _resolve_adjacent_expression(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    payload: TargetExpressionNodeIR,
    *,
    path: str,
) -> _ExpressionResolution:
    side_type = payload.adjacent_side or "Both"
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for primary_id in candidate_targets:
        primary = state.units.get(primary_id)
        if primary is None:
            skipped.append({"target_id": primary_id, "reason": "unit_missing"})
            continue
        position = _position(primary.flags.get("position"))
        if position is None:
            skipped.append({"target_id": primary_id, "reason": "target_position_missing"})
            continue
        wanted = set()
        if side_type in {"Both", "", "Left"}:
            wanted.add(position - 1)
        if side_type in {"Both", "", "Right"}:
            wanted.add(position + 1)
        if not wanted:
            skipped.append({"target_id": primary_id, "reason": f"target_adjacent_side_not_admitted:{side_type}"})
            continue
        for unit_id, unit in state.units.items():
            if unit_id == primary_id or not is_same_combat_team(primary, unit):
                continue
            unit_position = _position(unit.flags.get("position"))
            if unit_position not in wanted:
                continue
            ok, reason = UnitLifecycleSystem().can_target(state, unit_id)
            if not ok:
                skipped.append({"target_id": unit_id, "primary_target_id": primary_id, "reason": reason})
                continue
            selected.append(unit_id)
    ordered = tuple(
        sorted(
            _dedupe(tuple(selected)),
            key=lambda target_id: (_position(state.units[target_id].flags.get("position")) or 0, target_id),
        )
    )
    step = {
        "operation": "target_adjacent",
        "side_type": side_type,
        "candidate_pool_before": list(candidate_targets),
        "selected_targets": list(ordered),
        "skipped_targets": skipped,
        "position_source": "UnitState.flags.position",
    }
    if skipped and not ordered:
        return _inline_result(path, "TargetMapAdjoinEntity", "", (), "target_adjacent_blocked", [step])
    return _inline_result(path, "TargetMapAdjoinEntity", "", ordered, "", [step])


def _select_random_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    *,
    event_payload: dict[str, JSONValue],
    path: str,
    source_trace: dict[str, JSONValue],
) -> _ExpressionResolution:
    choices = rng_choices_from_payload(event_payload)
    outcomes = tuple(
        RNGOutcome(
            outcome_id=str(target_id),
            payload={
                "selected_target_id": target_id,
                "selected_index": index,
                "candidate_pool": list(candidate_targets),
                "value": target_id,
            },
            weight=1.0,
        )
        for index, target_id in enumerate(candidate_targets)
    )
    actor_id = str(event_payload.get("actor_id") or event_payload.get("caster_id") or "")
    action_id = str(event_payload.get("action_id") or "")
    task_id = str(event_payload.get("task_id") or "")
    hit_index_value = event_payload.get("hit_index", 0)
    hit_index = int(hit_index_value) if isinstance(hit_index_value, int) and not isinstance(hit_index_value, bool) else 0
    decision_index_value = event_payload.get("rng_decision_index", hit_index)
    decision_index = (
        int(decision_index_value)
        if isinstance(decision_index_value, int) and not isinstance(decision_index_value, bool)
        else hit_index
    )
    identity_seed = {
        "decision_scope": "target_expression",
        "decision_index": max(0, decision_index),
        "actor_id": actor_id,
        "action_id": action_id,
        "action_level": event_payload.get("action_level", 0),
        "task_id": task_id,
        "hit_index": max(0, hit_index),
        "target_expression_id": path,
        "event_index": state.event_index,
    }
    event_suffix = choice_key_for_identity("target_random_event", identity_seed).rsplit(":", 1)[-1]
    event_id = f"rng:{state.event_index}:target_random:{event_suffix}"
    identity = {
        **identity_seed,
        "target_id": "",
        "derived_event_id": event_id,
    }
    request = RNGRequest(
        rng_type="target_random",
        purpose="target_random",
        event_id=event_id,
        choice_key=choice_key_for_identity("target_random", identity),
        source="target_system",
        before_state=state.rng_state,
        decision_kind="choice",
        outcomes=outcomes,
        source_trace=source_trace,
        metadata={
            "candidate_pool": list(candidate_targets),
            "path": path,
            "actor_id": actor_id,
            "action_id": action_id,
            "task_id": task_id,
            "hit_index": hit_index,
        },
        invalid_choice_reason="target_random_choice_invalid",
        identity=identity,
    )
    resolution = resolve_rng_request(
        request,
        rng_choices=choices,
        rng_mode=rng_mode_from_payload(event_payload, default="explicit_ledger"),
    )
    if not resolution.ok:
        return _inline_result(
            path,
            "TargetShuffle",
            "",
            (),
            resolution.blocked_reason,
            [
                {
                    "operation": "target_random",
                    "candidate_pool_before": list(candidate_targets),
                    "choice_key": request.choice_key,
                    "available_rng_outcomes": resolution.available_rng_outcomes(),
                    "raw_choice": resolution.raw_choice,
                }
            ],
        )
    if resolution.selected_outcome is None or resolution.event is None:
        return _inline_result(path, "TargetShuffle", "", (), "target_random_choice_invalid")
    selected_id = str(resolution.selected_outcome.payload.get("selected_target_id") or "")
    selected_index = int(resolution.selected_outcome.payload.get("selected_index") or 0)
    step = {
        "operation": "target_random",
        "candidate_pool_before": list(candidate_targets),
        "selected_targets": [selected_id],
        "selected_index": selected_index,
        "rng_event_id": event_id,
        "choice_key": request.choice_key,
        "choice_source": resolution.choice_source,
    }
    return _inline_result(path, "TargetShuffle", "", (selected_id,), "", [step], (resolution.event,))


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
    if int(result.value) != float(result.value) or result.value <= 0:
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
    if int(result.value) != float(result.value) or result.value < 0:
        return 0, step, "numeric_not_non_negative_integer"
    return int(result.value), step, ""


def _safe_concat_alias(alias: str) -> tuple[str, ...]:
    return {
        "AbilityTargetAndAdjoinEntity": ("AbilityTargetEntity", "AbilityTargetAdjoinEntity"),
        "AbilityTargetServantOrSummoner": ("AbilityTargetEntity.GetSummoner", "AbilityTargetEntity.GetServant"),
        "CasterBEServant": ("Caster.GetBEServant",),
        "CasterWithAbilityTargetAndAdjoinEntity": ("Caster", "AbilityTargetAndAdjoinEntity"),
        "CasterServantOrSummoner": ("Caster.GetSummoner", "Caster.GetServant"),
        "CurrentAimAtTarget": ("CurrentActionTarget",),
    }.get(alias, ())


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


def _safe_alias_expansion(alias: str) -> tuple[str, tuple[dict[str, JSONValue], ...]] | None:
    direct: dict[str, tuple[str, tuple[dict[str, JSONValue], ...]]] = {
        "AbilityTargetAdjoinEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity"},)),
        "AbilityTargetLeftEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity", "SideType": "Left"},)),
        "AbilityTargetRightEntity": ("AbilityTargetEntity", ({"kind": "TargetMapAdjoinEntity", "SideType": "Right"},)),
        "AllLightTeamIgnoreServant": ("AllLightTeam", ({"kind": "TargetRemoveServant"},)),
        "AllLightTeamOnlyAddSPOnceForServant": ("AllLightTeam", ({"kind": "TargetRemoveServant"},)),
        "AllLightTeamWithAllLightTeamUnselectable": ("AllLightTeamWithUnselectable", ()),
        "AllLightTeamWithAllUnselectableLightTeam": ("AllLightTeamWithUnselectable", ()),
        "AllDarkTeamWithAllDarkTeamUnselectable": ("AllDarkTeamWithUnselectable", ()),
        "AllTeammateOnlyAddSPOnceForServant": ("AllTeammate", ({"kind": "TargetRemoveServant"},)),
        "AllEnemyIgnoreServant": ("AllEnemy", ({"kind": "TargetRemoveServant"},)),
        "CasterSummoner": ("Caster", ({"kind": "TargetMapSummoner"},)),
        "LightTeamLeftWithoutServant": (
            "AllLightTeam",
            (
                {"kind": "TargetRemoveServant"},
                {"kind": "TargetSortByFormation", "HighestFirst": True},
                {"kind": "TargetIndex", "IndexType": "First"},
            ),
        ),
        "LightTeamRightWithoutServant": (
            "AllLightTeam",
            (
                {"kind": "TargetRemoveServant"},
                {"kind": "TargetSortByFormation", "HighestFirst": True},
                {"kind": "TargetIndex", "IndexType": "Last"},
            ),
        ),
        "LeftToRightLightTeamTarget": ("AllLightTeam", ({"kind": "TargetSortByFormation"},)),
        "ParamEntityAdjoinEntity": ("ParamEntity", ({"kind": "TargetMapAdjoinEntity"},)),
        "ParamEntitySummoner": ("ParamEntity", ({"kind": "TargetMapSummoner"},)),
        "CasterAdjoinEntity": ("Caster", ({"kind": "TargetMapAdjoinEntity"},)),
        "ModifierOwnerSummoner": ("ModifierOwnerEntity", ({"kind": "TargetMapSummoner"},)),
        "ModifierOwnerEntityAdjoinEntity": ("ModifierOwnerEntity", ({"kind": "TargetMapAdjoinEntity"},)),
        "ModifierOwnerSummonedMinions": ("ModifierOwnerEntity", ({"kind": "TargetMapSummonedMinions"},)),
    }
    if alias in direct:
        return direct[alias]
    if not _safe_dot_alias(alias):
        return None
    parts = tuple(part for part in alias.split(".") if part)
    if len(parts) < 2:
        return None
    base_alias = parts[0]
    operations: list[dict[str, JSONValue]] = []
    for op in parts[1:]:
        operation = _dot_alias_operation(op)
        if operation is None:
            return None
        operations.append(operation)
    return base_alias, tuple(operations)


def _safe_dot_alias(alias: str) -> bool:
    if "." not in alias:
        return False
    return not any(token in alias for token in (" ", "+", "-", "|", "(", ")"))


def _dot_alias_operation(op: str) -> dict[str, JSONValue] | None:
    mapping: dict[str, dict[str, JSONValue]] = {
        "GetAliveOnly": {"kind": "GetAliveOnly"},
        "SortByHP": {"kind": "TargetSortByProperty", "PropertyType": "CurrentHP"},
        "SortByHPRatio": {"kind": "TargetSortByPropertyRatio", "PropertyRatioType": "HPRatio"},
        "SortByMaxHP": {"kind": "TargetSortByProperty", "PropertyType": "MaxHP"},
        "SortByStance": {"kind": "TargetSortByProperty", "PropertyType": "CurrentStance"},
        "SortByStanceRatio": {"kind": "TargetSortByPropertyRatio", "PropertyRatioType": "StanceRatio"},
        "SortByBreakDamageAddedRatio": {"kind": "TargetSortByBreakDamageAddedRatio"},
        "SortByFormation": {"kind": "TargetSortByFormation"},
        "Reverse": {"kind": "TargetReverse"},
        "Select1": {"kind": "TargetIndex", "IndexType": "IndexStrict"},
        "Select2": {"kind": "TargetIndex", "IndexType": "IndexStrict", "IndexValue": 1},
        "Select3": {"kind": "TargetIndex", "IndexType": "IndexStrict", "IndexValue": 2},
        "Select4": {"kind": "TargetIndex", "IndexType": "IndexStrict", "IndexValue": 3},
        "SelectLast": {"kind": "TargetIndex", "IndexType": "Last"},
        "Shuffle": {"kind": "TargetShuffle"},
        "GetAdjoinEntity": {"kind": "TargetMapAdjoinEntity"},
        "GetServant": {"kind": "TargetMapServant"},
        "GetBEServant": {"kind": "TargetMapBEServant"},
        "GetServantAndDummyCharacter": {"kind": "TargetMapServantAndDummyCharacter"},
        "GetDummyCharacter": {"kind": "TargetMapDummyCharacter"},
        "WithServant": {"kind": "TargetWithServant"},
        "WithBEServant": {"kind": "TargetWithBEServant"},
        "WithServantAndDummyCharacter": {"kind": "TargetWithServantAndDummyCharacter"},
        "RemoveBattleEvent": {"kind": "TargetRemoveBattleEvent"},
        "RemoveBEServant": {"kind": "TargetRemoveBEServant"},
        "RemoveCharacterChangeTarget": {"kind": "TargetRemoveCharacterChangeTarget"},
        "RemoveNonSelfCreateBattleEvent": {"kind": "TargetRemoveNonSelfCreateBattleEvent"},
        "RemoveServant": {"kind": "TargetRemoveServant"},
        "RemoveUnselectable": {"kind": "TargetRemoveUnselectable"},
        "GetSummoner": {"kind": "TargetMapSummoner"},
        "WithSummoner": {"kind": "TargetWithSummoner"},
        "GetSummonedMinions": {"kind": "TargetMapSummonedMinions"},
        "GetSkillAllTarget": {
            "kind": "TargetSkillAllTarget",
            "operation": "GetSkillAllTarget",
        },
        "GetSkillTarget": {
            "kind": "TargetSkillAllTarget",
            "operation": "GetSkillTarget",
        },
    }
    return mapping.get(op)


def _apply_alias_operation(
    state: BattleState,
    candidate_targets: tuple[str, ...],
    operation: dict[str, JSONValue],
    *,
    event_payload: dict[str, JSONValue],
    path: str,
) -> _ExpressionResolution:
    kind = str(operation.get("kind") or "")
    if kind == "GetAliveOnly":
        selected: list[str] = []
        skipped: list[JSONValue] = []
        lifecycle = UnitLifecycleSystem()
        for target_id in candidate_targets:
            ok, reason = lifecycle.can_target(state, target_id)
            if ok:
                selected.append(target_id)
            else:
                skipped.append({"target_id": target_id, "reason": reason})
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            tuple(selected),
            "" if selected else "target_alive_filter_empty",
            [{"operation": "GetAliveOnly", "candidate_pool_before": list(candidate_targets), "selected_targets": selected, "skipped_targets": skipped}],
        )
    if kind == "TargetReverse":
        return _inline_result(path, kind, "", tuple(reversed(candidate_targets)), "", [{"operation": "Reverse", "candidate_pool_before": list(candidate_targets)}])
    if kind == "TargetShuffle":
        return _select_random_targets(
            state,
            candidate_targets,
            event_payload=event_payload,
            path=path,
            source_trace={"target_expression_path": path, "expression_kind": kind},
        )
    if kind in {"TargetSortByProperty", "TargetSortByPropertyRatio", "TargetSortByFormation", "TargetSortByBreakDamageAddedRatio"}:
        return _resolve_sort_expression(
            state,
            candidate_targets,
            _typed_alias_operation_node(operation),
            expression_kind=kind,
            path=path,
        )
    if kind in {"TargetIndex", "TargetTake"}:
        return _resolve_take_expression(
            candidate_targets,
            _typed_alias_operation_node(operation),
            expression_kind=kind,
            dynamic_values=None,
            binding_sources=(),
            path=path,
        )
    if kind == "TargetMapAdjoinEntity":
        return _resolve_adjacent_expression(
            state,
            candidate_targets,
            _typed_alias_operation_node(operation),
            path=path,
        )
    if kind == "TargetSkillAllTarget":
        target_ids, reason = _target_ids_from_payload(
            state,
            event_payload,
            (
                "skill_target_ids",
                "selected_target_ids",
                "requested_target_ids",
                "target_ids",
            ),
            missing_reason="skill_all_targets_missing",
        )
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            target_ids,
            reason,
            [
                {
                    "operation": str(
                        operation.get("operation") or "GetSkillAllTarget"
                    ),
                    "candidate_pool_before": list(candidate_targets),
                    "selected_targets": list(target_ids),
                    "source": "event_payload",
                }
            ],
        )
    if kind == "TargetMapServant":
        selected, reason, steps = _servants_for_targets(state, candidate_targets)
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, steps)
    if kind == "TargetMapBEServant":
        selected, reason, steps = _be_servants_for_targets(state, candidate_targets)
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, steps)
    if kind == "TargetMapServantAndDummyCharacter":
        servants, servant_reason, servant_steps = _servants_for_targets(state, candidate_targets)
        dummy, dummy_reason, dummy_steps = _dummy_characters_for_targets(state, candidate_targets)
        selected = _dedupe((*servants, *dummy))
        reason = "" if selected else servant_reason or dummy_reason or "target_map_servant_and_dummy_character_empty"
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, [*servant_steps, *dummy_steps])
    if kind == "TargetMapDummyCharacter":
        selected, reason, steps = _dummy_characters_for_targets(state, candidate_targets)
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, steps)
    if kind == "TargetWithServant":
        mapped, _, map_steps = _servants_for_targets(state, candidate_targets)
        selected = _dedupe((*candidate_targets, *mapped))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_with_servant_empty",
            [
                *map_steps,
                {
                    "operation": "WithServant",
                    "candidate_pool_before": list(candidate_targets),
                    "selected_targets": list(selected),
                },
            ],
        )
    if kind == "TargetWithBEServant":
        mapped, _, map_steps = _be_servants_for_targets(state, candidate_targets)
        selected = _dedupe((*candidate_targets, *mapped))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_with_be_servant_empty",
            [
                *map_steps,
                {
                    "operation": "WithBEServant",
                    "candidate_pool_before": list(candidate_targets),
                    "selected_targets": list(selected),
                },
            ],
        )
    if kind == "TargetWithServantAndDummyCharacter":
        servants, _, servant_steps = _servants_for_targets(state, candidate_targets)
        dummy, _, dummy_steps = _dummy_characters_for_targets(state, candidate_targets)
        selected = _dedupe((*candidate_targets, *servants, *dummy))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_with_servant_and_dummy_character_empty",
            [
                *servant_steps,
                *dummy_steps,
                {
                    "operation": "WithServantAndDummyCharacter",
                    "candidate_pool_before": list(candidate_targets),
                    "selected_targets": list(selected),
                },
            ],
        )
    if kind == "TargetRemoveServant":
        selected = tuple(target_id for target_id in candidate_targets if not _is_servant_unit(state, target_id))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_remove_servant_empty",
            [{"operation": "RemoveServant", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected)}],
        )
    if kind == "TargetRemoveBEServant":
        selected = tuple(target_id for target_id in candidate_targets if not _is_be_servant_unit(state, target_id))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_remove_be_servant_empty",
            [{"operation": "RemoveBEServant", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected)}],
        )
    if kind == "TargetRemoveUnselectable":
        selected = tuple(
            target_id
            for target_id in candidate_targets
            if UnitLifecycleSystem().can_target(state, target_id)[0] and not _is_unselectable_unit(state, target_id)
        )
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_remove_unselectable_empty",
            [{"operation": "RemoveUnselectable", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected)}],
        )
    if kind in {"TargetRemoveBattleEvent", "TargetRemoveNonSelfCreateBattleEvent"}:
        selected = tuple(target_id for target_id in candidate_targets if not _is_battle_event_unit(state, target_id))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_remove_battle_event_empty",
            [{"operation": kind.removeprefix("Target"), "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected)}],
        )
    if kind == "TargetRemoveCharacterChangeTarget":
        selected = tuple(target_id for target_id in candidate_targets if not _is_character_change_target_unit(state, target_id))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_remove_character_change_target_empty",
            [{"operation": "RemoveCharacterChangeTarget", "candidate_pool_before": list(candidate_targets), "selected_targets": list(selected)}],
        )
    if kind == "TargetMapSummoner":
        selected, reason, steps = _summoners_for_targets(state, candidate_targets)
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, steps)
    if kind == "TargetWithSummoner":
        mapped, _, map_steps = _summoners_for_targets(state, candidate_targets)
        selected = _dedupe((*candidate_targets, *mapped))
        return _inline_result(
            path,
            "TargetAliasOperation",
            "",
            selected,
            "" if selected else "target_with_summoner_empty",
            [
                *map_steps,
                {
                    "operation": "WithSummoner",
                    "candidate_pool_before": list(candidate_targets),
                    "selected_targets": list(selected),
                },
            ],
        )
    if kind == "TargetMapSummonedMinions":
        selected, reason, steps = _summoned_minions_for_targets(state, candidate_targets)
        return _inline_result(path, "TargetAliasOperation", "", selected, reason, steps)
    return _inline_result(path, "TargetAliasOperation", "", (), f"target_alias_operation_not_supported:{kind or 'missing'}")


def _typed_alias_operation_node(operation: dict[str, JSONValue]) -> TargetExpressionNodeIR:
    kind = str(operation.get("kind") or "")
    numeric = operation.get("IndexValue") if kind == "TargetIndex" else operation.get("Count")
    numeric_expr: dict[str, JSONValue] = {}
    if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
        numeric_expr = {
            "schema_version": "hsr.numeric_expression.v1",
            "kind": "fixed",
            "value": float(numeric),
            "supported": True,
        }
    return TargetExpressionNodeIR(
        expression_kind=kind,
        adjacent_side=str(operation.get("SideType") or "Both"),
        count_expr=numeric_expr if kind == "TargetTake" else {},
        index_type=str(operation.get("IndexType") or "IndexStrict"),
        index_expr=numeric_expr if kind == "TargetIndex" else {},
        sort_kind=kind if kind.startswith("TargetSort") else "",
        sort_key=str(
            operation.get("PropertyType")
            or operation.get("PropertyRatioType")
            or ("formation_position" if kind == "TargetSortByFormation" else "")
        ),
        highest_first=bool(operation.get("HighestFirst")),
    )


def _stable_path(path: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in path)[:80]


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


def _target_ids_from_resolution_or_payload(
    state: BattleState,
    target_resolution: TargetResolution | None,
    event_payload: dict[str, JSONValue],
) -> tuple[tuple[str, ...], str]:
    if target_resolution is not None and target_resolution.selected:
        target_ids = _existing_targets(state, target_resolution.selected)
        if target_ids:
            return target_ids, ""
        return (), "skill_target_entity_list_units_missing"
    return _target_ids_from_payload(
        state,
        event_payload,
        ("selected_target_ids", "skill_target_ids", "target_ids", "requested_target_ids"),
        missing_reason="skill_target_entity_list_missing",
    )


def _target_ids_from_payload(
    state: BattleState,
    event_payload: dict[str, JSONValue],
    keys: tuple[str, ...],
    *,
    missing_reason: str,
) -> tuple[tuple[str, ...], str]:
    for key in keys:
        value = event_payload.get(key)
        if isinstance(value, (list, tuple)):
            target_ids = _existing_targets(state, tuple(str(item) for item in value if isinstance(item, str)))
            if target_ids:
                return target_ids, ""
    return (), missing_reason


def _existing_targets(state: BattleState, target_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target_id for target_id in target_ids if target_id in state.units))


def _last_summon_monsters(state: BattleState) -> tuple[tuple[str, ...], str]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing"
    raw = runtime.get("last_summon_monsters")
    if not isinstance(raw, list):
        return (), "last_summon_monsters_missing"
    lifecycle = UnitLifecycleSystem()
    target_ids: list[str] = []
    skipped_reasons: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        if not _runtime_entity_is_active(runtime, item):
            skipped_reasons.append("summon_runtime_entity_missing_or_removed")
            continue
        targetable, targetable_reason = _runtime_entity_targetability(runtime, item)
        if not targetable:
            skipped_reasons.append(targetable_reason)
            continue
        ok, reason = lifecycle.can_target(state, item, allow_defeated=False)
        if ok:
            target_ids.append(item)
        else:
            skipped_reasons.append(reason)
    if not target_ids:
        if skipped_reasons:
            return (), _first_specific_reason(skipped_reasons)
        return (), "last_summon_monsters_empty"
    return tuple(dict.fromkeys(target_ids)), ""


def _caster_summoned_minions(state: BattleState, caster_id: str) -> tuple[tuple[str, ...], str]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing"
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing"
    raw = by_owner.get(caster_id)
    if raw is None:
        return (), ""
    if not isinstance(raw, list):
        return (), "caster_summoned_minions_invalid"
    lifecycle = UnitLifecycleSystem()
    target_ids: list[str] = []
    skipped_reasons: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        if not _runtime_entity_is_active(runtime, item):
            skipped_reasons.append("summon_runtime_entity_missing_or_removed")
            continue
        targetable, targetable_reason = _runtime_entity_targetability(runtime, item)
        if not targetable:
            skipped_reasons.append(targetable_reason)
            continue
        ok, reason = lifecycle.can_target(state, item, allow_defeated=False)
        if ok:
            target_ids.append(item)
        else:
            skipped_reasons.append(reason)
    if not target_ids:
        if skipped_reasons:
            return (), _first_specific_reason(skipped_reasons)
        return (), "caster_summoned_minions_empty"
    return tuple(dict.fromkeys(target_ids)), ""


def _servant_entity_list(state: BattleState) -> tuple[tuple[str, ...], str]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing"
    servants = runtime.get("servants")
    if not isinstance(servants, dict):
        return (), "summon_runtime_servants_missing"
    lifecycle = UnitLifecycleSystem()
    target_ids: list[str] = []
    skipped_reasons: list[str] = []
    for unit_id, entry in sorted(servants.items()):
        if not isinstance(unit_id, str) or not isinstance(entry, dict):
            continue
        if entry.get("removed_event_index") is not None:
            continue
        if not _runtime_entity_is_active(runtime, unit_id):
            skipped_reasons.append("summon_runtime_entity_missing_or_removed")
            continue
        targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
        if not targetable:
            skipped_reasons.append(targetable_reason)
            continue
        if unit_id not in state.units or not _is_servant_unit(state, unit_id):
            skipped_reasons.append("not_servant_unit")
            continue
        ok, reason = lifecycle.can_target(state, unit_id)
        if ok:
            target_ids.append(unit_id)
        else:
            skipped_reasons.append(reason)
    if not target_ids:
        if skipped_reasons:
            return (), _first_specific_reason(skipped_reasons)
        return (), "servant_entity_list_empty"
    return tuple(dict.fromkeys(target_ids)), ""


def _caster_servants(state: BattleState, caster_id: str) -> tuple[tuple[str, ...], str]:
    selected, reason, _ = _servants_for_targets(state, (caster_id,))
    if reason:
        return (), reason
    return selected, ""


def _friend_servant_select(state: BattleState, caster_id: str) -> tuple[tuple[str, ...], str]:
    caster = state.units.get(caster_id)
    if caster is None:
        return (), "caster_missing_for_friend_servant_select"
    servants, reason = _servant_entity_list(state)
    if reason:
        return (), reason
    selected = tuple(
        unit_id
        for unit_id in servants
        for unit in (state.units.get(unit_id),)
        if unit is not None and is_same_combat_team(caster, unit)
    )
    if not selected:
        return (), "friend_servant_select_empty"
    return tuple(dict.fromkeys(selected)), ""


def _servants_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing", [{"operation": "GetServant", "candidate_pool_before": list(candidate_targets)}]
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing", [{"operation": "GetServant", "candidate_pool_before": list(candidate_targets)}]
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for owner_id in candidate_targets:
        raw = by_owner.get(owner_id)
        if not isinstance(raw, list):
            skipped.append({"owner_id": owner_id, "reason": "owner_has_no_runtime_summons"})
            continue
        for unit_id in raw:
            if not isinstance(unit_id, str):
                continue
            if not _runtime_entity_is_active(runtime, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "runtime_entity_missing_or_removed"})
                continue
            targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
            if not targetable:
                skipped.append({"unit_id": unit_id, "reason": targetable_reason})
                continue
            if not _is_servant_unit(state, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "not_servant_unit"})
                continue
            ok, reason = lifecycle.can_target(state, unit_id)
            if not ok:
                skipped.append({"unit_id": unit_id, "reason": reason})
                continue
            selected.append(unit_id)
    steps = [
        {
            "operation": "GetServant",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if not selected:
        return (), "target_map_servant_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _be_servants_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing", [{"operation": "GetBEServant", "candidate_pool_before": list(candidate_targets)}]
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing", [{"operation": "GetBEServant", "candidate_pool_before": list(candidate_targets)}]
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for owner_id in candidate_targets:
        raw = by_owner.get(owner_id)
        if not isinstance(raw, list):
            skipped.append({"owner_id": owner_id, "reason": "owner_has_no_runtime_summons"})
            continue
        for unit_id in raw:
            if not isinstance(unit_id, str):
                continue
            if not _runtime_entity_is_active(runtime, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "runtime_entity_missing_or_removed"})
                continue
            targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
            if not targetable:
                skipped.append({"unit_id": unit_id, "reason": targetable_reason})
                continue
            if not _is_be_servant_unit(state, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "not_be_servant_unit"})
                continue
            ok, reason = lifecycle.can_target(state, unit_id)
            if not ok:
                skipped.append({"unit_id": unit_id, "reason": reason})
                continue
            selected.append(unit_id)
    steps = [
        {
            "operation": "GetBEServant",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if not selected:
        return (), "target_map_be_servant_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _dummy_characters_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing", [{"operation": "GetDummyCharacter", "candidate_pool_before": list(candidate_targets)}]
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing", [{"operation": "GetDummyCharacter", "candidate_pool_before": list(candidate_targets)}]
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for owner_id in candidate_targets:
        raw = by_owner.get(owner_id)
        if not isinstance(raw, list):
            skipped.append({"owner_id": owner_id, "reason": "owner_has_no_runtime_summons"})
            continue
        for unit_id in raw:
            if not isinstance(unit_id, str):
                continue
            if not _runtime_entity_is_active(runtime, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "runtime_entity_missing_or_removed"})
                continue
            targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
            if not targetable:
                skipped.append({"unit_id": unit_id, "reason": targetable_reason})
                continue
            if not _is_dummy_character_unit(state, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "not_dummy_character_unit"})
                continue
            ok, reason = lifecycle.can_target(state, unit_id)
            if not ok:
                skipped.append({"unit_id": unit_id, "reason": reason})
                continue
            selected.append(unit_id)
    steps = [
        {
            "operation": "GetDummyCharacter",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if not selected:
        return (), "target_map_dummy_character_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _summoned_minions_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing", [{"operation": "GetSummonedMinions", "candidate_pool_before": list(candidate_targets)}]
    by_owner = runtime.get("by_owner")
    if not isinstance(by_owner, dict):
        return (), "summon_runtime_by_owner_missing", [{"operation": "GetSummonedMinions", "candidate_pool_before": list(candidate_targets)}]
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for owner_id in candidate_targets:
        raw = by_owner.get(owner_id)
        if not isinstance(raw, list):
            skipped.append({"owner_id": owner_id, "reason": "owner_has_no_runtime_summons"})
            continue
        for unit_id in raw:
            if not isinstance(unit_id, str):
                continue
            unit = state.units.get(unit_id)
            if unit is None:
                skipped.append({"unit_id": unit_id, "reason": "unit_missing"})
                continue
            if unit.flags.get("summon_kind") not in {"servant", "summoned_monster"}:
                skipped.append({"unit_id": unit_id, "reason": "not_summon_unit"})
                continue
            if not _runtime_entity_is_active(runtime, unit_id):
                skipped.append({"unit_id": unit_id, "reason": "runtime_entity_missing_or_removed"})
                continue
            targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
            if not targetable:
                skipped.append({"unit_id": unit_id, "reason": targetable_reason})
                continue
            ok, reason = lifecycle.can_target(state, unit_id)
            if not ok:
                skipped.append({"unit_id": unit_id, "reason": reason})
                continue
            selected.append(unit_id)
    steps = [
        {
            "operation": "GetSummonedMinions",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if not selected:
        return (), "target_map_summoned_minions_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _summoners_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    runtime = state.global_flags.get("summon_runtime")
    if not _summon_runtime_schema_ok(runtime):
        return (), "summon_runtime_missing", [{"operation": "GetSummoner", "candidate_pool_before": list(candidate_targets)}]
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for unit_id in candidate_targets:
        unit = state.units.get(unit_id)
        if unit is None:
            skipped.append({"unit_id": unit_id, "reason": "unit_missing"})
            continue
        if unit.flags.get("summon_kind") not in {"servant", "summoned_monster"}:
            skipped.append({"unit_id": unit_id, "reason": "not_summon_unit"})
            continue
        if not _runtime_entity_is_active(runtime, unit_id):
            skipped.append({"unit_id": unit_id, "reason": "runtime_entity_missing_or_removed"})
            continue
        targetable, targetable_reason = _runtime_entity_targetability(runtime, unit_id)
        if not targetable:
            skipped.append({"unit_id": unit_id, "reason": targetable_reason})
            continue
        owner_id = unit.flags.get("owner_id")
        if not isinstance(owner_id, str) or owner_id not in state.units:
            skipped.append({"unit_id": unit_id, "reason": "summon_owner_missing"})
            continue
        ok, reason = lifecycle.can_target(state, owner_id)
        if not ok:
            skipped.append({"unit_id": unit_id, "owner_id": owner_id, "reason": reason})
            continue
        selected.append(owner_id)
    steps = [
        {
            "operation": "GetSummoner",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if not selected:
        return (), "target_map_summoner_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _actual_owners_for_targets(
    state: BattleState,
    candidate_targets: tuple[str, ...],
) -> tuple[tuple[str, ...], str, list[JSONValue]]:
    """Resolve each entity to the combat owner that should receive attribution.

    Ordinary combatants own themselves. Summoned entities require the same
    source-backed runtime ownership relation used by GetSummoner; missing or
    removed summon ownership remains fail-closed.
    """

    selected: list[str] = []
    skipped: list[JSONValue] = []
    for unit_id in candidate_targets:
        unit = state.units.get(unit_id)
        if unit is None:
            skipped.append({"unit_id": unit_id, "reason": "unit_missing"})
            continue
        if unit.flags.get("summon_kind") not in {"servant", "summoned_monster"}:
            selected.append(unit_id)
            continue
        owners, reason, owner_steps = _summoners_for_targets(state, (unit_id,))
        if reason:
            skipped.append(
                {
                    "unit_id": unit_id,
                    "reason": reason,
                    "owner_resolution_steps": owner_steps,
                }
            )
            continue
        selected.extend(owners)
    steps = [
        {
            "operation": "GetActualOwner",
            "candidate_pool_before": list(candidate_targets),
            "selected_targets": list(dict.fromkeys(selected)),
            "skipped_targets": skipped,
        }
    ]
    if skipped:
        return (), "target_fetch_actual_owner_incomplete", steps
    if not selected:
        return (), "target_fetch_actual_owner_empty", steps
    return tuple(dict.fromkeys(selected)), "", steps


def _is_servant_unit(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    return bool(unit is not None and unit.side == "summon" and unit.flags.get("summon_kind") == "servant")


def _is_be_servant_unit(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    return bool(
        _is_servant_unit(state, unit_id)
        and (
            unit.flags.get("servant_subtype") in {"BEServant", "battle_event"}
            or unit.flags.get("servant_kind") in {"BEServant", "battle_event"}
            or unit.flags.get("battle_event_subtype") in {"BEServant", "Servant"}
            or unit.flags.get("entity_type") == "battle_event"
        )
    )


def _is_dummy_character_unit(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    return unit.flags.get("summon_kind") == "dummy_character" or unit.flags.get("battle_event_subtype") == "DummyCharacter"


def _is_battle_event_unit(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    return unit.flags.get("entity_type") == "battle_event" or unit.flags.get("battle_event_subtype") is not None


def unit_is_unselectable(state: BattleState, unit_id: str) -> bool:
    """Return the canonical runtime target-selectability decision for one unit."""
    unit = state.units.get(unit_id)
    if unit is None:
        return True
    return runtime_unit_is_unselectable(unit)


def _is_unselectable_unit(state: BattleState, unit_id: str) -> bool:
    return unit_is_unselectable(state, unit_id)


def _is_character_change_target_unit(state: BattleState, unit_id: str) -> bool:
    unit = state.units.get(unit_id)
    if unit is None:
        return False
    return bool(
        unit.flags.get("character_change_target") is True
        or unit.flags.get("is_character_change_target") is True
        or unit.flags.get("target_kind") == "character_change"
    )


def _battle_event_entity_list(state: BattleState) -> tuple[tuple[str, ...], str]:
    selected = tuple(unit_id for unit_id in sorted(state.units) if _is_battle_event_unit(state, unit_id))
    if not selected:
        return (), "battle_event_entity_list_empty"
    return selected, ""


def _grid_fight_entity_list(state: BattleState, alias: str) -> tuple[tuple[str, ...], str]:
    lifecycle = UnitLifecycleSystem()
    selected: list[str] = []
    skipped: list[JSONValue] = []
    for unit_id, unit in sorted(state.units.items()):
        if unit.flags.get("grid_fight_backend") is not True and unit.flags.get("grid_fight_role") is not True:
            continue
        if alias.endswith("RoleOnly") and unit.flags.get("grid_fight_role") is not True:
            skipped.append({"unit_id": unit_id, "reason": "grid_fight_role_required"})
            continue
        if "ActivedRoleOnly" in alias and unit.flags.get("grid_fight_active") is not True:
            skipped.append({"unit_id": unit_id, "reason": "grid_fight_active_required"})
            continue
        ok, reason = lifecycle.can_target(state, unit_id)
        if not ok:
            skipped.append({"unit_id": unit_id, "reason": reason})
            continue
        selected.append(unit_id)
    if not selected:
        reason = str(skipped[0].get("reason")) if skipped and isinstance(skipped[0], dict) else "grid_fight_entity_list_empty"
        return (), reason
    return tuple(dict.fromkeys(selected)), ""


def _runtime_entity_is_active(runtime: dict[str, JSONValue], unit_id: str) -> bool:
    entities = runtime.get("entities")
    if not isinstance(entities, dict):
        return False
    entry = entities.get(unit_id)
    if not isinstance(entry, dict):
        return False
    if entry.get("status") == "removed" or entry.get("removed_event_index") is not None:
        return False
    return True


def _runtime_entity_targetability(runtime: dict[str, JSONValue], unit_id: str) -> tuple[bool, str]:
    if not _runtime_entity_is_active(runtime, unit_id):
        return False, "summon_runtime_entity_missing_or_removed"
    entities = runtime.get("entities")
    entry = entities.get(unit_id) if isinstance(entities, dict) else None
    if not isinstance(entry, dict):
        return False, "summon_runtime_entity_missing"
    targetability = entry.get("targetability")
    if isinstance(targetability, dict) and targetability.get("targetable") is False:
        return False, "summon_runtime_entity_not_targetable"
    return True, ""


def _first_specific_reason(reasons: list[str]) -> str:
    priority = (
        "summon_runtime_entity_missing_or_removed",
        "summon_runtime_entity_not_targetable",
        "unit_removed",
        "unit_defeated",
        "unit_missing",
    )
    for expected in priority:
        if expected in reasons:
            return expected
    return reasons[0] if reasons else "target_candidates_empty"


def _summon_runtime_schema_ok(runtime: JSONValue) -> bool:
    return isinstance(runtime, dict) and runtime.get("schema_version") in SUPPORTED_SUMMON_RUNTIME_SCHEMA_VERSIONS


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


def _policy_metadata(policy: TargetPolicy) -> dict[str, JSONValue]:
    return {
        "policy_id": policy.policy_id,
        "allow_enemy": policy.allow_enemy,
        "allow_ally": policy.allow_ally,
        "allow_self": policy.allow_self,
        "allow_defeated": policy.allow_defeated,
        "target_mode": policy.target_mode,
        "selection_mode": policy.selection_mode,
        "target_relation": policy.target_relation,
        "selection_min": policy.selection_min,
        "selection_max": policy.selection_max,
        "impact_mode": policy.impact_mode,
        "allow_off_field": policy.allow_off_field,
        "bounce_policy": policy.bounce_policy,
        "source_trace": policy.source_trace,
        "metadata": policy.metadata,
    }


def _target_groups(
    state: BattleState,
    actor_id: str,
    primary: str,
    policy: TargetPolicy,
) -> dict[str, tuple[str, ...]]:
    if policy.target_mode == "blast":
        adjacent = _adjacent_units(state, actor_id, primary, policy)
        impact = (primary, *adjacent)
        return {
            "primary": (primary,),
            "adjacent": adjacent,
            "selected": impact,
            "impact": impact,
        }
    if policy.target_mode == "bounce":
        return {
            "primary": (primary,),
            "selected": (primary,),
            "impact": (primary,),
            "bounce_pending": (primary,),
        }
    return {
        "primary": (primary,),
        "selected": (primary,),
        "impact": (primary,),
    }


def _target_mode_blocked_reason(policy: TargetPolicy) -> str:
    if policy.target_relation == "unknown":
        return "target_relation_not_admitted"
    if policy.selection_min < 0 or policy.selection_max < policy.selection_min:
        return "target_selection_cardinality_invalid"
    if policy.target_mode == "bounce":
        if str(policy.bounce_policy.get("coverage_status") or "") == "executable":
            return ""
        reason = str(policy.bounce_policy.get("blocked_reason") or "bounce_policy_not_executable")
        return reason
    if policy.target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    if policy.target_mode not in {"single", "aoe", "blast", "self_or_team"}:
        return f"unsupported_target_mode:{policy.target_mode}"
    return ""


def _deterministic_roll(rng_state: str, event_id: str, candidates: tuple[str, ...], previous: tuple[str, ...]) -> float:
    raw = "|".join((rng_state, event_id, ",".join(candidates), ",".join(previous)))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _adjacent_units(
    state: BattleState,
    actor_id: str,
    primary_id: str,
    policy: TargetPolicy,
) -> tuple[str, ...]:
    primary = state.units.get(primary_id)
    if primary is None:
        return ()
    position = _position(primary.flags.get("position"))
    if position is None:
        return ()
    actor = state.units.get(actor_id)
    if actor is None:
        return ()
    candidates = [
        unit_id
        for unit_id, unit in state.units.items()
        if unit_id != primary_id
        and _policy_allows(actor_id, actor, unit_id, unit, policy)
        and _targetability_reason(state, unit_id, policy, UnitLifecycleSystem()) == ""
        and _position(unit.flags.get("position")) in {position - 1, position + 1}
    ]
    ordered = sorted(
        candidates,
        key=lambda unit_id: (
            abs((_position(state.units[unit_id].flags.get("position")) or position) - position),
            _position(state.units[unit_id].flags.get("position")) or 0,
            unit_id,
        ),
    )
    return tuple(ordered)


def _selection_cardinality_blocked_reason(
    target_ids: tuple[str, ...],
    policy: TargetPolicy,
) -> str:
    if len(set(target_ids)) != len(target_ids):
        return "duplicate_target_selection"
    count = len(target_ids)
    if count < policy.selection_min:
        return f"target_selection_too_few:{count}:{policy.selection_min}"
    if count > policy.selection_max:
        return f"target_selection_too_many:{count}:{policy.selection_max}"
    return ""


def _target_enumeration_metadata(
    state: BattleState,
    actor_id: str,
    target_ids: tuple[str, ...],
    target_mode: str,
) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {
        "actor_id": actor_id,
        "target_mode": target_mode,
    }
    actor = state.units.get(actor_id)
    if actor is None or not is_dark_team(actor):
        return metadata
    aggro_rows = {
        target_id: effective_unit_stat(state.units[target_id], "base_aggro")
        for target_id in target_ids
    }
    total = sum(row.value for row in aggro_rows.values())
    metadata["aggro_selection"] = {
        "mode": "external_weighted_choice",
        "total_weight": total,
        "targets": {
            target_id: {
                **row.to_json(),
                "probability": row.value / total if total > 0.0 else None,
            }
            for target_id, row in aggro_rows.items()
        },
    }
    return metadata


def _targetability_reason(
    state: BattleState,
    unit_id: str,
    policy: TargetPolicy,
    lifecycle: UnitLifecycleSystem,
) -> str:
    target_ok, lifecycle_reason = lifecycle.can_target(
        state,
        unit_id,
        allow_defeated=policy.allow_defeated,
    )
    if not target_ok:
        return lifecycle_reason
    unit = state.units.get(unit_id)
    if unit is None:
        return "unit_missing"
    if unit.flags.get("targetable") is False:
        return "unit_untargetable"
    off_field = unit.flags.get("on_field") is False or unit.flags.get("battle_position") in {
        "backline",
        "off_field",
    }
    if off_field and not policy.allow_off_field:
        return "unit_off_field"
    return ""


def _position(value: JSONValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
